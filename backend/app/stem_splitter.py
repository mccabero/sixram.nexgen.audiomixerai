"""Phase 8 - Stem Splitter.

A standalone module: take a media URL, download the audio, and separate it into
isolated instrument stems with Demucs. Nothing here touches the mix and
mastering pipeline; splits live in their own storage tree and their own slice of
the metadata database.

torch and demucs are imported lazily on purpose. If they are not installed the
splitter endpoints answer 503 and the rest of the backend runs normally, the
same way phase6 treats yt-dlp.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np
from fastapi import HTTPException

from .config import (
    MAX_SPLIT_SECONDS,
    SPLIT_MODELS,
    SPLIT_STEM_ORDER,
    SPLIT_STEM_PRESENTATION,
    SPLITS_ROOT,
)
from .logging_utils import append_project_log, utc_now_iso
from .models import CreateSplitRequest, ExportSplitMixRequest, Split, SplitJob
from .storage import store


ACTIVE_SPLIT_STATUSES = {"Pending", "Downloading", "Preparing", "Separating", "Finishing"}
_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_YOUTUBE_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})")

# Guards the metadata read-modify-write cycles this module performs. The store
# has its own lock for file access, but a split job does load/mutate/save from a
# background thread while requests come in, so the sequence needs its own.
_SPLIT_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# storage helpers
# ---------------------------------------------------------------------------


def split_subdirs(split_id: str) -> dict[str, Path]:
    root = SPLITS_ROOT / split_id
    return {
        "root": root,
        "source": root / "source",
        "stems": root / "stems",
        "preview": root / "preview",
        "exports": root / "exports",
        "logs": root / "logs",
    }


def ensure_split_dirs(split_id: str) -> dict[str, Path]:
    dirs = split_subdirs(split_id)
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _relative_media_path(path: Path) -> str:
    """Path as served by the /media static mount."""
    from .config import STORAGE_ROOT

    try:
        return path.resolve().relative_to(STORAGE_ROOT).as_posix()
    except ValueError:
        return path.name


def _find_split(data: dict[str, Any], split_id: str) -> dict[str, Any]:
    for split in data.get("splits", []):
        if split.get("id") == split_id:
            return split
    raise HTTPException(status_code=404, detail="Split not found.")


def _log(split_id: str, message: str) -> None:
    try:
        append_project_log(split_subdirs(split_id)["logs"], message)
    except Exception:
        pass


def _mutate_split(split_id: str, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with _SPLIT_LOCK:
        data = store.load()
        split = _find_split(data, split_id)
        mutator(split)
        split["updatedAt"] = utc_now_iso()
        store.save(data)
        return json.loads(json.dumps(split))


def _set_progress(split_id: str, status: str, progress: int, message: str) -> None:
    def apply(split: dict[str, Any]) -> None:
        split["status"] = status
        job = split.setdefault("job", {})
        job["status"] = status
        job["progress"] = max(0, min(100, int(progress)))
        job["message"] = message
        job["updatedAt"] = utc_now_iso()

    _mutate_split(split_id, apply)


def _cancel_requested(split_id: str) -> bool:
    with _SPLIT_LOCK:
        data = store.load()
        try:
            split = _find_split(data, split_id)
        except HTTPException:
            return True
        return bool((split.get("job") or {}).get("cancelRequested"))


class SplitCancelled(Exception):
    """Raised inside the separation callback when the user cancels."""


# ---------------------------------------------------------------------------
# dependency checks
# ---------------------------------------------------------------------------


def separation_environment() -> dict[str, Any]:
    """Report what the splitter needs, without importing the heavy modules."""
    import importlib.util

    torch_spec = importlib.util.find_spec("torch")
    demucs_spec = importlib.util.find_spec("demucs")
    ytdlp_spec = importlib.util.find_spec("yt_dlp")

    torch_version = None
    threads = None
    if torch_spec is not None:
        try:
            import torch

            torch_version = torch.__version__
            threads = torch.get_num_threads()
        except Exception:
            torch_version = "present but failed to import"

    ok = torch_spec is not None and demucs_spec is not None and ytdlp_spec is not None
    missing = []
    if torch_spec is None:
        missing.append("torch")
    if demucs_spec is None:
        missing.append("demucs")
    if ytdlp_spec is None:
        missing.append("yt-dlp")

    return {
        "ok": ok,
        "missing": missing,
        "torchVersion": torch_version,
        "torchThreads": threads,
        "models": list(SPLIT_MODELS.keys()),
        "installHint": (
            "pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install demucs"
            if missing
            else None
        ),
    }


def _require_separation_environment() -> None:
    env = separation_environment()
    if not env["ok"]:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Stem splitting needs {', '.join(env['missing'])}. "
                "Install with: pip install torch --index-url https://download.pytorch.org/whl/cpu "
                "&& pip install demucs"
            ),
        )


def _ffmpeg() -> str:
    from .audio_engine import _ffmpeg_exe

    try:
        return _ffmpeg_exe()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# audio helpers (wave + numpy only, no extra dependencies)
# ---------------------------------------------------------------------------


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())

    if width != 2:
        raise HTTPException(status_code=400, detail=f"Expected 16-bit WAV, got {width * 8}-bit.")

    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).T
    else:
        samples = samples.reshape(1, -1)
    return samples, rate


def _write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    interleaved = (clipped.T.reshape(-1) * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(samples.shape[0])
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(interleaved.tobytes())


def _levels(samples: np.ndarray) -> tuple[float, float]:
    if samples.size == 0:
        return -99.0, -99.0
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    peak_db = 20 * np.log10(peak) if peak > 0 else -99.0
    rms_db = 20 * np.log10(rms) if rms > 0 else -99.0
    return round(float(peak_db), 1), round(float(rms_db), 1)


def _encode_preview(ffmpeg_path: str, source: Path, destination: Path) -> bool:
    """192k MP3 used for browser playback. Six decoded WAVs is too much RAM."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [ffmpeg_path, "-y", "-i", str(source), "-vn", "-codec:a", "libmp3lame", "-b:a", "192k", str(destination)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and destination.exists()


