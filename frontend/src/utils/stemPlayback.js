/**
 * Multi-stem synchronised playback.
 *
 * Six <audio> elements drift apart within seconds because each one has its own
 * clock. Instead every stem is decoded into one shared AudioContext and all
 * sources are started on a single scheduled timestamp, which keeps them
 * sample-accurate for the whole song. Mute and level changes are gain changes
 * on a live graph, so they take effect instantly without restarting playback.
 */

const SCHEDULE_LEAD_SECONDS = 0.06;

export function dbToGain(db) {
  return Math.pow(10, db / 20);
}

export function gainToDb(gain) {
  if (gain <= 0.0001) return -60;
  return 20 * Math.log10(gain);
}

export default class StemPlayer {
  constructor() {
    this.context = null;
    this.master = null;
    this.stems = new Map(); // id -> { buffer, gainNode, node, gainDb, muted }
    this.duration = 0;
    this.playing = false;
    this.startedAt = 0; // context time when playback started
    this.offset = 0; // position within the song when playback started
    this.soloId = null;
    this.destroyed = false;
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

  /**
   * @param {Array<{id: string, url: string}>} stems
   * @param {(loaded: number, total: number) => void} [onProgress]
   */
  async load(stems, onProgress) {
    const context = this._ensureContext();
    let loaded = 0;

    const entries = await Promise.all(
      stems.map(async (stem) => {
        const response = await fetch(stem.url);
        if (!response.ok) throw new Error(`Could not load ${stem.id} (${response.status}).`);
        const encoded = await response.arrayBuffer();
        const buffer = await context.decodeAudioData(encoded);
        loaded += 1;
        if (onProgress) onProgress(loaded, stems.length);
        return { id: stem.id, buffer };
      })
    );

    if (this.destroyed) return;

    for (const entry of entries) {
      const gainNode = context.createGain();
      gainNode.connect(this.master);
      this.stems.set(entry.id, {
        buffer: entry.buffer,
        gainNode,
        node: null,
        gainDb: 0,
        muted: false,
      });
      this.duration = Math.max(this.duration, entry.buffer.duration);
    }

    this._applyGains();
  }

  _applyGains() {
    if (!this.context) return;
    const now = this.context.currentTime;
    for (const [id, stem] of this.stems) {
      const silenced = stem.muted || (this.soloId !== null && this.soloId !== id);
      const target = silenced ? 0 : dbToGain(stem.gainDb);
      // Short ramp instead of a step, so toggling mute does not click.
      stem.gainNode.gain.cancelScheduledValues(now);
      stem.gainNode.gain.setValueAtTime(stem.gainNode.gain.value, now);
      stem.gainNode.gain.linearRampToValueAtTime(target, now + 0.015);
    }
  }

  _stopNodes() {
    for (const stem of this.stems.values()) {
      if (stem.node) {
        try {
          stem.node.onended = null;
          stem.node.stop();
          stem.node.disconnect();
        } catch {
          /* already stopped */
        }
        stem.node = null;
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

    for (const stem of this.stems.values()) {
      const node = context.createBufferSource();
      node.buffer = stem.buffer;
      node.connect(stem.gainNode);
      // Every source gets the SAME startAt, which is what keeps them locked.
      node.start(startAt, offset);
      stem.node = node;
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

  setStemGain(id, db) {
    const stem = this.stems.get(id);
    if (!stem) return;
    stem.gainDb = db;
    this._applyGains();
  }

  setStemMuted(id, muted) {
    const stem = this.stems.get(id);
    if (!stem) return;
    stem.muted = muted;
    this._applyGains();
  }

  setSolo(id) {
    this.soloId = id;
    this._applyGains();
  }

  /**
   * Peak envelope for drawing a waveform, computed from the decoded buffer so
   * the picture matches what you actually hear.
   */
  getPeaks(id, buckets = 200) {
    const stem = this.stems.get(id);
    if (!stem) return [];
    const data = stem.buffer.getChannelData(0);
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
    this.stems.clear();
    if (this.context) {
      this.context.close().catch(() => {});
      this.context = null;
    }
  }
}
