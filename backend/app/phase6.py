import json
import threading
import uuid
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .audio_engine import ensure_audio_environment, export_audio_file, master_audio_file
from .logging_utils import append_project_log, utc_now_iso
from .models import ExportFile, ExportMixRequest, GenerateMasterRequest, MasterVersion, ProcessingJob, Project, ProjectBackupRequest, UpdateMasteringControlsRequest
from .storage import display_path, ensure_project_dirs, project_subdirs, resolve_stored_file_path, store, _find_project


MASTERING_PRESETS: dict[str, dict[str, Any]] = {
    "Demo": {"targetLufs": -16.0, "description": "Open and natural for quick sharing.", "warning": None},
    "Streaming": {"targetLufs": -14.0, "description": "Balanced loudness target for most streaming platforms.", "warning": None},
    "YouTube/Facebook": {"targetLufs": -14.0, "description": "Video-platform friendly loudness and true-peak safety.", "warning": None},
    "Balanced Loud": {"targetLufs": -11.0, "description": "Louder master with moderate dynamics control.", "warning": "Louder masters may reduce dynamics."},
    "Loud Rock": {"targetLufs": -9.0, "description": "Aggressive loudness for dense rock mixes.", "warning": "Loud Rock can reduce punch if the mix is already clipped."},
    "Very Loud": {"targetLufs": -7.0, "description": "Maximum loudness preview for reference only.", "warning": "Very Loud may cause distortion if pushed too hard."},
}

OUTPUT_FORMATS: dict[str, dict[str, str]] = {
    "WAV 16-bit": {"extension": ".wav", "description": "CD-compatible PCM WAV"},
    "WAV 24-bit": {"extension": ".wav", "description": "Higher-resolution PCM WAV"},
    "MP3 320kbps": {"extension": ".mp3", "description": "High-quality MP3"},
    "FLAC": {"extension": ".flac", "description": "Lossless compressed audio"},
}

TRUE_PEAK_CEILING_DB = -1.0
ACTIVE_JOB_STATUSES = {"Pending", "Processing"}
RUNNING_MASTERING_JOB_IDS: set[str] = set()
RUNNING_MASTERING_JOB_LOCK = threading.Lock()


def get_mastering_presets() -> dict[str, list[dict[str, Any]]]:
    return {
        "presets": [{"name": name, **preset} for name, preset in MASTERING_PRESETS.items()],
        "outputFormats": [{"name": name, **details} for name, details in OUTPUT_FORMATS.items()],
        "truePeakCeilingDb": TRUE_PEAK_CEILING_DB,
    }


def update_mastering_controls(project_id: str, payload: UpdateMasteringControlsRequest) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    controls = _ensure_mastering_controls(project)
    fields = payload.model_fields_set

    if "selectedMixVersionId" in fields:
        selected = payload.selectedMixVersionId
        if selected:
            _find_mix_version(project, selected)
        controls["selectedMixVersionId"] = selected
    if "preset" in fields:
        preset = payload.preset or "Streaming"
        if preset not in MASTERING_PRESETS:
            raise HTTPException(status_code=400, detail="Invalid mastering preset.")
        controls["preset"] = preset
    if "outputFormat" in fields:
        output_format = payload.outputFormat or "WAV 16-bit"
        if output_format not in OUTPUT_FORMATS:
            raise HTTPException(status_code=400, detail="Unsupported output format.")
        controls["outputFormat"] = output_format

    for field in fields:
        if field in {"selectedMixVersionId", "preset", "outputFormat"}:
            continue
        value = getattr(payload, field)
        if value is not None:
            controls[field] = round(float(value), 2)

    now = utc_now_iso()
    project["masteringSettings"]["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Updated mastering controls for {controls.get('preset', 'Streaming')} preset.")
    return Project(**project)


def create_mastering_job(project_id: str, payload: GenerateMasterRequest) -> ProcessingJob:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _validate_preset_and_format(payload.preset, payload.outputFormat)
    data = store.load()
    project = _find_project(data, project_id)
    _find_mix_version(project, payload.selectedMixVersionId)
    active_job = next(
        (job for job in reversed(project.get("processingJobs", [])) if job.get("type") == "Mastering" and job.get("status") in ACTIVE_JOB_STATUSES),
        None,
    )
    if active_job:
        append_project_log(project_subdirs(project_id)["logs"], f"Reused active mastering job {active_job['id']}.")
        return ProcessingJob(**active_job)

    now = utc_now_iso()
    job = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "type": "Mastering",
        "status": "Pending",
        "progress": 0,
        "currentStemId": None,
        "message": "Mastering queued.",
        "errors": [],
        "createdAt": now,
        "updatedAt": now,
        "completedAt": None,
    }
    project.setdefault("processingJobs", []).append(job)
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Mastering job {job['id']} queued for {payload.preset} / {payload.outputFormat}.")
    return ProcessingJob(**job)


