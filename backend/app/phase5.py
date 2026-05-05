import json
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .audio_engine import ensure_audio_environment, generate_advanced_mix
from .logging_utils import append_project_log, utc_now_iso
from .models import MixVersion, ProcessingJob, Project, UpdateMixControlsRequest, UpdateMixVersionRequest
from .phase2 import _clear_rough_mix_reference, _ensure_mix_setting, _mix_source_path
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


MIX_PRESETS: dict[str, dict[str, Any]] = {
    "Balanced": {
        "description": "Neutral full-band balance with vocals slightly forward.",
        "targetLufsRecommendation": -16.0,
        "controls": {
            "preset": "Balanced",
            "vocalBoost": 2.0,
            "vocalBusLevel": 0.4,
            "vocalGlueAmount": 22,
            "vocalDelayAmount": 4,
            "backingVocalWidth": 55,
            "drumPunch": 50,
            "bassWeight": 50,
            "brightness": 0,
            "warmth": 0,
            "width": 55,
            "reverbAmount": 24,
            "vocalReverbAmount": 14,
            "roomSize": 38,
        },
        "roleGains": {
            "Lead Vocal": 0.8,
            "Backing Vocal": -1.4,
            "Electric Guitar": -0.4,
            "Acoustic Guitar": -0.3,
            "Keys/Piano": -0.5,
            "Pads/Strings": -1.5,
            "FX/Ambience": -2.0,
        },
    },
    "Vocal Forward": {
        "description": "Keeps the lead vocal clearly in front with support instruments tucked under it.",
        "targetLufsRecommendation": -15.5,
        "controls": {
            "preset": "Vocal Forward",
            "vocalBoost": 3.0,
            "vocalBusLevel": 0.8,
            "vocalGlueAmount": 44,
            "vocalDelayAmount": 12,
            "backingVocalWidth": 62,
            "drumPunch": 45,
            "bassWeight": 45,
            "brightness": 8,
            "warmth": 0,
            "width": 52,
            "reverbAmount": 28,
            "vocalReverbAmount": 22,
            "roomSize": 42,
        },
        "roleGains": {
            "Lead Vocal": 1.4,
            "Backing Vocal": -1.8,
            "Electric Guitar": -1.2,
            "Acoustic Guitar": -0.8,
            "Keys/Piano": -1.1,
            "Pads/Strings": -1.8,
            "FX/Ambience": -2.2,
        },
    },
    "Rock Band": {
        "description": "Punchier drums, solid bass, wider guitars, and controlled ambience.",
        "targetLufsRecommendation": -14.5,
        "controls": {
            "preset": "Rock Band",
            "vocalBoost": 1.2,
            "vocalBusLevel": 0,
            "vocalGlueAmount": 52,
            "vocalDelayAmount": 18,
            "backingVocalWidth": 54,
            "drumPunch": 72,
            "bassWeight": 62,
            "brightness": 7,
            "warmth": 8,
            "width": 62,
            "reverbAmount": 24,
            "vocalReverbAmount": 26,
            "roomSize": 34,
        },
        "roleGains": {"Drums": 0.8, "Kick": 0.5, "Snare": 0.4, "Bass": 0.5, "Electric Guitar": 0.7, "Pads/Strings": -2.4, "FX/Ambience": -2.5},
    },
    "Worship Band": {
        "description": "Open vocal-led mix with wider pads, keys, and spacious reverbs.",
        "targetLufsRecommendation": -15.0,
        "controls": {
            "preset": "Worship Band",
            "vocalBoost": 1.9,
            "vocalBusLevel": 0.3,
            "vocalGlueAmount": 48,
            "vocalDelayAmount": 42,
            "backingVocalWidth": 74,
            "drumPunch": 50,
            "bassWeight": 52,
            "brightness": 4,
            "warmth": 6,
            "width": 70,
            "reverbAmount": 52,
            "vocalReverbAmount": 48,
            "roomSize": 66,
        },
        "roleGains": {"Lead Vocal": 0.7, "Backing Vocal": -0.8, "Keys/Piano": 0.3, "Pads/Strings": 0.4, "FX/Ambience": -0.6, "Electric Guitar": -0.5},
    },
    "Acoustic": {
        "description": "Natural, lighter processing for vocal and acoustic-driven arrangements.",
        "targetLufsRecommendation": -16.5,
        "controls": {
            "preset": "Acoustic",
            "vocalBoost": 2.0,
            "vocalBusLevel": 0.2,
            "vocalGlueAmount": 38,
            "vocalDelayAmount": 18,
            "backingVocalWidth": 48,
            "drumPunch": 32,
            "bassWeight": 42,
            "brightness": 5,
            "warmth": 10,
            "width": 54,
            "reverbAmount": 38,
            "vocalReverbAmount": 36,
            "roomSize": 48,
        },
        "roleGains": {"Lead Vocal": 0.8, "Acoustic Guitar": 0.5, "Drums": -1.4, "Kick": -1.0, "Snare": -0.7, "Pads/Strings": -1.2},
    },
    "Pop": {
        "description": "Brighter vocal-forward balance with controlled low end and clean width.",
        "targetLufsRecommendation": -14.0,
        "controls": {
            "preset": "Pop",
            "vocalBoost": 2.2,
            "vocalBusLevel": 0.4,
            "vocalGlueAmount": 62,
            "vocalDelayAmount": 24,
            "backingVocalWidth": 68,
            "drumPunch": 62,
            "bassWeight": 64,
            "brightness": 12,
            "warmth": 2,
            "width": 64,
            "reverbAmount": 34,
            "vocalReverbAmount": 32,
            "roomSize": 40,
        },
        "roleGains": {"Lead Vocal": 0.9, "Kick": 0.4, "Bass": 0.5, "Backing Vocal": -1.0, "Pads/Strings": -0.8, "FX/Ambience": -1.2},
    },
    "Live Rehearsal": {
        "description": "Stable cleanup and balance while preserving a live-room feel.",
        "targetLufsRecommendation": -17.0,
        "controls": {
            "preset": "Live Rehearsal",
            "vocalBoost": 1.0,
            "vocalBusLevel": -0.2,
            "vocalGlueAmount": 34,
            "vocalDelayAmount": 12,
            "backingVocalWidth": 42,
            "drumPunch": 42,
            "bassWeight": 48,
            "brightness": -4,
            "warmth": 8,
            "width": 44,
            "reverbAmount": 18,
            "vocalReverbAmount": 20,
            "roomSize": 26,
        },
        "roleGains": {"Lead Vocal": 0.3, "Drums": -0.5, "Electric Guitar": -0.4, "FX/Ambience": -2.5, "Pads/Strings": -1.8},
    },
}

