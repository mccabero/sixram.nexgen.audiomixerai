"""Phase 9 - chord and tuning analysis.

Pure DSP. Nothing here touches FastAPI, the metadata store or the filesystem
beyond reading the stem files it is handed, so it stays testable on its own
and the orchestration in chord_sheet.py can be reasoned about separately.

The engine takes the stems the Phase 8 splitter already produced:

  harmony   bass + other + guitar + piano   chroma, and the chords themselves
  drums     the kit on its own              the beat grid
  bass      the low end on its own          a root cue the chroma cannot give

What it deliberately does NOT do is claim an instrument tuning. Chord
recognition returns sounding pitches, which are correct whatever the guitar is
tuned to; the tuning only decides which shape a player fingers. Inferring that
shape from a mix is not reliable - separation bleed puts energy well below a
guitar's low E - so the engine reports ranked suggestions and leaves standard
tuning as the default until a person says otherwise.
"""

from __future__ import annotations

import numpy as np

from .config import (
    ANALYSIS_HOP,
    ANALYSIS_SR,
    BEATS_PER_BAR,
    CHORD_HARMONY_STEMS,
    LOW_CONFIDENCE,
    OPEN_SHAPES,
    TUNING_LABELS,
)

SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

MAJ = (0, 4, 7)
MIN = (0, 3, 7)
N_CHORD = 24

MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)

KRUMHANSL_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KRUMHANSL_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Keys whose signature is written with flats. A sheet in G minor reads Bb and
# Eb; printing A# and D# is the fastest way to look like a machine wrote it.
FLAT_KEYS = {"F major", "Bb major", "Eb major", "Ab major", "Db major", "Gb major",
             "D minor", "G minor", "C minor", "F minor", "Bb minor", "Eb minor"}

# A guitar's lowest string in standard tuning. Anything the analysis finds
# below this is either a detuned instrument or, far more often, bleed.
GUITAR_LOW_E_MIDI = 40  # E2


class AnalysisCancelled(Exception):
    """Raised from the progress callback when the caller wants out."""


# Flat spellings almost nobody writes. A chromatic chord in a flat key still
# reads F#m, not Gbm - the flat signature governs the diatonic notes, not every
# accidental that wanders through.
AWKWARD_FLATS = {"Gb": "F#", "Cb": "B", "Fb": "E"}


def chord_name(index: int, flats: bool = False, key_root: str | None = None) -> str:
    if index == N_CHORD:
        return "N"
    root = (FLAT if flats else SHARP)[index % 12]
    if flats and root in AWKWARD_FLATS and root != key_root:
        root = AWKWARD_FLATS[root]
    return root + ("" if index < 12 else "m")


def transpose_chord(index: int, semitones: int) -> int:
    if index == N_CHORD:
        return N_CHORD
    quality = 0 if index < 12 else 12
    return ((index % 12) + semitones) % 12 + quality


def _tick(progress, fraction: float, message: str) -> None:
    if progress is not None and progress(fraction, message) is False:
        raise AnalysisCancelled()


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def load_stems(stems_dir, max_seconds: float | None = None) -> dict:
    """Sum the harmonic stems, and keep drums and bass separately."""
    import librosa

    found: dict[str, np.ndarray] = {}
    for name in list(CHORD_HARMONY_STEMS) + ["drums"]:
        path = stems_dir / f"{name}.wav"
        if not path.exists():
            continue
        audio, _ = librosa.load(path, sr=ANALYSIS_SR, mono=True, duration=max_seconds)
        found[name] = audio

    if not found:
        raise ValueError(f"No usable stems in {stems_dir}")

    length = max(len(a) for a in found.values())

    def padded(name: str) -> np.ndarray:
        audio = found.get(name)
        if audio is None:
            return np.zeros(length, dtype=np.float32)
        if len(audio) < length:
            return np.pad(audio, (0, length - len(audio)))
        return audio

    harmony = np.zeros(length, dtype=np.float32)
    used = []
    for name in CHORD_HARMONY_STEMS:
        if name in found:
            harmony += padded(name)
            used.append(name)

    peak = float(np.max(np.abs(harmony))) or 1.0
    return {
        "harmony": harmony / peak,
        "bass": padded("bass"),
        "drums": padded("drums"),
        "guitar": padded("guitar"),
        "durationSeconds": length / ANALYSIS_SR,
        "stemsUsed": used,
    }