def run_mastering_job(project_id: str, job_id: str, payload: GenerateMasterRequest) -> None:
    with RUNNING_MASTERING_JOB_LOCK:
        if job_id in RUNNING_MASTERING_JOB_IDS:
            append_project_log(project_subdirs(project_id)["logs"], f"Ignored duplicate mastering runner for job {job_id}.")
            return
        RUNNING_MASTERING_JOB_IDS.add(job_id)

    try:
        _run_mastering_job(project_id, job_id, payload)
    finally:
        with RUNNING_MASTERING_JOB_LOCK:
            RUNNING_MASTERING_JOB_IDS.discard(job_id)


def _run_mastering_job(project_id: str, job_id: str, payload: GenerateMasterRequest) -> None:
    try:
        _update_job(project_id, job_id, status="Processing", progress=4, message="Preparing selected mix.")
        master = generate_master(
            project_id,
            payload,
            progress_callback=lambda fraction, message: _update_job(
                project_id,
                job_id,
                progress=_scaled_progress(fraction, 6, 92),
                message=message,
            ),
        )
        _update_job(project_id, job_id, progress=96, message=f"Saving {master.label}.")
        now = utc_now_iso()
        data = store.load()
        project = _find_project(data, project_id)
        job = _find_job(project, job_id)
        job["status"] = "Completed"
        job["progress"] = 100
        job["currentStemId"] = None
        job["message"] = f"Mastering completed: {master.label}."
        job["updatedAt"] = now
        job["completedAt"] = now
        store.save(data)
        append_project_log(project_subdirs(project_id)["logs"], f"Mastering job {job_id} completed.")
    except Exception as exc:
        error_message = _error_detail(exc) or "Mastering failed."
        now = utc_now_iso()
        data = store.load()
        project = _find_project(data, project_id)
        job = _find_job(project, job_id)
        job["status"] = "Failed"
        job["progress"] = 100
        job["currentStemId"] = None
        job["message"] = error_message
        job["errors"] = [{"stemId": None, "filename": None, "error": error_message}]
        job["updatedAt"] = now
        job["completedAt"] = now
        store.save(data)
        append_project_log(project_subdirs(project_id)["logs"], f"Mastering job {job_id} failed: {error_message}")


