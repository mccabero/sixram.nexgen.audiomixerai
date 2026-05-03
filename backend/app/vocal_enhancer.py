import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .audio_engine import enhance_vocal_file, ensure_audio_environment
from .logging_utils import append_project_log, utc_now_iso
from .models import (
    ProcessingJob,
    Project,
    Stem,
    UpdateVocalEnhancementSettingsRequest,
    VOCAL_ENHANCER_PRESETS,
    validate_music_key,
    validate_music_scale,
    validate_pitch_correction_mode,
    validate_vocal_enhancer_preset,
)
from .stem_detection import effective_stem_type
from .storage import (
    _find_project,
    display_path,
    project_subdirs,
    resolve_stored_file_path,
    store,
)


ACTIVE_JOB_STATUSES = {"Pending", "Processing"}
VOCAL_TYPES = {"Lead Vocal", "Backing Vocal"}
RUNNING_VOCAL_JOB_IDS: set[str] = set()
RUNNING_VOCAL_JOB_LOCK = threading.Lock()


def get_vocal_enhancer_presets() -> dict[str, list[str]]:
    return {
        "presets": VOCAL_ENHANCER_PRESETS,
        "pitchCorrectionModes": ["Off", "Natural", "Medium", "Strong"],
        "keys": ["Auto", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"],
        "scales": ["Major", "Minor", "Chromatic"],
    }


def update_vocal_enhancement_settings(project_id: str, stem_id: str, payload: UpdateVocalEnhancementSettingsRequest) -> Stem:
    data = store.load()
    project = _find_project(data, project_id)
    stem = _find_stem(project, stem_id)
    settings = _ensure_vocal_settings(stem)

    if payload.preset is not None:
        if not validate_vocal_enhancer_preset(payload.preset):
            raise HTTPException(status_code=400, detail="Invalid vocal enhancer preset.")
        settings["preset"] = payload.preset
    if payload.pitchCorrection is not None:
        if not validate_pitch_correction_mode(payload.pitchCorrection):
            raise HTTPException(status_code=400, detail="Invalid pitch correction mode.")
        settings["pitchCorrection"] = payload.pitchCorrection
    if payload.key is not None:
        if not validate_music_key(payload.key):
            raise HTTPException(status_code=400, detail="Invalid music key.")
        settings["key"] = payload.key
    if payload.scale is not None:
        if not validate_music_scale(payload.scale):
            raise HTTPException(status_code=400, detail="Invalid music scale.")
        settings["scale"] = payload.scale
    if payload.enabled is not None:
        settings["enabled"] = bool(payload.enabled)
    if payload.useEnhancedInMix is not None:
        settings["useEnhancedInMix"] = bool(payload.useEnhancedInMix)

    if not settings.get("enabled"):
        stem["vocalEnhancementStatus"] = "Disabled"
    elif _enhancement_result_matches(stem, settings):
        stem["vocalEnhancementStatus"] = "Completed"
    else:
        stem["vocalEnhancementStatus"] = "Pending"

    _clear_rough_mix_reference(project)
    project["updatedAt"] = utc_now_iso()
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Updated vocal enhancer settings for {stem['originalFilename']}.")
    return Stem(**stem)


def create_vocal_enhancement_job(project_id: str) -> ProcessingJob:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    data = store.load()
    project = _find_project(data, project_id)
    if not project.get("stems"):
        raise HTTPException(status_code=400, detail="Upload stems before enhancing vocals.")
    if not _enabled_vocal_stems(project):
        raise HTTPException(status_code=400, detail="Enable vocal enhancement for at least one vocal stem.")

    active_job = next(
        (job for job in reversed(project.get("processingJobs", [])) if job.get("type") == "Vocal Enhancement" and job.get("status") in ACTIVE_JOB_STATUSES),
        None,
    )
    if active_job:
        append_project_log(project_subdirs(project_id)["logs"], f"Reused active vocal enhancement job {active_job['id']}.")
        return ProcessingJob(**active_job)

    now = utc_now_iso()
    job = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "type": "Vocal Enhancement",
        "status": "Pending",
        "progress": 0,
        "currentStemId": None,
        "message": "Vocal enhancement queued.",
        "errors": [],
        "createdAt": now,
        "updatedAt": now,
        "completedAt": None,
    }
    project.setdefault("processingJobs", []).append(job)
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Vocal enhancement job {job['id']} queued.")
    return ProcessingJob(**job)