# ---------------------------------------------------------------------------
# tuning
# ---------------------------------------------------------------------------


def measure_tuning(harmony: np.ndarray) -> dict:
    """Deviation from the A440 grid, and whether it holds across the track.

    A steady offset is a tuning reference. A drifting one means the source was
    speed-changed, which is a different problem needing a different fix, so the
    two are reported apart rather than averaged into one number.
    """
    import librosa

    overall = float(librosa.estimate_tuning(y=harmony, sr=ANALYSIS_SR))

    window = ANALYSIS_SR * 30
    per_window = []
    for start in range(0, len(harmony), window):
        chunk = harmony[start : start + window]
        if len(chunk) < ANALYSIS_SR * 5 or float(np.max(np.abs(chunk))) < 1e-3:
            continue
        per_window.append(float(librosa.estimate_tuning(y=chunk, sr=ANALYSIS_SR)) * 100)

    spread = float(np.std(per_window)) if per_window else 0.0
    return {
        "cents": round(overall * 100, 1),
        "spreadCents": round(spread, 1),
        "stable": bool(spread < 8.0),
        "semitoneOffset": overall,
    }


def speed_ratio(actual_seconds: float, reference_seconds: float | None) -> dict | None:
    """Catch an upload that was sped up or slowed to dodge Content ID.

    A few percent of speed change is a few percent of pitch change, which is
    enough to put every chord on the wrong root. It is invisible to a tuning
    estimator - the whole track moves together - but it shows up plainly as a
    duration that does not match the release.
    """
    if not reference_seconds or not actual_seconds or reference_seconds <= 0:
        return None
    ratio = actual_seconds / reference_seconds
    if abs(ratio - 1.0) < 0.005:
        return {"ratio": round(ratio, 4), "altered": False, "cents": 0.0}
    return {
        "ratio": round(ratio, 4),
        "altered": True,
        # slower upload => lower pitch => positive correction needed
        "cents": round(1200.0 * np.log2(1.0 / ratio), 1),
    }


def lowest_sustained_midi(audio: np.ndarray, floor_note: str = "E1") -> int | None:
    """Bottom of an instrument's range, judged against the whole track.

    Thresholding per frame picks up room rumble and separation bleed in the
    quiet moments; thresholding against the track's own maximum does not.
    """
    import librosa

    if float(np.max(np.abs(audio))) < 1e-4:
        return None

    fmin = librosa.note_to_hz(floor_note)
    cqt = np.abs(librosa.cqt(y=audio, sr=ANALYSIS_SR, hop_length=ANALYSIS_HOP, fmin=fmin, n_bins=48, bins_per_octave=12))
    ceiling = float(cqt.max())
    if ceiling <= 0:
        return None

    lows = []
    for frame in range(cqt.shape[1]):
        column = cqt[:, frame]
        if float(column.max()) < ceiling * 0.08:
            continue
        strong = np.nonzero(column > ceiling * 0.04)[0]
        if len(strong):
            lows.append(int(strong[0]))

    if len(lows) < 40:
        return None
    return int(round(librosa.hz_to_midi(fmin) + int(np.percentile(lows, 10))))


