#!/usr/bin/env python3
"""Phase 9 probe - chord and tuning detection over an existing split.

Standalone on purpose. This reads a directory produced by the Phase 8 stem
splitter and prints what a chord engine would produce: measured tuning, a
beat-synchronous chord chart with a confidence per chord, a key estimate and
an inferred guitar tuning.

Nothing here is wired into the backend. It exists to answer one question
before Phase 9 is built at all: is the chord detection good enough to be
worth shipping, and does its confidence signal actually track correctness?

Usage:
    python tools/chord_probe.py storage/splits/<splitId>
    python tools/chord_probe.py storage/splits/<splitId> --max-seconds 60
    python tools/chord_probe.py storage/splits/<splitId> --json probe.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ANALYSIS_SR = 22050
HOP = 512
BEATS_PER_BAR = 4

# Stems that carry harmony. Whichever exist get summed; a 4-stem split just
# contributes bass + other.
HARMONIC_STEMS = ("bass", "other", "guitar", "piano")

SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

MAJ = (0, 4, 7)
MIN = (0, 3, 7)
N_CHORD = 24  # index of the "no chord" state

# Shapes a guitarist can play open. Used to infer tuning and capo: whichever
# transposition puts the most of the song's duration onto these shapes is the
# one the band was most likely fingering.
OPEN_SHAPES = {"E", "A", "D", "G", "C", "Em", "Am", "Dm"}

# Major-scale degrees, for the key estimate.
MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
KRUMHANSL_MAJOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
KRUMHANSL_MINOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)


def chord_name(index: int, flats: bool = False) -> str:
    if index == N_CHORD:
        return "N"
    names = FLAT if flats else SHARP
    root = index % 12
    return names[root] + ("" if index < 12 else "m")


def transpose_chord(index: int, semitones: int) -> int:
    if index == N_CHORD:
        return N_CHORD
    quality = 0 if index < 12 else 12
    return ((index % 12) + semitones) % 12 + quality


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def load_stems(stems_dir: Path, max_seconds: float | None) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Return (harmonic, bass, drums, duration). Missing stems are silent."""
    import librosa

    found: dict[str, np.ndarray] = {}
    for name in HARMONIC_STEMS + ("drums",):
        path = stems_dir / f"{name}.wav"
        if not path.exists():
            continue
        y, _ = librosa.load(path, sr=ANALYSIS_SR, mono=True, duration=max_seconds)
        found[name] = y

    if not found:
        raise SystemExit(f"No stems found in {stems_dir}")

    length = max(len(y) for y in found.values())

    def padded(name: str) -> np.ndarray:
        y = found.get(name)
        if y is None:
            return np.zeros(length, dtype=np.float32)
        if len(y) < length:
            return np.pad(y, (0, length - len(y)))
        return y

    harmonic = np.zeros(length, dtype=np.float32)
    present = []
    for name in HARMONIC_STEMS:
        if name in found:
            harmonic += padded(name)
            present.append(name)

    peak = float(np.max(np.abs(harmonic))) or 1.0
    harmonic = harmonic / peak

    print(f"  harmonic stems: {' + '.join(present)}")
    return harmonic, padded("bass"), padded("drums"), length / ANALYSIS_SR


# ---------------------------------------------------------------------------
# tuning
# ---------------------------------------------------------------------------


def measure_tuning(harmonic: np.ndarray) -> dict:
    """Deviation from the A440 grid, plus how stable that deviation is.

    A steady offset is the band's tuning reference. A drifting one means the
    upload was speed-changed, which is a different problem with a different
    fix, so the two are reported separately.
    """
    import librosa

    overall = float(librosa.estimate_tuning(y=harmonic, sr=ANALYSIS_SR))

    window = ANALYSIS_SR * 30
    per_window = []
    for start in range(0, len(harmonic), window):
        chunk = harmonic[start : start + window]
        if len(chunk) < ANALYSIS_SR * 5:
            continue
        if float(np.max(np.abs(chunk))) < 1e-3:
            continue
        per_window.append(float(librosa.estimate_tuning(y=chunk, sr=ANALYSIS_SR)))

    spread = float(np.std(per_window)) * 100 if per_window else 0.0
    return {
        "cents": overall * 100,
        "windowSpreadCents": spread,
        "stable": spread < 8.0,
        "windows": [round(v * 100, 1) for v in per_window],
    }


