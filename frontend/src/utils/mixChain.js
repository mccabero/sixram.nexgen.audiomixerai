/**
 * Builds the render's processing chain as Web Audio nodes.
 *
 * Nothing here decides what the chain *is*: the backend serves the resolved
 * stage list from advanced_chain_spec(), and this file only instantiates it.
 * That is deliberate - the previous design would have had the same filter
 * frequencies written out in two languages, drifting apart on the first tweak.
 *
 * Exactness, stage by stage:
 *   highpass    magnitude-exact - scipy's sections run twice forward, because
 *               the render filters zero-phase and no live graph can do that
 *   eq          exact - RBJ biquads, same coefficients as the render
 *   width       exact - the same mid/side arithmetic
 *   saturation  curve-exact - tanh(x*drive)/tanh(drive); see the note below
 *               on why the browser's oversampling is left off
 *   compressor  close - the curve maps, the detector does not (see below)
 *   deesser     close - band-split compression rather than the render's
 *                       percentile-threshold detector
 */

import { resolveBand } from "./eq.js";

const SATURATION_CURVE_POINTS = 2048;

/** A pass-through pair so a stage that resolves to nothing stays connectable. */
function passthrough(context) {
  const node = context.createGain();
  return { input: node, output: node, nodes: [node] };
}

function chainNodes(context, nodes) {
  if (!nodes.length) return passthrough(context);
  nodes.forEach((node, index) => {
    const next = nodes[index + 1];
    if (next) node.connect(next);
  });
  return { input: nodes[0], output: nodes[nodes.length - 1], nodes };
}

/**
 * The render's _high_pass runs sosfiltfilt - forward and backward, zero-phase.
 * That is non-causal: it reads the future, so no real-time graph can reproduce
 * it. Running the sections twice forward reproduces the magnitude response
 * exactly (|H| squared, the same as filtfilt) and differs only in phase, which
 * is what you want when the preview exists to judge balance and tone.
 */
function buildHighpass(context, stage) {
  const sections = Array.isArray(stage.sos) ? stage.sos : [];
  if (!sections.length) return passthrough(context);
  // scipy hands us [b0, b1, b2, a0, a1, a2] per section; IIRFilterNode wants
  // them normalised with a0 = 1.
  const makeSection = (row) => {
    const [b0, b1, b2, a0, a1, a2] = row.map(Number);
    if (!a0) return null;
    try {
      return context.createIIRFilter([b0 / a0, b1 / a0, b2 / a0], [1, a1 / a0, a2 / a0]);
    } catch {
      return null;
    }
  };
  const forward = sections.map(makeSection).filter(Boolean);
  const again = sections.map(makeSection).filter(Boolean);
  return chainNodes(context, [...forward, ...again]);
}

function buildEq(context, bands) {
  const nodes = (bands || []).map((band) => {
    const filter = context.createBiquadFilter();
    filter.type = band.type;
    filter.frequency.value = band.frequency;
    filter.Q.value = band.q;
    filter.gain.value = band.gainDb;
    return filter;
  });
  return chainNodes(context, nodes);
}

/**
 * Parallel compression. The render blends `mix` of a compressed copy back over
 * the dry signal, so the preview does the same rather than compressing the
 * whole path. DynamicsCompressorNode's detector differs from the render's
 * control-rate envelope, so this is the closest stage, not an exact one.
 */
function buildCompressor(context, stage) {
  const input = context.createGain();
  const output = context.createGain();
  const mix = Math.max(0, Math.min(1, Number(stage.mix) || 0));
  if (mix <= 0) {
    input.connect(output);
    return { input, output, nodes: [input, output] };
  }

  const dry = context.createGain();
  dry.gain.value = 1 - mix;
  const wet = context.createGain();
  wet.gain.value = mix;

  const compressor = context.createDynamicsCompressor();
  compressor.threshold.value = Number(stage.thresholdDb);
  compressor.knee.value = Number(stage.kneeDb ?? 6);
  compressor.ratio.value = Number(stage.ratio);
  compressor.attack.value = Number(stage.attackMs ?? 8) / 1000;
  compressor.release.value = Number(stage.releaseMs ?? 90) / 1000;

  input.connect(dry);
  dry.connect(output);
  input.connect(compressor);
  compressor.connect(wet);
  wet.connect(output);
  return { input, output, nodes: [input, dry, compressor, wet, output] };
}

