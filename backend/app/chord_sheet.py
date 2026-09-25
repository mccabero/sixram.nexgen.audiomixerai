"""Phase 9 - Chord Sheets.

A consumer of Phase 8, not a second pipeline. A sheet holds a splitId and reads
the stems the splitter already produced, so downloading, separating, caching by
video id and the whole cancel/progress machinery come for free. Ask for a sheet
on a URL that has been split before and the analysis starts immediately.

Sheets keep their own storage tree and their own slice of the metadata
database. That matters because a split is disposable - delete it, re-split,
nothing lost - whereas a sheet accumulates corrections a person made by hand.
Deleting the split leaves the sheet intact and only costs it play-along.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from .config import (
    BEATS_PER_BAR,
    CHORDSHEETS_ROOT,
    LOW_CONFIDENCE,
    SPLITS_ROOT,
    TUNING_LABELS,
)
from .logging_utils import append_project_log, utc_now_iso
from .models import ChordSheet, ChordSheetJob, CreateChordSheetRequest
from .storage import store

ACTIVE_SHEET_STATUSES = {"Pending", "Separating", "Analysing", "Finishing"}

BARS_PER_ROW = 4

_SHEET_LOCK = threading.RLock()


class SheetCancelled(Exception):
    """Raised inside the analysis callback when the user cancels."""


# ---------------------------------------------------------------------------
# storage helpers
# ---------------------------------------------------------------------------


def sheet_subdirs(sheet_id: str) -> dict[str, Path]:
    root = CHORDSHEETS_ROOT / sheet_id
    return {
        "root": root,
        "analysis": root / "analysis",
        "sheet": root / "sheet",
        "exports": root / "exports",
        "logs": root / "logs",
    }


def ensure_sheet_dirs(sheet_id: str) -> dict[str, Path]:
    dirs = sheet_subdirs(sheet_id)
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _log(sheet_id: str, message: str) -> None:
    try:
        append_project_log(sheet_subdirs(sheet_id)["logs"], message)
    except Exception:
        pass


def _find_sheet(data: dict[str, Any], sheet_id: str) -> dict[str, Any]:
    for sheet in data.get("chordSheets", []):
        if sheet.get("id") == sheet_id:
            return sheet
    raise HTTPException(status_code=404, detail="Chord sheet not found.")


def _mutate_sheet(sheet_id: str, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with _SHEET_LOCK:
        data = store.load()
        sheet = _find_sheet(data, sheet_id)
        mutator(sheet)
        sheet["updatedAt"] = utc_now_iso()
        store.save(data)
        return json.loads(json.dumps(sheet))


def _set_progress(sheet_id: str, status: str, progress: int, message: str) -> None:
    def apply(sheet: dict[str, Any]) -> None:
        sheet["status"] = status
        job = sheet.setdefault("job", {})
        job["status"] = status
        job["progress"] = max(0, min(100, int(progress)))
        job["message"] = message
        job["updatedAt"] = utc_now_iso()

    _mutate_sheet(sheet_id, apply)


def _cancel_requested(sheet_id: str) -> bool:
    with _SHEET_LOCK:
        data = store.load()
        try:
            sheet = _find_sheet(data, sheet_id)
        except HTTPException:
            return True
        return bool((sheet.get("job") or {}).get("cancelRequested"))


# ---------------------------------------------------------------------------
# dependency checks
# ---------------------------------------------------------------------------


def chord_sheet_environment() -> dict[str, Any]:
    """Report what the analyser needs, without importing anything heavy."""
    import importlib.util

    from .stem_splitter import separation_environment

    librosa_spec = importlib.util.find_spec("librosa")
    separation = separation_environment()

    missing = []
    if librosa_spec is None:
        missing.append("librosa")

    return {
        "ok": not missing and separation["ok"],
        "missing": missing,
        "separation": separation,
        "lowConfidenceThreshold": LOW_CONFIDENCE,
        "installHint": "pip install librosa" if missing else None,
    }


def _require_analysis_environment() -> None:
    """What analysing an existing split needs: librosa, and nothing else."""
    env = chord_sheet_environment()
    if env["missing"]:
        raise HTTPException(status_code=503, detail=f"Chord analysis needs {', '.join(env['missing'])}.")


def _require_separation_for_new_split() -> None:
    """Only a sheet that has to make its own split needs torch and demucs.

    Analysing stems that are already on disk does not, so a machine where the
    separation install failed can still open chord sheets for the splits it
    already has.
    """
    env = chord_sheet_environment()
    if not env["separation"]["ok"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "That link has not been split yet, and separating it needs "
                f"{', '.join(env['separation']['missing'])}."
            ),
        )


# ---------------------------------------------------------------------------
# chart + ChordPro assembly
# ---------------------------------------------------------------------------


def build_chart(chords: list[dict]) -> list[dict]:
    """Group chords into bars and bars into rows, the way a chart reads.

    A chord is placed in the bar it starts in; a bar with nothing starting in
    it is a held chord, and the UI draws it as a continuation rather than
    repeating the label.
    """
    playing = [c for c in chords if c["label"] != "N"]
    if not playing:
        return []

    last_bar = max(c["bar"] for c in playing)
    bars: list[dict] = []
    for index in range(last_bar + 1):
        starting = [c for c in playing if c["bar"] == index]
        bars.append(
            {
                "bar": index,
                "startSeconds": starting[0]["startSeconds"] if starting else None,
                "chords": starting,
                "held": not starting,
            }
        )

    rows = []
    running = 0.0
    for start in range(0, len(bars), BARS_PER_ROW):
        chunk = bars[start : start + BARS_PER_ROW]
        first = next((b["startSeconds"] for b in chunk if b["startSeconds"] is not None), None)
        # A row where every bar is held has no chord start of its own. It still
        # happens at a time, so it inherits the last one rather than reading
        # as a gap in the song.
        if first is None:
            first = running
        running = first
        rows.append({"row": start // BARS_PER_ROW, "startSeconds": first, "bars": chunk})
    return rows


def to_chordpro(sheet: dict[str, Any], analysis: dict[str, Any]) -> str:
    """The canonical format. Transpose, capo and re-spelling are text edits on
    this, which is why the sheet is stored as ChordPro rather than as layout."""
    tuning = analysis.get("tuning") or {}
    lines = [
        f"{{title: {sheet.get('title', 'Untitled')}}}",
        f"{{key: {(analysis.get('key') or {}).get('key', '')}}}",
        f"{{tempo: {analysis.get('tempo', '')}}}",
        f"{{time: {BEATS_PER_BAR}/4}}",
        f"{{tuning: {tuning.get('assumed', 'E Standard')}}}",
    ]
    if tuning.get("cents"):
        lines.append(f"{{comment: reference pitch {tuning['cents']:+} cents}}")
    lines.append("")

    rows = analysis.get("lyricRows") or []
    if rows:
        # With words, ChordPro puts the chord inline at the syllable it lands
        # on, which is the whole reason the format exists.
        for row in rows:
            if row["instrumental"]:
                lines.append("| " + " | ".join(c["label"] for c in row["chords"]) + " |")
                continue
            text = row["text"]
            for chord in sorted(row["chords"], key=lambda c: -c["charOffset"]):
                cut = min(max(chord["charOffset"], 0), len(text))
                text = f"{text[:cut]}[{chord['label']}]{text[cut:]}"
            lines.append(text)
        return "\n".join(lines) + "\n"

    for row in build_chart(analysis.get("chords") or []):
        cells = []
        for bar in row["bars"]:
            if bar["held"]:
                cells.append("%")
                continue
            cells.append(" ".join(f"[{c['label']}]" for c in bar["chords"]))
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


def to_plain_text(sheet: dict[str, Any], analysis: dict[str, Any]) -> str:
    header = [
        sheet.get("title", "Untitled"),
        f"Key {(analysis.get('key') or {}).get('key', '?')}   "
        f"{analysis.get('tempo', '?')} BPM   "
        f"{(analysis.get('tuning') or {}).get('assumed', 'E Standard')}",
        "",
    ]
    rows = analysis.get("lyricRows") or []
    if rows:
        from . import lyrics as lyrics_module

        return "\n".join(header) + "\n" + lyrics_module.render_text(rows) + "\n"

    body = []
    for row in build_chart(analysis.get("chords") or []):
        cells = []
        for bar in row["bars"]:
            label = "%" if bar["held"] else " ".join(c["label"] for c in bar["chords"])
            cells.append(f"{label:<10}")
        body.append("| " + "| ".join(cells) + "|")
    return "\n".join(header + body) + "\n"


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def list_chord_sheets() -> list[ChordSheet]:
    data = store.load()
    sheets = sorted(data.get("chordSheets", []), key=lambda s: s.get("createdAt", ""), reverse=True)
    return [ChordSheet(**sheet) for sheet in sheets]


def get_chord_sheet(sheet_id: str) -> ChordSheet:
    data = store.load()
    return ChordSheet(**_find_sheet(data, sheet_id))


def get_chord_sheet_job(sheet_id: str) -> ChordSheetJob:
    data = store.load()
    sheet = _find_sheet(data, sheet_id)
    job = sheet.get("job")
    if not job:
        raise HTTPException(status_code=404, detail="No job for this chord sheet.")
    return ChordSheetJob(**job)


def active_chord_sheet_summary() -> dict[str, Any] | None:
    data = store.load()
    for sheet in data.get("chordSheets", []):
        if sheet.get("status") in ACTIVE_SHEET_STATUSES:
            return {
                "id": sheet["id"],
                "title": sheet.get("title"),
                "status": sheet.get("status"),
                "progress": (sheet.get("job") or {}).get("progress", 0),
                "message": (sheet.get("job") or {}).get("message"),
            }
    return None


def get_analysis(sheet_id: str) -> dict[str, Any]:
    """The full analysis payload, kept on disk rather than in the database."""
    path = sheet_subdirs(sheet_id)["analysis"] / "analysis.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="This chord sheet has no analysis yet.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _decorate(payload)


def _decorate(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the views derived from the stored chords.

    The chart and the lyric rows are both computed on read rather than saved,
    so a transposition or a hand correction cannot leave them disagreeing with
    the chords they came from.
    """
    from . import lyrics as lyrics_module

    chords = payload.get("chords") or []
    payload["chart"] = build_chart(chords)

    stored = payload.get("lyrics")
    if stored and stored.get("lines"):
        payload["lyricRows"] = lyrics_module.place_chords(
            [dict(line) for line in stored["lines"]],
            chords,
            float(payload.get("durationSeconds") or 0),
        )
    else:
        payload["lyricRows"] = []
    return payload