ACTIVE_JOB_STATUSES = {"Pending", "Processing", "Cancelling"}
RUNNING_MIX_JOB_IDS: set[str] = set()
RUNNING_MIX_JOB_LOCK = threading.Lock()
VOCAL_TYPES = {"Lead Vocal", "Backing Vocal"}


def get_mix_presets() -> dict[str, list[dict[str, Any]]]:
    return {
        "presets": [
            {
                "name": name,
                "description": preset["description"],
                "targetLufsRecommendation": preset["targetLufsRecommendation"],
                "controls": preset["controls"],
            }
            for name, preset in MIX_PRESETS.items()
        ]
    }


def create_advanced_mix_job(project_id: str, instrumental: bool = False) -> ProcessingJob:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    data = store.load()
    project = _find_project(data, project_id)
    if not project.get("stems"):
        raise HTTPException(status_code=400, detail="Upload stems before generating a mix.")
    job_type = "Instrumental Mix" if instrumental else "Advanced Mix"
    active_job = next(
        (job for job in reversed(project.get("processingJobs", [])) if job.get("type") == job_type and job.get("status") in ACTIVE_JOB_STATUSES),
        None,
    )
    if active_job:
        append_project_log(project_subdirs(project_id)["logs"], f"Reused active {job_type.lower()} job {active_job['id']}.")
        return ProcessingJob(**active_job)

    now = utc_now_iso()
    job = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "type": job_type,
        "status": "Pending",
        "progress": 0,
        "currentStemId": None,
        "message": f"{job_type} queued.",
        "errors": [],
        "createdAt": now,
        "updatedAt": now,
        "completedAt": None,
    }
    project.setdefault("processingJobs", []).append(job)
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"{job_type} job {job['id']} queued.")
    return ProcessingJob(**job)


