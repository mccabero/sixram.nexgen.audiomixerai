import uuid
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .audio_engine import analyze_audio_file, ensure_audio_environment, generate_rough_mix
from .logging_utils import append_project_log, utc_now_iso
from .models import ProcessingJob, Project, RoughMixResponse, UpdateMixStemRequest
from .stem_detection import effective_stem_type
from .storage import (
    JobCancelled,
    display_path,
    ensure_project_dirs,
    mark_processing_job_cancelled,
    project_subdirs,
    raise_if_processing_job_cancelled,
    resolve_stored_file_path,
    store,
    _find_project,
)


ROLE_TARGETS = {
    "Lead Vocal": {"target": -18.0, "priority": 100},
    "Drums": {"target": -19.5, "priority": 92},
    "Kick": {"target": -20.0, "priority": 94},
    "Snare": {"target": -22.0, "priority": 86},
    "Bass": {"target": -20.5, "priority": 90},
    "Backing Vocal": {"target": -24.0, "priority": 72},
    "Electric Guitar": {"target": -23.5, "priority": 68},
    "Acoustic Guitar": {"target": -24.5, "priority": 64},
    "Keys/Piano": {"target": -25.0, "priority": 60},
    "Pads/Strings": {"target": -28.0, "priority": 42},
    "FX/Ambience": {"target": -30.0, "priority": 32},
    "Other": {"target": -27.0, "priority": 45},
    "Unknown": {"target": -27.0, "priority": 40},
}


ACTIVE_JOB_STATUSES = {"Pending", "Processing", "Cancelling"}
RUNNING_JOB_IDS: set[str] = set()
RUNNING_JOB_LOCK = threading.Lock()


def create_analysis_job(project_id: str) -> ProcessingJob:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    data = store.load()
    project = _find_project(data, project_id)
    if not project.get("stems"):
        raise HTTPException(status_code=400, detail="Upload stems before running analysis.")
    active_job = next(
        (job for job in reversed(project.get("processingJobs", [])) if job.get("type") == "Analysis" and job.get("status") in ACTIVE_JOB_STATUSES),
        None,
    )
    if active_job:
        append_project_log(project_subdirs(project_id)["logs"], f"Reused active analysis job {active_job['id']}.")
        return ProcessingJob(**active_job)

    now = utc_now_iso()
    job = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "type": "Analysis",
        "status": "Pending",
        "progress": 0,
        "currentStemId": None,
        "message": "Analysis queued.",
        "errors": [],
        "createdAt": now,
        "updatedAt": now,
        "completedAt": None,
    }
    project.setdefault("processingJobs", []).append(job)
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Analysis job {job['id']} queued.")
    return ProcessingJob(**job)


def get_processing_job(project_id: str, job_id: str) -> ProcessingJob:
    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    return ProcessingJob(**job)


def run_analysis_job(project_id: str, job_id: str) -> None:
    with RUNNING_JOB_LOCK:
        if job_id in RUNNING_JOB_IDS:
            append_project_log(project_subdirs(project_id)["logs"], f"Ignored duplicate analysis runner for job {job_id}.")
            return
        RUNNING_JOB_IDS.add(job_id)

    try:
        _run_analysis_job(project_id, job_id)
    except JobCancelled:
        mark_processing_job_cancelled(project_id, job_id)
    finally:
        with RUNNING_JOB_LOCK:
            RUNNING_JOB_IDS.discard(job_id)