def run_vocal_enhancement_job(project_id: str, job_id: str) -> None:
    with RUNNING_VOCAL_JOB_LOCK:
        if job_id in RUNNING_VOCAL_JOB_IDS:
            append_project_log(project_subdirs(project_id)["logs"], f"Ignored duplicate vocal enhancement runner for job {job_id}.")
            return
        RUNNING_VOCAL_JOB_IDS.add(job_id)

    try:
        _run_vocal_enhancement_job(project_id, job_id)
    finally:
        with RUNNING_VOCAL_JOB_LOCK:
            RUNNING_VOCAL_JOB_IDS.discard(job_id)


def _run_vocal_enhancement_job(project_id: str, job_id: str) -> None:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        _fail_job(project_id, job_id, str(exc))
        return

    _update_job(project_id, job_id, status="Processing", progress=1, message="Enhancing vocal stems.")
    append_project_log(project_subdirs(project_id)["logs"], f"Vocal enhancement job {job_id} started.")

    data = store.load()
    project = _find_project(data, project_id)
    stems = _enabled_vocal_stems(project)
    total = len(stems)
    successes = 0

    for index, stem in enumerate(stems, start=1):
        settings = _ensure_vocal_settings(stem)
        _update_job(
            project_id,
            job_id,
            currentStemId=stem["id"],
            message=f"Enhancing {stem['originalFilename']}.",
            progress=max(1, int(((index - 1) / total) * 100)),
        )
        _update_stem_vocal(project_id, stem["id"], status="Processing")
        try:
            source_path, source_kind, source_display_path = _vocal_source_path(stem)
            if not source_path.exists():
                raise FileNotFoundError(f"Stored file not found: {source_display_path}")

            output_dir = project_subdirs(project_id)["processed"] / "vocals"
            output_path = _unique_enhanced_path(output_dir, stem["originalFilename"])
            result = enhance_vocal_file(
                source_path,
                output_path,
                preset=settings["preset"],
                pitch_correction=settings["pitchCorrection"],
                key=settings["key"],
                scale=settings["scale"],
            )
            enhanced_path = display_path(result.path)
            enhancement_result = {
                "stemId": stem["id"],
                "status": "Completed",
                "enhancedAt": utc_now_iso(),
                "sourceFilePath": source_display_path,
                "sourceKind": source_kind,
                "enhancedFilePath": enhanced_path,
                "enhancedFileUrl": _media_url(enhanced_path),
                "preset": settings["preset"],
                "pitchCorrection": settings["pitchCorrection"],
                "key": settings["key"],
                "scale": settings["scale"],
                "peakDbfs": result.peak_dbfs,
                "rmsDbfs": result.rms_dbfs,
                "integratedLufs": result.integrated_lufs,
                "originalMetrics": result.original_metrics,
                "enhancedMetrics": result.enhanced_metrics,
                "metricDeltas": result.metric_deltas,
                "operations": result.operations,
                "warnings": result.warnings,
                "error": None,
            }
            _update_stem_vocal(project_id, stem["id"], status="Completed", result=enhancement_result)
            successes += 1
            append_project_log(project_subdirs(project_id)["logs"], f"Enhanced vocal {stem['originalFilename']} to {enhanced_path}.")
        except Exception as exc:
            error_message = str(exc) or "Vocal enhancement failed."
            enhancement_result = {
                "stemId": stem["id"],
                "status": "Failed",
                "enhancedAt": utc_now_iso(),
                "sourceFilePath": stem.get("filePath"),
                "sourceKind": "Original",
                "enhancedFilePath": None,
                "enhancedFileUrl": None,
                "preset": settings.get("preset", "Natural Clean"),
                "pitchCorrection": settings.get("pitchCorrection", "Off"),
                "key": settings.get("key", "Auto"),
                "scale": settings.get("scale", "Major"),
                "peakDbfs": None,
                "rmsDbfs": None,
                "integratedLufs": None,
                "originalMetrics": None,
                "enhancedMetrics": None,
                "metricDeltas": {},
                "operations": [],
                "warnings": ["Vocal enhancement failed; the mixer can continue using cleaned/original stem."],
                "error": error_message,
            }
            _update_stem_vocal(project_id, stem["id"], status="Failed", result=enhancement_result)
            _append_job_error(project_id, job_id, stem["id"], stem["originalFilename"], error_message)
            append_project_log(project_subdirs(project_id)["logs"], f"Vocal enhancement failed for {stem['originalFilename']}: {error_message}")

        _update_job(project_id, job_id, progress=int((index / total) * 100))

    final_status = "Completed" if successes > 0 else "Failed"
    final_message = "Vocal enhancement completed." if final_status == "Completed" else "Vocal enhancement failed for all enabled stems."
    now = utc_now_iso()
    data = store.load()
    project = _find_project(data, project_id)
    if final_status == "Completed":
        project["status"] = "Vocals Enhanced"
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
    append_project_log(project_subdirs(project_id)["logs"], f"Vocal enhancement job {job_id} {final_status.lower()}.")