/** Band-split de-esser over the render's own sibilance window. */
function buildDeEsser(context, stage) {
  const strength = Math.max(0, Math.min(1, Number(stage.strength) || 0));
  const input = context.createGain();
  const output = context.createGain();
  if (strength <= 0) {
    input.connect(output);
    return { input, output, nodes: [input, output] };
  }

  const high = context.createBiquadFilter();
  high.type = "highpass";
  high.frequency.value = 4800;
  const low = context.createBiquadFilter();
  low.type = "lowpass";
  low.frequency.value = Math.min(10800, context.sampleRate / 2 - 200);

  const compressor = context.createDynamicsCompressor();
  compressor.threshold.value = -32;
  compressor.knee.value = 6;
  compressor.ratio.value = 2 + strength * 6;
  compressor.attack.value = 0.002;
  compressor.release.value = 0.045;

  // The band leaves the dry path and comes back compressed.
  const bandOut = context.createGain();
  const bandInvert = context.createGain();
  bandInvert.gain.value = -1;

  input.connect(high);
  high.connect(low);
  low.connect(bandInvert);
  bandInvert.connect(output); // remove the raw band
  low.connect(compressor);
  compressor.connect(bandOut);
  bandOut.connect(output); // add it back, compressed
  input.connect(output);

  return { input, output, nodes: [input, high, low, compressor, bandOut, bandInvert, output] };
}

/** Mid/side width: side *= (1 + amount), exactly as _apply_width does. */
function buildWidth(context, amount) {
  const value = Number(amount) || 0;
  const input = context.createGain();
  const output = context.createGain();
  if (Math.abs(value) < 0.01) {
    input.connect(output);
    return { input, output, nodes: [input, output] };
  }

  input.channelCount = 2;
  input.channelCountMode = "explicit";

  const splitter = context.createChannelSplitter(2);
  const merger = context.createChannelMerger(2);
  const midFromL = context.createGain();
  const midFromR = context.createGain();
  midFromL.gain.value = 0.5;
  midFromR.gain.value = 0.5;
  const sideFromL = context.createGain();
  const sideFromR = context.createGain();
  sideFromL.gain.value = 0.5;
  sideFromR.gain.value = -0.5;

  const mid = context.createGain();
  const side = context.createGain();
  side.gain.value = Math.max(0, 1 + value);
  const sideInvert = context.createGain();
  sideInvert.gain.value = -1;

  input.connect(splitter);
  splitter.connect(midFromL, 0);
  splitter.connect(midFromR, 1);
  splitter.connect(sideFromL, 0);
  splitter.connect(sideFromR, 1);
  midFromL.connect(mid);
  midFromR.connect(mid);
  sideFromL.connect(side);
  sideFromR.connect(side);

  mid.connect(merger, 0, 0);
  side.connect(merger, 0, 0);
  mid.connect(merger, 0, 1);
  side.connect(sideInvert);
  sideInvert.connect(merger, 0, 1);
  merger.connect(output);

  return {
    input,
    output,
    nodes: [input, splitter, midFromL, midFromR, sideFromL, sideFromR, mid, side, sideInvert, merger, output],
  };
}

export function saturationCurve(drive) {
  const d = Math.max(1, Number(drive) || 1);
  const curve = new Float32Array(SATURATION_CURVE_POINTS);
  const denominator = Math.tanh(d);
  for (let index = 0; index < SATURATION_CURVE_POINTS; index += 1) {
    const x = (index / (SATURATION_CURVE_POINTS - 1)) * 2 - 1;
    curve[index] = Math.tanh(x * d) / denominator;
  }
  return curve;
}

function buildSaturation(context, stage) {
  const mix = Math.max(0, Math.min(1, Number(stage.mix) || 0));
  const input = context.createGain();
  const output = context.createGain();
  if (mix <= 0) {
    input.connect(output);
    return { input, output, nodes: [input, output] };
  }

  const shaper = context.createWaveShaper();
  shaper.curve = saturationCurve(stage.drive);
  // Measured, not assumed: Chromium's "4x" oversampling returns something far
  // from the curve (errors larger than the signal), while "none" tracks
  // tanh(x*drive)/tanh(drive) to float32. The render oversamples to keep
  // harmonics from aliasing; at these drive and mix levels the aliasing is
  // well below the error 4x would introduce here.
  shaper.oversample = "none";

  const dry = context.createGain();
  dry.gain.value = 1 - mix;
  const wet = context.createGain();
  wet.gain.value = mix;

  input.connect(dry);
  dry.connect(output);
  input.connect(shaper);
  shaper.connect(wet);
  wet.connect(output);
  return { input, output, nodes: [input, shaper, dry, wet, output] };
}