def run_advanced_mix_job(project_id: str, job_id: str, instrumental: bool = False) -> None:
    with RUNNING_MIX_JOB_LOCK:
        if job_id in RUNNING_MIX_JOB_IDS:
            append_project_log(project_subdirs(project_id)["logs"], f"Ignored duplicate mix runner for job {job_id}.")
            return
        RUNNING_MIX_JOB_IDS.add(job_id)

    try:
        _run_advanced_mix_job(project_id, job_id, instrumental)
    except JobCancelled:
        mark_processing_job_cancelled(project_id, job_id)
    finally:
        with RUNNING_MIX_JOB_LOCK:
            RUNNING_MIX_JOB_IDS.discard(job_id)


def _run_advanced_mix_job(project_id: str, job_id: str, instrumental: bool) -> None:
    job_type = "Instrumental Mix" if instrumental else "Advanced Mix"
    try:
        _update_job(project_id, job_id, status="Processing", progress=4, message="Preparing source stems.")
        version = generate_advanced_mix_preview(
            project_id,
            instrumental=instrumental,
            progress_callback=lambda fraction, message: _update_job(
                project_id,
                job_id,
                progress=_scaled_progress(fraction, 6, 92),
                message=message,
            ),
        )
        raise_if_processing_job_cancelled(project_id, job_id)
        _update_job(project_id, job_id, progress=96, message=f"Saving {version.label}.")
        now = utc_now_iso()
        data = store.load()
        project = _find_project(data, project_id)
        job = _find_job(project, job_id)
        job["status"] = "Completed"
        job["progress"] = 100
        job["currentStemId"] = None
        job["message"] = f"{job_type} completed: {version.label}."
        job["updatedAt"] = now
        job["completedAt"] = now
        store.save(data)
        append_project_log(project_subdirs(project_id)["logs"], f"{job_type} job {job_id} completed.")
    except JobCancelled:
        raise
    except Exception as exc:
        error_message = str(exc) or f"{job_type} failed."
        now = utc_now_iso()
        data = store.load()
        project = _find_project(data, project_id)
        job = _find_job(project, job_id)
        job["status"] = "Failed"
        job["progress"] = 100
        job["message"] = error_message
        job["errors"] = [{"stemId": None, "filename": None, "error": error_message}]
        job["updatedAt"] = now
        job["completedAt"] = now
        store.save(data)
        append_project_log(project_subdirs(project_id)["logs"], f"{job_type} job {job_id} failed: {error_message}")


def update_mix_controls(project_id: str, payload: UpdateMixControlsRequest) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    controls = _ensure_mix_controls(project)
    fields = payload.model_fields_set

    if "preset" in fields:
        preset_name = payload.preset or "Balanced"
        if preset_name not in MIX_PRESETS:
            raise HTTPException(status_code=400, detail="Invalid mix preset.")
        controls.update(deepcopy(MIX_PRESETS[preset_name]["controls"]))

    for field in fields:
        if field == "preset":
            continue
        value = getattr(payload, field)
        if value is not None:
            controls[field] = round(float(value), 2)

    now = utc_now_iso()
    project["mixSettings"]["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Updated advanced mix controls for {controls.get('preset', 'Balanced')} preset.")
    return Project(**project)


