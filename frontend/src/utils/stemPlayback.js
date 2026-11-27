/**
 * Multi-stem synchronised playback with a live channel strip.
 *
 * Six <audio> elements drift apart within seconds because each one has its own
 * clock. Instead every stem is decoded into one shared AudioContext and all
 * sources are started on a single scheduled timestamp, which keeps them
 * sample-accurate for the whole song.
 *
 * Each stem then runs through its own strip:
 *
 *   source -> normalize -> automatic chain -> channel EQ -> gain
 *          -> equal-power pan -> master, with reverb and delay sends
 *
 * Every control is a parameter write on a graph that never stops, so moving a
 * fader or an EQ band is audible immediately with no decode and no re-render.
 * The filters are the same RBJ biquads the backend renders with, built from
 * the same saved numbers, so the preview and the render agree.
 */

import { EQ_BAND_COUNT, isBandActive, normalizeEqBands } from "./eq.js";
import { buildStemChain, createDelayBus, createReverbImpulse, disconnectAll } from "./mixChain.js";

// Decoded PCM buffers keyed by URL. AudioBuffer is a plain data container —
// the spec allows it to be shared across AudioContext instances. Caching here
// means navigating back to the same song skips both the network fetch and the
// CPU-intensive decode step, so playback is available immediately.
const _bufferCache = new Map();

const SCHEDULE_LEAD_SECONDS = 0.06;
const RAMP_SECONDS = 0.02;

export function dbToGain(db) {
  return Math.pow(10, db / 20);
}

export function gainToDb(gain) {
  if (gain <= 0.0001) return -60;
  return 20 * Math.log10(gain);
}

/**
 * Equal-power pan law, unity at centre - the same curve as the backend's
 * _apply_pan, including its sqrt(2) compensation. Without that factor a
 * centred stem would sit 3 dB quieter in the preview than in the render.
 */
export function panGains(pan) {
  const normalized = Math.max(-1, Math.min(1, (Number(pan) || 0) / 100));
  const theta = (normalized + 1) * (Math.PI / 4);
  return {
    left: Math.cos(theta) * Math.SQRT2,
    right: Math.sin(theta) * Math.SQRT2,
  };
}

export default class StemPlayer {
  constructor() {
    this.context = null;
    this.master = null;
    this.stems = new Map();
    this.duration = 0;
    this.playing = false;
    this.startedAt = 0;
    this.offset = 0;
    this.soloId = null;
    this.destroyed = false;
    this.buses = null;
    this.chainPayload = null;
  }