def _enabled_vocal_stems(project: dict[str, Any]) -> list[dict[str, Any]]:
    enabled = []
    for stem in project.get("stems", []):
        settings = _ensure_vocal_settings(stem)
        if not settings.get("enabled"):
            continue
        stem_type = effective_stem_type(stem)
        if stem_type in VOCAL_TYPES or stem.get("stemType") in VOCAL_TYPES:
            enabled.append(stem)
    return enabled


def _ensure_vocal_settings(stem: dict[str, Any]) -> dict[str, Any]:
    settings = stem.setdefault(
        "vocalEnhancementSettings",
        {
            "enabled": False,
            "preset": "Natural Clean",
            "pitchCorrection": "Off",
            "key": "Auto",
            "scale": "Major",
            "useEnhancedInMix": True,
        },
    )
    settings.setdefault("enabled", False)
    settings.setdefault("preset", "Natural Clean")
    settings.setdefault("pitchCorrection", "Off")
    settings.setdefault("key", "Auto")
    settings.setdefault("scale", "Major")
    settings.setdefault("useEnhancedInMix", True)
    stem.setdefault("vocalEnhancementStatus", "Not Enhanced")
    stem.setdefault("vocalEnhancementResult", None)
    return settings


def _enhancement_result_matches(stem: dict[str, Any], settings: dict[str, Any]) -> bool:
    result = stem.get("vocalEnhancementResult")
    if not result or result.get("status") != "Completed":
        return False
    return (
        result.get("preset") == settings.get("preset")
        and result.get("pitchCorrection") == settings.get("pitchCorrection")
        and result.get("key") == settings.get("key")
        and result.get("scale") == settings.get("scale")
        and bool(result.get("enhancedFilePath"))
    )


def _vocal_source_path(stem: dict[str, Any]) -> tuple[Path, str, str]:
    cleaning_settings = stem.get("cleaningSettings") or {}
    cleaning_result = stem.get("cleaningResult") or {}
    if (
        cleaning_settings.get("enabled")
        and cleaning_settings.get("useCleanedInMix", True)
        and cleaning_result.get("status") == "Completed"
        and cleaning_result.get("cleanedFilePath")
    ):
        cleaned_path = resolve_stored_file_path(cleaning_result["cleanedFilePath"])
        if cleaned_path.exists():
            return cleaned_path, "Cleaned", cleaning_result["cleanedFilePath"]
    return resolve_stored_file_path(stem["filePath"]), "Original", stem["filePath"]


def _update_stem_vocal(project_id: str, stem_id: str, status: str, result: dict[str, Any] | None = None) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    stem = _find_stem(project, stem_id)
    stem["vocalEnhancementStatus"] = status
    if result is not None:
        stem["vocalEnhancementResult"] = result
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
    append_project_log(project_subdirs(project_id)["logs"], f"Vocal enhancement job {job_id} failed: {error_message}")


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


def _unique_enhanced_path(output_dir: Path, original_filename: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = Path(original_filename).stem
    safe_base = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in base).strip("._-") or "vocal"
    version = 1
    while (output_dir / f"{safe_base}_enhanced_v{version:03d}.wav").exists():
        version += 1
    return output_dir / f"{safe_base}_enhanced_v{version:03d}.wav"


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