def tuning_suggestions(events: list[dict], guitar_low_midi: int | None, bass_low_midi: int | None = None) -> dict:
    """Rank tunings by how much of the song they put onto open shapes.

    Coverage is a fact about the chords; it is not on its own evidence that a
    guitar was detuned, because a flat key scores exactly the same way. A song
    in G minor looks "tuned down a whole step" to a shape counter and is
    nothing of the sort. So standard tuning stays the default and the rest are
    offered as alternatives with their numbers shown.
    """
    playing = [e for e in events if e["index"] != N_CHORD]
    total = sum(e["duration"] for e in playing) or 1.0

    def coverage(shift: int) -> float:
        hit = sum(e["duration"] for e in playing if chord_name(transpose_chord(e["index"], shift)) in OPEN_SHAPES)
        return hit / total

    options = []
    for shift in range(0, 4):
        options.append(
            {
                "semitoneShift": shift,
                "label": TUNING_LABELS.get(shift, f"Down {shift} semitones"),
                "openShapeCoverage": round(coverage(shift), 3),
            }
        )

    capo = [{"fret": fret, "openShapeCoverage": round(coverage(-fret), 3)} for fret in range(0, 6)]
    best_capo = max(capo, key=lambda c: c["openShapeCoverage"])

    ranked = sorted(options, key=lambda o: -o["openShapeCoverage"])
    standard = options[0]
    margin = ranked[0]["openShapeCoverage"] - standard["openShapeCoverage"]

    # The only signal that would actually say "detuned" is a guitar sounding
    # below where it can reach in standard tuning. On a separated stem that
    # signal is not trustworthy: Demucs leaks bass and kick into the guitar
    # stem, and on the Toto reference track it put the guitar's "lowest note"
    # a whole tone under the low E of a guitar that was never detuned.
    below_standard = 0
    if guitar_low_midi is not None:
        below_standard = max(0, GUITAR_LOW_E_MIDI - guitar_low_midi)

    # If the guitar's floor sits in or under the bass's range, we are reading
    # bleed, not a guitar string.
    bleed = bass_low_midi is not None and guitar_low_midi is not None and guitar_low_midi <= bass_low_midi + 2
    if bleed:
        below_standard = 0

    if below_standard and ranked[0]["semitoneShift"] == below_standard and margin > 0.15:
        evidence = "weak"
    elif bleed:
        evidence = "inconclusive - guitar stem overlaps the bass"
    elif margin > 0.15:
        evidence = "shape coverage only - a flat key looks the same"
    else:
        evidence = "none"

    # Standard tuning is always what the sheet is written in until a person
    # says otherwise. Coverage is a fact about the chords, never on its own a
    # reason to re-spell the whole song: a track in G minor scores exactly
    # like a guitar tuned down a whole step, and is nothing of the sort.
    suggested = ranked[0] if ranked[0]["semitoneShift"] and margin > 0.15 else None

    return {
        "assumed": standard["label"],
        "semitoneShift": 0,
        "confidence": round(min(0.3, margin), 2),
        "evidence": evidence,
        "suggested": suggested,
        "lowestGuitarNote": _note_name(guitar_low_midi),
        "semitonesBelowStandard": below_standard,
        "bleedSuspected": bool(bleed),
        "options": options,
        "capoSuggestion": best_capo["fret"],
        "capoCoverage": best_capo["openShapeCoverage"],
    }


def _note_name(midi: int | None) -> str | None:
    if midi is None:
        return None
    import librosa

    return str(librosa.midi_to_note(int(midi)))


# ---------------------------------------------------------------------------
# chords
# ---------------------------------------------------------------------------


def build_templates() -> np.ndarray:
    """Triad templates carrying a harmonic series, not flat bit masks.

    Real instruments put energy on partials: the third harmonic of the root
    lands on the fifth. A binary template reads that partial as independent
    evidence for the fifth and scores related chords too closely together.
    """
    templates = np.zeros((25, 12), dtype=np.float64)
    partials = [(0, 1.0), (12, 0.6), (19, 0.36), (24, 0.22), (28, 0.13), (31, 0.08)]

    for root in range(12):
        for offset, intervals in ((0, MAJ), (12, MIN)):
            vector = np.zeros(12)
            for position, interval in enumerate(intervals):
                voice = 1.0 if position == 0 else 0.8
                for semitone, amplitude in partials:
                    vector[(root + interval + semitone) % 12] += amplitude * voice
            templates[root + offset] = vector / np.linalg.norm(vector)

    templates[N_CHORD] = np.ones(12) / np.sqrt(12)
    return templates


