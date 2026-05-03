import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .audio_engine import extract_stem_detection_features
from .config import STEM_TYPES
from .logging_utils import append_project_log, utc_now_iso
from .models import Project, Stem
from .storage import (
    _find_project,
    _mark_type_dependent_mix_stale,
    filename_learning_tokens,
    project_subdirs,
    remember_filename_correction,
    resolve_stored_file_path,
    store,
)


DETECTION_THRESHOLD = 60

FILENAME_RULES = [
    ("Backing Vocal", 94, ["backingvocal", "backingvocals", "backing vocal", "backing vocals", "backingvox", "bgvox", "bvox", "bgv", "harmony", "harmonies", "backing"]),
    ("Lead Vocal", 95, ["leadvocal", "leadvox", "lead_vox", "lead_vocal", "vocal", "vox"]),
    ("Kick", 96, ["kick", "bd", "kickdrum", "kick drum"]),
    ("Snare", 96, ["snare", "snr", "sd"]),
    ("Drums", 92, ["drums", "drum", "kit", "drumkit", "overheads", "overhead", "oh", "room", "toms", "tom"]),
    ("Bass", 95, ["bass", "subbass", "sub_bass", "bassdi", "bass di", "hartke", "ampeg", "sansamp"]),
    ("Acoustic Guitar", 92, ["acoustic", "agtr", "acgtr", "acousticguitar", "acoustic guitar"]),
    ("Electric Guitar", 90, ["electricguitar", "electric guitar", "egtr", "eg", "gtr", "guitar", "elgtr", "fender", "laney", "marshall", "mesa", "orange", "peavey", "5150"]),
    ("Keys/Piano", 90, ["keyspiano", "keys", "piano", "synth", "organ", "rhodes", "wurlitzer", "wurli", "clav"]),
    ("Pads/Strings", 90, ["pad", "pads", "strings", "string", "violin", "cello", "orchestra", "choir"]),
    ("FX/Ambience", 90, ["fx", "sfx", "ambience", "ambiance", "ambient", "risers", "riser"]),
]

BRAND_HINT_CONFIDENCE = {
    "fender": 78,
    "laney": 82,
    "marshall": 82,
    "mesa": 80,
    "orange": 76,
    "peavey": 76,
    "5150": 78,
    "hartke": 84,
    "ampeg": 86,
    "sansamp": 82,
}

EXACT_FILENAME_ALIASES = {
    "eg": "Electric Guitar",
    "egtr": "Electric Guitar",
    "elgtr": "Electric Guitar",
    "gtr": "Electric Guitar",
    "ag": "Acoustic Guitar",
    "agtr": "Acoustic Guitar",
    "acgtr": "Acoustic Guitar",
    "bgv": "Backing Vocal",
    "vox": "Lead Vocal",
    "bd": "Kick",
    "sd": "Snare",
    "snr": "Snare",
    "oh": "Drums",
}