def _write_analysis(sheet_id: str, payload: dict[str, Any]) -> None:
    path = sheet_subdirs(sheet_id)["analysis"] / "analysis.json"
    stored = {k: v for k, v in payload.items() if k not in ("chart", "lyricRows", "view")}
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# create / run
# ---------------------------------------------------------------------------


def _resolve_split(payload: CreateChordSheetRequest) -> dict[str, Any]:
    """Find a split to analyse, or line one up to be made."""
    from .stem_splitter import _extract_video_id, create_split
    from .models import CreateSplitRequest

    data = store.load()

    if payload.splitId:
        for split in data.get("splits", []):
            if split.get("id") == payload.splitId:
                return split
        raise HTTPException(status_code=404, detail="Split not found.")

    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Give either a splitId or a URL.")

    # Any ready split of this video will do - a 6-stem one is better, since
    # guitar and piano land in the harmony sum instead of the "other" bucket.
    video_id = _extract_video_id(url)
    if video_id:
        candidates = [
            s
            for s in data.get("splits", [])
            if s.get("videoId") == video_id and s.get("status") == "Ready"
        ]
        if candidates:
            candidates.sort(key=lambda s: (s.get("stemSet") != "6", s.get("createdAt", "")))
            return candidates[0]

    # Nothing cached: a 4-stem split is faster and its stems are cleaner, which
    # is what the harmony sum wants anyway.
    _require_separation_for_new_split()
    return json.loads(create_split(CreateSplitRequest(url=url, stemSet="4")).model_dump_json())


