/**
 * Checks that the browser resolves EQ bands to the same biquads the render
 * does. Run backend/tests/smoke_mix_chain.py first - it writes the fixture.
 *
 * This is the drift guard for the live mixer preview: the whole design rests
 * on both sides building the same filter from the same numbers, and nothing
 * else would notice if one of them quietly changed.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { biquadCoefficients, resolveBand } from "../src/utils/eq.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = resolve(here, "eq-parity-fixture.json");

let fixture;
try {
  fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
} catch {
  console.error(`No fixture at ${fixturePath}.\nRun: python backend/tests/smoke_mix_chain.py`);
  process.exit(1);
}

const TOLERANCE = 1e-9;
let failures = 0;

for (const testCase of fixture.cases) {
  const resolved = resolveBand(fixture.sampleRate, testCase.lowHz, testCase.highHz, testCase.gainDb);
  const expected = testCase.expected;
  const label = `${testCase.lowHz}-${testCase.highHz} Hz @ ${testCase.gainDb} dB`;

  if (!resolved) {
    console.error(`FAIL ${label}: the browser resolved nothing, the render resolved ${expected.type}`);
    failures += 1;
    continue;
  }

  const deltas = {
    type: resolved.type === expected.type ? 0 : 1,
    frequency: Math.abs(resolved.frequency - expected.frequency),
    q: Math.abs(resolved.q - expected.q),
    gainDb: Math.abs(resolved.gainDb - expected.gainDb),
  };
  const bad = Object.entries(deltas).filter(([key, value]) => (key === "type" ? value : value > TOLERANCE));

  if (bad.length) {
    console.error(`FAIL ${label}: ${bad.map(([k, v]) => `${k} off by ${v}`).join(", ")}`);
    failures += 1;
  } else {
    // Resolution agrees; coefficients follow from it, but check them too so a
    // change to the RBJ formulas cannot slip through either.
    const k = biquadCoefficients(resolved.type, resolved.frequency, resolved.q, resolved.gainDb, fixture.sampleRate);
    if (!Object.values(k).every(Number.isFinite)) {
      console.error(`FAIL ${label}: produced non-finite coefficients`);
      failures += 1;
    } else {
      console.log(`ok   ${label} -> ${resolved.type} @ ${resolved.frequency.toFixed(2)} Hz, Q ${resolved.q.toFixed(3)}`);
    }
  }
}

if (failures) {
  console.error(`\n${failures} of ${fixture.cases.length} bands differ between the render and the preview.`);
  process.exit(1);
}
console.log(`\nAll ${fixture.cases.length} bands resolve identically in both.`);