def lowest_sustained_note(bass: np.ndarray, tuning: float) -> str | None:
    """Lowest pitch the bass actually sits on, as a tuning hint.

    Uses the CQT rather than pyin: a pitch tracker over five minutes is slow
    and we only need the bottom of the range, not a melody.
    """
    import librosa

    if float(np.max(np.abs(bass))) < 1e-4:
        return None

    fmin = librosa.note_to_hz("C1")
    cqt = np.abs(librosa.cqt(y=bass, sr=ANALYSIS_SR, hop_length=HOP, fmin=fmin, n_bins=48, bins_per_octave=12, tuning=tuning))

    lows = []
    for frame in range(cqt.shape[1]):
        column = cqt[:, frame]
        peak = float(column.max())
        if peak < 1e-3:
            continue
        strong = np.nonzero(column > peak * 0.35)[0]
        if len(strong):
            lows.append(int(strong[0]))

    if len(lows) < 20:
        return None

    # 5th percentile, not the minimum: one stray frame should not define the
    # bottom of the range.
    bin_index = int(np.percentile(lows, 5))
    midi = librosa.hz_to_midi(fmin) + bin_index
    return str(librosa.midi_to_note(int(round(midi))))


def infer_guitar_tuning(events: list[dict]) -> dict:
    """Score how playable the song is once transposed, and read tuning off that.

    Chord recognition returns sounding pitches, which are correct whatever the
    guitar is tuned to. What tuning changes is the shape under the fingers, so
    the question is which transposition puts the most of the song onto open
    shapes.
    """
    total = sum(e["duration"] for e in events if e["index"] != N_CHORD) or 1.0

    def score(shift: int) -> float:
        hit = 0.0
        for event in events:
            if event["index"] == N_CHORD:
                continue
            if chord_name(transpose_chord(event["index"], shift)) in OPEN_SHAPES:
                hit += event["duration"]
        return hit / total

    down = {shift: score(shift) for shift in range(0, 4)}
    capo = {fret: score(-fret) for fret in range(0, 6)}

    best_down = max(down, key=lambda k: down[k])
    best_capo = max(capo, key=lambda k: capo[k])

    labels = {0: "E Standard", 1: "Eb Standard (half step down)", 2: "D Standard (whole step down)", 3: "C# Standard"}
    margin = down[best_down] - down[0]

    return {
        "tuning": labels.get(best_down, f"down {best_down} semitones"),
        "semitoneShift": best_down,
        "openShapeCoverage": round(down[best_down], 3),
        "standardCoverage": round(down[0], 3),
        "confidence": round(min(1.0, max(0.0, margin * 4)), 2) if best_down else round(down[0], 2),
        "capoSuggestion": best_capo,
        "capoCoverage": round(capo[best_capo], 3),
        "allShifts": {k: round(v, 3) for k, v in down.items()},
    }


# ---------------------------------------------------------------------------
# chord decoding
# ---------------------------------------------------------------------------