def generate_master(project_id: str, payload: GenerateMasterRequest, progress_callback=None) -> MasterVersion:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _validate_preset_and_format(payload.preset, payload.outputFormat)
    data = store.load()
    project = _find_project(data, project_id)
    ensure_project_dirs(project_id)
    mix_version = _find_mix_version(project, payload.selectedMixVersionId)
    input_path = _source_mix_path(mix_version)
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Selected mix file is missing: {mix_version.get('wavPath') or mix_version.get('mp3Path')}.")

    preset = MASTERING_PRESETS[payload.preset]
    target_lufs = float(preset["targetLufs"])
    controls = payload.model_dump()
    controls["targetLufs"] = target_lufs
    controls["truePeakCeilingDb"] = TRUE_PEAK_CEILING_DB

    masters_dir = project_subdirs(project_id)["exports"] / "masters"
    reports_dir = project_subdirs(project_id)["exports"] / "reports"
    version_number = _next_master_version(project, masters_dir)
    label = f"master_v{version_number:03d}"
    output_path = masters_dir / f"{label}{_format_extension(payload.outputFormat)}"
    report_json_path = reports_dir / f"{label}_report.json"
    report_txt_path = reports_dir / f"{label}_report.txt"

    append_project_log(project_subdirs(project_id)["logs"], f"Mastering {mix_version.get('label', 'selected mix')} as {label} with {payload.preset} preset.")
    result = master_audio_file(
        input_path,
        output_path,
        payload.outputFormat,
        controls=controls,
        target_lufs=target_lufs,
        true_peak_ceiling_db=TRUE_PEAK_CEILING_DB,
        progress_callback=progress_callback,
    )

    now = utc_now_iso()
    file_path = display_path(result.path)
    report = {
        "integratedLufs": result.output_metrics.get("integratedLufs"),
        "peakDbfs": result.output_metrics.get("peakDbfs"),
        "truePeakDbfs": result.output_metrics.get("truePeakDbfs"),
        "dynamicRangeDb": result.dynamic_range_db,
        "clippingDetected": bool(result.output_metrics.get("clippingDetected", False)),
        "clippingSampleCount": int(result.output_metrics.get("clippingSampleCount", 0) or 0),
        "clippingPercentage": result.output_metrics.get("clippingPercentage", 0),
        "preset": payload.preset,
        "outputFormat": payload.outputFormat,
        "filePath": file_path,
        "timestamp": now,
        "targetLufs": target_lufs,
        "truePeakCeilingDb": TRUE_PEAK_CEILING_DB,
        "sourceMixVersionId": payload.selectedMixVersionId,
        "sourceMixLabel": mix_version.get("label"),
        "inputMetrics": result.input_metrics,
        "outputMetrics": result.output_metrics,
        "operations": result.operations,
        "warnings": result.warnings,
        "errors": result.errors,
    }
    _write_report_files(report_json_path, report_txt_path, report)

    master_version = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "versionNumber": version_number,
        "label": f"Master v{version_number:03d}",
        "sourceMixVersionId": payload.selectedMixVersionId,
        "sourceMixLabel": mix_version.get("label"),
        "preset": payload.preset,
        "outputFormat": payload.outputFormat,
        "createdAt": now,
        "filePath": file_path,
        "fileUrl": _media_url(file_path),
        "reportJsonPath": display_path(report_json_path),
        "reportTxtPath": display_path(report_txt_path),
        "reportJsonUrl": _media_url(display_path(report_json_path)),
        "reportTxtUrl": _media_url(display_path(report_txt_path)),
        "targetLufs": target_lufs,
        "truePeakCeilingDb": TRUE_PEAK_CEILING_DB,
        "integratedLufs": result.output_metrics.get("integratedLufs"),
        "peakDbfs": result.output_metrics.get("peakDbfs"),
        "truePeakDbfs": result.output_metrics.get("truePeakDbfs"),
        "dynamicRangeDb": result.dynamic_range_db,
        "clippingDetected": bool(result.output_metrics.get("clippingDetected", False)),
        "warnings": result.warnings,
        "errors": result.errors,
        "settings": controls,
        "report": report,
    }

    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_mastering_settings(project)
    settings["masterVersions"].append(master_version)
    settings["latestMasterVersionId"] = master_version["id"]
    settings["controls"].update(
        {
            "selectedMixVersionId": payload.selectedMixVersionId,
            "preset": payload.preset,
            "brightness": payload.brightness,
            "warmth": payload.warmth,
            "compressionAmount": payload.compressionAmount,
            "limiterStrength": payload.limiterStrength,
            "stereoWidth": payload.stereoWidth,
            "outputFormat": payload.outputFormat,
        }
    )
    settings["updatedAt"] = now
    project["status"] = "Master Ready"
    project["updatedAt"] = now
    store.save(data)

    for warning in result.warnings:
        append_project_log(project_subdirs(project_id)["logs"], f"Mastering warning: {warning}")
    for error in result.errors:
        append_project_log(project_subdirs(project_id)["logs"], f"Mastering processing error: {error}")
    append_project_log(project_subdirs(project_id)["logs"], f"Master saved to {file_path}. Report saved to {display_path(report_json_path)}.")
    return MasterVersion(**master_version)


def export_mix_without_mastering(project_id: str, payload: ExportMixRequest) -> ExportFile:
    return _export_selected_mix(project_id, payload, export_type="Unmastered Mix", output_folder="mixes", prefix="mix_export", require_instrumental=False)


def export_instrumental(project_id: str, payload: ExportMixRequest) -> ExportFile:
    return _export_selected_mix(project_id, payload, export_type="Instrumental", output_folder="instrumentals", prefix="instrumental", require_instrumental=True)


