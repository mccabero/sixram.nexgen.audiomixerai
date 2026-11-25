"""Guards the one thing the live mixer preview depends on: that the browser
and the render are still describing the same chain.

The preview does not reimplement the processing - it is served
advanced_chain_spec() and builds Web Audio nodes from it. That only stays
honest while:

  * every stage kind the spec emits has a processor on the Python side, and
  * the EQ band resolver keeps producing the coefficients the browser's
    eq.js produces from the same inputs.

Run me, then run `node frontend/scripts/check-eq-parity.mjs` to check the
JavaScript half against the fixture this writes.
"""

import json
import sys
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.audio_engine import (  # noqa: E402
    ROUGH_MIX_SAMPLE_RATE,
    _advanced_chain,
    _apply_stem_eq,
    _eq_band_params,
    _stage_processor,
    advanced_chain_spec,
    stem_normalize_gain_db,
)
from app.config import STEM_TYPES  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "scripts" / "eq-parity-fixture.json"

KNOWN_KINDS = {"highpass", "eq", "compressor", "deesser", "width", "saturation"}

CONTROL_SETS = [
    {"brightness": 0, "warmth": 0, "drumPunch": 50, "bassWeight": 50, "width": 55, "backingVocalWidth": 55},
    {"brightness": 40, "warmth": -25, "drumPunch": 85, "bassWeight": 15, "width": 95, "backingVocalWidth": 5},
]


def check_spec_covers_every_stage() -> None:
    for stem_type in STEM_TYPES + ["Unknown", "Something New"]:
        for controls in CONTROL_SETS:
            for amount in (0.0, 0.5, 1.0):
                spec = advanced_chain_spec(stem_type, ROUGH_MIX_SAMPLE_RATE, controls, amount)
                chain = _advanced_chain(stem_type, ROUGH_MIX_SAMPLE_RATE, controls, amount)
                assert len(spec) == len(chain), f"{stem_type}: spec and chain lengths differ"
                for stage, (label, _processor) in zip(spec, chain):
                    assert stage["label"] == label, f"{stem_type}: label mismatch {stage['label']} != {label}"
                    assert stage["kind"] in KNOWN_KINDS, (
                        f"{stem_type}: stage kind {stage['kind']!r} is not one the browser knows how to build. "
                        "Add it to frontend/src/utils/mixChain.js before shipping it here."
                    )
                    if stage["kind"] == "highpass":
                        assert stage.get("sos"), f"{stem_type}: high-pass stage is missing its coefficients"
    print("  every spec stage has a processor and a kind the browser can build")


def check_chain_runs() -> None:
    rng = np.random.default_rng(1)
    audio = (rng.standard_normal((4096, 2)) * 0.1).astype(np.float32)
    for stem_type in STEM_TYPES:
        spec = advanced_chain_spec(stem_type, ROUGH_MIX_SAMPLE_RATE, CONTROL_SETS[1], 0.6)
        out = audio.copy()
        for stage in spec:
            out = _stage_processor(stage, ROUGH_MIX_SAMPLE_RATE)(out)
        assert np.all(np.isfinite(out)), f"{stem_type}: chain produced non-finite samples"
    print("  every stem type's chain runs and stays finite")


def check_user_eq_is_a_no_op_when_flat() -> None:
    rng = np.random.default_rng(2)
    audio = (rng.standard_normal((2048, 2)) * 0.1).astype(np.float32)
    flat = [
        {"type": "lowshelf", "frequency": 120, "gainDb": 0, "q": 0.707, "enabled": True},
        {"type": "peaking", "frequency": 400, "gainDb": 0, "q": 1.0, "enabled": True},
        {"type": "peaking", "frequency": 3000, "gainDb": 0, "q": 1.0, "enabled": True},
        {"type": "highshelf", "frequency": 8000, "gainDb": 0, "q": 0.707, "enabled": True},
    ]
    assert np.array_equal(_apply_stem_eq(audio, ROUGH_MIX_SAMPLE_RATE, flat), audio), (
        "a flat channel EQ must leave the audio untouched, or every existing project re-renders differently"
    )
    disabled = [dict(band) for band in flat]
    disabled[2].update({"gainDb": 6.0, "enabled": False})
    assert np.array_equal(_apply_stem_eq(audio, ROUGH_MIX_SAMPLE_RATE, disabled), audio), (
        "a disabled band must be a true bypass"
    )
    print("  a flat or disabled channel EQ changes nothing")


def check_normalize_gain() -> None:
    assert stem_normalize_gain_db("Lead Vocal", None) == 0.0
    assert stem_normalize_gain_db("Lead Vocal", -99.0) == 0.0
    assert stem_normalize_gain_db("Lead Vocal", -18.1) == 0.0, "inside the deadband"
    assert abs(stem_normalize_gain_db("Lead Vocal", -24.0) - 6.0) < 1e-9
    assert stem_normalize_gain_db("Lead Vocal", -40.0) == 12.0, "clamped"
    print("  normalize gain matches the render's reference table")


def write_parity_fixture() -> None:
    """Resolved bands for the JavaScript side to reproduce."""
    cases = []
    for low, high, gain in [
        (220, 420, -1.8),
        (2500, 5200, 2.6),
        (45, 110, 1.0),
        (4500, 9000, 1.8),
        (120, 360, -1.1),
        (1200, 3600, -0.8),
        (650, 1400, 0.8),
    ]:
        params = _eq_band_params(ROUGH_MIX_SAMPLE_RATE, low, high, gain)
        if params:
            cases.append({"lowHz": low, "highHz": high, "gainDb": gain, "expected": params})
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps({"sampleRate": ROUGH_MIX_SAMPLE_RATE, "cases": cases}, indent=2), encoding="utf-8")
    print(f"  wrote {len(cases)} resolved bands to {FIXTURE.relative_to(FIXTURE.parents[2])}")


def main() -> None:
    print("mix chain smoke test")
    check_spec_covers_every_stage()
    check_chain_runs()
    check_user_eq_is_a_no_op_when_flat()
    check_normalize_gain()
    write_parity_fixture()
    print("OK - now run: node frontend/scripts/check-eq-parity.mjs")


if __name__ == "__main__":
    main()