def build_templates() -> np.ndarray:
    """24 triad templates with a harmonic series behind each chord tone.

    Binary templates measurably underperform: real instruments put energy on
    partials, so the third harmonic of the root lands on the fifth and a flat
    template mistakes that for chord tone evidence.
    """
    templates = np.zeros((25, 12), dtype=np.float64)
    partials = [(0, 1.0), (12, 0.6), (19, 0.36), (24, 0.22), (28, 0.13), (31, 0.08)]

    for root in range(12):
        for offset, intervals in ((0, MAJ), (12, MIN)):
            vector = np.zeros(12)
            for position, interval in enumerate(intervals):
                # the root carries a little more weight than the upper voices
                voice = 1.0 if position == 0 else 0.8
                for semitone, amplitude in partials:
                    pc = (root + interval + semitone) % 12
                    vector[pc] += amplitude * voice
            templates[root + offset] = vector / np.linalg.norm(vector)

    templates[N_CHORD] = np.ones(12) / np.sqrt(12)
    return templates


def build_transitions(stay: float = 0.72) -> np.ndarray:
    """Chords persist, and when they move they move to near neighbours."""
    fifths = {(i * 7) % 12: i for i in range(12)}

    def circle_distance(a: int, b: int) -> int:
        pos_a, pos_b = fifths[a % 12], fifths[b % 12]
        raw = abs(pos_a - pos_b)
        return min(raw, 12 - raw)

    matrix = np.zeros((25, 25))
    for i in range(25):
        for j in range(25):
            if i == j:
                continue
            if i == N_CHORD or j == N_CHORD:
                matrix[i, j] = 0.35
                continue
            distance = circle_distance(i % 12, j % 12)
            quality_change = 0.6 if (i < 12) != (j < 12) else 0.0
            matrix[i, j] = np.exp(-(distance + quality_change) / 1.6)

    for i in range(25):
        row = matrix[i]
        total = row.sum()
        if total > 0:
            matrix[i] = row / total * (1.0 - stay)
        matrix[i, i] = stay
    return matrix


def decode_chords(harmonic: np.ndarray, bass: np.ndarray, drums: np.ndarray, tuning: float, bass_weight: float, stay: float, temperature: float) -> dict:
    import librosa

    # Beats come off the drum stem. Tracking beats on a full mix is a coin
    # flip on anything dense; on an isolated kit it is nearly free.
    beat_source = drums if float(np.max(np.abs(drums))) > 1e-4 else harmonic
    tempo, beats = librosa.beat.beat_track(y=beat_source, sr=ANALYSIS_SR, hop_length=HOP, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])

    # Percussive energy smears chroma, so strip it before the CQT even though
    # the harmonic stems are already drum-free: guitars have transients too.
    harm, _ = librosa.effects.hpss(harmonic)

    chroma = librosa.feature.chroma_cqt(
        y=harm, sr=ANALYSIS_SR, hop_length=HOP, tuning=tuning, bins_per_octave=36, n_chroma=12
    )
    bass_chroma = librosa.feature.chroma_cqt(
        y=bass, sr=ANALYSIS_SR, hop_length=HOP, tuning=tuning, bins_per_octave=36, n_chroma=12
    )

    if len(beats) < 4:
        raise SystemExit("Beat tracking failed - too few beats detected.")

    beat_chroma = librosa.util.sync(chroma, beats, aggregate=np.median)
    beat_bass = librosa.util.sync(bass_chroma, beats, aggregate=np.median)
    beat_times = librosa.frames_to_time(beats, sr=ANALYSIS_SR, hop_length=HOP)

    templates = build_templates()
    n_beats = beat_chroma.shape[1]

    norms = np.linalg.norm(beat_chroma, axis=0)
    energy = norms / (np.median(norms) or 1.0)
    normalised = beat_chroma / np.maximum(norms, 1e-8)
    bass_norms = np.linalg.norm(beat_bass, axis=0)
    bass_normalised = beat_bass / np.maximum(bass_norms, 1e-8)

    scores = templates @ normalised  # (25, n_beats)

    # The bass stem is a strong root cue and costs nothing to fold in.
    for chord in range(24):
        scores[chord] += bass_weight * bass_normalised[chord % 12]

    # Silence and washes of noise should read as "no chord" rather than being
    # forced onto the nearest triad.
    scores[N_CHORD] = 0.55 + np.clip(0.4 - energy, 0, None)

    probability = np.exp((scores - scores.max(axis=0)) / temperature)
    probability /= probability.sum(axis=0, keepdims=True)

    transitions = build_transitions(stay)
    path = librosa.sequence.viterbi(probability, transitions)

    # Confidence: how far clear the decoded chord is of its best rival on the
    # raw evidence, before smoothing talked us into it.
    confidences = np.zeros(n_beats)
    for beat in range(n_beats):
        chosen = probability[path[beat], beat]
        rivals = np.delete(probability[:, beat], path[beat])
        best_rival = float(rivals.max())
        confidences[beat] = chosen / (chosen + best_rival + 1e-9)

    events = []
    start = 0
    for beat in range(1, n_beats + 1):
        if beat < n_beats and path[beat] == path[start]:
            continue
        end_time = float(beat_times[beat]) if beat < n_beats else float(beat_times[-1])
        events.append(
            {
                "index": int(path[start]),
                "label": chord_name(int(path[start])),
                "start": float(beat_times[start]),
                "end": end_time,
                "duration": end_time - float(beat_times[start]),
                "beats": beat - start,
                "confidence": round(float(np.mean(confidences[start:beat])), 3),
            }
        )
        start = beat

    return {
        "tempo": tempo,
        "beatTimes": beat_times,
        "events": events,
        "beatConfidence": confidences,
        "chroma": beat_chroma,
    }