# ---------------------------------------------------------------------------
# download + convert
# ---------------------------------------------------------------------------


def _sanitize(title: str, fallback: str = "split") -> str:
    cleaned = _SAFE_CHARS.sub("_", title).strip("._-")
    return cleaned[:80] or fallback


def _extract_video_id(url: str) -> str | None:
    match = _YOUTUBE_ID.search(url)
    return match.group(1) if match else None


def _download_audio(split_id: str, url: str, source_dir: Path) -> dict[str, Any]:
    try:
        import yt_dlp  # type: ignore[import-not-found]
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="yt-dlp is not installed. Run 'pip install yt-dlp'.") from exc

    source_dir.mkdir(parents=True, exist_ok=True)
    for stale in source_dir.glob("download.*"):
        stale.unlink(missing_ok=True)

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(source_dir / "download.%(ext)s"),
        "restrictfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "js_runtimes": {"node": {}},
        # Same client order phase6 already uses for mastering references.
        "extractor_args": {
            "youtube": {"player_client": ["tv", "ios", "web_safari", "android", "web"]},
        },
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if not isinstance(info, dict):
        raise HTTPException(status_code=400, detail="Could not read media information from that URL.")

    downloaded = [p for p in source_dir.iterdir() if p.is_file() and p.stem == "download"]
    if not downloaded:
        raise HTTPException(status_code=400, detail="No audio was downloaded from the provided URL.")

    duration = float(info.get("duration") or 0)
    if duration and duration > MAX_SPLIT_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"That track is {duration / 60:.0f} minutes. The limit is "
                f"{MAX_SPLIT_SECONDS // 60} minutes so a split cannot run away on CPU."
            ),
        )

    return {
        "path": downloaded[0],
        "title": info.get("title") or "Untitled",
        "duration": duration,
        "uploader": info.get("uploader"),
        "videoId": info.get("id") or _extract_video_id(url),
    }