function buildStage(context, stage) {
  switch (stage.kind) {
    case "highpass":
      return buildHighpass(context, stage);
    case "eq":
      return buildEq(context, stage.bands);
    case "compressor":
      return buildCompressor(context, stage);
    case "deesser":
      return buildDeEsser(context, stage);
    case "width":
      return buildWidth(context, stage.amount);
    case "saturation":
      return buildSaturation(context, stage);
    default:
      return passthrough(context);
  }
}

/**
 * Build the whole automatic chain plus the presence control.
 * Returns an input node, an output node, and everything to disconnect later.
 */
export function buildStemChain(context, { chain, chainEnabled, presenceAmount, presenceBand }) {
  const input = context.createGain();
  const all = [input];
  let tail = input;

  if (chainEnabled !== false) {
    (chain || []).forEach((stage) => {
      const built = buildStage(context, stage);
      tail.connect(built.input);
      tail = built.output;
      all.push(...built.nodes);
    });

    // _apply_stem_presence: one band whose window depends on the stem type.
    const amount = Math.max(-1, Math.min(1, (Number(presenceAmount) || 0) / 50));
    if (Math.abs(amount) >= 0.02 && presenceBand) {
      const band = resolveBand(
        context.sampleRate,
        presenceBand.lowHz,
        presenceBand.highHz,
        amount * (presenceBand.scale ?? 1),
      );
      if (band) {
        const built = buildEq(context, [band]);
        tail.connect(built.input);
        tail = built.output;
        all.push(...built.nodes);
      }
    }
  }

  return { input, output: tail, nodes: all };
}

/**
 * Impulse for the shared reverb buses.
 *
 * The render's _diffuse_reverb is an algorithmic network, so this is the one
 * place the preview can only approximate: an exponentially decaying noise tail
 * with the same room-size-driven length, pre-delay and high-frequency damping.
 */
export function createReverbImpulse(context, roomSize) {
  const size = Math.max(0.1, Math.min(1.2, Number(roomSize) || 0.5));
  const sampleRate = context.sampleRate;
  const preDelay = Math.floor(((12 + size * 22) / 1000) * sampleRate);
  const length = Math.max(1, Math.floor(sampleRate * (0.6 + size * 1.9)));
  const decay = 0.76 + Math.min(1, size) * 0.16;
  const dampingHz = 8200 - Math.min(3200, size * 2600);

  const impulse = context.createBuffer(2, preDelay + length, sampleRate);
  // One-pole low-pass per channel, so the tail darkens as it decays.
  const coefficient = Math.exp((-2 * Math.PI * dampingHz) / sampleRate);

  for (let channel = 0; channel < 2; channel += 1) {
    const data = impulse.getChannelData(channel);
    let previous = 0;
    for (let index = 0; index < length; index += 1) {
      const noise = Math.random() * 2 - 1;
      previous = noise * (1 - coefficient) + previous * coefficient;
      const envelope = Math.pow(1 - index / length, 1 / (1 - decay) / 8);
      data[preDelay + index] = previous * envelope;
    }
  }
  return impulse;
}

/** A damped feedback delay, matching _delay_effect's darkening repeats. */
export function createDelayBus(context, delaySeconds, feedback = 0.2) {
  const input = context.createGain();
  const delay = context.createDelay(Math.max(0.05, Math.min(4, delaySeconds || 0.3)) + 0.05);
  delay.delayTime.value = Math.max(0.02, Math.min(4, delaySeconds || 0.3));
  const feedbackGain = context.createGain();
  feedbackGain.gain.value = Math.max(0, Math.min(0.8, feedback));
  const damping = context.createBiquadFilter();
  damping.type = "lowpass";
  damping.frequency.value = 5600;
  const output = context.createGain();

  input.connect(delay);
  delay.connect(damping);
  damping.connect(output);
  damping.connect(feedbackGain);
  feedbackGain.connect(delay);

  return { input, output, nodes: [input, delay, damping, feedbackGain, output] };
}

export function disconnectAll(nodes) {
  (nodes || []).forEach((node) => {
    try {
      node.disconnect();
    } catch {
      /* already gone */
    }
  });
}