def _find_cached_sheet(data: dict[str, Any], split_id: str) -> dict[str, Any] | None:
    for sheet in data.get("chordSheets", []):
        if sheet.get("splitId") != split_id or sheet.get("status") != "Ready":
            continue
        if (CHORDSHEETS_ROOT / sheet["id"] / "analysis" / "analysis.json").exists():
            return sheet
    return None


def create_chord_sheet(payload: CreateChordSheetRequest) -> ChordSheet:
    _require_analysis_environment()

    split = _resolve_split(payload)

    with _SHEET_LOCK:
        data = store.load()
        cached = _find_cached_sheet(data, split["id"])
        if cached:
            _log(cached["id"], "Reused the existing chord sheet for this split.")
            return ChordSheet(**cached)

        sheet_id = uuid.uuid4().hex
        now = utc_now_iso()
        sheet = {
            "id": sheet_id,
            "splitId": split["id"],
            "url": split.get("url", payload.url or ""),
            "videoId": split.get("videoId"),
            "title": split.get("title") or "Chord sheet",
            "uploader": split.get("uploader"),
            "durationSeconds": float(split.get("durationSeconds") or 0),
            "status": "Pending",
            "createdAt": now,
            "updatedAt": now,
            "job": {
                "id": uuid.uuid4().hex,
                "sheetId": sheet_id,
                "status": "Pending",
                "progress": 0,
                "message": "Queued",
                "cancelRequested": False,
                "createdAt": now,
                "updatedAt": now,
            },
        }
        data.setdefault("chordSheets", []).append(sheet)
        store.save(data)

    ensure_sheet_dirs(sheet_id)
    _log(sheet_id, f"Created chord sheet for split {split['id']}.")
    return ChordSheet(**sheet)