def build_transitions(stay: float = 0.72) -> np.ndarray:
    """Chords persist; when they move they move to near neighbours."""
    fifths = {(i * 7) % 12: i for i in range(12)}

    def circle_distance(a: int, b: int) -> int:
        raw = abs(fifths[a % 12] - fifths[b % 12])
        return min(raw, 12 - raw)

    matrix = np.zeros((25, 25))
    for i in range(25):
        for j in range(25):
            if i == j:
                continue
            if i == N_CHORD or j == N_CHORD:
                matrix[i, j] = 0.35
                continue
            quality_change = 0.6 if (i < 12) != (j < 12) else 0.0
            matrix[i, j] = np.exp(-(circle_distance(i % 12, j % 12) + quality_change) / 1.6)

    for i in range(25):
        total = matrix[i].sum()
        if total > 0:
            matrix[i] = matrix[i] / total * (1.0 - stay)
        matrix[i, i] = stay
    return matrix


def track_beats(drums: np.ndarray, harmony: np.ndarray) -> tuple[float, np.ndarray]:
    """Beat grid off the drum stem, seeded so it cannot land an octave out.

    librosa's default start_bpm of 120 pulled a 86 BPM shuffle up to 161 on the
    full track while getting it right on a 45 second excerpt. Seeding the
    tracker from the median of its own tempo curve removes the ambiguity.
    """
    import librosa
    import librosa.feature.rhythm as librosa_rhythm

    source = drums if float(np.max(np.abs(drums))) > 1e-4 else harmony
    onset = librosa.onset.onset_strength(y=source, sr=ANALYSIS_SR, hop_length=ANALYSIS_HOP, aggregate=np.median)

    try:
        curve = librosa_rhythm.tempo(onset_envelope=onset, sr=ANALYSIS_SR, hop_length=ANALYSIS_HOP, aggregate=None)
    except Exception:
        curve = librosa.beat.tempo(onset_envelope=onset, sr=ANALYSIS_SR, hop_length=ANALYSIS_HOP, aggregate=None)

    seed = float(np.median(np.atleast_1d(curve)))
    while seed > 150:
        seed /= 2
    while seed < 65 and seed > 0:
        seed *= 2

    tempo, beats = librosa.beat.beat_track(
        onset_envelope=onset, sr=ANALYSIS_SR, hop_length=ANALYSIS_HOP, start_bpm=seed, units="frames"
    )
    return float(np.atleast_1d(tempo)[0]), beats


