import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .audio_engine import analyze_vocal_file, enhance_vocal_file, ensure_audio_environment
from .logging_utils import append_project_log, utc_now_iso
from .models import (
    CreateVocalPresetRequest,
    ProcessingJob,
    Project,
    Stem,
    UpdateVocalEnhancementSettingsRequest,
    VOCAL_ENHANCER_PRESETS,
    validate_music_key,
    validate_music_scale,
    validate_pitch_correction_mode,
    validate_vocal_fx_style,
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
VOCAL_CONTROL_DEFAULTS = {
    "bodyAmount": 0,
    "presenceAmount": 0,
    "airAmount": 0,
    "deEssAmount": 50,
    "compressionAmount": 45,
    "riderAmount": 45,
    "saturationAmount": 50,
    "doublerAmount": 50,
    "breathReductionAmount": 35,
    "mouthClickReductionAmount": 30,
    "pitchStrength": 50,
    "pitchHumanize": 60,
}
VOCAL_CONTROL_FIELDS = tuple(VOCAL_CONTROL_DEFAULTS.keys())
VOCAL_SETTING_PATCH_FIELDS = (
    "enabled",
    "preset",
    "pitchCorrection",
    "key",
    "scale",
    "fxStyle",
    "fxAmount",
    "bodyAmount",
    "presenceAmount",
    "airAmount",
    "deEssAmount",
    "compressionAmount",
    "riderAmount",
    "saturationAmount",
    "doublerAmount",
    "breathReductionAmount",
    "mouthClickReductionAmount",
    "pitchStrength",
    "pitchHumanize",
    "useEnhancedInMix",
)
MIX_CONTROL_PATCH_FIELDS = (
    "preset",
    "vocalBoost",
    "vocalBusLevel",
    "vocalGlueAmount",
    "vocalDelayAmount",
    "vocalReverbAmount",
    "reverbAmount",
)


def get_vocal_enhancer_presets() -> dict[str, list[str]]:
    return {
        "presets": VOCAL_ENHANCER_PRESETS,
        "pitchCorrectionModes": ["Off", "Natural", "Medium", "Strong"],
        "fxStyles": ["Dry", "Natural Plate", "Small Hall", "Slap Delay", "Quarter Delay", "Worship Wide"],
        "keys": ["Auto", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"],
        "scales": ["Major", "Minor", "Chromatic"],
    }


def list_custom_vocal_presets() -> dict[str, list[dict[str, Any]]]:
    data = store.load()
    presets = data.setdefault("vocalPresetLibrary", {}).setdefault("presets", [])
    return {"presets": sorted(presets, key=lambda preset: preset.get("updatedAt", preset.get("createdAt", "")), reverse=True)}


def create_custom_vocal_preset(payload: CreateVocalPresetRequest) -> dict[str, Any]:
    data = store.load()
    library = data.setdefault("vocalPresetLibrary", {}).setdefault("presets", [])
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Preset name cannot be empty.")
    if any(item.get("name", "").lower() == name.lower() for item in library):
        raise HTTPException(status_code=400, detail="A vocal preset with this name already exists.")

    settings = _sanitize_custom_preset_settings(payload.settings)
    now = utc_now_iso()
    preset = {
        "id": uuid.uuid4().hex,
        "name": name,
        "settings": settings,
        "createdAt": now,
        "updatedAt": now,
    }
    library.append(preset)
    store.save(data)
    return preset


def delete_custom_vocal_preset(preset_id: str) -> dict[str, str]:
    data = store.load()
    library = data.setdefault("vocalPresetLibrary", {}).setdefault("presets", [])
    index = next((idx for idx, preset in enumerate(library) if preset.get("id") == preset_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Custom vocal preset not found.")
    library.pop(index)
    store.save(data)
    return {"message": "Custom vocal preset deleted."}


def analyze_project_vocals(project_id: str) -> Project:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    data = store.load()
    project = _find_project(data, project_id)
    stems = _vocal_candidate_stems(project)
    if not stems:
        raise HTTPException(status_code=400, detail="Set at least one stem type to Lead Vocal or Backing Vocal before analyzing vocals.")

    successes = 0
    for stem in stems:
        try:
            source_path, source_kind, source_display_path = _vocal_source_path(stem)
            if not source_path.exists():
                raise FileNotFoundError(f"Stored file not found: {source_display_path}")
            profile = analyze_vocal_file(source_path)
            result = _build_vocal_recommendation(stem, profile, source_kind, source_display_path)
            stem["vocalAnalysisResult"] = result
            successes += 1
            append_project_log(
                project_subdirs(project_id)["logs"],
                f"Analyzed vocal {stem['originalFilename']} for recommendations: {result['summary']}",
            )
        except Exception as exc:
            error_message = str(exc) or "Vocal recommendation analysis failed."
            stem["vocalAnalysisResult"] = {
                "stemId": stem["id"],
                "status": "Failed",
                "analyzedAt": utc_now_iso(),
                "sourceFilePath": stem.get("filePath"),
                "sourceKind": "Original",
                "confidence": 0,
                "summary": "Could not create vocal recommendations.",
                "issues": [],
                "recommendedSettings": {},
                "features": {},
                "warnings": ["Use the manual vocal enhancer controls or try running stem analysis/cleaning first."],
                "error": error_message,
            }
            append_project_log(project_subdirs(project_id)["logs"], f"Vocal recommendation analysis failed for {stem['originalFilename']}: {error_message}")

    pitch_summary = _apply_vocal_pitch_consensus(stems)
    if pitch_summary:
        append_project_log(project_subdirs(project_id)["logs"], pitch_summary)

    now = utc_now_iso()
    project["status"] = "Vocal Recommendations Ready" if successes else project.get("status", "Stems Uploaded")
    project["updatedAt"] = now
    store.save(data)
    return Project(**project)


def apply_vocal_recommendation(project_id: str, stem_id: str) -> Stem:
    data = store.load()
    project = _find_project(data, project_id)
    stem = _find_stem(project, stem_id)
    _apply_recommended_settings_to_stem(project, stem)
    _clear_rough_mix_reference(project)
    project["updatedAt"] = utc_now_iso()
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Applied vocal recommendation to {stem['originalFilename']}.")
    return Stem(**stem)


def apply_all_vocal_recommendations(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    applied_count = 0
    for stem in _vocal_candidate_stems(project):
        result = stem.get("vocalAnalysisResult")
        if result and result.get("status") == "Completed" and result.get("recommendedSettings"):
            _apply_recommended_settings_to_stem(project, stem)
            applied_count += 1
    if applied_count == 0:
        raise HTTPException(status_code=400, detail="No completed vocal recommendations are available to apply.")

    _clear_rough_mix_reference(project)
    project["updatedAt"] = utc_now_iso()
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Applied {applied_count} vocal recommendations.")
    return Project(**project)


def run_vocal_quality_doctor(project_id: str) -> Project:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    data = store.load()
    project = _find_project(data, project_id)
    stems = _vocal_candidate_stems(project)
    if not stems:
        raise HTTPException(status_code=400, detail="Set at least one stem type to Lead Vocal or Backing Vocal before running Vocal Doctor.")

    successes = 0
    for stem in stems:
        try:
            source_path, source_kind, source_display_path = _vocal_source_path(stem)
            if not source_path.exists():
                raise FileNotFoundError(f"Stored file not found: {source_display_path}")
            profile = _profile_for_vocal_doctor(stem, source_path)
            result = _build_vocal_quality_doctor(stem, project, profile, source_kind, source_display_path)
            stem["vocalQualityDoctorResult"] = result
            successes += 1
            append_project_log(project_subdirs(project_id)["logs"], f"Vocal Doctor diagnosed {stem['originalFilename']}: {result['summary']}")
        except Exception as exc:
            error_message = str(exc) or "Vocal Doctor failed."
            stem["vocalQualityDoctorResult"] = {
                "stemId": stem["id"],
                "status": "Failed",
                "diagnosedAt": utc_now_iso(),
                "score": 0,
                "summary": "Vocal Doctor could not diagnose this stem.",
                "problems": [],
                "recommendedSettings": {},
                "mixControlSuggestions": {},
                "nextSteps": ["Run normal vocal analysis or check that the source file is still available."],
                "warnings": [],
                "error": error_message,
            }
            append_project_log(project_subdirs(project_id)["logs"], f"Vocal Doctor failed for {stem['originalFilename']}: {error_message}")

    project["status"] = "Vocal Doctor Ready" if successes else project.get("status", "Stems Uploaded")
    project["updatedAt"] = utc_now_iso()
    store.save(data)
    return Project(**project)


def apply_vocal_doctor_fix(project_id: str, stem_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    stem = _find_stem(project, stem_id)
    doctor = stem.get("vocalQualityDoctorResult") or {}
    if doctor.get("status") != "Completed":
        raise HTTPException(status_code=400, detail="Run Vocal Doctor for this stem before applying a fix.")

    settings_patch = doctor.get("recommendedSettings") or {}
    mix_patch = doctor.get("mixControlSuggestions") or {}
    if not settings_patch and not mix_patch:
        raise HTTPException(status_code=400, detail="Vocal Doctor did not find settings to apply.")

    settings = _ensure_vocal_settings(stem)
    for key in VOCAL_SETTING_PATCH_FIELDS:
        if key in settings_patch:
            settings[key] = settings_patch[key]

    controls = project.setdefault("mixSettings", {}).setdefault("controls", {})
    for key in MIX_CONTROL_PATCH_FIELDS:
        if key in mix_patch:
            controls[key] = mix_patch[key]

    if not settings.get("enabled"):
        stem["vocalEnhancementStatus"] = "Disabled"
    elif _enhancement_result_matches(stem, settings):
        stem["vocalEnhancementStatus"] = "Completed"
    else:
        stem["vocalEnhancementStatus"] = "Pending"

    _clear_rough_mix_reference(project)
    project["updatedAt"] = utc_now_iso()
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Applied Vocal Doctor fix to {stem['originalFilename']}.")
    return Project(**project)


def _apply_recommended_settings_to_stem(project: dict[str, Any], stem: dict[str, Any]) -> None:
    result = stem.get("vocalAnalysisResult")
    if not result or result.get("status") != "Completed":
        raise HTTPException(status_code=400, detail="Analyze this vocal before applying recommended settings.")
    recommended_settings = result.get("recommendedSettings") or {}
    if not recommended_settings:
        raise HTTPException(status_code=400, detail="No recommended vocal settings are available to apply.")

    settings = _ensure_vocal_settings(stem)
    for key in VOCAL_SETTING_PATCH_FIELDS:
        if key in recommended_settings:
            settings[key] = recommended_settings[key]
    settings["enabled"] = True
    settings.setdefault("useEnhancedInMix", True)

    stem["vocalEnhancementStatus"] = "Completed" if _enhancement_result_matches(stem, settings) else "Pending"


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
    if payload.fxStyle is not None:
        if not validate_vocal_fx_style(payload.fxStyle):
            raise HTTPException(status_code=400, detail="Invalid vocal FX style.")
        settings["fxStyle"] = payload.fxStyle
    if payload.fxAmount is not None:
        settings["fxAmount"] = round(float(payload.fxAmount), 2)
    for field in VOCAL_CONTROL_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            settings[field] = round(float(value), 2)
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

    _update_job(project_id, job_id, status="Processing", progress=2, message="Preparing vocal enhancement job.")
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
            progress=_item_progress(index, total, 0.0),
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
                fx_style=settings["fxStyle"],
                fx_amount=float(settings["fxAmount"]),
                body_amount=float(settings["bodyAmount"]),
                presence_amount=float(settings["presenceAmount"]),
                air_amount=float(settings["airAmount"]),
                de_ess_amount=float(settings["deEssAmount"]),
                compression_amount=float(settings["compressionAmount"]),
                rider_amount=float(settings["riderAmount"]),
                saturation_amount=float(settings["saturationAmount"]),
                doubler_amount=float(settings["doublerAmount"]),
                breath_reduction_amount=float(settings["breathReductionAmount"]),
                mouth_click_reduction_amount=float(settings["mouthClickReductionAmount"]),
                pitch_strength=float(settings["pitchStrength"]),
                pitch_humanize=float(settings["pitchHumanize"]),
                progress_callback=lambda fraction, message, stem=stem, index=index: _update_job(
                    project_id,
                    job_id,
                    currentStemId=stem["id"],
                    message=f"{message}: {stem['originalFilename']}.",
                    progress=_item_progress(index, total, fraction),
                ),
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
                "fxStyle": settings["fxStyle"],
                "fxAmount": float(settings["fxAmount"]),
                "bodyAmount": float(settings["bodyAmount"]),
                "presenceAmount": float(settings["presenceAmount"]),
                "airAmount": float(settings["airAmount"]),
                "deEssAmount": float(settings["deEssAmount"]),
                "compressionAmount": float(settings["compressionAmount"]),
                "riderAmount": float(settings["riderAmount"]),
                "saturationAmount": float(settings["saturationAmount"]),
                "doublerAmount": float(settings["doublerAmount"]),
                "breathReductionAmount": float(settings["breathReductionAmount"]),
                "mouthClickReductionAmount": float(settings["mouthClickReductionAmount"]),
                "pitchStrength": float(settings["pitchStrength"]),
                "pitchHumanize": float(settings["pitchHumanize"]),
                "peakDbfs": result.peak_dbfs,
                "rmsDbfs": result.rms_dbfs,
                "integratedLufs": result.integrated_lufs,
                "originalMetrics": result.original_metrics,
                "enhancedMetrics": result.enhanced_metrics,
                "metricDeltas": result.metric_deltas,
                "operations": result.operations,
                "warnings": result.warnings,
                "report": _build_enhancement_report(stem, settings, result.original_metrics, result.enhanced_metrics, result.metric_deltas, result.operations, result.warnings),
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
                "fxStyle": settings.get("fxStyle", "Dry"),
                "fxAmount": float(settings.get("fxAmount", 0)),
                "bodyAmount": float(settings.get("bodyAmount", 0)),
                "presenceAmount": float(settings.get("presenceAmount", 0)),
                "airAmount": float(settings.get("airAmount", 0)),
                "deEssAmount": float(settings.get("deEssAmount", 50)),
                "compressionAmount": float(settings.get("compressionAmount", 45)),
                "riderAmount": float(settings.get("riderAmount", 45)),
                "saturationAmount": float(settings.get("saturationAmount", 50)),
                "doublerAmount": float(settings.get("doublerAmount", 50)),
                "breathReductionAmount": float(settings.get("breathReductionAmount", 35)),
                "mouthClickReductionAmount": float(settings.get("mouthClickReductionAmount", 30)),
                "pitchStrength": float(settings.get("pitchStrength", 50)),
                "pitchHumanize": float(settings.get("pitchHumanize", 60)),
                "peakDbfs": None,
                "rmsDbfs": None,
                "integratedLufs": None,
                "originalMetrics": None,
                "enhancedMetrics": None,
                "metricDeltas": {},
                "operations": [],
                "warnings": ["Vocal enhancement failed; the mixer can continue using cleaned/original stem."],
                "report": {},
                "error": error_message,
            }
            _update_stem_vocal(project_id, stem["id"], status="Failed", result=enhancement_result)
            _append_job_error(project_id, job_id, stem["id"], stem["originalFilename"], error_message)
            append_project_log(project_subdirs(project_id)["logs"], f"Vocal enhancement failed for {stem['originalFilename']}: {error_message}")

        _update_job(project_id, job_id, progress=_item_progress(index, total, 1.0))

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


def _vocal_candidate_stems(project: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for stem in project.get("stems", []):
        detection = stem.get("detectionResult") or {}
        if stem.get("stemType") in VOCAL_TYPES or detection.get("suggestedStemType") in VOCAL_TYPES:
            candidates.append(stem)
    return candidates


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


def _build_vocal_recommendation(stem: dict[str, Any], profile: dict[str, Any], source_kind: str, source_display_path: str) -> dict[str, Any]:
    issues: list[dict[str, str]] = []

    def value(key: str, default: float = 0.0) -> float:
        raw = profile.get(key)
        return float(raw) if isinstance(raw, (int, float)) else default

    def add_issue(issue_type: str, severity: str, message: str) -> None:
        issues.append({"type": issue_type, "severity": severity, "message": message})

    lufs = profile.get("integratedLufs")
    peak = value("peakDbfs", -90)
    rms = value("rmsDbfs", -90)
    noise_floor = profile.get("noiseFloorDbfs")
    silence = value("silencePercentage", 0)
    mud = value("mudRatio")
    body = value("bodyRatio")
    presence = value("presenceRatio")
    harshness = value("harshnessRatio")
    sibilance = value("sibilanceRatio")
    air = value("airRatio")
    rumble = value("lowRumbleRatio")
    flatness = value("spectralFlatness")
    spread = value("levelSpreadDb")
    harmonic = value("harmonicRatio", 0.5)
    centroid = value("spectralCentroidHz")

    if profile.get("clippingDetected") or peak > -0.5:
        add_issue("Clipping", "High", "Peak level is close to clipping; the enhanced vocal should keep more headroom.")
    if isinstance(lufs, (int, float)) and lufs > -13:
        add_issue("Too Loud", "Medium", "Vocal loudness is already high; avoid pushing compression and saturation too hard.")
    if (isinstance(lufs, (int, float)) and lufs < -30) or rms < -35:
        add_issue("Too Quiet", "Medium", "Vocal level is low; use leveling and compression before mixing.")
    if isinstance(noise_floor, (int, float)) and noise_floor > -45:
        add_issue("Noise", "High", "Noise floor is elevated; use the cleaner or a repair-oriented vocal preset.")
    elif flatness > 0.08 and rms > -45:
        add_issue("Hiss", "Medium", "High spectral flatness suggests hiss or room noise.")
    if silence > 45:
        add_issue("Silence", "Medium", "The file has a lot of silence; preserve alignment but check unused sections.")
    if spread > 13:
        add_issue("Uneven Level", "Medium", "Vocal level varies a lot; vocal rider and compression should help.")
    if rumble > 0.08:
        add_issue("Low Rumble", "Medium", "Low-frequency rumble is present; keep the high-pass cleanup active.")
    if mud > 0.32 and presence < 0.15:
        add_issue("Muddy", "Medium", "Low-mid energy is strong compared with presence; reduce body and add clarity.")
    if body < 0.08 and centroid > 1800:
        add_issue("Thin", "Medium", "Body energy is light; add body and a little saturation.")
    if presence < 0.09 and air < 0.035:
        add_issue("Dull", "Medium", "Presence and air are low; add clarity before mixing.")
    if harshness > 0.28:
        add_issue("Harsh", "Medium", "Upper-mid energy is strong; reduce presence and de-ess carefully.")
    if sibilance > 0.13:
        add_issue("Sibilant", "High", "Sibilance band is prominent; increase de-essing and avoid too much air.")

    stem_type = stem.get("stemType") if stem.get("stemType") in VOCAL_TYPES else (stem.get("detectionResult") or {}).get("suggestedStemType", "Lead Vocal")
    is_backing = stem_type == "Backing Vocal"
    issue_types = {issue["type"] for issue in issues}

    estimated_key = str(profile.get("estimatedKey") or "Auto")
    estimated_scale = str(profile.get("estimatedScale") or "Major")
    key_confidence = int(profile.get("keyConfidence") or 0)

    recommended: dict[str, float | str | bool] = {
        "enabled": True,
        "preset": "Backing Vocal Wide" if is_backing else "Natural Clean",
        "pitchCorrection": "Off",
        "key": estimated_key if key_confidence >= 55 else "Auto",
        "scale": estimated_scale if key_confidence >= 55 else "Major",
        "fxStyle": "Dry",
        "fxAmount": 0,
        "bodyAmount": 0,
        "presenceAmount": 0,
        "airAmount": 0,
        "deEssAmount": 50,
        "compressionAmount": 50,
        "riderAmount": 48,
        "saturationAmount": 45,
        "doublerAmount": 68 if is_backing else 35,
        "breathReductionAmount": 44 if is_backing else 38,
        "mouthClickReductionAmount": 38,
        "pitchStrength": 42,
        "pitchHumanize": 76,
        "useEnhancedInMix": True,
    }

    if not is_backing and not issue_types:
        recommended["preset"] = "Pop Vocal"
    if {"Noise", "Hiss", "Low Rumble"} & issue_types:
        recommended["preset"] = "Live Vocal Fix"
        recommended["saturationAmount"] = 35
    elif {"Dull", "Thin"} & issue_types and not is_backing:
        recommended["preset"] = "Bright AI Polish"
    elif "Muddy" in issue_types and not is_backing:
        recommended["preset"] = "Pop Vocal"

    if "Muddy" in issue_types:
        recommended["bodyAmount"] = -22
        recommended["presenceAmount"] = 12
        recommended["airAmount"] = 10
    if "Thin" in issue_types:
        recommended["bodyAmount"] = max(float(recommended["bodyAmount"]), 18)
        recommended["saturationAmount"] = 62
    if "Dull" in issue_types:
        recommended["presenceAmount"] = max(float(recommended["presenceAmount"]), 18)
        recommended["airAmount"] = max(float(recommended["airAmount"]), 22)
    if "Harsh" in issue_types:
        recommended["presenceAmount"] = min(float(recommended["presenceAmount"]), -16)
        recommended["deEssAmount"] = 68
    if "Sibilant" in issue_types:
        recommended["deEssAmount"] = 78
        recommended["airAmount"] = min(float(recommended["airAmount"]), -8)
    if "Low Rumble" in issue_types and "Thin" not in issue_types:
        recommended["bodyAmount"] = min(float(recommended["bodyAmount"]), -10)
    if "Uneven Level" in issue_types:
        recommended["compressionAmount"] = 74
        recommended["riderAmount"] = 78
    if "Too Quiet" in issue_types:
        recommended["compressionAmount"] = max(float(recommended["compressionAmount"]), 68)
        recommended["riderAmount"] = max(float(recommended["riderAmount"]), 72)
    if "Too Loud" in issue_types or "Clipping" in issue_types:
        recommended["compressionAmount"] = min(float(recommended["compressionAmount"]), 58)
        recommended["saturationAmount"] = min(float(recommended["saturationAmount"]), 34)

    if harmonic > 0.56 and "Noise" not in issue_types and "Silence" not in issue_types:
        recommended["pitchCorrection"] = "Natural"
        recommended["pitchStrength"] = 35 if is_backing else 42
        recommended["pitchHumanize"] = 82 if is_backing else 76
    if "Hiss" in issue_types or "Noise" in issue_types:
        recommended["breathReductionAmount"] = 55
        recommended["mouthClickReductionAmount"] = 45
    if "Sibilant" in issue_types:
        recommended["breathReductionAmount"] = max(float(recommended["breathReductionAmount"]), 48)

    confidence = 84
    if "Noise" in issue_types or "Silence" in issue_types:
        confidence -= 10
    if "Clipping" in issue_types:
        confidence -= 8
    if harmonic < 0.42:
        confidence -= 8
    if profile.get("durationSeconds") and float(profile["durationSeconds"]) < 2:
        confidence -= 18
    confidence = max(40, min(95, confidence))

    if issues:
        top_issues = ", ".join(issue["type"].lower() for issue in issues[:3])
        summary = f"Recommended {recommended['preset']} settings for {top_issues}."
    else:
        summary = f"Recommended {recommended['preset']} settings for a balanced vocal polish."

    warnings = []
    if confidence < 65:
        warnings.append("Recommendation confidence is modest; compare A/B before using it in the final mix.")
    if "Sibilant" in issue_types and recommended["airAmount"] > 0:
        warnings.append("Sibilant vocals can get sharper with air boosts; keep A/B preview honest.")

    feature_payload = {
        key: item
        for key, item in profile.items()
        if (isinstance(item, (int, float, str)) and not isinstance(item, bool)) or item is None
    }
    return {
        "stemId": stem["id"],
        "status": "Completed",
        "analyzedAt": utc_now_iso(),
        "sourceFilePath": source_display_path,
        "sourceKind": source_kind,
        "confidence": confidence,
        "summary": summary,
        "issues": issues,
        "recommendedSettings": recommended,
        "features": feature_payload,
        "warnings": warnings,
        "error": None,
    }


def _profile_for_vocal_doctor(stem: dict[str, Any], source_path: Path) -> dict[str, Any]:
    result = stem.get("vocalAnalysisResult") or {}
    features = result.get("features") or {}
    if result.get("status") == "Completed" and features:
        return dict(features)
    return analyze_vocal_file(source_path)


def _build_vocal_quality_doctor(stem: dict[str, Any], project: dict[str, Any], profile: dict[str, Any], source_kind: str, source_display_path: str) -> dict[str, Any]:
    settings = _ensure_vocal_settings(stem)
    enhancement = stem.get("vocalEnhancementResult") or {}
    cleaning = stem.get("cleaningSettings") or {}
    analysis = stem.get("vocalAnalysisResult") or {}
    controls = (project.get("mixSettings") or {}).get("controls") or {}
    stem_type = stem.get("stemType") if stem.get("stemType") in VOCAL_TYPES else (stem.get("detectionResult") or {}).get("suggestedStemType", "Lead Vocal")
    is_backing = stem_type == "Backing Vocal"

    problems: list[dict[str, str]] = []
    warnings: list[str] = []
    recommended: dict[str, float | str | bool] = {
        "enabled": True,
        "useEnhancedInMix": True,
    }
    mix_suggestions: dict[str, float | str | bool] = {}
    next_steps: list[str] = []
    score = 92

    def value(key: str, default: float = 0.0) -> float:
        item = profile.get(key)
        return float(item) if isinstance(item, (int, float)) else default

    def add_problem(issue_type: str, severity: str, message: str, penalty: int) -> None:
        nonlocal score
        problems.append({"type": issue_type, "severity": severity, "message": message})
        score -= penalty

    source_lufs = value("integratedLufs", value("rmsDbfs", -24.0))
    source_peak = value("peakDbfs", -12.0)
    noise_floor = value("noiseFloorDbfs", -60.0)
    silence = value("silencePercentage", 0.0)
    sibilance = value("sibilanceRatio")
    harshness = value("harshnessRatio")
    presence = value("presenceRatio")
    air = value("airRatio")
    mud = value("mudRatio")
    body = value("bodyRatio")
    flatness = value("spectralFlatness")
    centroid = value("spectralCentroidHz")

    if not settings.get("enabled"):
        add_problem("Enhancer Off", "High", "This vocal has not been queued for enhancement, so the mix may still be using the raw tone.", 18)
        next_steps.append("Apply Doctor Fix, then render Enhance Vocals.")
    if enhancement.get("status") != "Completed":
        add_problem("Needs Render", "High", "No finished enhanced vocal exists yet; current mixer previews may not include the vocal polish chain.", 14)
        next_steps.append("Render Enhance Vocals after applying settings.")
    elif not settings.get("useEnhancedInMix", True):
        add_problem("Not In Mix", "High", "An enhanced vocal exists, but the mixer is not set to use it.", 16)
    if cleaning.get("mode") == "Strong":
        add_problem("Over-clean Risk", "Medium", "Strong cleaning can make vocals watery or phasey before enhancement.", 9)
        warnings.append("Try Medium or Light cleaning if the vocal sounds thin, smeared, or metallic.")

    if source_peak > -0.6 or profile.get("clippingDetected"):
        add_problem("Clipped Source", "High", "The vocal source is close to clipping; aggressive compression, saturation, or air boosts can make distortion more obvious.", 14)
        recommended["compressionAmount"] = min(float(settings.get("compressionAmount", 45)), 58)
        recommended["saturationAmount"] = min(float(settings.get("saturationAmount", 50)), 34)
    if source_lufs > -12:
        add_problem("Too Hot", "Medium", "The vocal is already loud, so extra compression can flatten it.", 8)
        recommended["compressionAmount"] = min(float(settings.get("compressionAmount", 45)), 58)
        recommended["riderAmount"] = min(float(settings.get("riderAmount", 45)), 62)
    if source_lufs < -30:
        add_problem("Too Quiet", "Medium", "The vocal is low before processing and may fall behind the band.", 8)
        recommended["compressionAmount"] = max(float(settings.get("compressionAmount", 45)), 68)
        recommended["riderAmount"] = max(float(settings.get("riderAmount", 45)), 74)
    if noise_floor > -45 or flatness > 0.09:
        add_problem("Noisy", "High", "Noise or hiss is elevated; bright effects can exaggerate it.", 13)
        recommended.update({"preset": "Live Vocal Fix", "fxAmount": min(float(settings.get("fxAmount", 0)), 18), "saturationAmount": min(float(settings.get("saturationAmount", 50)), 36)})
    if silence > 55:
        add_problem("Long Silence", "Low", "The file contains a lot of silence; keep alignment, but check that the vocal sections are actually present.", 4)

    if sibilance > 0.13:
        add_problem("Sibilant", "High", "S and sh sounds are strong; too much air or delay will make them sharper.", 12)
        recommended["deEssAmount"] = max(float(settings.get("deEssAmount", 50)), 78)
        recommended["airAmount"] = min(float(settings.get("airAmount", 0)), -8)
    if harshness > 0.28:
        add_problem("Harsh", "Medium", "Upper mids are forward; presence boost may make the vocal edgy.", 9)
        recommended["presenceAmount"] = min(float(settings.get("presenceAmount", 0)), -14)
        recommended["deEssAmount"] = max(float(settings.get("deEssAmount", 50)), 68)
    if presence < 0.09 and air < 0.035:
        add_problem("Dull", "Medium", "Presence and air are low, so the vocal may sound covered or far away.", 8)
        recommended["preset"] = "Bright AI Polish" if not is_backing else "Backing Vocal Wide"
        recommended["presenceAmount"] = max(float(settings.get("presenceAmount", 0)), 18)
        recommended["airAmount"] = max(float(settings.get("airAmount", 0)), 18)
    if mud > 0.32 and presence < 0.15:
        add_problem("Muddy", "Medium", "Low-mid energy is masking clarity.", 8)
        recommended["bodyAmount"] = min(float(settings.get("bodyAmount", 0)), -20)
        recommended["presenceAmount"] = max(float(recommended.get("presenceAmount", settings.get("presenceAmount", 0))), 10)
    if body < 0.08 and centroid > 1800:
        add_problem("Thin", "Medium", "The vocal has little body compared with its brightness.", 7)
        recommended["bodyAmount"] = max(float(settings.get("bodyAmount", 0)), 18)
        recommended["saturationAmount"] = max(float(settings.get("saturationAmount", 50)), 58)

    if settings.get("pitchCorrection") == "Strong":
        add_problem("Heavy Pitch", "Medium", "Strong pitch polish can sound artificial on live or expressive vocals.", 8)
        recommended.update({"pitchCorrection": "Natural", "pitchStrength": 42, "pitchHumanize": 82})
    if settings.get("fxStyle") != "Dry" and float(settings.get("fxAmount", 0)) > 0:
        add_problem("Printed FX", "Medium", "This enhanced vocal already prints ambience, and the mixer adds space again, so the vocal can lose focus.", 7)
        recommended["fxStyle"] = "Dry"
        recommended["fxAmount"] = 0
    if not is_backing and float(settings.get("doublerAmount", 50)) > 35:
        add_problem("Lead Too Wide", "Medium", "The lead vocal doubler is high; this can pull the lead away from the center.", 8)
        recommended["doublerAmount"] = 18
    if float(settings.get("fxAmount", 0)) > 48:
        add_problem("Too Wet", "Medium", "Vocal FX amount is high and may blur words in the mix.", 8)
        recommended["fxStyle"] = "Dry"
        recommended["fxAmount"] = 0
    if settings.get("fxStyle") == "Worship Wide" and not is_backing:
        add_problem("Wide Lead FX", "Medium", "Worship Wide is lush, but it can push a lead vocal behind the band.", 7)
        recommended["fxStyle"] = "Dry"
        recommended["fxAmount"] = 0
    if float(settings.get("compressionAmount", 45)) > 82:
        add_problem("Overcompressed", "Medium", "Very high vocal compression can reduce emotion and add pumping.", 7)
        recommended["compressionAmount"] = 66
    if float(settings.get("airAmount", 0)) > 32 and sibilance > 0.1:
        add_problem("Air Too Sharp", "Medium", "Air boost is high for a sibilant vocal.", 7)
        recommended["airAmount"] = -6

    if not is_backing:
        if float(controls.get("vocalBoost", 1.5)) < 2:
            add_problem("Buried In Mix", "Medium", "The lead vocal mix macro is modest; it may sit behind guitars, keys, or drums.", 8)
            mix_suggestions["vocalBoost"] = 2.5
            mix_suggestions["vocalBusLevel"] = max(float(controls.get("vocalBusLevel", 0)), 1.0)
        if float(controls.get("vocalDelayAmount", 25)) > 60:
            add_problem("Delay Blur", "Medium", "Global vocal delay is high and can smear lyric clarity.", 7)
            mix_suggestions["vocalDelayAmount"] = 35
        if float(controls.get("vocalReverbAmount", 35)) > 60 or float(controls.get("reverbAmount", 35)) > 68:
            add_problem("Reverb Wash", "Medium", "Reverb macros are high enough to push vocals backward.", 7)
            mix_suggestions["vocalReverbAmount"] = 38
            mix_suggestions["reverbAmount"] = min(float(controls.get("reverbAmount", 35)), 50)

    for issue in analysis.get("issues") or []:
        issue_type = issue.get("type")
        if issue_type and not any(problem["type"] == issue_type for problem in problems):
            add_problem(str(issue_type), str(issue.get("severity", "Medium")), str(issue.get("message", "Vocal analysis found this issue.")), 4)

    if not problems:
        summary = "Vocal Doctor found no major issues. Keep the current settings and compare the enhanced vocal in context."
        next_steps.append("Render a fresh mix and compare Source In Mix vs Enhanced In Mix.")
    else:
        top = ", ".join(problem["type"].lower() for problem in problems[:3])
        summary = f"Vocal Doctor found {top}; apply the fix, render vocals, then regenerate the mix."
        next_steps.append("Apply Doctor Fix.")
        next_steps.append("Render Enhance Vocals.")
        next_steps.append("Generate a new Mix version and compare it against the previous mix.")

    score = max(15, min(100, score))
    return {
        "stemId": stem["id"],
        "status": "Completed",
        "diagnosedAt": utc_now_iso(),
        "sourceFilePath": source_display_path,
        "sourceKind": source_kind,
        "score": score,
        "summary": summary,
        "problems": problems,
        "recommendedSettings": _doctor_settings_patch(settings, recommended),
        "mixControlSuggestions": _doctor_mix_patch(controls, mix_suggestions),
        "nextSteps": _dedupe_preserve_order(next_steps),
        "warnings": warnings,
        "error": None,
    }


def _doctor_settings_patch(current: dict[str, Any], recommended: dict[str, float | str | bool]) -> dict[str, float | str | bool]:
    patch: dict[str, float | str | bool] = {}
    for key in VOCAL_SETTING_PATCH_FIELDS:
        if key not in recommended:
            continue
        value = recommended[key]
        if current.get(key) != value:
            patch[key] = value
    return patch


def _doctor_mix_patch(current: dict[str, Any], recommended: dict[str, float | str | bool]) -> dict[str, float | str | bool]:
    patch: dict[str, float | str | bool] = {}
    for key in MIX_CONTROL_PATCH_FIELDS:
        if key in recommended and current.get(key) != recommended[key]:
            patch[key] = recommended[key]
    return patch


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _apply_vocal_pitch_consensus(stems: list[dict[str, Any]]) -> str | None:
    candidates: dict[tuple[str, str], float] = {}
    for stem in stems:
        result = stem.get("vocalAnalysisResult") or {}
        if result.get("status") != "Completed":
            continue
        features = result.get("features") or {}
        key = features.get("estimatedKey")
        scale = features.get("estimatedScale")
        confidence = features.get("keyConfidence")
        if not key or key == "Auto" or not isinstance(confidence, (int, float)) or confidence < 48:
            continue
        candidates[(str(key), str(scale or "Major"))] = candidates.get((str(key), str(scale or "Major")), 0.0) + float(confidence)
    if not candidates:
        return None
    (key, scale), score = max(candidates.items(), key=lambda item: item[1])
    for stem in stems:
        result = stem.get("vocalAnalysisResult") or {}
        settings = result.get("recommendedSettings") or {}
        if result.get("status") == "Completed" and settings.get("pitchCorrection") != "Off":
            settings["key"] = key
            settings["scale"] = scale
            warnings = result.setdefault("warnings", [])
            warnings.append(f"Project pitch workflow selected {key} {scale} for vocal pitch polish.")
    return f"Vocal pitch workflow selected {key} {scale} from vocal analysis confidence score {score:.0f}."


def _ensure_vocal_settings(stem: dict[str, Any]) -> dict[str, Any]:
    settings = stem.setdefault(
        "vocalEnhancementSettings",
        {
            "enabled": False,
            "preset": "Natural Clean",
            "pitchCorrection": "Off",
            "key": "Auto",
            "scale": "Major",
            "fxStyle": "Dry",
            "fxAmount": 0,
            "bodyAmount": 0,
            "presenceAmount": 0,
            "airAmount": 0,
            "deEssAmount": 50,
            "compressionAmount": 45,
            "riderAmount": 45,
            "saturationAmount": 50,
            "doublerAmount": 50,
            "breathReductionAmount": 35,
            "mouthClickReductionAmount": 30,
            "pitchStrength": 50,
            "pitchHumanize": 60,
            "useEnhancedInMix": True,
        },
    )
    settings.setdefault("enabled", False)
    settings.setdefault("preset", "Natural Clean")
    settings.setdefault("pitchCorrection", "Off")
    settings.setdefault("key", "Auto")
    settings.setdefault("scale", "Major")
    settings.setdefault("fxStyle", "Dry")
    settings.setdefault("fxAmount", 0)
    settings.setdefault("bodyAmount", 0)
    settings.setdefault("presenceAmount", 0)
    settings.setdefault("airAmount", 0)
    settings.setdefault("deEssAmount", 50)
    settings.setdefault("compressionAmount", 45)
    settings.setdefault("riderAmount", 45)
    settings.setdefault("saturationAmount", 50)
    settings.setdefault("doublerAmount", 50)
    settings.setdefault("breathReductionAmount", 35)
    settings.setdefault("mouthClickReductionAmount", 30)
    settings.setdefault("pitchStrength", 50)
    settings.setdefault("pitchHumanize", 60)
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
        and result.get("fxStyle", "Dry") == settings.get("fxStyle")
        and float(result.get("fxAmount", 0)) == float(settings.get("fxAmount", 0))
        and _control_result_matches(result, settings)
        and bool(result.get("enhancedFilePath"))
    )


def _control_result_matches(result: dict[str, Any], settings: dict[str, Any]) -> bool:
    return all(float(result.get(key, default)) == float(settings.get(key, default)) for key, default in VOCAL_CONTROL_DEFAULTS.items())


def _build_enhancement_report(
    stem: dict[str, Any],
    settings: dict[str, Any],
    original_metrics: dict[str, Any],
    enhanced_metrics: dict[str, Any],
    metric_deltas: dict[str, Any],
    operations: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    improvements: list[str] = []
    if isinstance(metric_deltas.get("noiseFloorDbfs"), (int, float)) and metric_deltas["noiseFloorDbfs"] < -0.5:
        improvements.append(f"Noise floor improved by {abs(metric_deltas['noiseFloorDbfs']):.1f} dB.")
    if isinstance(metric_deltas.get("silencePercentage"), (int, float)) and metric_deltas["silencePercentage"] < -1:
        improvements.append("Quiet sections were tightened without trimming alignment.")
    if any("de-esser" in operation.lower() for operation in operations):
        improvements.append("Sibilance control was applied.")
    if any("vocal rider" in operation.lower() for operation in operations):
        improvements.append("Level consistency was improved with vocal riding.")
    if any("breath" in operation.lower() for operation in operations):
        improvements.append("Breath sections were softened.")
    if any("mouth" in operation.lower() or "click" in operation.lower() for operation in operations):
        improvements.append("Mouth clicks and short spikes were softened.")
    if any("pitch" in operation.lower() and "skipped" not in operation.lower() for operation in operations):
        improvements.append("Pitch polish was applied with the selected key workflow.")
    if not improvements:
        improvements.append("Tone, level, and safety processing were rendered.")

    before_lufs = original_metrics.get("integratedLufs")
    after_lufs = enhanced_metrics.get("integratedLufs")
    before_peak = original_metrics.get("peakDbfs")
    after_peak = enhanced_metrics.get("peakDbfs")
    summary_parts = [f"{settings.get('preset', 'Natural Clean')} rendered"]
    if isinstance(before_lufs, (int, float)) and isinstance(after_lufs, (int, float)):
        summary_parts.append(f"LUFS {before_lufs:.1f} -> {after_lufs:.1f}")
    if isinstance(before_peak, (int, float)) and isinstance(after_peak, (int, float)):
        summary_parts.append(f"peak {before_peak:.1f} -> {after_peak:.1f} dBFS")

    return {
        "stemId": stem.get("id"),
        "filename": stem.get("originalFilename"),
        "summary": "; ".join(summary_parts) + ".",
        "before": original_metrics,
        "after": enhanced_metrics,
        "deltas": metric_deltas,
        "improvements": improvements,
        "settings": {key: settings.get(key) for key in ["preset", "pitchCorrection", "key", "scale", "fxStyle", *VOCAL_CONTROL_FIELDS]},
        "warnings": warnings,
        "generatedAt": utc_now_iso(),
    }


def _sanitize_custom_preset_settings(payload: UpdateVocalEnhancementSettingsRequest) -> dict[str, Any]:
    settings = payload.model_dump(exclude_unset=True)
    allowed_fields = {
        "preset",
        "pitchCorrection",
        "key",
        "scale",
        "fxStyle",
        "fxAmount",
        "bodyAmount",
        "presenceAmount",
        "airAmount",
        "deEssAmount",
        "compressionAmount",
        "riderAmount",
        "saturationAmount",
        "doublerAmount",
        "breathReductionAmount",
        "mouthClickReductionAmount",
        "pitchStrength",
        "pitchHumanize",
    }
    sanitized = {key: value for key, value in settings.items() if key in allowed_fields and value is not None}
    if not sanitized:
        raise HTTPException(status_code=400, detail="Choose at least one vocal setting before saving a preset.")
    return sanitized


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


def _item_progress(index: int, total: int, fraction: float, start: int = 4, end: int = 96) -> int:
    if total <= 0:
        return start
    safe_fraction = max(0.0, min(1.0, float(fraction)))
    progress = start + (((index - 1) + safe_fraction) / total) * (end - start)
    return max(start, min(end, int(round(progress))))


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