def create_project_backup(project_id: str, payload: ProjectBackupRequest) -> ExportFile:
    data = store.load()
    project = _find_project(data, project_id)
    ensure_project_dirs(project_id)
    backups_dir = project_subdirs(project_id)["exports"] / "backups"
    version_number = _next_export_number(project, backups_dir, "project_backup", ".zip")
    output_path = backups_dir / f"project_backup_v{version_number:03d}.zip"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    append_project_log(project_subdirs(project_id)["logs"], f"Creating project backup v{version_number:03d}. Include originals: {payload.includeOriginalStems}.")
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project_metadata.json", json.dumps(project, indent=2))
        _add_tree_to_zip(archive, project_subdirs(project_id)["logs"], "logs")
        _add_tree_to_zip(archive, project_subdirs(project_id)["exports"] / "masters", "exports/masters")
        _add_tree_to_zip(archive, project_subdirs(project_id)["exports"] / "reports", "exports/reports")
        _add_tree_to_zip(archive, project_subdirs(project_id)["processed"] / "mixes", "processed/mixes")
        if payload.includeOriginalStems:
            _add_tree_to_zip(archive, project_subdirs(project_id)["original"], "original")

    export_file = _export_file_record(
        project_id=project_id,
        export_type="Project Backup",
        label=f"Project Backup v{version_number:03d}",
        path=output_path,
        output_format="ZIP",
        source_mix_version_id=None,
        include_originals=payload.includeOriginalStems,
    )
    _save_export_record(project_id, export_file)
    append_project_log(project_subdirs(project_id)["logs"], f"Project backup saved to {export_file['filePath']}.")
    return ExportFile(**export_file)


def _export_selected_mix(project_id: str, payload: ExportMixRequest, export_type: str, output_folder: str, prefix: str, require_instrumental: bool) -> ExportFile:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload.outputFormat not in OUTPUT_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported output format.")
    data = store.load()
    project = _find_project(data, project_id)
    mix_version = _find_mix_version(project, payload.selectedMixVersionId)
    if require_instrumental and _mix_has_vocals(mix_version):
        raise HTTPException(status_code=400, detail="Generate or select a mix version with lead and backing vocals muted before exporting an instrumental.")
    input_path = _source_mix_path(mix_version)
    if not input_path.exists():
        raise HTTPException(status_code=404, detail="Selected mix file is missing.")

    output_dir = project_subdirs(project_id)["exports"] / output_folder
    version_number = _next_export_number(project, output_dir, prefix, _format_extension(payload.outputFormat))
    output_path = output_dir / f"{prefix}_v{version_number:03d}{_format_extension(payload.outputFormat)}"
    append_project_log(project_subdirs(project_id)["logs"], f"Exporting {export_type.lower()} from {mix_version.get('label', 'selected mix')} to {payload.outputFormat}.")
    export_audio_file(input_path, output_path, payload.outputFormat)
    export_file = _export_file_record(
        project_id=project_id,
        export_type=export_type,
        label=f"{export_type} v{version_number:03d}",
        path=output_path,
        output_format=payload.outputFormat,
        source_mix_version_id=payload.selectedMixVersionId,
    )
    _save_export_record(project_id, export_file)
    append_project_log(project_subdirs(project_id)["logs"], f"{export_type} saved to {export_file['filePath']}.")
    return ExportFile(**export_file)


def _ensure_mastering_settings(project: dict[str, Any]) -> dict[str, Any]:
    project.setdefault("masteringSettings", {})
    settings = project["masteringSettings"]
    settings.setdefault("controls", _default_mastering_controls())
    for key, value in _default_mastering_controls().items():
        settings["controls"].setdefault(key, value)
    settings.setdefault("masterVersions", [])
    settings.setdefault("latestMasterVersionId", None)
    settings.setdefault("exportFiles", [])
    settings.setdefault("updatedAt", None)
    return settings


def _ensure_mastering_controls(project: dict[str, Any]) -> dict[str, Any]:
    return _ensure_mastering_settings(project)["controls"]