def decode_chords(
    harmony: np.ndarray,
    bass: np.ndarray,
    drums: np.ndarray,
    semitone_offset: float,
    bass_weight: float = 0.35,
    stay: float = 0.72,
    temperature: float = 0.06,
    progress=None,
) -> dict:
    import librosa

    _tick(progress, 0.10, "Tracking the beat...")
    tempo, beats = track_beats(drums, harmony)
    if len(beats) < 4:
        raise ValueError("Beat tracking failed - too few beats detected.")

    _tick(progress, 0.25, "Separating harmonic content...")
    harmonic_part, _ = librosa.effects.hpss(harmony)

    _tick(progress, 0.45, "Building chroma...")
    chroma = librosa.feature.chroma_cqt(
        y=harmonic_part, sr=ANALYSIS_SR, hop_length=ANALYSIS_HOP, tuning=semitone_offset, bins_per_octave=36, n_chroma=12
    )
    bass_chroma = librosa.feature.chroma_cqt(
        y=bass, sr=ANALYSIS_SR, hop_length=ANALYSIS_HOP, tuning=semitone_offset, bins_per_octave=36, n_chroma=12
    )

    _tick(progress, 0.65, "Decoding chords...")
    beat_chroma = librosa.util.sync(chroma, beats, aggregate=np.median)
    beat_bass = librosa.util.sync(bass_chroma, beats, aggregate=np.median)
    beat_times = librosa.frames_to_time(beats, sr=ANALYSIS_SR, hop_length=ANALYSIS_HOP)

    templates = build_templates()
    n_beats = beat_chroma.shape[1]

    norms = np.linalg.norm(beat_chroma, axis=0)
    energy = norms / (np.median(norms) or 1.0)
    normalised = beat_chroma / np.maximum(norms, 1e-8)
    bass_normalised = beat_bass / np.maximum(np.linalg.norm(beat_bass, axis=0), 1e-8)

    scores = templates @ normalised
    for chord in range(24):
        scores[chord] += bass_weight * bass_normalised[chord % 12]
    scores[N_CHORD] = 0.55 + np.clip(0.4 - energy, 0, None)

    probability = np.exp((scores - scores.max(axis=0)) / temperature)
    probability /= probability.sum(axis=0, keepdims=True)

    path = librosa.sequence.viterbi(probability, build_transitions(stay))

    # Confidence is the margin on the raw evidence, before smoothing talked us
    # into the answer - otherwise a long confident-looking run of one chord is
    # just the transition prior admiring itself.
    confidences = np.zeros(n_beats)
    for beat in range(n_beats):
        chosen = probability[path[beat], beat]
        best_rival = float(np.delete(probability[:, beat], path[beat]).max())
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
                "start": round(float(beat_times[start]), 3),
                "end": round(end_time, 3),
                "duration": round(end_time - float(beat_times[start]), 3),
                "beats": beat - start,
                "beatIndex": start,
                "bar": start // BEATS_PER_BAR,
                "confidence": round(float(np.mean(confidences[start:beat])), 3),
            }
        )
        start = beat

    return {
        "tempo": round(tempo, 1),
        "beatTimes": [round(float(t), 3) for t in beat_times],
        "events": events,
        "chroma": beat_chroma,
    }


def estimate_key(events: list[dict], chroma: np.ndarray) -> dict:
    """Two independent estimates; whether they agree is itself the confidence."""
    weights = np.zeros(24)
    for event in events:
        if event["index"] != N_CHORD:
            weights[event["index"]] += event["duration"]

    best_key, best_score = "C major", -1.0
    for tonic in range(12):
        for mode, degrees in (("major", MAJOR_SCALE), ("minor", MINOR_SCALE)):
            scale = {(tonic + step) % 12 for step in degrees}
            score = 0.0
            for chord in range(24):
                if weights[chord] == 0:
                    continue
                root = chord % 12
                triad = MAJ if chord < 12 else MIN
                if all((root + i) % 12 in scale for i in triad):
                    score += weights[chord] * (1.4 if root == tonic else 1.0)
            if score > best_score:
                best_key, best_score = f"{SHARP[tonic]} {mode}", score

    profile = chroma.mean(axis=1)
    profile = profile / (np.linalg.norm(profile) or 1.0)
    chroma_key, chroma_score = "C major", -1.0
    for tonic in range(12):
        for mode, template in (("major", KRUMHANSL_MAJOR), ("minor", KRUMHANSL_MINOR)):
            rotated = np.roll(template, tonic)
            score = float(profile @ (rotated / np.linalg.norm(rotated)))
            if score > chroma_score:
                chroma_key, chroma_score = f"{SHARP[tonic]} {mode}", score

    # Spell the sheet the way the key is written, not the way the index falls.
    flats = _prefers_flats(best_key)
    return {
        "key": _respell(best_key, flats),
        "fromChords": _respell(best_key, flats),
        "fromChroma": _respell(chroma_key, _prefers_flats(chroma_key)),
        "agree": best_key == chroma_key,
        "useFlats": flats,
    }