def run_chord_sheet(sheet_id: str) -> None:
    """Background worker. Separates if it has to, then analyses."""
    from . import chord_engine
    from .stem_splitter import run_split

    started = time.time()

    try:
        data = store.load()
        sheet = _find_sheet(data, sheet_id)
        split_id = sheet["splitId"]

        split = next((s for s in data.get("splits", []) if s.get("id") == split_id), None)
        if split is None:
            raise HTTPException(status_code=404, detail="The split this sheet belongs to is gone.")

        # --- separate, only if the split is not already done ---------------
        if split.get("status") != "Ready":
            _set_progress(sheet_id, "Separating", 4, "Separating stems first...")
            _log(sheet_id, "Split is not ready; running separation first.")
            run_split(split_id)

            data = store.load()
            split = next((s for s in data.get("splits", []) if s.get("id") == split_id), None)
            if not split or split.get("status") != "Ready":
                raise HTTPException(status_code=502, detail="Separation did not finish, so there is nothing to analyse.")

            def apply_split_info(item: dict[str, Any]) -> None:
                item["title"] = split.get("title") or item.get("title")
                item["uploader"] = split.get("uploader")
                item["videoId"] = split.get("videoId")
                item["durationSeconds"] = float(split.get("durationSeconds") or 0)

            _mutate_sheet(sheet_id, apply_split_info)

        if _cancel_requested(sheet_id):
            raise SheetCancelled()

        # --- analyse -------------------------------------------------------
        stems_dir = SPLITS_ROOT / split_id / "stems"
        if not stems_dir.is_dir():
            raise HTTPException(status_code=409, detail="The split's stems are no longer on disk. Re-split it first.")

        _set_progress(sheet_id, "Analysing", 12, "Reading stems...")
        last_report = {"at": 0.0}

        def on_progress(fraction: float, message: str) -> bool:
            if _cancel_requested(sheet_id):
                return False
            now = time.time()
            if now - last_report["at"] < 1.0:
                return True
            last_report["at"] = now
            # 12% to 92% of the bar belongs to analysis.
            _set_progress(sheet_id, "Analysing", 12 + int(fraction * 80), message)
            return True

        analysis = chord_engine.analyse(stems_dir, progress=on_progress)

        if _cancel_requested(sheet_id):
            raise SheetCancelled()

        # --- write ---------------------------------------------------------
        _set_progress(sheet_id, "Finishing", 94, "Writing the sheet...")
        dirs = ensure_sheet_dirs(sheet_id)
        analysis["splitId"] = split_id
        analysis["stemSet"] = split.get("stemSet")
        _write_analysis(sheet_id, analysis)

        current = store.load()
        record = _find_sheet(current, sheet_id)
        (dirs["sheet"] / "sheet.pro").write_text(to_chordpro(record, analysis), encoding="utf-8")

        elapsed = time.time() - started
        summary = analysis["summary"]

        def finish(item: dict[str, Any]) -> None:
            item["status"] = "Ready"
            item["completedAt"] = utc_now_iso()
            item["elapsedSeconds"] = round(elapsed, 1)
            item["error"] = None
            item["tempo"] = analysis["tempo"]
            item["key"] = (analysis.get("key") or {}).get("key")
            item["tuning"] = (analysis.get("tuning") or {}).get("assumed")
            item["referenceCents"] = (analysis.get("tuning") or {}).get("cents")
            item["transpose"] = 0
            item["capo"] = 0
            item["chordCount"] = summary["chordCount"]
            item["meanConfidence"] = summary["meanConfidence"]
            item["lowConfidenceRatio"] = summary["lowConfidenceRatio"]
            job = item.setdefault("job", {})
            job["status"] = "Ready"
            job["progress"] = 100
            job["message"] = "Done"
            job["updatedAt"] = utc_now_iso()

        _mutate_sheet(sheet_id, finish)
        _log(
            sheet_id,
            f"Analysed in {elapsed:.1f}s - {summary['chordCount']} chords, "
            f"{summary['lowConfidenceRatio']:.0%} low confidence.",
        )

    except SheetCancelled:
        _log(sheet_id, "Cancelled.")

        def cancelled(item: dict[str, Any]) -> None:
            item["status"] = "Cancelled"
            job = item.setdefault("job", {})
            job["status"] = "Cancelled"
            job["message"] = "Cancelled"
            job["cancelRequested"] = False
            job["updatedAt"] = utc_now_iso()

        _mutate_sheet(sheet_id, cancelled)

    except Exception as exc:  # noqa: BLE001 - the worker must never take the server down
        detail = getattr(exc, "detail", None) or str(exc)
        _log(sheet_id, f"Failed: {detail}")

        def failed(item: dict[str, Any]) -> None:
            item["status"] = "Failed"
            item["error"] = str(detail)
            job = item.setdefault("job", {})
            job["status"] = "Failed"
            job["message"] = str(detail)
            job["updatedAt"] = utc_now_iso()

        _mutate_sheet(sheet_id, failed)