def _run_analysis_job(project_id: str, job_id: str) -> None:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        _fail_job(project_id, job_id, str(exc))
        return

    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    if job.get("status") == "Completed":
        append_project_log(project_subdirs(project_id)["logs"], f"Skipped completed analysis job {job_id}.")
        return

    _update_job(project_id, job_id, status="Processing", progress=2, message="Preparing analysis job.")
    append_project_log(project_subdirs(project_id)["logs"], f"Analysis job {job_id} started.")

    data = store.load()
    project = _find_project(data, project_id)
    stems = list(project.get("stems", []))
    total = len(stems)
    successes = 0

    for index, stem in enumerate(stems, start=1):
        _update_job(
            project_id,
            job_id,
            currentStemId=stem["id"],
            message=f"Analyzing {stem['originalFilename']}.",
            progress=_item_progress(index, total, 0.0),
        )
        try:
            file_path = resolve_stored_file_path(stem["filePath"])
            if not file_path.exists():
                raise FileNotFoundError(f"Stored file not found: {stem['filePath']}")

            metrics = analyze_audio_file(
                file_path,
                progress_callback=lambda fraction, message, stem=stem, index=index: _update_job(
                    project_id,
                    job_id,
                    currentStemId=stem["id"],
                    message=f"{message}: {stem['originalFilename']}.",
                    progress=_item_progress(index, total, fraction),
                ),
            )
            result = {
                "stemId": stem["id"],
                "status": "Completed",
                "analyzedAt": utc_now_iso(),
                **metrics,
                "error": None,
            }
            _update_stem_analysis(project_id, stem["id"], result)
            successes += 1
            append_project_log(project_subdirs(project_id)["logs"], f"Analyzed stem {stem['originalFilename']}.")
        except JobCancelled:
            raise
        except Exception as exc:
            error_message = str(exc) or "Analysis failed."
            result = {
                "stemId": stem["id"],
                "status": "Failed",
                "analyzedAt": utc_now_iso(),
                "durationSeconds": None,
                "sampleRate": None,
                "channels": None,
                "peakDbfs": None,
                "rmsDbfs": None,
                "integratedLufs": None,
                "truePeakDbfs": None,
                "clippingDetected": False,
                "clippingSampleCount": 0,
                "clippingPercentage": 0,
                "silencePercentage": None,
                "noiseFloorDbfs": None,
                "warnings": [],
                "error": error_message,
            }
            _update_stem_analysis(project_id, stem["id"], result)
            _append_job_error(project_id, job_id, stem["id"], stem["originalFilename"], error_message)
            append_project_log(project_subdirs(project_id)["logs"], f"Analysis failed for {stem['originalFilename']}: {error_message}")

        _update_job(project_id, job_id, progress=_item_progress(index, total, 1.0))

    raise_if_processing_job_cancelled(project_id, job_id)
    _refresh_analysis_warnings(project_id)
    final_status = "Completed" if successes > 0 else "Failed"
    final_message = "Analysis completed." if final_status == "Completed" else "Analysis failed for all stems."
    now = utc_now_iso()
    data = store.load()
    project = _find_project(data, project_id)
    project["status"] = "Analyzed" if final_status == "Completed" else project.get("status", "Stems Uploaded")
    project["updatedAt"] = now
    job = _find_job(project, job_id)
    job["status"] = final_status
    job["progress"] = 100
    job["currentStemId"] = None
    job["message"] = final_message
    job["updatedAt"] = now
    job["completedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Analysis job {job_id} {final_status.lower()}.")


def generate_auto_balance(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_completed_analysis(project)
    now = utc_now_iso()
    type_counters: dict[str, int] = {}

    for stem in project.get("stems", []):
        stem_type = effective_stem_type(stem)
        type_counters[stem_type] = type_counters.get(stem_type, 0) + 1
        analysis = stem.get("analysisResult") or {}
        role = ROLE_TARGETS.get(stem_type, ROLE_TARGETS["Unknown"])
        target_lufs = role["target"]
        measured_lufs = analysis.get("integratedLufs")
        peak_dbfs = analysis.get("peakDbfs")

        if measured_lufs is None:
            suggested_gain = 0.0
            rationale = "No LUFS analysis yet; conservative neutral gain."
        else:
            suggested_gain = _clamp(target_lufs - float(measured_lufs), -18.0, 12.0)
            if peak_dbfs is not None:
                max_gain_for_headroom = -3.0 - float(peak_dbfs)
                suggested_gain = min(suggested_gain, max_gain_for_headroom)
            rationale = f"Targets {target_lufs:.1f} LUFS for {stem_type.lower()} role."

        suggestion = {
            "stemId": stem["id"],
            "suggestedGainDb": round(suggested_gain, 2),
            "suggestedPan": _suggest_pan(stem_type, type_counters[stem_type]),
            "rolePriority": int(role["priority"]),
            "targetLufs": target_lufs,
            "rationale": rationale,
            "generatedAt": now,
        }
        stem["autoBalanceSuggestion"] = suggestion
        _ensure_mix_setting(project, stem["id"])

    project["mixSettings"]["autoBalanceGeneratedAt"] = now
    project["mixSettings"]["updatedAt"] = now
    project["status"] = "Auto Balance Ready"
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], "Generated auto-balance suggestions.")
    return Project(**project)