# ---------------------------------------------------------------------------
# key
# ---------------------------------------------------------------------------


def estimate_key(events: list[dict], chroma: np.ndarray) -> dict:
    """Two independent estimates. Agreement is itself a confidence signal."""
    weights = np.zeros(24)
    for event in events:
        if event["index"] != N_CHORD:
            weights[event["index"]] += event["duration"]

    best_key, best_score = None, -1.0
    for tonic in range(12):
        for mode, offset in (("major", 0), ("minor", 3)):
            scale = {(tonic + step) % 12 for step in MAJOR_SCALE} if mode == "major" else {
                (tonic + step) % 12 for step in (0, 2, 3, 5, 7, 8, 10)
            }
            score = 0.0
            for chord in range(24):
                if weights[chord] == 0:
                    continue
                root = chord % 12
                triad = MAJ if chord < 12 else MIN
                if all((root + i) % 12 in scale for i in triad):
                    score += weights[chord]
                    if root == tonic:
                        score += weights[chord] * 0.4
            if score > best_score:
                best_key, best_score = f"{SHARP[tonic]} {mode}", score

    profile = chroma.mean(axis=1)
    profile = profile / (np.linalg.norm(profile) or 1.0)
    kr_best, kr_score = None, -1.0
    for tonic in range(12):
        for name, template in (("major", KRUMHANSL_MAJOR), ("minor", KRUMHANSL_MINOR)):
            rotated = np.roll(template, tonic)
            rotated = rotated / np.linalg.norm(rotated)
            score = float(profile @ rotated)
            if score > kr_score:
                kr_best, kr_score = f"{SHARP[tonic]} {name}", score

    return {"fromChords": best_key, "fromChroma": kr_best, "agree": best_key == kr_best}


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def print_chart(events: list[dict], low_confidence: float) -> None:
    line: list[str] = []
    bar_start = 0.0
    for event in events:
        marker = "?" if event["confidence"] < low_confidence else " "
        cell = f"{event['label']}{marker}"
        if not line:
            bar_start = event["start"]
        line.append(f"{cell:<6}")
        if len(line) == 4:
            print(f"  {int(bar_start // 60):d}:{bar_start % 60:05.2f}  | " + "| ".join(line) + "|")
            line = []
    if line:
        print(f"  {int(bar_start // 60):d}:{bar_start % 60:05.2f}  | " + "| ".join(line) + "|")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("split_dir", type=Path, help="storage/splits/<splitId>")
    parser.add_argument("--max-seconds", type=float, default=None, help="analyse only the first N seconds")
    parser.add_argument("--bass-weight", type=float, default=0.35, help="how hard the bass stem votes on the root")
    parser.add_argument("--low-confidence", type=float, default=0.62, help="chords below this are flagged with ?")
    parser.add_argument("--stay", type=float, default=0.72, help="Viterbi self-transition; lower = chords change more freely")
    parser.add_argument("--temperature", type=float, default=0.06, help="emission softmax temperature; higher = softer evidence")
    parser.add_argument("--json", type=Path, default=None, help="also write the full result as JSON")
    args = parser.parse_args()

    stems_dir = args.split_dir / "stems"
    if not stems_dir.is_dir():
        stems_dir = args.split_dir
    if not stems_dir.is_dir():
        raise SystemExit(f"Not a directory: {args.split_dir}")

    started = time.time()
    print(f"\nProbing {args.split_dir}")
    harmonic, bass, drums, duration = load_stems(stems_dir, args.max_seconds)
    print(f"  duration: {duration:.1f}s  loaded in {time.time() - started:.1f}s\n")

    tuning = measure_tuning(harmonic)
    semitone_offset = tuning["cents"] / 100.0
    low_note = lowest_sustained_note(bass, semitone_offset)

    result = decode_chords(harmonic, bass, drums, semitone_offset, args.bass_weight, args.stay, args.temperature)
    events = result["events"]
    key = estimate_key(events, result["chroma"])
    guitar = infer_guitar_tuning(events)

    playing = [e for e in events if e["index"] != N_CHORD]
    confidences = [e["confidence"] for e in playing]
    flagged = [e for e in playing if e["confidence"] < args.low_confidence]
    covered = sum(e["duration"] for e in playing)

    print("TUNING")
    print(f"  reference offset   {tuning['cents']:+.1f} cents  ({'stable' if tuning['stable'] else 'DRIFTING - check for a speed-changed upload'})")
    print(f"  window spread      {tuning['windowSpreadCents']:.1f} cents")
    print(f"  lowest bass note   {low_note or 'n/a'}")
    print(f"  inferred tuning    {guitar['tuning']}  (confidence {guitar['confidence']})")
    print(f"  open-shape cover   {guitar['openShapeCoverage']:.0%} shifted vs {guitar['standardCoverage']:.0%} as played")
    print(f"  capo suggestion    fret {guitar['capoSuggestion']} ({guitar['capoCoverage']:.0%} open shapes)")

    print("\nMUSIC")
    print(f"  tempo              {result['tempo']:.1f} BPM")
    print(f"  key (from chords)  {key['fromChords']}")
    print(f"  key (from chroma)  {key['fromChroma']}   {'agree' if key['agree'] else 'DISAGREE'}")

    print("\nCHORDS")
    print(f"  {len(playing)} chord events over {covered:.0f}s ({covered / duration:.0%} of the track)")
    print(f"  distinct chords    {len({e['label'] for e in playing})}")
    print(f"  mean confidence    {np.mean(confidences):.3f}   median {np.median(confidences):.3f}")
    print(f"  flagged low        {len(flagged)} of {len(playing)} ({len(flagged) / max(1, len(playing)):.0%})")

    print("\nCHART  (? = low confidence)")
    print_chart(events, args.low_confidence)

    elapsed = time.time() - started
    print(f"\nDone in {elapsed:.1f}s ({duration / max(elapsed, 0.01):.1f}x realtime)\n")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "splitDir": str(args.split_dir),
                    "durationSeconds": duration,
                    "tuning": tuning,
                    "lowestBassNote": low_note,
                    "guitarTuning": guitar,
                    "tempo": result["tempo"],
                    "key": key,
                    "events": events,
                    "elapsedSeconds": elapsed,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Wrote {args.json}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