# ---------------------------------------------------------------------------
# mutations
# ---------------------------------------------------------------------------


def request_sheet_cancel(sheet_id: str) -> ChordSheet:
    def apply(sheet: dict[str, Any]) -> None:
        if sheet.get("status") not in ACTIVE_SHEET_STATUSES:
            raise HTTPException(status_code=409, detail="This chord sheet is not running.")
        job = sheet.setdefault("job", {})
        job["cancelRequested"] = True
        job["message"] = "Cancelling..."
        job["updatedAt"] = utc_now_iso()

    return ChordSheet(**_mutate_sheet(sheet_id, apply))


def retry_chord_sheet(sheet_id: str) -> ChordSheet:
    def apply(sheet: dict[str, Any]) -> None:
        if sheet.get("status") in ACTIVE_SHEET_STATUSES:
            raise HTTPException(status_code=409, detail="This chord sheet is already running.")
        sheet["status"] = "Pending"
        sheet["error"] = None
        job = sheet.setdefault("job", {})
        job["status"] = "Pending"
        job["progress"] = 0
        job["message"] = "Queued"
        job["cancelRequested"] = False
        job["updatedAt"] = utc_now_iso()

    return ChordSheet(**_mutate_sheet(sheet_id, apply))


def delete_chord_sheet(sheet_id: str) -> dict[str, str]:
    import shutil

    with _SHEET_LOCK:
        data = store.load()
        sheet = _find_sheet(data, sheet_id)
        if sheet.get("status") in ACTIVE_SHEET_STATUSES:
            raise HTTPException(status_code=409, detail="Cancel the chord sheet before deleting it.")
        data["chordSheets"] = [s for s in data.get("chordSheets", []) if s.get("id") != sheet_id]
        store.save(data)

    shutil.rmtree(sheet_subdirs(sheet_id)["root"], ignore_errors=True)
    return {"status": "deleted", "sheetId": sheet_id}