def detect_project_stems(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    if not project.get("stems"):
        raise HTTPException(status_code=400, detail="Upload stems before running stem detection.")

    common_project_tokens = _common_project_filename_tokens(project)
    for stem in project.get("stems", []):
        detection = detect_stem(project_id, stem, data.get("detectionMemory", {}), common_project_tokens)
        if (
            stem.get("stemTypeSource") == "Detected"
            and stem.get("stemType") == detection.get("suggestedStemType")
            and int(detection.get("confidence", 0)) >= DETECTION_THRESHOLD
        ):
            detection["accepted"] = True
        stem["detectionResult"] = detection
        if stem.get("stemType", "Unknown") == "Unknown":
            stem["stemTypeSource"] = "Unknown"
        append_project_log(
            project_subdirs(project_id)["logs"],
            f"Detected {stem['originalFilename']} as {detection['suggestedStemType']} at {detection['confidence']}% via {detection['method']}: {detection['reason']}",
        )

    project["status"] = "Stem Detection Ready"
    project["updatedAt"] = utc_now_iso()
    _refresh_detection_summary(project, data)
    store.save(data)
    return Project(**project)


def accept_all_confident_detections(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    accepted_count = 0
    for stem in project.get("stems", []):
        if stem.get("stemTypeSource") == "Manual" and stem.get("stemType") != "Unknown":
            continue
        detection = stem.get("detectionResult")
        if not detection:
            continue
        if detection.get("suggestedStemType") == "Unknown" or int(detection.get("confidence", 0)) < DETECTION_THRESHOLD:
            continue
        if detection.get("accepted"):
            continue
        stem["stemType"] = detection["suggestedStemType"]
        stem["stemTypeSource"] = "Detected"
        detection["accepted"] = True
        _mark_type_dependent_mix_stale(project, stem["id"])
        accepted_count += 1

    if accepted_count == 0:
        raise HTTPException(status_code=400, detail="No confident pending detections are available to accept.")

    project["updatedAt"] = utc_now_iso()
    _refresh_detection_summary(project, data)
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Accepted {accepted_count} confident stem detection suggestions.")
    return Project(**project)


def accept_stem_detection(project_id: str, stem_id: str) -> Stem:
    data = store.load()
    project = _find_project(data, project_id)
    stem = _find_stem(project, stem_id)
    detection = stem.get("detectionResult")
    if detection is None:
        raise HTTPException(status_code=400, detail="Run stem detection before accepting a suggestion.")
    if detection.get("suggestedStemType") == "Unknown" or int(detection.get("confidence", 0)) < DETECTION_THRESHOLD:
        raise HTTPException(status_code=400, detail="Detection confidence is too low to accept. Choose a stem type manually.")

    stem["stemType"] = detection["suggestedStemType"]
    stem["stemTypeSource"] = "Detected"
    stem["detectionResult"]["accepted"] = True
    _mark_type_dependent_mix_stale(project, stem_id)
    project["updatedAt"] = utc_now_iso()
    _refresh_detection_summary(project, data)
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Accepted detected stem type for {stem['originalFilename']}: {stem['stemType']}.")
    return Stem(**stem)


def learn_stem_type_correction(project_id: str, stem_id: str, stem_type: str) -> Stem:
    if stem_type not in STEM_TYPES:
        raise HTTPException(status_code=400, detail="Invalid stem type.")
    data = store.load()
    project = _find_project(data, project_id)
    stem = _find_stem(project, stem_id)
    stem["stemType"] = stem_type
    stem["stemTypeSource"] = "Manual" if stem_type != "Unknown" else "Unknown"
    if stem.get("detectionResult"):
        stem["detectionResult"]["accepted"] = stem.get("detectionResult", {}).get("suggestedStemType") == stem_type and stem_type != "Unknown"
    remember_filename_correction(data, stem.get("originalFilename", ""), stem_type)
    _mark_type_dependent_mix_stale(project, stem_id)
    project["updatedAt"] = utc_now_iso()
    _refresh_detection_summary(project, data)
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Saved manual correction for {stem['originalFilename']} as {stem_type}.")
    return Stem(**stem)


def detect_stem(project_id: str, stem: dict[str, Any], memory: dict[str, Any], ignored_memory_tokens: set[str] | None = None) -> dict[str, Any]:
    now = utc_now_iso()
    filename_result = _detect_from_filename(stem["originalFilename"])
    if filename_result:
        stem_type, confidence, reason = filename_result
        return _result(stem["id"], stem_type, confidence, reason, "filename", now, {})

    memory_result = _detect_from_memory(stem["originalFilename"], memory, ignored_memory_tokens or set())
    if memory_result:
        stem_type, confidence, reason = memory_result
        return _result(stem["id"], stem_type, confidence, reason, "memory", now, {})

    try:
        features = extract_stem_detection_features(resolve_stored_file_path(stem["filePath"]))
        stem_type, confidence, reason = _detect_from_audio_features(features)
        if confidence < DETECTION_THRESHOLD:
            return _result(
                stem["id"],
                "Unknown",
                confidence,
                f"Audio features were inconclusive. Best candidate was {stem_type}: {reason}",
                "audio",
                now,
                features,
            )
        return _result(stem["id"], stem_type, confidence, reason, "audio", now, features)
    except Exception as exc:
        return _result(stem["id"], "Unknown", 0, f"Stem detection failed: {exc}", "failed", now, {})


def effective_stem_type(stem: dict[str, Any]) -> str:
    stem_type = stem.get("stemType", "Unknown")
    source = stem.get("stemTypeSource", "Unknown")
    if source == "Manual" and stem_type != "Unknown":
        return stem_type
    if source == "Detected" and stem_type != "Unknown":
        return stem_type
    return "Unknown"


def clear_detection_memory() -> dict[str, int | str]:
    data = store.load()
    patterns = data.setdefault("detectionMemory", {}).setdefault("filenamePatterns", {})
    cleared_count = len(patterns)
    data["detectionMemory"]["filenamePatterns"] = {}
    for project in data.get("projects", []):
        _refresh_detection_summary(project, data)
    store.save(data)
    return {"message": "Detection memory cleared.", "clearedPatternCount": cleared_count}


def get_detection_memory_summary() -> dict[str, int]:
    data = store.load()
    patterns = data.setdefault("detectionMemory", {}).setdefault("filenamePatterns", {})
    return {"learnedPatternCount": len(patterns)}


def _detect_from_filename(filename: str) -> tuple[str, int, str] | None:
    normalized, compact, tokens = _normalize_filename(filename)
    token_set = set(tokens)
    candidates: list[tuple[int, int, str, str]] = []

    for stem_type, confidence, keywords in FILENAME_RULES:
        for keyword in keywords:
            score = _keyword_match_score(keyword, normalized, compact, token_set)
            if score <= 0:
                continue
            keyword_compact = re.sub(r"[^a-z0-9]+", "", keyword.lower())
            adjusted_confidence = confidence
            if keyword_compact in BRAND_HINT_CONFIDENCE:
                adjusted_confidence = BRAND_HINT_CONFIDENCE[keyword_compact]
            candidates.append((adjusted_confidence, score, stem_type, keyword))

    if not candidates:
        return None

    confidence, _score, stem_type, keyword = max(candidates, key=lambda item: (item[1], item[0]))
    keyword_compact = re.sub(r"[^a-z0-9]+", "", keyword.lower())
    if keyword_compact in BRAND_HINT_CONFIDENCE:
        return stem_type, confidence, f"Filename contains instrument/amp hint '{keyword}'."
    return stem_type, confidence, f"Filename contains '{keyword}'."


def _detect_from_memory(filename: str, memory: dict[str, Any], ignored_tokens: set[str]) -> tuple[str, int, str] | None:
    patterns = memory.get("filenamePatterns", {})
    for token in filename_learning_tokens(filename):
        if token in ignored_tokens:
            continue
        entry = patterns.get(token)
        if not entry:
            continue
        if entry.get("ambiguous"):
            continue
        stem_type = entry.get("stemType")
        if stem_type not in STEM_TYPES or stem_type == "Unknown":
            continue
        count = int(entry.get("count", 1))
        confidence = min(92, 76 + count * 4)
        return stem_type, confidence, f"Filename pattern '{token}' was learned from a manual correction."
    return None


def _keyword_match_score(keyword: str, normalized: str, compact: str, token_set: set[str]) -> int:
    keyword_normalized = re.sub(r"[^a-z0-9]+", " ", keyword.lower()).strip()
    keyword_compact = re.sub(r"[^a-z0-9]+", "", keyword.lower())

    if not keyword_compact:
        return 0
    if keyword_compact in EXACT_FILENAME_ALIASES:
        return 4 if keyword_compact in token_set else 0
    if " " in keyword_normalized:
        return 5 if keyword_normalized in normalized else 0
    if keyword_compact in token_set:
        return 5
    if keyword_compact == compact:
        return 4
    if len(keyword_compact) >= 5 and keyword_compact in compact:
        return 3
    return 0


def _detect_from_audio_features(features: dict[str, float | int | None]) -> tuple[str, int, str]:
    centroid = float(features.get("spectralCentroidHz") or 0)
    low = float(features.get("lowFrequencyEnergyRatio") or 0)
    sub = float(features.get("subEnergyRatio") or 0)
    bass = float(features.get("bassEnergyRatio") or 0)
    mid = float(features.get("midEnergyRatio") or 0)
    high = float(features.get("highEnergyRatio") or 0)
    zcr = float(features.get("zeroCrossingRate") or 0)
    transient = float(features.get("transientDensity") or 0)
    harmonic = float(features.get("harmonicRatio") or 0.5)
    percussive = float(features.get("percussiveRatio") or 0.5)
    width = float(features.get("stereoWidth") or 0)

    scores: dict[str, tuple[float, list[str]]] = {
        "Bass": (0, []),
        "Kick": (0, []),
        "Drums": (0, []),
        "Snare": (0, []),
        "Lead Vocal": (0, []),
        "Electric Guitar": (0, []),
        "Keys/Piano": (0, []),
        "Pads/Strings": (0, []),
        "FX/Ambience": (0, []),
    }

    _add(scores, "Bass", low * 70 + (20 if centroid < 900 else 0) + (15 if transient < 3 else 0) + (10 if harmonic > 0.52 else 0), "strong low-frequency energy and stable harmonic content")
    _add(scores, "Kick", sub * 95 + (22 if transient >= 1.5 else 0) + (15 if percussive > 0.55 else 0) + (10 if centroid < 1400 else 0), "low-end transient energy")
    _add(scores, "Drums", transient * 10 + percussive * 45 + high * 35 + (15 if centroid > 1400 else 0), "transient-heavy broadband percussive content")
    _add(scores, "Snare", transient * 8 + mid * 45 + high * 25 + (12 if 1200 <= centroid <= 4500 else 0) - low * 20, "midrange transient profile")
    _add(scores, "Lead Vocal", harmonic * 45 + mid * 55 + (18 if 900 <= centroid <= 3300 else 0) + (8 if 0.025 <= zcr <= 0.18 else 0) - low * 25, "voice-like midrange harmonic profile")
    _add(scores, "Electric Guitar", harmonic * 35 + mid * 50 + transient * 4 + (14 if 1200 <= centroid <= 4200 else 0) + (8 if 0.04 <= zcr <= 0.2 else 0), "midrange harmonic content with strumming-like transients")
    _add(scores, "Keys/Piano", harmonic * 42 + mid * 32 + width * 18 + (10 if transient < 4 else 0), "sustained harmonic content with moderate width")
    _add(scores, "Pads/Strings", harmonic * 45 + width * 30 + (18 if transient < 1.4 else 0) + (10 if high < 0.28 else 0), "wide sustained harmonic texture")
    _add(scores, "FX/Ambience", width * 45 + high * 28 + (14 if harmonic < 0.52 else 0) + (12 if transient < 1.2 else 0), "wide ambience-like texture")

    best_type, (raw_score, reasons) = max(scores.items(), key=lambda item: item[1][0])
    confidence = int(max(0, min(86, round(raw_score))))
    reason = reasons[0] if reasons else "best matching audio profile"
    return best_type, confidence, reason


def _add(scores: dict[str, tuple[float, list[str]]], stem_type: str, score: float, reason: str) -> None:
    current_score, reasons = scores[stem_type]
    scores[stem_type] = (current_score + score, [*reasons, reason])


def _normalize_filename(filename: str) -> tuple[str, str, list[str]]:
    base = Path(filename).stem.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", base).strip()
    compact = re.sub(r"[^a-z0-9]+", "", base)
    tokens = [token for token in normalized.split() if token]
    if compact:
        tokens.append(compact)
    return normalized, compact, tokens


def _common_project_filename_tokens(project: dict[str, Any]) -> set[str]:
    stems = project.get("stems", [])
    if len(stems) < 3:
        return set()

    counts: dict[str, int] = {}
    for stem in stems:
        tokens = set(filename_learning_tokens(stem.get("originalFilename", "")))
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1

    stem_count = len(stems)
    return {token for token, count in counts.items() if count >= 3 and count / stem_count >= 0.5}


def _result(
    stem_id: str,
    stem_type: str,
    confidence: int,
    reason: str,
    method: str,
    detected_at: str,
    features: dict[str, float | int | None],
) -> dict[str, Any]:
    if confidence < DETECTION_THRESHOLD:
        stem_type = "Unknown"
    return {
        "stemId": stem_id,
        "suggestedStemType": stem_type,
        "confidence": int(max(0, min(100, confidence))),
        "reason": reason,
        "method": method,
        "detectedAt": detected_at,
        "accepted": False,
        "features": features,
    }


def _find_stem(project: dict[str, Any], stem_id: str) -> dict[str, Any]:
    stem = next((item for item in project.get("stems", []) if item["id"] == stem_id), None)
    if stem is None:
        raise HTTPException(status_code=404, detail="Stem not found.")
    return stem


def _refresh_detection_summary(project: dict[str, Any], data: dict[str, Any]) -> None:
    patterns = data.setdefault("detectionMemory", {}).setdefault("filenamePatterns", {})
    confident_pending = 0
    accepted = 0
    for stem in project.get("stems", []):
        detection = stem.get("detectionResult")
        if not detection:
            continue
        if stem.get("stemTypeSource") == "Manual" and stem.get("stemType") != "Unknown":
            continue
        if detection.get("accepted"):
            accepted += 1
        elif detection.get("suggestedStemType") != "Unknown" and int(detection.get("confidence", 0)) >= DETECTION_THRESHOLD:
            confident_pending += 1
    project["detectionSummary"] = {
        "learnedPatternCount": len(patterns),
        "confidentPendingCount": confident_pending,
        "acceptedCount": accepted,
    }
