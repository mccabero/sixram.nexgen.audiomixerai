/**
 * Channel EQ maths, shared by the live preview and the curve display.
 *
 * These are the RBJ audio-EQ-cookbook formulas, the same ones the backend's
 * _rbj_biquad_sos builds for the render. Keeping the coefficients here rather
 * than reading them off a BiquadFilterNode means the curve can be drawn before
 * any audio is loaded, and it gives us one place to check parity against the
 * Python side.
 */

export const EQ_BAND_COUNT = 4;
export const EQ_MIN_FREQUENCY = 20;
export const EQ_MAX_FREQUENCY = 20000;
export const EQ_MIN_GAIN_DB = -18;
export const EQ_MAX_GAIN_DB = 18;
export const EQ_MIN_Q = 0.1;
export const EQ_MAX_Q = 10;

const BAND_FREQUENCIES = {
  "Lead Vocal": [120, 400, 3000, 8000],
  "Backing Vocal": [140, 450, 3000, 9000],
  Drums: [80, 400, 3000, 7000],
  Kick: [60, 200, 1200, 4000],
  Snare: [120, 400, 3000, 8000],
  Bass: [60, 180, 800, 2500],
  "Electric Guitar": [120, 400, 2500, 6000],
  "Acoustic Guitar": [120, 350, 3000, 8000],
  "Keys/Piano": [100, 350, 2500, 7000],
  "Pads/Strings": [120, 400, 2000, 8000],
  "FX/Ambience": [100, 400, 2500, 9000],
};

const BAND_TYPES = ["lowshelf", "peaking", "peaking", "highshelf"];
const BAND_LABELS = ["Low", "Low Mid", "High Mid", "High"];

export function bandLabel(index) {
  return BAND_LABELS[index] ?? `Band ${index + 1}`;
}

/** Neutral four-band EQ. Mirrors the backend's default_eq_bands exactly. */
export function defaultEqBands(stemType) {
  const frequencies = BAND_FREQUENCIES[stemType] ?? [100, 400, 2500, 8000];
  return frequencies.map((frequency, index) => ({
    type: BAND_TYPES[index],
    frequency,
    gainDb: 0,
    q: BAND_TYPES[index] === "peaking" ? 1 : 0.707,
    enabled: true,
  }));
}

export function normalizeEqBands(bands, stemType) {
  const defaults = defaultEqBands(stemType);
  if (!Array.isArray(bands) || !bands.length) return defaults;
  return defaults.map((fallback, index) => {
    const band = bands[index];
    if (!band) return fallback;
    return {
      type: BAND_TYPES.includes(band.type) ? band.type : fallback.type,
      frequency: clamp(Number(band.frequency) || fallback.frequency, EQ_MIN_FREQUENCY, EQ_MAX_FREQUENCY),
      gainDb: clamp(Number(band.gainDb) || 0, EQ_MIN_GAIN_DB, EQ_MAX_GAIN_DB),
      q: clamp(Number(band.q) || fallback.q, EQ_MIN_Q, EQ_MAX_Q),
      enabled: band.enabled !== false,
    };
  });
}

export function isBandActive(band) {
  return Boolean(band) && band.enabled !== false && Math.abs(Number(band.gainDb) || 0) >= 0.05;
}

export function isEqFlat(bands) {
  return !(bands || []).some(isBandActive);
}

function clamp(value, min, max) {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

/**
 * RBJ biquad coefficients, normalised so a0 === 1.
 * Same branch structure as the backend's _rbj_biquad_sos.
 */
export function biquadCoefficients(type, frequency, q, gainDb, sampleRate) {
  const A = Math.pow(10, gainDb / 40);
  const w0 = (2 * Math.PI * frequency) / sampleRate;
  const cosW0 = Math.cos(w0);
  const sinW0 = Math.sin(w0);
  const alpha = sinW0 / (2 * Math.max(0.05, q));

  let b0;
  let b1;
  let b2;
  let a0;
  let a1;
  let a2;

  if (type === "peaking") {
    b0 = 1 + alpha * A;
    b1 = -2 * cosW0;
    b2 = 1 - alpha * A;
    a0 = 1 + alpha / A;
    a1 = -2 * cosW0;
    a2 = 1 - alpha / A;
  } else {
    const beta = 2 * Math.sqrt(A) * alpha;
    if (type === "lowshelf") {
      b0 = A * (A + 1 - (A - 1) * cosW0 + beta);
      b1 = 2 * A * (A - 1 - (A + 1) * cosW0);
      b2 = A * (A + 1 - (A - 1) * cosW0 - beta);
      a0 = A + 1 + (A - 1) * cosW0 + beta;
      a1 = -2 * (A - 1 + (A + 1) * cosW0);
      a2 = A + 1 + (A - 1) * cosW0 - beta;
    } else {
      b0 = A * (A + 1 + (A - 1) * cosW0 + beta);
      b1 = -2 * A * (A - 1 + (A + 1) * cosW0);
      b2 = A * (A + 1 + (A - 1) * cosW0 - beta);
      a0 = A + 1 - (A - 1) * cosW0 + beta;
      a1 = 2 * (A - 1 - (A + 1) * cosW0);
      a2 = A + 1 - (A - 1) * cosW0 - beta;
    }
  }

  return { b0: b0 / a0, b1: b1 / a0, b2: b2 / a0, a1: a1 / a0, a2: a2 / a0 };
}

/** |H(e^jw)| in dB for one band at one frequency. */
function bandMagnitudeDb(band, frequency, sampleRate) {
  const { b0, b1, b2, a1, a2 } = biquadCoefficients(
    band.type,
    band.frequency,
    band.q,
    band.gainDb,
    sampleRate,
  );
  const w = (2 * Math.PI * frequency) / sampleRate;
  const cos1 = Math.cos(w);
  const sin1 = Math.sin(w);
  const cos2 = Math.cos(2 * w);
  const sin2 = Math.sin(2 * w);

  const numReal = b0 + b1 * cos1 + b2 * cos2;
  const numImag = -(b1 * sin1 + b2 * sin2);
  const denReal = 1 + a1 * cos1 + a2 * cos2;
  const denImag = -(a1 * sin1 + a2 * sin2);

  const numMag = Math.hypot(numReal, numImag);
  const denMag = Math.hypot(denReal, denImag) || 1e-12;
  return 20 * Math.log10(Math.max(1e-12, numMag / denMag));
}

/** Combined response of every active band, in dB, one value per frequency. */
export function eqResponseDb(bands, frequencies, sampleRate = 44100) {
  const active = (bands || []).filter(isBandActive);
  return frequencies.map((frequency) =>
    active.reduce((total, band) => total + bandMagnitudeDb(band, frequency, sampleRate), 0),
  );
}

/** Log-spaced frequencies for drawing the curve. */
export function logFrequencies(count = 160, min = EQ_MIN_FREQUENCY, max = EQ_MAX_FREQUENCY) {
  const ratio = Math.log(max / min);
  return Array.from({ length: count }, (_, index) => min * Math.exp((ratio * index) / (count - 1)));
}