def update_sheet_view(sheet_id: str, transpose: int, capo: int, tuning_shift: int) -> dict[str, Any]:
    """Re-spell the sheet. Never re-analyses - this is a text transform.

    Chords are stored as sounding pitches. Transposing, adding a capo or
    declaring the guitar tuned down all change only which shape is printed, so
    all three collapse into one integer applied at render time.
    """
    from . import chord_engine

    if not -11 <= transpose <= 11:
        raise HTTPException(status_code=400, detail="Transpose must be between -11 and 11 semitones.")
    if not 0 <= capo <= 11:
        raise HTTPException(status_code=400, detail="Capo must be between 0 and 11.")
    if tuning_shift not in TUNING_LABELS:
        raise HTTPException(status_code=400, detail="Unknown tuning.")

    analysis = get_analysis(sheet_id)
    shift = transpose - capo + tuning_shift

    source_key = (analysis.get("key") or {}).get("key") or "C major"
    flats, key_root = chord_engine.spelling_after_shift(source_key, shift)
    for chord in analysis.get("chords") or []:
        if chord["label"] == "N":
            continue
        if chord.get("edited"):
            continue  # a hand correction is not the engine's to re-spell
        chord["label"] = chord_engine.chord_name(
            chord_engine.transpose_chord(chord["index"], shift), flats, key_root
        )

    def apply(sheet: dict[str, Any]) -> None:
        sheet["transpose"] = transpose
        sheet["capo"] = capo
        sheet["tuningShift"] = tuning_shift
        sheet["tuning"] = TUNING_LABELS[tuning_shift]

    _mutate_sheet(sheet_id, apply)

    analysis = _decorate(analysis)
    analysis["view"] = {
        "transpose": transpose,
        "capo": capo,
        "tuningShift": tuning_shift,
        "shift": shift,
        "readingKey": f"{key_root} {source_key.split(' ')[1]}",
    }
    return analysis


