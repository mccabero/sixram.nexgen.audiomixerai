import uuid
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .audio_engine import clean_audio_file, ensure_audio_environment
from .logging_utils import append_project_log, utc_now_iso
from .models import ProcessingJob, Project, Stem, UpdateCleaningSettingsRequest, validate_cleaning_mode
from .stem_detection import effective_stem_type
from .storage import (
    _find_project,
    display_path,
    ensure_project_dirs,
    project_subdirs,
    resolve_stored_file_path,
    store,
)


ACTIVE_JOB_STATUSES = {"Pending", "Processing"}
STALE_CLEANING_JOB_AFTER = timedelta(minutes=30)
VALID_HUM_FREQUENCIES = {50, 60}
RUNNING_CLEANING_JOB_IDS: set[str] = set()
RUNNING_CLEANING_JOB_LOCK = threading.Lock()


def update_stem_cleaning_settings(project_id: str, stem_id: str, payload: UpdateCleaningSettingsRequest) -> Stem:
    data = store.load()
    project = _find_project(data, project_id)
    stem = _find_stem(project, stem_id)
    settings = _ensure_cleaning_settings(stem)

    if payload.mode is not None:
        if not validate_cleaning_mode(payload.mode):
            raise HTTPException(status_code=400, detail="Invalid cleaning mode.")
        settings["mode"] = payload.mode
        settings["enabled"] = payload.mode != "Off"
    if payload.enabled is not None:
        settings["enabled"] = bool(payload.enabled)
        if settings["enabled"] and settings.get("mode") == "Off":
            settings["mode"] = "Light"
        if not settings["enabled"]:
            settings["mode"] = "Off"
    if payload.humRemoval is not None:
        settings["humRemoval"] = bool(payload.humRemoval)
    if payload.humFrequency is not None:
        if payload.humFrequency not in VALID_HUM_FREQUENCIES:
            raise HTTPException(status_code=400, detail="Hum frequency must be 50Hz or 60Hz.")
        settings["humFrequency"] = int(payload.humFrequency)
    if payload.useCleanedInMix is not None:
        settings["useCleanedInMix"] = bool(payload.useCleanedInMix)

    if not settings.get("enabled") or settings.get("mode") == "Off":
        stem["cleaningStatus"] = "Disabled"
    elif _cleaning_result_matches(stem, settings):
        stem["cleaningStatus"] = "Completed"
    else:
        stem["cleaningStatus"] = "Pending"

    _clear_rough_mix_reference(project)
    project["updatedAt"] = utc_now_iso()
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Updated cleaning settings for {stem['originalFilename']}.")
    return Stem(**stem)


def create_cleaning_job(project_id: str) -> ProcessingJob:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    data = store.load()
    project = _find_project(data, project_id)
    if not project.get("stems"):
        raise HTTPException(status_code=400, detail="Upload stems before running cleaning.")
    if not _enabled_stems(project):
        raise HTTPException(status_code=400, detail="Enable cleaning for at least one stem before running cleaning.")

    active_job = next(
        (job for job in reversed(project.get("processingJobs", [])) if job.get("type") == "Cleaning" and job.get("status") in ACTIVE_JOB_STATUSES),
        None,
    )
    if active_job:
        if _cleaning_job_is_stale(active_job):
            _mark_stale_cleaning_job(project, active_job, project_id)
        else:
            append_project_log(project_subdirs(project_id)["logs"], f"Reused active cleaning job {active_job['id']}.")
            return ProcessingJob(**active_job)

    now = utc_now_iso()
    job = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "type": "Cleaning",
        "status": "Pending",
        "progress": 0,
        "currentStemId": None,
        "message": "Cleaning queued.",
        "errors": [],
        "createdAt": now,
        "updatedAt": now,
        "completedAt": None,
    }
    project.setdefault("processingJobs", []).append(job)
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Cleaning job {job['id']} queued.")
    return ProcessingJob(**job)


def _cleaning_job_is_stale(job: dict[str, Any]) -> bool:
    updated_at = job.get("updatedAt") or job.get("createdAt")
    if not updated_at:
        return True
    try:
        parsed = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - parsed > STALE_CLEANING_JOB_AFTER


def _mark_stale_cleaning_job(project: dict[str, Any], job: dict[str, Any], project_id: str) -> None:
    now = utc_now_iso()
    message = "Previous cleaning job was interrupted or stopped. Start cleaning again."
    job["status"] = "Failed"
    job["progress"] = 100
    job["currentStemId"] = None
    job["message"] = message
    job.setdefault("errors", []).append({"stemId": None, "filename": None, "error": message})
    job["updatedAt"] = now
    job["completedAt"] = now
    for stem in project.get("stems", []):
        settings = _ensure_cleaning_settings(stem)
        if not settings.get("enabled") or settings.get("mode") == "Off":
            stem["cleaningStatus"] = "Disabled"
        elif _cleaning_result_matches(stem, settings):
            stem["cleaningStatus"] = "Completed"
        elif stem.get("cleaningStatus") in {"Processing", "Pending"}:
            stem["cleaningStatus"] = "Pending"
    project["updatedAt"] = now
    append_project_log(project_subdirs(project_id)["logs"], f"Marked stale cleaning job {job.get('id')} as failed before queuing a new job.")