def spelling_after_shift(key: str, shift: int) -> tuple[bool, str]:
    """Whether the sheet reads in flats once transposed, and its new tonic.

    Spelling has to follow the key the player is reading, not the key it was
    recorded in. G minor transposed up a semitone is G# minor with five sharps,
    not Ab minor with seven flats, so the same chord prints C#m rather than
    Dbm even though the recording was written flat.
    """
    root, mode = key.split(" ")
    index = (SHARP.index(root) if root in SHARP else FLAT.index(root))
    shifted = (index + shift) % 12
    flats = f"{FLAT[shifted]} {mode}" in FLAT_KEYS
    return flats, (FLAT if flats else SHARP)[shifted]


def _prefers_flats(key: str) -> bool:
    if key in FLAT_KEYS:
        return True
    root = key.split(" ")[0]
    return root in {"A#", "D#", "G#", "C#", "F#"} and key.endswith("minor")


def _respell(key: str, flats: bool) -> str:
    root, mode = key.split(" ")
    if not flats:
        return key
    return f"{FLAT[SHARP.index(root)]} {mode}"


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------


def analyse(stems_dir, reference_seconds: float | None = None, max_seconds: float | None = None, progress=None) -> dict:
    """Run the whole analysis over one split's stems."""
    _tick(progress, 0.02, "Loading stems...")
    stems = load_stems(stems_dir, max_seconds)

    _tick(progress, 0.06, "Measuring tuning...")
    tuning = measure_tuning(stems["harmony"])
    speed = speed_ratio(stems["durationSeconds"], reference_seconds)

    decoded = decode_chords(
        stems["harmony"], stems["bass"], stems["drums"], tuning["semitoneOffset"], progress=progress
    )

    _tick(progress, 0.82, "Estimating key...")
    key = estimate_key(decoded["events"], decoded["chroma"])
    flats = key["useFlats"]

    _tick(progress, 0.88, "Inferring tuning options...")
    guitar_low = lowest_sustained_midi(stems["guitar"]) if float(np.max(np.abs(stems["guitar"]))) > 1e-4 else None
    bass_low = lowest_sustained_midi(stems["bass"], floor_note="C1") if float(np.max(np.abs(stems["bass"]))) > 1e-4 else None
    tuning.update(tuning_suggestions(decoded["events"], guitar_low, bass_low))
    tuning["speed"] = speed

    key_root = key["key"].split(" ")[0]
    events = []
    for event in decoded["events"]:
        events.append(
            {
                "label": chord_name(event["index"], flats, key_root),
                "index": event["index"],
                "startSeconds": event["start"],
                "endSeconds": event["end"],
                "durationSeconds": event["duration"],
                "beats": event["beats"],
                "bar": event["bar"],
                "confidence": event["confidence"],
                "lowConfidence": event["confidence"] < LOW_CONFIDENCE,
                "edited": False,
            }
        )

    playing = [e for e in events if e["label"] != "N"]
    confidences = [e["confidence"] for e in playing] or [0.0]

    _tick(progress, 0.95, "Assembling sheet...")
    return {
        "durationSeconds": round(stems["durationSeconds"], 2),
        "stemsUsed": stems["stemsUsed"],
        "tempo": decoded["tempo"],
        "key": key,
        "tuning": tuning,
        "beatTimes": decoded["beatTimes"],
        "chords": events,
        "summary": {
            "chordCount": len(playing),
            "distinctChords": len({e["label"] for e in playing}),
            "meanConfidence": round(float(np.mean(confidences)), 3),
            "medianConfidence": round(float(np.median(confidences)), 3),
            "lowConfidenceCount": sum(1 for e in playing if e["lowConfidence"]),
            "lowConfidenceRatio": round(sum(1 for e in playing if e["lowConfidence"]) / max(1, len(playing)), 3),
        },
    }