def update_sheet_chord(sheet_id: str, bar: int, start_seconds: float, label: str) -> dict[str, Any]:
    """Correct one chord by hand. Edits survive a re-analysis."""
    analysis_path = sheet_subdirs(sheet_id)["analysis"] / "analysis.json"
    if not analysis_path.exists():
        raise HTTPException(status_code=404, detail="This chord sheet has no analysis yet.")

    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    label = (label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Give a chord label.")

    for chord in payload.get("chords") or []:
        if chord["bar"] == bar and abs(chord["startSeconds"] - start_seconds) < 0.05:
            chord["label"] = label
            chord["edited"] = True
            chord["confidence"] = 1.0
            chord["lowConfidence"] = False
            break
    else:
        raise HTTPException(status_code=404, detail="No chord at that position.")

    _write_analysis(sheet_id, payload)
    return _decorate(payload)


def export_chord_sheet(sheet_id: str, fmt: str = "chordpro") -> dict[str, Any]:
    from .config import STORAGE_ROOT

    if fmt not in {"chordpro", "txt"}:
        raise HTTPException(status_code=400, detail="Format must be chordpro or txt.")

    analysis = get_analysis(sheet_id)
    data = store.load()
    sheet = _find_sheet(data, sheet_id)

    dirs = ensure_sheet_dirs(sheet_id)
    suffix = "pro" if fmt == "chordpro" else "txt"
    body = to_chordpro(sheet, analysis) if fmt == "chordpro" else to_plain_text(sheet, analysis)

    path = dirs["exports"] / f"chord-sheet.{suffix}"
    path.write_text(body, encoding="utf-8")

    try:
        relative = path.resolve().relative_to(STORAGE_ROOT).as_posix()
    except ValueError:
        relative = path.name

    return {"fileName": path.name, "filePath": relative, "bytes": path.stat().st_size}


def mark_interrupted_sheets() -> None:
    """Called at startup.

    A sheet that was mid-analysis when the backend stopped can never resume, so
    leaving it Running would strand it in the UI forever. Restarting clears it,
    and Retry re-runs the analysis against the same split - which by then is
    almost always still cached, so the retry is quick.
    """
    with _SHEET_LOCK:
        data = store.load()
        changed = False
        for sheet in data.get("chordSheets", []):
            if sheet.get("status") not in ACTIVE_SHEET_STATUSES:
                continue
            sheet["status"] = "Failed"
            sheet["error"] = "The backend restarted while this chord sheet was running."
            sheet["updatedAt"] = utc_now_iso()
            job = sheet.setdefault("job", {})
            job["status"] = "Failed"
            job["message"] = "Interrupted by a backend restart."
            job["cancelRequested"] = False
            job["updatedAt"] = utc_now_iso()
            changed = True
        if changed:
            store.save(data)


# ---------------------------------------------------------------------------
# lyrics
# ---------------------------------------------------------------------------


def attach_lyrics(
    sheet_id: str,
    source: str = "auto",
    text: str | None = None,
    artist: str | None = None,
    track: str | None = None,
) -> dict[str, Any]:
    """Look lyrics up, or take the ones the user pasted.

    'auto' asks LRCLIB, deriving artist and track from the video title unless
    they are given. A miss is not an error - it is the ordinary case for local,
    regional and unreleased material - so it comes back saying nothing was
    found and inviting a paste.
    """
    from . import lyrics as lyrics_module

    analysis_path = sheet_subdirs(sheet_id)["analysis"] / "analysis.json"
    if not analysis_path.exists():
        raise HTTPException(status_code=404, detail="Analyse this chord sheet before adding lyrics.")

    data = store.load()
    sheet = _find_sheet(data, sheet_id)
    payload = json.loads(analysis_path.read_text(encoding="utf-8"))

    if source == "manual":
        if not (text or "").strip():
            raise HTTPException(status_code=400, detail="Paste some lyrics first.")
        found = lyrics_module.from_pasted(text or "")
        _log(sheet_id, f"Added pasted lyrics ({len(found['lines'])} lines).")
    elif source == "auto":
        guessed_artist, guessed_track = lyrics_module.clean_title(sheet.get("title") or "")
        found = lyrics_module.fetch_from_lrclib(
            track=(track or guessed_track or "").strip(),
            artist=(artist or guessed_artist or sheet.get("uploader") or "").strip() or None,
            duration=float(sheet.get("durationSeconds") or 0) or None,
        )
        if not found:
            _log(sheet_id, "No LRCLIB match for this track.")
            return {
                "found": False,
                "searchedFor": {"artist": artist or guessed_artist, "track": track or guessed_track},
                "message": "No match on LRCLIB. Paste the lyrics instead and they will be laid out the same way.",
            }
        _log(sheet_id, f"Fetched lyrics from {found['source']} ({len(found['lines'])} lines).")
    else:
        raise HTTPException(status_code=400, detail="Source must be auto or manual.")

    payload["lyrics"] = found
    _write_analysis(sheet_id, payload)

    def apply(item: dict[str, Any]) -> None:
        item["lyricsSource"] = found["source"]
        item["lyricsSynced"] = found["synced"]
        item["lyricLineCount"] = len([line for line in found["lines"] if line.get("text")])

    _mutate_sheet(sheet_id, apply)

    result = _decorate(payload)
    result["found"] = True
    return result


def clear_lyrics(sheet_id: str) -> dict[str, Any]:
    analysis_path = sheet_subdirs(sheet_id)["analysis"] / "analysis.json"
    if not analysis_path.exists():
        raise HTTPException(status_code=404, detail="This chord sheet has no analysis yet.")

    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    payload.pop("lyrics", None)
    _write_analysis(sheet_id, payload)

    def apply(item: dict[str, Any]) -> None:
        item["lyricsSource"] = None
        item["lyricsSynced"] = False
        item["lyricLineCount"] = 0

    _mutate_sheet(sheet_id, apply)
    return _decorate(payload)