def _find_job(project: dict[str, Any], job_id: str) -> dict[str, Any]:
    job = next((item for item in project.get("processingJobs", []) if item.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    return job


def _update_job(project_id: str, job_id: str, **updates: Any) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    job.update(updates)
    job["updatedAt"] = utc_now_iso()
    store.save(data)


def _scaled_progress(fraction: float, start: int, end: int) -> int:
    safe_fraction = max(0.0, min(1.0, float(fraction)))
    return max(start, min(end, int(round(start + safe_fraction * (end - start)))))


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc)


def _default_mastering_controls() -> dict[str, Any]:
    return {
        "selectedMixVersionId": None,
        "preset": "Streaming",
        "brightness": 0,
        "warmth": 0,
        "compressionAmount": 45,
        "limiterStrength": 55,
        "stereoWidth": 55,
        "outputFormat": "WAV 16-bit",
    }


def _validate_preset_and_format(preset: str, output_format: str) -> None:
    if preset not in MASTERING_PRESETS:
        raise HTTPException(status_code=400, detail="Invalid mastering preset.")
    if output_format not in OUTPUT_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported output format.")


def _find_mix_version(project: dict[str, Any], version_id: str) -> dict[str, Any]:
    versions = project.get("mixSettings", {}).get("mixVersions", [])
    version = next((item for item in versions if item.get("id") == version_id), None)
    if version is None:
        raise HTTPException(status_code=404, detail="Selected mix version was not found. Generate an advanced mix first.")
    return version


def _source_mix_path(mix_version: dict[str, Any]) -> Path:
    path_value = mix_version.get("wavPath") or mix_version.get("mp3Path")
    if not path_value:
        raise HTTPException(status_code=400, detail="Selected mix version does not have an audio file.")
    return resolve_stored_file_path(path_value)


def _next_master_version(project: dict[str, Any], output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = [int(item.get("versionNumber", 0)) for item in project.get("masteringSettings", {}).get("masterVersions", [])]
    number = max(existing, default=0) + 1
    while any((output_dir / f"master_v{number:03d}{details['extension']}").exists() for details in OUTPUT_FORMATS.values()):
        number += 1
    return number


def _next_export_number(project: dict[str, Any], output_dir: Path, prefix: str, extension: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = [path for path in output_dir.glob(f"{prefix}_v*{extension}")]
    number = len(existing) + 1
    while (output_dir / f"{prefix}_v{number:03d}{extension}").exists():
        number += 1
    return number


def _write_report_files(json_path: Path, txt_path: Path, report: dict[str, Any]) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(report, json_file, indent=2)
    lines = [
        "Local Stem Mixer AI - Mastering Loudness Report",
        f"Timestamp: {report['timestamp']}",
        f"Preset: {report['preset']}",
        f"Output format: {report['outputFormat']}",
        f"File path: {report['filePath']}",
        f"Target LUFS: {report['targetLufs']}",
        f"Integrated LUFS: {report.get('integratedLufs')}",
        f"Peak dBFS: {report.get('peakDbfs')}",
        f"True peak dBTP: {report.get('truePeakDbfs')}",
        f"Dynamic range estimate: {report.get('dynamicRangeDb')} dB",
        f"Clipping detected: {report.get('clippingDetected')}",
        f"Clipping samples: {report.get('clippingSampleCount')}",
        "",
        "Operations:",
        *[f"- {item}" for item in report.get("operations", [])],
        "",
        "Warnings:",
        *[f"- {item}" for item in report.get("warnings", [])],
    ]
    with txt_path.open("w", encoding="utf-8") as txt_file:
        txt_file.write("\n".join(lines))


def _export_file_record(
    project_id: str,
    export_type: str,
    label: str,
    path: Path,
    output_format: str | None,
    source_mix_version_id: str | None,
    include_originals: bool | None = None,
) -> dict[str, Any]:
    file_path = display_path(path)
    return {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "type": export_type,
        "label": label,
        "sourceMixVersionId": source_mix_version_id,
        "outputFormat": output_format,
        "createdAt": utc_now_iso(),
        "filePath": file_path,
        "fileUrl": _media_url(file_path),
        "sizeBytes": path.stat().st_size if path.exists() else None,
        "includeOriginalStems": include_originals,
        "warnings": [],
    }


def _save_export_record(project_id: str, export_file: dict[str, Any]) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_mastering_settings(project)
    settings["exportFiles"].append(export_file)
    settings["updatedAt"] = utc_now_iso()
    project["status"] = "Exported"
    project["updatedAt"] = settings["updatedAt"]
    store.save(data)


def _mix_has_vocals(mix_version: dict[str, Any]) -> bool:
    vocal_types = {"Lead Vocal", "Backing Vocal"}
    return any(source.get("stemType") in vocal_types for source in mix_version.get("sourceFiles", []))


def _add_tree_to_zip(archive: zipfile.ZipFile, source_dir: Path, arc_prefix: str) -> None:
    if not source_dir.exists():
        return
    for path in source_dir.rglob("*"):
        if path.is_file():
            archive.write(path, f"{arc_prefix}/{path.relative_to(source_dir).as_posix()}")


def _format_extension(output_format: str) -> str:
    if output_format not in OUTPUT_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported output format.")
    return OUTPUT_FORMATS[output_format]["extension"]


def _media_url(path_value: str | None) -> str | None:
    if path_value is None:
        return None
    normalized = path_value.replace("\\", "/")
    if normalized.startswith("storage/"):
        normalized = normalized[len("storage/") :]
    return f"/media/{normalized}"