def reset_advanced_mix(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    controls = _ensure_mix_controls(project)
    preset_name = controls.get("preset", "Balanced")
    if preset_name not in MIX_PRESETS:
        preset_name = "Balanced"
    controls.update(deepcopy(MIX_PRESETS[preset_name]["controls"]))
    _reset_stem_processing_settings(project)
    _clear_rough_mix_reference(project)

    now = utc_now_iso()
    project["mixSettings"]["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], "Reset advanced mixer settings to the current auto mix preset.")
    return Project(**project)


def reset_stem_processing(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _reset_stem_processing_settings(project)
    _clear_rough_mix_reference(project)

    now = utc_now_iso()
    project["mixSettings"]["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], "Reset stem processing settings to the current auto mix defaults.")
    return Project(**project)


def generate_advanced_mix_preview(project_id: str, instrumental: bool = False, progress_callback=None) -> MixVersion:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    data = store.load()
    project = _find_project(data, project_id)
    ensure_project_dirs(project_id)
    controls = _ensure_mix_controls(project)
    preset_name = controls.get("preset", "Balanced")
    if preset_name not in MIX_PRESETS:
        raise HTTPException(status_code=400, detail="Invalid mix preset.")

    output_dir = project_subdirs(project_id)["processed"] / "mixes"
    version_number = _next_mix_version(project, output_dir)
    stem_inputs = _advanced_mix_inputs(project, MIX_PRESETS[preset_name], instrumental=instrumental)
    if not stem_inputs:
        detail = "No audible instrumental stems are available." if instrumental else "No audible stems are available. Check mute and solo settings."
        raise HTTPException(status_code=400, detail=detail)

    render_label = "instrumental mix" if instrumental else "advanced mix"
    append_project_log(project_subdirs(project_id)["logs"], f"Generating {render_label} v{version_number:03d} with {preset_name} preset.")
    result = generate_advanced_mix(stem_inputs, output_dir, version_number, controls, progress_callback=progress_callback)
    if result.mp3_error:
        result.warnings.append(f"MP3 encode failed; WAV mix is available. {result.mp3_error}")
    for warning in result.warnings:
        append_project_log(project_subdirs(project_id)["logs"], f"Advanced mix warning: {warning}")
    for error in result.errors:
        append_project_log(project_subdirs(project_id)["logs"], f"Advanced mix stem error: {error}")

    now = utc_now_iso()
    wav_path = display_path(result.wav_path)
    mp3_path = display_path(result.mp3_path) if result.mp3_path else None
    metadata_path = display_path(result.metadata_path) if result.metadata_path else None
    version = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "versionNumber": version_number,
        "label": f"Instrumental v{version_number:03d}" if instrumental else f"Mix v{version_number:03d}",
        "preset": preset_name,
        "createdAt": now,
        "wavPath": wav_path,
        "mp3Path": mp3_path,
        "wavUrl": _media_url(wav_path),
        "mp3Url": _media_url(mp3_path) if mp3_path else None,
        "metadataPath": metadata_path,
        "integratedLufs": result.integrated_lufs,
        "peakDbfs": result.peak_dbfs,
        "truePeakDbfs": result.true_peak_dbfs,
        "limiterGainDb": result.limiter_gain_db,
        "targetLufsRecommendation": MIX_PRESETS[preset_name]["targetLufsRecommendation"],
        "settings": {
            "controls": deepcopy(controls),
            "stems": deepcopy(project.get("mixSettings", {}).get("stems", [])),
            "instrumental": instrumental,
        },
        "sourceFiles": result.source_files,
        "warnings": result.warnings,
        "errors": result.errors,
    }

    _write_mix_metadata(result.metadata_path, version)

    data = store.load()
    project = _find_project(data, project_id)
    project["mixSettings"].setdefault("mixVersions", []).append(version)
    project["mixSettings"]["latestMixVersionId"] = version["id"]
    project["mixSettings"]["updatedAt"] = now
    project["status"] = "Advanced Mix Ready"
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"{render_label.title()} v{version_number:03d} saved to {wav_path}.")
    return MixVersion(**version)


def update_mix_version(project_id: str, version_id: str, payload: UpdateMixVersionRequest) -> MixVersion:
    data = store.load()
    project = _find_project(data, project_id)
    version = _find_mix_version(project, version_id)
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Mix version label cannot be empty.")
    previous_label = version.get("label", "Mix")
    version["label"] = label
    project["mixSettings"]["updatedAt"] = utc_now_iso()
    project["updatedAt"] = project["mixSettings"]["updatedAt"]
    _write_mix_metadata_for_version(version)
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Renamed mix version {previous_label} to {label}.")
    return MixVersion(**version)


def delete_mix_version(project_id: str, version_id: str) -> dict[str, str]:
    data = store.load()
    project = _find_project(data, project_id)
    mix_settings = project.get("mixSettings", {})
    versions = mix_settings.get("mixVersions", [])
    index = next((idx for idx, item in enumerate(versions) if item.get("id") == version_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Mix version not found.")

    if any(master.get("sourceMixVersionId") == version_id for master in project.get("masteringSettings", {}).get("masterVersions", [])):
        raise HTTPException(status_code=400, detail="This mix version is used by a saved master. Keep it for traceability.")

    version = versions.pop(index)
    for key in ["wavPath", "mp3Path", "metadataPath"]:
        path_value = version.get(key)
        if not path_value:
            continue
        path = resolve_stored_file_path(path_value)
        if path.exists() and _is_generated_mix_path(project_id, path):
            path.unlink()

    if mix_settings.get("latestMixVersionId") == version_id:
        mix_settings["latestMixVersionId"] = versions[-1]["id"] if versions else None
    mastering_controls = project.get("masteringSettings", {}).get("controls", {})
    if mastering_controls.get("selectedMixVersionId") == version_id:
        mastering_controls["selectedMixVersionId"] = mix_settings.get("latestMixVersionId")

    now = utc_now_iso()
    mix_settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Deleted mix version {version.get('label', version_id)}.")
    return {"message": "Mix version deleted."}


def _advanced_mix_inputs(project: dict[str, Any], preset: dict[str, Any], instrumental: bool = False) -> list[dict[str, Any]]:
    settings = {item["stemId"]: item for item in project.get("mixSettings", {}).get("stems", [])}
    controls = project.get("mixSettings", {}).get("controls", {})
    stems = project.get("stems", [])
    candidate_stems = [stem for stem in stems if not (instrumental and effective_stem_type(stem) in VOCAL_TYPES)]
    solo_active = any(settings.get(stem["id"], {}).get("solo") for stem in candidate_stems)
    active_stems = [stem for stem in candidate_stems if _is_audible(stem, settings.get(stem["id"]), solo_active)]
    lead_vocal_active = any(effective_stem_type(stem) == "Lead Vocal" for stem in active_stems)
    backing_vocals = [stem for stem in active_stems if effective_stem_type(stem) == "Backing Vocal"]
    backing_vocal_index = 0
    low_end_adjustments = _low_end_adjustments(active_stems)
    inputs = []

    for stem in candidate_stems:
        setting = settings.get(stem["id"]) or _ensure_mix_setting(project, stem["id"])
        if not _is_audible(stem, setting, solo_active):
            continue

        file_path = _mix_source_path(stem)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Stored file not found for {stem['originalFilename']}.")

        stem_type = effective_stem_type(stem)
        source_kind, source_display_path = _source_kind_and_path(stem, file_path)
        role_gain = float(preset.get("roleGains", {}).get(stem_type, 0))
        role_gain += _vocal_priority_adjustment(stem_type, lead_vocal_active)
        role_gain += low_end_adjustments.get(stem["id"], 0)
        if stem_type == "Backing Vocal":
            backing_vocal_index += 1
            if len(backing_vocals) > 1:
                role_gain -= min(1.8, 0.32 * (len(backing_vocals) - 1))

        defaults = _default_stem_processing(stem_type)
        setting.setdefault("processingChainEnabled", True)
        setting.setdefault("reverbSend", defaults["reverbSend"])
        setting.setdefault("delaySend", defaults["delaySend"])
        setting.setdefault("presenceAmount", defaults["presenceAmount"])
        setting.setdefault("compressionAmount", defaults["compressionAmount"])
        pan = float(setting.get("pan", 0))
        if stem_type == "Backing Vocal" and len(backing_vocals) > 1 and abs(pan) < 1:
            pan = _backing_stack_pan(backing_vocal_index, len(backing_vocals), controls)

        inputs.append(
            {
                "stemId": stem["id"],
                "path": file_path,
                "sourceFilePath": source_display_path,
                "sourceKind": source_kind,
                "filename": stem["originalFilename"],
                "stemType": stem_type,
                "gainDb": float(setting.get("gainDb", 0)),
                "presetGainDb": role_gain,
                "pan": pan,
                "processingChainEnabled": bool(setting.get("processingChainEnabled", True)),
                "reverbSend": float(setting.get("reverbSend", defaults["reverbSend"])),
                "delaySend": float(setting.get("delaySend", defaults["delaySend"])),
                "presenceAmount": float(setting.get("presenceAmount", defaults["presenceAmount"])),
                "compressionAmount": float(setting.get("compressionAmount", defaults["compressionAmount"])),
            }
        )

    return inputs


def _ensure_mix_controls(project: dict[str, Any]) -> dict[str, Any]:
    project.setdefault("mixSettings", {}).setdefault("controls", deepcopy(MIX_PRESETS["Balanced"]["controls"]))
    controls = project["mixSettings"]["controls"]
    for key, value in MIX_PRESETS["Balanced"]["controls"].items():
        controls.setdefault(key, value)
    if controls.get("preset") not in MIX_PRESETS:
        controls.update(deepcopy(MIX_PRESETS["Balanced"]["controls"]))
    return controls


def _find_job(project: dict[str, Any], job_id: str) -> dict[str, Any]:
    job = next((item for item in project.get("processingJobs", []) if item.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    return job


def _update_job(project_id: str, job_id: str, **updates: Any) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    if job.get("status") in {"Cancelling", "Cancelled"}:
        raise JobCancelled(job.get("message") or "Job was stopped by the user.")
    job.update(updates)
    job["updatedAt"] = utc_now_iso()
    store.save(data)


def _scaled_progress(fraction: float, start: int, end: int) -> int:
    safe_fraction = max(0.0, min(1.0, float(fraction)))
    return max(start, min(end, int(round(start + safe_fraction * (end - start)))))


def _find_mix_version(project: dict[str, Any], version_id: str) -> dict[str, Any]:
    version = next((item for item in project.get("mixSettings", {}).get("mixVersions", []) if item.get("id") == version_id), None)
    if version is None:
        raise HTTPException(status_code=404, detail="Mix version not found.")
    return version


def _write_mix_metadata_for_version(version: dict[str, Any]) -> None:
    metadata_path = version.get("metadataPath")
    if not metadata_path:
        return
    path = resolve_stored_file_path(metadata_path)
    if not path.exists():
        return
    _write_mix_metadata(path, version)


def _is_generated_mix_path(project_id: str, path: Path) -> bool:
    try:
        resolved = path.resolve()
        mixes_dir = (project_subdirs(project_id)["processed"] / "mixes").resolve()
        return resolved == mixes_dir or resolved.is_relative_to(mixes_dir)
    except OSError:
        return False


def _is_audible(stem: dict[str, Any], setting: dict[str, Any] | None, solo_active: bool) -> bool:
    if setting is None:
        return not solo_active
    if solo_active and not setting.get("solo"):
        return False
    return not setting.get("mute")


def _next_mix_version(project: dict[str, Any], output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_numbers = [int(version.get("versionNumber", 0)) for version in project.get("mixSettings", {}).get("mixVersions", [])]
    version_number = max(existing_numbers, default=0) + 1
    while (output_dir / f"mix_v{version_number:03d}.wav").exists() or (output_dir / f"mix_v{version_number:03d}.mp3").exists():
        version_number += 1
    return version_number


def _source_kind_and_path(stem: dict[str, Any], selected_path: Path) -> tuple[str, str]:
    vocal_result = stem.get("vocalEnhancementResult") or {}
    enhanced_path_value = vocal_result.get("enhancedFilePath")
    if enhanced_path_value:
        try:
            enhanced_path = resolve_stored_file_path(enhanced_path_value)
            if enhanced_path.resolve() == selected_path.resolve():
                return "Enhanced Vocal", enhanced_path_value
        except OSError:
            pass

    result = stem.get("cleaningResult") or {}
    cleaned_path_value = result.get("cleanedFilePath")
    if cleaned_path_value:
        try:
            cleaned_path = resolve_stored_file_path(cleaned_path_value)
            if cleaned_path.resolve() == selected_path.resolve():
                return "Cleaned", cleaned_path_value
        except OSError:
            pass
    return "Original", stem.get("filePath", display_path(selected_path))


def _default_stem_processing(stem_type: str) -> dict[str, float]:
    return {
        "Lead Vocal": {"reverbSend": 18, "delaySend": 4, "presenceAmount": 12, "compressionAmount": 52},
        "Backing Vocal": {"reverbSend": 34, "delaySend": 4, "presenceAmount": 0, "compressionAmount": 48},
        "Drums": {"reverbSend": 18, "delaySend": 0, "presenceAmount": 4, "compressionAmount": 46},
        "Kick": {"reverbSend": 4, "delaySend": 0, "presenceAmount": 0, "compressionAmount": 58},
        "Snare": {"reverbSend": 26, "delaySend": 0, "presenceAmount": 8, "compressionAmount": 50},
        "Bass": {"reverbSend": 2, "delaySend": 0, "presenceAmount": -4, "compressionAmount": 72},
        "Electric Guitar": {"reverbSend": 28, "delaySend": 8, "presenceAmount": 6, "compressionAmount": 38},
        "Acoustic Guitar": {"reverbSend": 34, "delaySend": 6, "presenceAmount": 8, "compressionAmount": 36},
        "Keys/Piano": {"reverbSend": 36, "delaySend": 6, "presenceAmount": 0, "compressionAmount": 28},
        "Pads/Strings": {"reverbSend": 62, "delaySend": 4, "presenceAmount": -6, "compressionAmount": 12},
        "FX/Ambience": {"reverbSend": 70, "delaySend": 10, "presenceAmount": -4, "compressionAmount": 6},
    }.get(stem_type, {"reverbSend": 30, "delaySend": 0, "presenceAmount": 0, "compressionAmount": 32})


def _reset_stem_processing_settings(project: dict[str, Any]) -> None:
    type_counters: dict[str, int] = {}
    for stem in project.get("stems", []):
        stem_type = effective_stem_type(stem)
        type_counters[stem_type] = type_counters.get(stem_type, 0) + 1
        setting = _ensure_mix_setting(project, stem["id"])
        suggestion = stem.get("autoBalanceSuggestion")
        if suggestion:
            setting["gainDb"] = suggestion.get("suggestedGainDb", 0)
            setting["pan"] = suggestion.get("suggestedPan", 0)
            setting["autoBalanceApplied"] = True
        else:
            setting["gainDb"] = 0
            setting["pan"] = _phase5_default_pan(stem_type, type_counters[stem_type])
            setting["autoBalanceApplied"] = False
        stem_defaults = _default_stem_processing(stem_type)
        setting["mute"] = False
        setting["solo"] = False
        setting["processingChainEnabled"] = True
        setting["reverbSend"] = stem_defaults["reverbSend"]
        setting["delaySend"] = stem_defaults["delaySend"]
        setting["presenceAmount"] = stem_defaults["presenceAmount"]
        setting["compressionAmount"] = stem_defaults["compressionAmount"]


def _phase5_default_pan(stem_type: str, type_index: int) -> float:
    if stem_type in {"Lead Vocal", "Bass", "Kick", "Drums"}:
        return 0.0
    if stem_type == "Snare":
        return 5.0
    if stem_type in {"Backing Vocal", "Electric Guitar", "Pads/Strings", "FX/Ambience"}:
        amount = {"Backing Vocal": 38, "Electric Guitar": 48, "Pads/Strings": 58, "FX/Ambience": 62}[stem_type]
        return -amount if type_index % 2 else amount
    if stem_type in {"Acoustic Guitar", "Keys/Piano"}:
        amount = {"Acoustic Guitar": 26, "Keys/Piano": 32}[stem_type]
        return -amount if type_index % 2 else amount
    return 0.0


def _backing_stack_pan(index: int, total: int, controls: dict[str, Any]) -> float:
    if total <= 1:
        return 0.0
    spread = max(18.0, min(72.0, float(controls.get("backingVocalWidth", 60)) * 0.72))
    if total == 2:
        return -spread if index == 1 else spread
    center = (total + 1) / 2.0
    offset = (index - center) / max(1.0, center - 1.0)
    return round(offset * spread, 2)


def _vocal_priority_adjustment(stem_type: str, lead_vocal_active: bool) -> float:
    if not lead_vocal_active:
        return 0.0
    return {
        "Electric Guitar": -0.8,
        "Acoustic Guitar": -0.5,
        "Keys/Piano": -0.7,
        "Pads/Strings": -1.0,
        "FX/Ambience": -1.2,
        "Backing Vocal": -0.5,
    }.get(stem_type, 0.0)


def _low_end_adjustments(stems: list[dict[str, Any]]) -> dict[str, float]:
    kick = next((stem for stem in stems if effective_stem_type(stem) == "Kick"), None)
    bass = next((stem for stem in stems if effective_stem_type(stem) == "Bass"), None)
    if not kick or not bass:
        return {}

    kick_lufs = (kick.get("analysisResult") or {}).get("integratedLufs")
    bass_lufs = (bass.get("analysisResult") or {}).get("integratedLufs")
    if not isinstance(kick_lufs, (int, float)) or not isinstance(bass_lufs, (int, float)):
        return {}
    if kick_lufs > bass_lufs + 2.0:
        return {bass["id"]: -0.7}
    if bass_lufs > kick_lufs + 2.0:
        return {kick["id"]: -0.6}
    return {}


def _write_mix_metadata(path: Path | None, version: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as metadata_file:
        json.dump(version, metadata_file, indent=2)


def _media_url(path_value: str | None) -> str | None:
    if path_value is None:
        return None
    normalized = path_value.replace("\\", "/")
    if normalized.startswith("storage/"):
        normalized = normalized[len("storage/") :]
    return f"/media/{normalized}"