def run_cleaning_job(project_id: str, job_id: str) -> None:
    with RUNNING_CLEANING_JOB_LOCK:
        if job_id in RUNNING_CLEANING_JOB_IDS:
            append_project_log(project_subdirs(project_id)["logs"], f"Ignored duplicate cleaning runner for job {job_id}.")
            return
        RUNNING_CLEANING_JOB_IDS.add(job_id)

    try:
        _run_cleaning_job(project_id, job_id)
    finally:
        with RUNNING_CLEANING_JOB_LOCK:
            RUNNING_CLEANING_JOB_IDS.discard(job_id)


def _run_cleaning_job(project_id: str, job_id: str) -> None:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        _fail_job(project_id, job_id, str(exc))
        return

    _update_job(project_id, job_id, status="Processing", progress=1, message="Cleaning stems.")
    append_project_log(project_subdirs(project_id)["logs"], f"Cleaning job {job_id} started.")

    data = store.load()
    project = _find_project(data, project_id)
    stems = _enabled_stems(project)
    total = len(stems)
    successes = 0

    for index, stem in enumerate(stems, start=1):
        settings = _ensure_cleaning_settings(stem)
        _update_job(
            project_id,
            job_id,
            currentStemId=stem["id"],
            message=f"Cleaning {stem['originalFilename']}.",
            progress=max(1, int(((index - 1) / total) * 100)),
        )
        _update_stem_cleaning(project_id, stem["id"], status="Processing")
        try:
            source_path = resolve_stored_file_path(stem["filePath"])
            if not source_path.exists():
                raise FileNotFoundError(f"Stored file not found: {stem['filePath']}")

            output_dir = project_subdirs(project_id)["processed"] / "cleaned"
            output_path = _unique_cleaned_path(output_dir, stem["originalFilename"])
            stem_type = effective_stem_type(stem)
            if stem_type == "Unknown":
                stem_type = stem.get("stemType", "Unknown")

            result = clean_audio_file(
                source_path,
                output_path,
                stem_type=stem_type,
                mode=settings["mode"],
                hum_removal=bool(settings.get("humRemoval")),
                hum_frequency=int(settings.get("humFrequency", 60)),
            )
            cleaned_path = display_path(result.path)
            cleaning_result = {
                "stemId": stem["id"],
                "status": "Completed",
                "cleanedAt": utc_now_iso(),
                "originalFilePath": stem["filePath"],
                "cleanedFilePath": cleaned_path,
                "cleanedFileUrl": _media_url(cleaned_path),
                "mode": settings["mode"],
                "humRemoval": bool(settings.get("humRemoval")),
                "humFrequency": int(settings.get("humFrequency", 60)),
                "peakDbfs": result.peak_dbfs,
                "rmsDbfs": result.rms_dbfs,
                "noiseFloorDbfs": result.noise_floor_dbfs,
                "originalMetrics": result.original_metrics,
                "cleanedMetrics": result.cleaned_metrics,
                "metricDeltas": result.metric_deltas,
                "operations": result.operations,
                "warnings": result.warnings,
                "error": None,
            }
            _update_stem_cleaning(project_id, stem["id"], status="Completed", result=cleaning_result)
            successes += 1
            append_project_log(project_subdirs(project_id)["logs"], f"Cleaned stem {stem['originalFilename']} to {cleaned_path}.")
        except Exception as exc:
            error_message = str(exc) or "Cleaning failed."
            cleaning_result = {
                "stemId": stem["id"],
                "status": "Failed",
                "cleanedAt": utc_now_iso(),
                "originalFilePath": stem.get("filePath"),
                "cleanedFilePath": None,
                "cleanedFileUrl": None,
                "mode": settings.get("mode", "Off"),
                "humRemoval": bool(settings.get("humRemoval")),
                "humFrequency": int(settings.get("humFrequency", 60)),
                "peakDbfs": None,
                "rmsDbfs": None,
                "noiseFloorDbfs": None,
                "originalMetrics": None,
                "cleanedMetrics": None,
                "metricDeltas": {},
                "operations": [],
                "warnings": ["Cleaning failed; the mixer will continue using the original stem."],
                "error": error_message,
            }
            _update_stem_cleaning(project_id, stem["id"], status="Failed", result=cleaning_result)
            _append_job_error(project_id, job_id, stem["id"], stem["originalFilename"], error_message)
            append_project_log(project_subdirs(project_id)["logs"], f"Cleaning failed for {stem['originalFilename']}: {error_message}")

        _update_job(project_id, job_id, progress=int((index / total) * 100))

    final_status = "Completed" if successes > 0 else "Failed"
    final_message = "Cleaning completed." if final_status == "Completed" else "Cleaning failed for all enabled stems."
    now = utc_now_iso()
    data = store.load()
    project = _find_project(data, project_id)
    project["status"] = "Cleaned" if final_status == "Completed" else project.get("status", "Stems Uploaded")
    project["updatedAt"] = now
    _clear_rough_mix_reference(project)
    job = _find_job(project, job_id)
    job["status"] = final_status
    job["progress"] = 100
    job["currentStemId"] = None
    job["message"] = final_message
    job["updatedAt"] = now
    job["completedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Cleaning job {job_id} {final_status.lower()}.")