def apply_auto_balance(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_completed_analysis(project)
    if not any(stem.get("autoBalanceSuggestion") for stem in project.get("stems", [])):
        store.save(data)
        generate_auto_balance(project_id)
        data = store.load()
        project = _find_project(data, project_id)

    now = utc_now_iso()
    for stem in project.get("stems", []):
        suggestion = stem.get("autoBalanceSuggestion")
        setting = _ensure_mix_setting(project, stem["id"])
        if suggestion:
            setting["gainDb"] = suggestion["suggestedGainDb"]
            setting["pan"] = suggestion["suggestedPan"]
            setting["autoBalanceApplied"] = True

    _clear_rough_mix_reference(project)
    project["mixSettings"]["autoBalanceAppliedAt"] = now
    project["mixSettings"]["updatedAt"] = now
    project["status"] = "Auto Balanced"
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], "Applied auto-balance settings.")
    return Project(**project)


def update_mix_stem(project_id: str, stem_id: str, payload: UpdateMixStemRequest) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    if not any(stem["id"] == stem_id for stem in project.get("stems", [])):
        raise HTTPException(status_code=404, detail="Stem not found.")

    setting = _ensure_mix_setting(project, stem_id)
    if payload.gainDb is not None:
        setting["gainDb"] = round(float(payload.gainDb), 2)
        setting["autoBalanceApplied"] = False
    if payload.pan is not None:
        setting["pan"] = round(float(payload.pan), 2)
        setting["autoBalanceApplied"] = False
    if payload.mute is not None:
        setting["mute"] = payload.mute
    if payload.solo is not None:
        setting["solo"] = payload.solo
    if payload.processingChainEnabled is not None:
        setting["processingChainEnabled"] = bool(payload.processingChainEnabled)
    if payload.reverbSend is not None:
        setting["reverbSend"] = round(float(payload.reverbSend), 2)
    if payload.delaySend is not None:
        setting["delaySend"] = round(float(payload.delaySend), 2)
    if payload.presenceAmount is not None:
        setting["presenceAmount"] = round(float(payload.presenceAmount), 2)
    if payload.compressionAmount is not None:
        setting["compressionAmount"] = round(float(payload.compressionAmount), 2)

    now = utc_now_iso()
    _clear_rough_mix_reference(project)
    project["mixSettings"]["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    changed = ", ".join(payload.model_fields_set) or "settings"
    append_project_log(project_subdirs(project_id)["logs"], f"Updated mixer {changed} for stem {stem_id}. Rough mix preview marked stale.")
    return Project(**project)


def generate_rough_mix_preview(project_id: str) -> RoughMixResponse:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    data = store.load()
    project = _find_project(data, project_id)
    ensure_project_dirs(project_id)
    audible_inputs = _rough_mix_inputs(project)
    if not audible_inputs:
        raise HTTPException(status_code=400, detail="No audible stems are available. Check mute and solo settings.")
    project["mixSettings"]["updatedAt"] = utc_now_iso()
    store.save(data)

    output_dir = project_subdirs(project_id)["processed"] / "rough_mix"
    append_project_log(project_subdirs(project_id)["logs"], "Generating rough mix preview.")
    result = generate_rough_mix(audible_inputs, output_dir)
    if result.mp3_error:
        append_project_log(project_subdirs(project_id)["logs"], f"MP3 preview encode failed; WAV preview is available. {result.mp3_error}")

    wav_path = display_path(result.wav_path)
    mp3_path = display_path(result.mp3_path) if result.mp3_path else None
    wav_url = _media_url(wav_path)
    mp3_url = _media_url(mp3_path) if mp3_path else None

    now = utc_now_iso()
    data = store.load()
    project = _find_project(data, project_id)
    project["mixSettings"]["roughMixWavPath"] = wav_path
    project["mixSettings"]["roughMixMp3Path"] = mp3_path
    project["mixSettings"]["roughMixWavUrl"] = wav_url
    project["mixSettings"]["roughMixMp3Url"] = mp3_url
    project["mixSettings"]["updatedAt"] = now
    project["status"] = "Rough Mix Ready"
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Rough mix preview saved to {wav_path}.")

    return RoughMixResponse(
        wavPath=wav_path,
        mp3Path=mp3_path,
        wavUrl=wav_url,
        mp3Url=mp3_url,
        peakDbfs=result.peak_dbfs,
        limiterGainDb=result.limiter_gain_db,
    )


def _update_stem_analysis(project_id: str, stem_id: str, result: dict[str, Any]) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    stem = next((item for item in project.get("stems", []) if item["id"] == stem_id), None)
    if stem is None:
        return
    stem["analysisResult"] = result
    stem["analysisStatus"] = result["status"]
    if result["status"] == "Completed":
        stem["metadata"] = {
            "durationSeconds": result["durationSeconds"],
            "sampleRate": result["sampleRate"],
            "channels": result["channels"],
        }
    project["updatedAt"] = utc_now_iso()
    store.save(data)


def _update_job(project_id: str, job_id: str, **updates: Any) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    if job.get("status") in {"Cancelling", "Cancelled"}:
        raise JobCancelled(job.get("message") or "Job was stopped by the user.")
    job.update(updates)
    job["updatedAt"] = utc_now_iso()
    store.save(data)


def _item_progress(index: int, total: int, fraction: float, start: int = 4, end: int = 96) -> int:
    if total <= 0:
        return start
    safe_fraction = max(0.0, min(1.0, float(fraction)))
    progress = start + (((index - 1) + safe_fraction) / total) * (end - start)
    return max(start, min(end, int(round(progress))))


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
    append_project_log(project_subdirs(project_id)["logs"], f"Analysis job {job_id} failed: {error_message}")


def _refresh_analysis_warnings(project_id: str) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    completed = [
        stem
        for stem in project.get("stems", [])
        if stem.get("analysisStatus") == "Completed" and isinstance(stem.get("analysisResult"), dict)
    ]
    durations = [
        float(stem["analysisResult"]["durationSeconds"])
        for stem in completed
        if isinstance(stem["analysisResult"].get("durationSeconds"), (int, float))
    ]
    reference_duration = sorted(durations)[len(durations) // 2] if durations else None

    for stem in completed:
        result = stem["analysisResult"]
        warnings = _analysis_warnings(result, reference_duration)
        result["warnings"] = warnings
        for warning in warnings:
            append_project_log(project_subdirs(project_id)["logs"], f"Analysis warning for {stem.get('originalFilename', 'stem')}: {warning}")

    store.save(data)


def _analysis_warnings(result: dict[str, Any], reference_duration: float | None) -> list[str]:
    warnings: list[str] = []
    peak = result.get("peakDbfs")
    lufs = result.get("integratedLufs")
    noise_floor = result.get("noiseFloorDbfs")
    silence = result.get("silencePercentage")
    duration = result.get("durationSeconds")

    if result.get("clippingDetected"):
        warnings.append("Clipping detected in the source stem.")
    if isinstance(noise_floor, (int, float)) and noise_floor > -45:
        warnings.append("Very noisy stem; consider cleaning before mixing.")
    if isinstance(silence, (int, float)) and silence >= 70:
        warnings.append("Mostly silent stem; confirm this file is intentional.")
    if isinstance(peak, (int, float)) and peak > -1.0:
        warnings.append("Very hot stem; auto-mix will preserve extra headroom.")
    if isinstance(lufs, (int, float)) and lufs > -10:
        warnings.append("Very loud stem; avoid adding more gain.")
    if isinstance(peak, (int, float)) and peak < -35:
        warnings.append("Very quiet stem; check the export level.")
    elif isinstance(lufs, (int, float)) and lufs < -38:
        warnings.append("Very quiet stem; check the export level.")
    if isinstance(reference_duration, (int, float)) and isinstance(duration, (int, float)) and reference_duration > 0:
        duration_delta = abs(duration - reference_duration)
        if duration_delta > max(2.0, reference_duration * 0.05):
            warnings.append("Duration differs from the other stems; confirm the stem starts at the same timeline position.")

    return warnings


def _append_job_error(project_id: str, job_id: str, stem_id: str, filename: str, error: str) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    job.setdefault("errors", []).append({"stemId": stem_id, "filename": filename, "error": error})
    job["updatedAt"] = utc_now_iso()
    store.save(data)


def _find_job(project: dict[str, Any], job_id: str) -> dict[str, Any]:
    job = next((item for item in project.get("processingJobs", []) if item["id"] == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    return job


def _require_completed_analysis(project: dict[str, Any]) -> None:
    stems = project.get("stems", [])
    if not stems:
        raise HTTPException(status_code=400, detail="Upload stems before generating auto-balance.")

    incomplete = [
        f"{stem.get('originalFilename', 'Stem')} ({stem.get('analysisStatus', 'Pending')})"
        for stem in stems
        if stem.get("analysisStatus") != "Completed"
    ]
    if incomplete:
        raise HTTPException(
            status_code=400,
            detail=f"Analyze all stems before generating auto-balance. Pending or failed stems: {', '.join(incomplete)}.",
        )


def _ensure_mix_setting(project: dict[str, Any], stem_id: str) -> dict[str, Any]:
    project.setdefault("mixSettings", {}).setdefault("stems", [])
    setting = next((item for item in project["mixSettings"]["stems"] if item["stemId"] == stem_id), None)
    if setting is None:
        setting = {
            "stemId": stem_id,
            "gainDb": 0,
            "pan": 0,
            "mute": False,
            "solo": False,
            "autoBalanceApplied": False,
            "processingChainEnabled": True,
            "reverbSend": 35,
            "delaySend": 0,
            "presenceAmount": 0,
            "compressionAmount": 50,
        }
        project["mixSettings"]["stems"].append(setting)
    else:
        setting.setdefault("processingChainEnabled", True)
        setting.setdefault("reverbSend", 35)
        setting.setdefault("delaySend", 0)
        setting.setdefault("presenceAmount", 0)
        setting.setdefault("compressionAmount", 50)
    return setting


def _clear_rough_mix_reference(project: dict[str, Any]) -> None:
    mix_settings = project.setdefault("mixSettings", {})
    mix_settings["roughMixWavPath"] = None
    mix_settings["roughMixMp3Path"] = None
    mix_settings["roughMixWavUrl"] = None
    mix_settings["roughMixMp3Url"] = None


def _rough_mix_inputs(project: dict[str, Any]) -> list[dict[str, Any]]:
    settings = {item["stemId"]: item for item in project.get("mixSettings", {}).get("stems", [])}
    solo_active = any(item.get("solo") for item in settings.values())
    inputs = []

    for stem in project.get("stems", []):
        setting = settings.get(stem["id"]) or _ensure_mix_setting(project, stem["id"])
        if solo_active and not setting.get("solo"):
            continue
        if setting.get("mute"):
            continue
        file_path = _mix_source_path(stem)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Stored file not found for {stem['originalFilename']}.")
        inputs.append(
            {
                "path": file_path,
                "gainDb": float(setting.get("gainDb", 0)),
                "pan": float(setting.get("pan", 0)),
                "filename": stem["originalFilename"],
            }
        )

    return inputs


def _mix_source_path(stem: dict[str, Any]) -> Path:
    vocal_settings = stem.get("vocalEnhancementSettings") or {}
    vocal_result = stem.get("vocalEnhancementResult") or {}
    if (
        vocal_settings.get("enabled")
        and vocal_settings.get("useEnhancedInMix", True)
        and vocal_result.get("status") == "Completed"
        and vocal_result.get("enhancedFilePath")
    ):
        enhanced_path = resolve_stored_file_path(vocal_result["enhancedFilePath"])
        if enhanced_path.exists():
            return enhanced_path

    settings = stem.get("cleaningSettings") or {}
    result = stem.get("cleaningResult") or {}
    if (
        settings.get("enabled")
        and settings.get("useCleanedInMix", True)
        and result.get("status") == "Completed"
        and result.get("cleanedFilePath")
    ):
        cleaned_path = resolve_stored_file_path(result["cleanedFilePath"])
        if cleaned_path.exists():
            return cleaned_path
    return resolve_stored_file_path(stem["filePath"])


def _suggest_pan(stem_type: str, type_index: int) -> float:
    if stem_type in {"Lead Vocal", "Bass", "Kick", "Drums"}:
        return 0.0
    if stem_type == "Snare":
        return 5.0
    if stem_type == "Backing Vocal":
        return -35.0 if type_index % 2 else 35.0
    if stem_type == "Electric Guitar":
        return -45.0 if type_index % 2 else 45.0
    if stem_type == "Acoustic Guitar":
        return -25.0 if type_index % 2 else 25.0
    if stem_type == "Keys/Piano":
        return -30.0 if type_index % 2 else 30.0
    if stem_type == "Pads/Strings":
        return -55.0 if type_index % 2 else 55.0
    if stem_type == "FX/Ambience":
        return -60.0 if type_index % 2 else 60.0
    return 0.0


def _media_url(path_value: str | None) -> str | None:
    if path_value is None:
        return None
    normalized = path_value.replace("\\", "/")
    if normalized.startswith("storage/"):
        normalized = normalized[len("storage/") :]
    return f"/media/{normalized}"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