  _ensureContext() {
    if (!this.context) {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) throw new Error("This browser has no Web Audio support.");
      this.context = new Ctor();
      this.master = this.context.createGain();
      this.master.gain.value = 0.85;
      this.master.connect(this.context.destination);
    }
    return this.context;
  }

  get sampleRate() {
    return this.context?.sampleRate ?? 44100;
  }

  /**
   * @param {Array<{id: string, url: string, gainDb?: number, pan?: number, muted?: boolean, bands?: Array, stemType?: string}>} stems
   * @param {(loaded: number, total: number) => void} [onProgress]
   */
  async load(stems, onProgress) {
    const context = this._ensureContext();
    let loaded = 0;

    const entries = await Promise.all(
      stems.map(async (stem) => {
        let buffer = _bufferCache.get(stem.url);
        if (!buffer) {
          const response = await fetch(stem.url);
          if (!response.ok) throw new Error(`Could not load ${stem.id} (${response.status}).`);
          const encoded = await response.arrayBuffer();
          buffer = await context.decodeAudioData(encoded);
          _bufferCache.set(stem.url, buffer);
        }
        loaded += 1;
        if (onProgress) onProgress(loaded, stems.length);
        return { stem, buffer };
      })
    );

    if (this.destroyed) return;

    for (const { stem, buffer } of entries) {
      this.stems.set(stem.id, this._createStrip(stem, buffer));
      this.duration = Math.max(this.duration, buffer.duration);
    }

    this._applyGains();
  }

  _createStrip(stem, buffer) {
    const context = this.context;

    // The render normalises each stem before the channel strip; without the
    // same gain here every compressor threshold downstream bites differently.
    const normalizeGain = context.createGain();
    const chainIn = context.createGain();
    const eqNodes = Array.from({ length: EQ_BAND_COUNT }, () => context.createBiquadFilter());
    const gainNode = context.createGain();
    // Explicit stereo so a mono stem is upmixed to both channels before the
    // pan split, which is what the backend's two-channel decode does.
    gainNode.channelCount = 2;
    gainNode.channelCountMode = "explicit";
    gainNode.channelInterpretation = "speakers";

    const splitter = context.createChannelSplitter(2);
    const leftGain = context.createGain();
    const rightGain = context.createGain();
    const merger = context.createChannelMerger(2);

    eqNodes.forEach((node, index) => {
      const next = eqNodes[index + 1];
      node.connect(next ?? gainNode);
    });
    normalizeGain.connect(chainIn);
    gainNode.connect(splitter);
    splitter.connect(leftGain, 0);
    splitter.connect(rightGain, 1);
    leftGain.connect(merger, 0, 0);
    rightGain.connect(merger, 0, 1);
    const stemOut = context.createGain();
    merger.connect(stemOut);
    stemOut.connect(this.master);

    // Sends are taken after gain and pan, which is where the render takes them.
    const reverbSend = context.createGain();
    reverbSend.gain.value = 0;
    const delaySend = context.createGain();
    delaySend.gain.value = 0;
    stemOut.connect(reverbSend);
    stemOut.connect(delaySend);

    const strip = {
      buffer,
      normalizeGain,
      chainIn,
      chainNodes: [],
      chainTail: null,
      stemOut,
      reverbSend,
      delaySend,
      spec: stem.spec || null,
      eqNodes,
      gainNode,
      splitter,
      leftGain,
      rightGain,
      merger,
      node: null,
      gainDb: Number(stem.gainDb) || 0,
      pan: Number(stem.pan) || 0,
      muted: Boolean(stem.muted),
      bands: normalizeEqBands(stem.bands, stem.stemType),
    };

    this._writeEq(strip, true);
    this._writePan(strip, true);
    this._buildChain(strip);
    return strip;
  }

  /**
   * (Re)build the automatic chain between the normalize gain and the channel
   * EQ. Rebuilt rather than retuned because IIR sections and waveshapers are
   * not automatable - a macro control change makes a brief seam in the
   * audio, which is the right trade for faders and EQ staying smooth.
   */
  _buildChain(strip) {
    const context = this.context;
    if (!context) return;

    try {
      strip.chainIn.disconnect();
    } catch {
      /* nothing connected yet */
    }
    disconnectAll(strip.chainNodes);
    strip.chainNodes = [];

    const head = strip.eqNodes[0] ?? strip.gainNode;
    const spec = strip.spec;
    if (!spec) {
      strip.chainIn.connect(head);
      return;
    }

    const built = buildStemChain(context, {
      chain: spec.chain,
      chainEnabled: spec.chainEnabled,
      presenceAmount: spec.presenceAmount,
      presenceBand: spec.presenceBand,
    });
    strip.chainIn.connect(built.input);
    built.output.connect(head);
    strip.chainNodes = built.nodes;

    const normalizeDb = Number(spec.normalizeGainDb) || 0;
    strip.normalizeGain.gain.value = dbToGain(normalizeDb);
    strip.presetGainDb = Number(spec.presetGainDb) || 0;
    this._writeSends(strip);
  }

  _writeSends(strip) {
    const spec = strip.spec;
    if (!spec) return;
    const buses = this.buses;
    const bus = buses?.[spec.sendBus] ?? buses?.space;

    try {
      strip.reverbSend.disconnect();
      strip.delaySend.disconnect();
    } catch {
      /* not connected */
    }
    if (!bus) return;
    strip.reverbSend.connect(bus.reverbIn);
    strip.delaySend.connect(bus.delayIn);

    const now = this.context?.currentTime ?? 0;
    rampParam(strip.reverbSend.gain, Number(spec.reverbSendAmount) || 0, now, RAMP_SECONDS);
    rampParam(strip.delaySend.gain, Number(spec.delaySendAmount) || 0, now, RAMP_SECONDS);
  }

  _writeEq(strip, immediate = false) {
    const now = this.context?.currentTime ?? 0;
    const at = immediate ? 0 : RAMP_SECONDS;
    strip.bands.forEach((band, index) => {
      const node = strip.eqNodes[index];
      if (!node) return;
      const active = isBandActive(band);
      if (node.type !== band.type) node.type = band.type;
      rampParam(node.frequency, band.frequency, now, at);
      rampParam(node.Q, band.q, now, at);
      // A disabled band stays in the chain at 0 dB: a biquad at unity gain is
      // a pass-through, and keeping the node avoids a rebuild mid-playback.
      rampParam(node.gain, active ? band.gainDb : 0, now, at);
    });
  }

  _writePan(strip, immediate = false) {
    const now = this.context?.currentTime ?? 0;
    const at = immediate ? 0 : RAMP_SECONDS;
    const { left, right } = panGains(strip.pan);
    rampParam(strip.leftGain.gain, left, now, at);
    rampParam(strip.rightGain.gain, right, now, at);
  }

  _applyGains() {
    if (!this.context) return;
    const now = this.context.currentTime;
    for (const [id, strip] of this.stems) {
      const silenced = strip.muted || (this.soloId !== null && this.soloId !== id);
      const target = silenced ? 0 : dbToGain(strip.gainDb + (strip.presetGainDb || 0));
      // Short ramp instead of a step, so toggling mute does not click.
      strip.gainNode.gain.cancelScheduledValues(now);
      strip.gainNode.gain.setValueAtTime(strip.gainNode.gain.value, now);
      strip.gainNode.gain.linearRampToValueAtTime(target, now + 0.015);
    }
  }

  _stopNodes() {
    for (const strip of this.stems.values()) {
      if (strip.node) {
        try {
          strip.node.onended = null;
          strip.node.stop();
          strip.node.disconnect();
        } catch {
          /* already stopped */
        }
        strip.node = null;
      }
    }
  }

  get currentTime() {
    if (!this.context) return this.offset;
    if (!this.playing) return this.offset;
    return Math.min(this.duration, this.offset + (this.context.currentTime - this.startedAt));
  }

  async play(fromSeconds) {
    const context = this._ensureContext();
    if (context.state === "suspended") await context.resume();
    if (!this.stems.size) return;

    this._stopNodes();

    const offset = Math.max(0, Math.min(this.duration, fromSeconds ?? this.currentTime));
    const startAt = context.currentTime + SCHEDULE_LEAD_SECONDS;

    for (const strip of this.stems.values()) {
      const node = context.createBufferSource();
      node.buffer = strip.buffer;
      node.connect(strip.normalizeGain);
      // Every source gets the SAME startAt, which is what keeps them locked.
      node.start(startAt, offset);
      strip.node = node;
    }

    this.offset = offset;
    this.startedAt = startAt;
    this.playing = true;
    this._applyGains();
  }

  pause() {
    if (!this.playing) return;
    const position = this.currentTime;
    this._stopNodes();
    this.offset = position;
    this.playing = false;
  }

  async seek(seconds) {
    const target = Math.max(0, Math.min(this.duration, seconds));
    if (this.playing) {
      await this.play(target);
    } else {
      this.offset = target;
    }
  }

  /**
   * Hand the player the chain the backend resolved: per-stem stages, the
   * normalize and preset gains, send levels, and the shared bus settings.
   */
  setChainPayload(payload) {
    this.chainPayload = payload || null;
    if (!this.context) return;
    this._buildBuses();
    const specs = new Map((payload?.stems || []).map((entry) => [entry.stemId, entry]));
    for (const [id, strip] of this.stems) {
      strip.spec = specs.get(id) || null;
      this._buildChain(strip);
    }
    this._applyGains();
  }

  _buildBuses() {
    const context = this.context;
    if (!context) return;
    if (this.buses) {
      Object.values(this.buses).forEach((bus) => disconnectAll(bus.nodes));
    }
    this.buses = {};

    const payload = this.chainPayload || {};
    const definitions = payload.buses || {};
    const stemSpecs = payload.stems || [];

    ["vocal", "drum", "space"].forEach((name) => {
      const definition = definitions[name] || { amount: 0.2, roomSize: 0.5 };
      const reverbIn = context.createGain();
      const convolver = context.createConvolver();
      convolver.buffer = createReverbImpulse(context, definition.roomSize);
      const amount = context.createGain();
      amount.gain.value = Math.max(0, Math.min(1.1, Number(definition.amount) || 0));
      reverbIn.connect(convolver);
      convolver.connect(amount);
      amount.connect(this.master);

      // One delay line per bus, timed from the first stem that feeds it, so
      // the repeats stay synced to the tempo the render used.
      const timed = stemSpecs.find((entry) => entry.sendBus === name && entry.delaySeconds);
      const delay = createDelayBus(context, timed?.delaySeconds ?? 0.3, 0.2);
      delay.output.connect(this.master);

      this.buses[name] = {
        reverbIn,
        delayIn: delay.input,
        nodes: [reverbIn, convolver, amount, ...delay.nodes],
      };
    });
  }

  has(id) {
    return this.stems.has(id);
  }

  setStemGain(id, db) {
    const strip = this.stems.get(id);
    if (!strip) return;
    strip.gainDb = Number(db) || 0;
    this._applyGains();
  }

  setStemMuted(id, muted) {
    const strip = this.stems.get(id);
    if (!strip) return;
    strip.muted = Boolean(muted);
    this._applyGains();
  }

  setSolo(id) {
    this.soloId = id;
    this._applyGains();
  }

  setStemPan(id, pan) {
    const strip = this.stems.get(id);
    if (!strip) return;
    strip.pan = Number(pan) || 0;
    this._writePan(strip);
  }

  setStemEq(id, bands, stemType) {
    const strip = this.stems.get(id);
    if (!strip) return;
    strip.bands = normalizeEqBands(bands, stemType);
    this._writeEq(strip);
  }

  getStemEq(id) {
    return this.stems.get(id)?.bands ?? null;
  }

  /** Apply a whole saved mix setting at once, for the initial sync. */
  setStemSettings(id, { gainDb, pan, muted, bands, stemType } = {}) {
    const strip = this.stems.get(id);
    if (!strip) return;
    if (gainDb !== undefined) strip.gainDb = Number(gainDb) || 0;
    if (muted !== undefined) strip.muted = Boolean(muted);
    if (pan !== undefined) {
      strip.pan = Number(pan) || 0;
      this._writePan(strip);
    }
    if (bands !== undefined) {
      strip.bands = normalizeEqBands(bands, stemType);
      this._writeEq(strip);
    }
    this._applyGains();
  }

  /**
   * Peak envelope for drawing a waveform, computed from the decoded buffer so
   * the picture matches what you actually hear.
   */
  getPeaks(id, buckets = 200) {
    const strip = this.stems.get(id);
    if (!strip) return [];
    const data = strip.buffer.getChannelData(0);
    const size = Math.floor(data.length / buckets) || 1;
    const peaks = [];
    for (let index = 0; index < buckets; index += 1) {
      const start = index * size;
      let peak = 0;
      for (let offset = 0; offset < size; offset += 16) {
        const value = Math.abs(data[start + offset] || 0);
        if (value > peak) peak = value;
      }
      peaks.push(peak);
    }
    const loudest = Math.max(...peaks, 0.0001);
    return peaks.map((value) => value / loudest);
  }

  setMasterVolume(value) {
    if (!this.master || !this.context) return;
    const now = this.context.currentTime;
    this.master.gain.cancelScheduledValues(now);
    this.master.gain.setValueAtTime(this.master.gain.value, now);
    this.master.gain.linearRampToValueAtTime(Math.max(0, Math.min(1, value)), now + 0.015);
  }

  destroy() {
    this.destroyed = true;
    this._stopNodes();
    if (this.buses) {
      Object.values(this.buses).forEach((bus) => disconnectAll(bus.nodes));
      this.buses = null;
    }
    this.stems.clear();
    if (this.context) {
      this.context.close().catch(() => {});
      this.context = null;
    }
  }
}

function rampParam(param, value, now, seconds) {
  if (!param) return;
  const target = Number.isFinite(value) ? value : 0;
  if (!seconds) {
    param.cancelScheduledValues(now);
    param.setValueAtTime(target, now);
    return;
  }
  param.cancelScheduledValues(now);
  param.setValueAtTime(param.value, now);
  param.linearRampToValueAtTime(target, now + seconds);
}