def _enabled_stems(project: dict[str, Any]) -> list[dict[str, Any]]:
    enabled = []
    for stem in project.get("stems", []):
        settings = _ensure_cleaning_settings(stem)
        if settings.get("enabled") and settings.get("mode") != "Off":
            enabled.append(stem)
    return enabled


def _ensure_cleaning_settings(stem: dict[str, Any]) -> dict[str, Any]:
    settings = stem.setdefault(
        "cleaningSettings",
        {
            "enabled": False,
            "mode": "Off",
            "humRemoval": False,
            "humFrequency": 60,
            "useCleanedInMix": True,
        },
    )
    settings.setdefault("enabled", False)
    settings.setdefault("mode", "Off")
    settings.setdefault("humRemoval", False)
    settings.setdefault("humFrequency", 60)
    settings.setdefault("useCleanedInMix", True)
    stem.setdefault("cleaningStatus", "Not Cleaned")
    stem.setdefault("cleaningResult", None)
    return settings


def _cleaning_result_matches(stem: dict[str, Any], settings: dict[str, Any]) -> bool:
    result = stem.get("cleaningResult")
    if not result or result.get("status") != "Completed":
        return False
    return (
        result.get("mode") == settings.get("mode")
        and bool(result.get("humRemoval")) == bool(settings.get("humRemoval"))
        and int(result.get("humFrequency", 60)) == int(settings.get("humFrequency", 60))
        and bool(result.get("cleanedFilePath"))
    )


def _update_stem_cleaning(project_id: str, stem_id: str, status: str, result: dict[str, Any] | None = None) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    stem = _find_stem(project, stem_id)
    stem["cleaningStatus"] = status
    if result is not None:
        stem["cleaningResult"] = result
    _clear_rough_mix_reference(project)
    project["updatedAt"] = utc_now_iso()
    store.save(data)


def _update_job(project_id: str, job_id: str, **updates: Any) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    job.update(updates)
    job["updatedAt"] = utc_now_iso()
    store.save(data)


def _append_job_error(project_id: str, job_id: str, stem_id: str, filename: str, error: str) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    job.setdefault("errors", []).append({"stemId": stem_id, "filename": filename, "error": error})
    job["updatedAt"] = utc_now_iso()
    store.save(data)


def _fail_job(project_id: str, job_id: str, error_message: str) -> None:
    now = utc_now_iso()
    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    job["status"] = "Failed"
    job["progress"] = 100
    job["currentStemId"] = None
    job["message"] = error_message
    job.setdefault("errors", []).append({"stemId": None, "filename": None, "error": error_message})
    job["updatedAt"] = now
    job["completedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Cleaning job {job_id} failed: {error_message}")


def _find_job(project: dict[str, Any], job_id: str) -> dict[str, Any]:
    job = next((item for item in project.get("processingJobs", []) if item["id"] == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    return job


def _find_stem(project: dict[str, Any], stem_id: str) -> dict[str, Any]:
    stem = next((item for item in project.get("stems", []) if item["id"] == stem_id), None)
    if stem is None:
        raise HTTPException(status_code=404, detail="Stem not found.")
    return stem


def _unique_cleaned_path(output_dir: Path, original_filename: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = Path(original_filename).stem
    safe_base = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in base).strip("._-") or "stem"
    version = 1
    while (output_dir / f"{safe_base}_cleaned_v{version:03d}.wav").exists():
        version += 1
    return output_dir / f"{safe_base}_cleaned_v{version:03d}.wav"


def _clear_rough_mix_reference(project: dict[str, Any]) -> None:
    mix_settings = project.setdefault("mixSettings", {})
    mix_settings["roughMixWavPath"] = None
    mix_settings["roughMixMp3Path"] = None
    mix_settings["roughMixWavUrl"] = None
    mix_settings["roughMixMp3Url"] = None
    mix_settings["updatedAt"] = utc_now_iso()


def _media_url(path_value: str | None) -> str | None:
    if path_value is None:
        return None
    normalized = path_value.replace("\\", "/")
    if normalized.startswith("storage/"):
        normalized = normalized[len("storage/") :]
    return f"/media/{normalized}"