def _convert_to_wav(ffmpeg_path: str, source: Path, destination: Path) -> None:
    result = subprocess.run(
        [
            ffmpeg_path, "-y",
            "-i", str(source),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            str(destination),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not destination.exists():
        tail = " | ".join((result.stderr or "").strip().splitlines()[-3:])
        raise HTTPException(status_code=400, detail=f"ffmpeg could not convert the audio: {tail or 'unknown error'}")


# ---------------------------------------------------------------------------
# separation
# ---------------------------------------------------------------------------


def _fit_channels(samples: np.ndarray, channels: int) -> np.ndarray:
    if samples.shape[0] > channels:
        return samples[:channels]
    if samples.shape[0] < channels:
        return np.repeat(samples[:1], channels, axis=0)
    return samples


def _prepare_input(wav_path: Path, target_rate: int, target_channels: int) -> np.ndarray:
    # Deliberately NOT demucs.audio.AudioFile: it shells out to bare "ffmpeg"
    # and "ffprobe", which this app does not put on PATH (it uses the binary
    # bundled with imageio-ffmpeg, which ships no ffprobe at all). That raised
    # WinError 2 on Windows. The input is already a WAV we converted ourselves.
    samples, rate = _read_wav(wav_path)

    if rate != target_rate:
        resampled = wav_path.with_name(f"input_{target_rate}.wav")
        result = subprocess.run(
            [
                _ffmpeg(), "-y",
                "-i", str(wav_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", str(target_rate),
                "-ac", str(target_channels),
                str(resampled),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not resampled.exists():
            raise HTTPException(status_code=400, detail=f"Could not resample to {target_rate} Hz.")
        samples, _ = _read_wav(resampled)

    return _fit_channels(samples, target_channels)


def _load_model(name: str):
    from demucs.pretrained import get_model

    model = get_model(name)
    model.cpu()
    model.eval()
    return model


def _apply(split_id: str, samples: np.ndarray, model: Any, on_progress: Callable[[float], None]) -> dict[str, np.ndarray]:
    import inspect

    import torch
    from demucs.apply import apply_model

    wav = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))
    reference = wav.mean(0)
    mean = reference.mean()
    std = reference.std()
    wav = (wav - mean) / (std if float(std) > 0 else 1.0)

    state: dict[str, Any] = {"last_check": 0.0}

    def callback(payload: dict[str, Any]) -> None:
        total = payload.get("audio_length") or 0
        offset = payload.get("segment_offset") or 0
        if total:
            on_progress(min(1.0, float(offset) / float(total)))
        # Cancellation is polled here rather than in a separate thread so it can
        # only land between segments, where the tensors are in a known state.
        now = time.time()
        if now - state["last_check"] > 2.0:
            state["last_check"] = now
            if _cancel_requested(split_id):
                raise SplitCancelled()

    kwargs: dict[str, Any] = {
        "device": "cpu",
        "shifts": 0,
        "split": True,
        "overlap": 0.25,
        "progress": False,
    }
    if "callback" in inspect.signature(apply_model).parameters:
        kwargs["callback"] = callback
        kwargs["callback_arg"] = {}

    sources = apply_model(model, wav[None], **kwargs)[0]
    sources = sources * (std if float(std) > 0 else 1.0) + mean

    return {name: tensor.detach().cpu().numpy() for name, tensor in zip(model.sources, sources)}


def _scaled(on_progress: Callable[[float], None], start: float, end: float) -> Callable[[float], None]:
    def scaled(fraction: float) -> None:
        on_progress(start + (end - start) * fraction)

    return scaled


def _separate(
    split_id: str,
    wav_path: Path,
    stem_set: str,
    depth: str,
    on_progress: Callable[[float], None],
) -> tuple[dict[str, np.ndarray], int]:
    """Standard runs one model. Deep runs two.

    Asking one model to pull six sources out of a full mix is a harder problem
    than asking it to pull guitar and piano out of a signal that no longer
    contains vocals, drums or bass. So the deep path separates 4 stems first,
    then runs the 6-stem model on the leftover "other" only. It costs roughly
    double the time and helps mainly the two weak sources, guitar and piano.
    """
    fine_name = SPLIT_MODELS[stem_set]

    if depth != "deep" or stem_set != "6":
        model = _load_model(fine_name)
        samples = _prepare_input(wav_path, int(model.samplerate), int(model.audio_channels))
        return _apply(split_id, samples, model, on_progress), int(model.samplerate)

    coarse = _load_model(SPLIT_MODELS["4"])
    samples = _prepare_input(wav_path, int(coarse.samplerate), int(coarse.audio_channels))
    first = _apply(split_id, samples, coarse, _scaled(on_progress, 0.0, 0.5))
    rate = int(coarse.samplerate)
    del coarse, samples

    residual = first.pop("other", None)
    if residual is None:
        raise HTTPException(status_code=500, detail="The 4-stem pass produced no residual to refine.")

    fine = _load_model(fine_name)
    residual = _fit_channels(residual, int(fine.audio_channels))
    second = _apply(split_id, residual, fine, _scaled(on_progress, 0.5, 1.0))
    del residual, fine

    merged: dict[str, np.ndarray] = {
        "vocals": first["vocals"],
        "drums": first["drums"],
        "bass": first["bass"],
    }
    for name in ("guitar", "piano"):
        part = second.get(name)
        if part is not None:
            merged[name] = part

    # Whatever the second pass still calls vocals/drums/bass is leakage that
    # belongs with "other" at this point, so fold it back in. That keeps the
    # stems summing to the original mix.
    leftover = second.get("other")
    for name in ("vocals", "drums", "bass"):
        part = second.get(name)
        if part is None:
            continue
        leftover = part if leftover is None else leftover + part
    if leftover is not None:
        merged["other"] = leftover

    return merged, rate


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def list_splits() -> list[Split]:
    data = store.load()
    splits = sorted(data.get("splits", []), key=lambda item: item.get("createdAt", ""), reverse=True)
    return [Split(**split) for split in splits]


def get_split(split_id: str) -> Split:
    data = store.load()
    return Split(**_find_split(data, split_id))


def get_split_job(split_id: str) -> SplitJob:
    data = store.load()
    split = _find_split(data, split_id)
    job = split.get("job")
    if not job:
        raise HTTPException(status_code=404, detail="This split has no job.")
    return SplitJob(**job)


def request_split_cancel(split_id: str) -> Split:
    def apply(split: dict[str, Any]) -> None:
        if split.get("status") not in ACTIVE_SPLIT_STATUSES:
            raise HTTPException(status_code=400, detail="This split is not running.")
        job = split.setdefault("job", {})
        job["cancelRequested"] = True
        job["message"] = "Cancelling after the current segment..."
        job["updatedAt"] = utc_now_iso()

    return Split(**_mutate_split(split_id, apply))


def delete_split(split_id: str) -> dict[str, str]:
    with _SPLIT_LOCK:
        data = store.load()
        split = _find_split(data, split_id)
        if split.get("status") in ACTIVE_SPLIT_STATUSES:
            raise HTTPException(status_code=400, detail="Cancel the split before deleting it.")
        data["splits"] = [item for item in data.get("splits", []) if item.get("id") != split_id]
        store.save(data)

    shutil.rmtree(split_subdirs(split_id)["root"], ignore_errors=True)
    return {"status": "deleted", "splitId": split_id}


def _find_cached_split(
    data: dict[str, Any],
    video_id: str | None,
    stem_set: str,
    depth: str,
) -> dict[str, Any] | None:
    if not video_id:
        return None
    for split in data.get("splits", []):
        if split.get("videoId") != video_id or split.get("stemSet") != stem_set:
            continue
        if split.get("depth", "standard") != depth:
            continue
        if split.get("status") != "Ready":
            continue
        stems = split.get("stems") or []
        if stems and all((SPLITS_ROOT / split["id"] / "stems" / stem["fileName"]).exists() for stem in stems):
            return split
    return None


def create_split(payload: CreateSplitRequest) -> Split:
    _require_separation_environment()

    url = (payload.url or "").strip()
    if not _URL_PATTERN.match(url):
        raise HTTPException(status_code=400, detail="The URL must start with http:// or https://.")

    stem_set = payload.stemSet if payload.stemSet in SPLIT_MODELS else "6"
    # Deep only buys anything for guitar and piano, which only the 6-stem model
    # produces, so it is silently ignored for the 4-stem set.
    depth = payload.depth if payload.depth in ("standard", "deep") else "standard"
    if stem_set != "6":
        depth = "standard"
    model_name = (
        SPLIT_MODELS[stem_set]
        if depth == "standard"
        else f"{SPLIT_MODELS['4']} -> {SPLIT_MODELS[stem_set]}"
    )

    with _SPLIT_LOCK:
        data = store.load()
        data.setdefault("splits", [])

        running = next((item for item in data["splits"] if item.get("status") in ACTIVE_SPLIT_STATUSES), None)
        if running:
            raise HTTPException(
                status_code=409,
                detail="A split is already running. Separation is CPU-bound, so they run one at a time.",
            )

        cached = _find_cached_split(data, _extract_video_id(url), stem_set, depth)
        if cached:
            _log(cached["id"], "Reused cached split for the same source and stem set.")
            return Split(**cached)

        now = utc_now_iso()
        split_id = uuid.uuid4().hex
        split = {
            "id": split_id,
            "url": url,
            "videoId": _extract_video_id(url),
            "title": "Fetching...",
            "uploader": None,
            "durationSeconds": 0.0,
            "stemSet": stem_set,
            "depth": depth,
            "modelName": model_name,
            "status": "Pending",
            "createdAt": now,
            "updatedAt": now,
            "completedAt": None,
            "error": None,
            "stems": [],
            "job": {
                "id": uuid.uuid4().hex,
                "splitId": split_id,
                "status": "Pending",
                "progress": 0,
                "message": "Split queued.",
                "cancelRequested": False,
                "createdAt": now,
                "updatedAt": now,
            },
        }
        data["splits"].append(split)
        store.save(data)

    ensure_split_dirs(split_id)
    _log(split_id, f"Split queued for {url} using {model_name}.")
    return Split(**split)


def run_split(split_id: str) -> None:
    """Background worker. Never raises: failures are recorded on the split."""
    started = time.time()
    try:
        data = store.load()
        split = _find_split(data, split_id)
        model_name = split["modelName"]
        stem_set = split.get("stemSet", "6")
        depth = split.get("depth", "standard")
        url = split["url"]
        dirs = ensure_split_dirs(split_id)
        ffmpeg_path = _ffmpeg()

        wav_path = dirs["source"] / "input.wav"

        # --- download -----------------------------------------------------
        # A retry after a failed separation reuses the audio already on disk
        # instead of pulling it down again.
        if wav_path.exists() and split.get("durationSeconds"):
            _set_progress(split_id, "Preparing", 14, "Reusing downloaded audio...")
            _log(split_id, "Reused the audio already downloaded for this split.")
        else:
            _set_progress(split_id, "Downloading", 4, "Downloading audio...")
            info = _download_audio(split_id, url, dirs["source"])
            if _cancel_requested(split_id):
                raise SplitCancelled()

            def apply_info(item: dict[str, Any]) -> None:
                item["title"] = info["title"]
                item["uploader"] = info.get("uploader")
                item["durationSeconds"] = float(info.get("duration") or 0)
                if info.get("videoId"):
                    item["videoId"] = info["videoId"]

            _mutate_split(split_id, apply_info)
            _log(split_id, f"Downloaded '{info['title']}'.")

            # --- convert --------------------------------------------------
            _set_progress(split_id, "Preparing", 14, "Converting to 44.1 kHz WAV...")
            _convert_to_wav(ffmpeg_path, info["path"], wav_path)

        if _cancel_requested(split_id):
            raise SplitCancelled()

        # --- separate -----------------------------------------------------
        _set_progress(split_id, "Separating", 20, f"Loading {model_name}...")

        last_report = {"at": 0.0}

        def on_progress(fraction: float) -> None:
            # 20% to 88% of the bar belongs to separation.
            now = time.time()
            if now - last_report["at"] < 1.5:
                return
            last_report["at"] = now
            stage = ""
            if depth == "deep" and stem_set == "6":
                stage = " (pass 1 of 2)" if fraction < 0.5 else " (pass 2 of 2)"
            _set_progress(
                split_id,
                "Separating",
                20 + int(fraction * 68),
                f"Separating sources{stage}... {int(fraction * 100)}%",
            )

        stems, samplerate = _separate(split_id, wav_path, stem_set, depth, on_progress)
        if _cancel_requested(split_id):
            raise SplitCancelled()

        # --- write stems + previews ---------------------------------------
        _set_progress(split_id, "Finishing", 90, "Writing stem files...")
        written: list[dict[str, Any]] = []
        ordered = [name for name in SPLIT_STEM_ORDER if name in stems]
        ordered += [name for name in stems if name not in ordered]

        for index, name in enumerate(ordered):
            samples = stems[name]
            stem_path = dirs["stems"] / f"{name}.wav"
            _write_wav(stem_path, samples, samplerate)

            preview_path = dirs["preview"] / f"{name}.mp3"
            has_preview = _encode_preview(ffmpeg_path, stem_path, preview_path)

            peak_db, rms_db = _levels(samples)
            presentation = SPLIT_STEM_PRESENTATION.get(name, {})
            written.append(
                {
                    "id": uuid.uuid4().hex,
                    "source": name,
                    "label": presentation.get("label", name.title()),
                    "note": presentation.get("note", ""),
                    "color": presentation.get("color", "#94a3b8"),
                    "quality": presentation.get("quality", "good"),
                    "fileName": stem_path.name,
                    "filePath": _relative_media_path(stem_path),
                    "previewPath": _relative_media_path(preview_path) if has_preview else None,
                    "peakDb": peak_db,
                    "rmsDb": rms_db,
                    "order": index,
                }
            )
            _set_progress(split_id, "Finishing", 90 + int(((index + 1) / len(ordered)) * 8), f"Wrote {name}.wav")

        elapsed = time.time() - started

        def finish(item: dict[str, Any]) -> None:
            item["stems"] = written
            item["status"] = "Ready"
            item["completedAt"] = utc_now_iso()
            item["error"] = None
            item["elapsedSeconds"] = round(elapsed, 1)
            job = item.setdefault("job", {})
            job["status"] = "Completed"
            job["progress"] = 100
            job["message"] = f"Done in {elapsed / 60:.1f} min."
            job["updatedAt"] = utc_now_iso()

        _mutate_split(split_id, finish)
        _log(split_id, f"Split completed in {elapsed:.0f}s with {len(written)} stems.")

    except SplitCancelled:
        _log(split_id, "Split cancelled by user.")

        def cancelled(item: dict[str, Any]) -> None:
            item["status"] = "Cancelled"
            item["error"] = None
            job = item.setdefault("job", {})
            job["status"] = "Cancelled"
            job["message"] = "Cancelled."
            job["updatedAt"] = utc_now_iso()

        try:
            _mutate_split(split_id, cancelled)
        except HTTPException:
            pass

    except Exception as exc:  # noqa: BLE001 - background task must not escape
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        _log(split_id, f"Split failed: {detail}")

        def failed(item: dict[str, Any]) -> None:
            item["status"] = "Failed"
            item["error"] = str(detail)
            job = item.setdefault("job", {})
            job["status"] = "Failed"
            job["message"] = str(detail)
            job["updatedAt"] = utc_now_iso()

        try:
            _mutate_split(split_id, failed)
        except HTTPException:
            pass


def export_split_mix(split_id: str, payload: ExportSplitMixRequest) -> dict[str, Any]:
    """Render a custom mixdown from the stems, honouring mute and gain."""
    data = store.load()
    split = _find_split(data, split_id)
    if split.get("status") != "Ready":
        raise HTTPException(status_code=400, detail="This split is not ready yet.")

    stems = {stem["id"]: stem for stem in split.get("stems", [])}
    if not stems:
        raise HTTPException(status_code=400, detail="This split has no stems.")

    requested = payload.stems or []
    if not requested:
        raise HTTPException(status_code=400, detail="Select at least one stem to export.")

    dirs = split_subdirs(split_id)
    mix: np.ndarray | None = None
    rate = 44100
    used: list[str] = []

    for entry in requested:
        stem = stems.get(entry.stemId)
        if stem is None or entry.muted:
            continue
        stem_path = dirs["stems"] / stem["fileName"]
        if not stem_path.exists():
            continue

        samples, rate = _read_wav(stem_path)
        gain = float(10 ** (entry.gainDb / 20.0))
        samples = samples * gain

        if mix is None:
            mix = samples
        else:
            width = min(mix.shape[1], samples.shape[1])
            mix = mix[:, :width] + samples[:, :width]
        used.append(stem["label"])

    if mix is None:
        raise HTTPException(status_code=400, detail="Every selected stem was muted or missing.")

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 1.0:
        mix = mix / peak * 0.999

    name = _sanitize(payload.name or f"{split.get('title', 'mix')}_custom")
    destination = dirs["exports"] / f"{name}.wav"
    counter = 1
    while destination.exists():
        destination = dirs["exports"] / f"{name}_{counter}.wav"
        counter += 1

    _write_wav(destination, mix, rate)

    if payload.format == "mp3":
        mp3_path = destination.with_suffix(".mp3")
        if _encode_preview(_ffmpeg(), destination, mp3_path):
            destination.unlink(missing_ok=True)
            destination = mp3_path

    _log(split_id, f"Exported custom mix '{destination.name}' from: {', '.join(used)}.")
    return {
        "fileName": destination.name,
        "filePath": _relative_media_path(destination),
        "stems": used,
        "peakDb": _levels(mix)[0],
    }

def mark_interrupted_splits() -> None:
    """Called at startup.

    A split that was mid-flight when the backend stopped can never resume, and
    leaving it Running would block every future split through the one-at-a-time
    guard. Restarting the backend clears the jam.
    """
    with _SPLIT_LOCK:
        data = store.load()
        changed = False
        for split in data.get("splits", []):
            if split.get("status") not in ACTIVE_SPLIT_STATUSES:
                continue
            split["status"] = "Failed"
            split["error"] = "The backend restarted while this split was running."
            split["updatedAt"] = utc_now_iso()
            job = split.setdefault("job", {})
            job["status"] = "Failed"
            job["message"] = "Interrupted by a backend restart."
            job["cancelRequested"] = False
            job["updatedAt"] = utc_now_iso()
            changed = True
        if changed:
            store.save(data)

def retry_split(split_id: str) -> Split:
    """Re-run a failed or cancelled split, reusing audio already downloaded."""
    with _SPLIT_LOCK:
        data = store.load()
        split = _find_split(data, split_id)
        if split.get("status") in ACTIVE_SPLIT_STATUSES:
            raise HTTPException(status_code=400, detail="This split is already running.")
        if split.get("status") == "Ready":
            raise HTTPException(status_code=400, detail="This split already finished.")

        running = next(
            (item for item in data.get("splits", []) if item.get("status") in ACTIVE_SPLIT_STATUSES),
            None,
        )
        if running:
            raise HTTPException(status_code=409, detail="Another split is running. Separation runs one at a time.")

        now = utc_now_iso()
        split["status"] = "Pending"
        split["error"] = None
        split["completedAt"] = None
        job = split.setdefault("job", {})
        job["status"] = "Pending"
        job["progress"] = 0
        job["message"] = "Split re-queued."
        job["cancelRequested"] = False
        job["updatedAt"] = now
        split["updatedAt"] = now
        store.save(data)

    ensure_split_dirs(split_id)
    _log(split_id, "Split re-queued by retry.")
    return Split(**split)


def archive_split_stems(split_id: str) -> dict[str, Any]:
    """Zip every stem so the player needs one click instead of six."""
    import zipfile

    data = store.load()
    split = _find_split(data, split_id)
    if split.get("status") != "Ready":
        raise HTTPException(status_code=400, detail="This split is not ready yet.")

    dirs = split_subdirs(split_id)
    stems = split.get("stems") or []
    present = [(stem, dirs["stems"] / stem["fileName"]) for stem in stems]
    present = [(stem, path) for stem, path in present if path.exists()]
    if not present:
        raise HTTPException(status_code=404, detail="No stem files were found on disk.")

    name = _sanitize(f"{split.get('title', 'split')}_stems")
    destination = dirs["exports"] / f"{name}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for stem, path in present:
            # ZIP_STORED, not DEFLATE: PCM audio barely compresses and deflating
            # ~350MB of WAV would cost far more time than the bytes it saves.
            archive.write(path, arcname=f"{name}/{stem['label'].lower()}.wav")

    _log(split_id, f"Archived {len(present)} stems into {destination.name}.")
    return {
        "fileName": destination.name,
        "filePath": _relative_media_path(destination),
        "stemCount": len(present),
        "bytes": destination.stat().st_size,
    }


def active_split_summary() -> dict[str, Any] | None:
    """Small payload for the global job bar, so a running split stays visible
    from anywhere in the app."""
    data = store.load()
    for split in data.get("splits", []):
        if split.get("status") in ACTIVE_SPLIT_STATUSES:
            job = split.get("job") or {}
            return {
                "splitId": split["id"],
                "title": split.get("title"),
                "status": split.get("status"),
                "progress": job.get("progress", 0),
                "message": job.get("message"),
            }
    return None

