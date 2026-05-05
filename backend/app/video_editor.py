import re
import subprocess
import uuid
from datetime import datetime, timezone
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import numpy as np
from fastapi import HTTPException, UploadFile
from scipy import signal

from .audio_engine import ensure_audio_environment
from .config import ALLOWED_VIDEO_EXTENSIONS, ALLOWED_VIDEO_LOGO_EXTENSIONS, BASE_DIR, MAX_VIDEO_LOGO_UPLOAD_BYTES, MAX_VIDEO_UPLOAD_BYTES
from .logging_utils import append_project_log, utc_now_iso
from .models import ProcessingJob, VideoWaveformStateResponse, UpdateVideoEditorSettingsRequest, VideoEditorStateResponse
from .storage import display_path, ensure_project_dirs, project_subdirs, resolve_stored_file_path, store, _find_project


ACTIVE_JOB_STATUSES = {"Pending", "Processing"}
VIDEO_JOB_TYPE = "Video Export"
VIDEO_PREVIEW_JOB_TYPE = "Video Preview"
AUDIO_ALIGN_SAMPLE_RATE = 8000
AUDIO_ALIGN_MAX_SECONDS = 90
EXPORT_PRESETS: dict[str, dict[str, Any]] = {
    "YouTube 1080p": {"width": 1920, "height": 1080, "crf": 20, "videoBitrate": None, "audioBitrate": "192k", "labelPrefix": "final_video"},
    "YouTube 1440p (2K)": {"width": 2560, "height": 1440, "crf": 20, "videoBitrate": None, "audioBitrate": "192k", "labelPrefix": "final_video"},
    "YouTube 4K": {"width": 3840, "height": 2160, "crf": 20, "videoBitrate": None, "audioBitrate": "192k", "labelPrefix": "final_video"},
    "Lightweight Preview": {"width": 1280, "height": 720, "crf": 28, "videoBitrate": None, "audioBitrate": "128k", "labelPrefix": "preview_video"},
    "Source Quality": {"width": None, "height": None, "crf": 20, "videoBitrate": None, "audioBitrate": "192k", "labelPrefix": "final_video"},
}
OVERLAY_POSITIONS = {"Lower Left", "Lower Right", "Top Left", "Top Right"}
OVERLAY_STYLES = {"Boxed", "Clean", "Shadow"}
OVERLAY_SIZES = {"Small", "Medium", "Large"}
WATERMARK_POSITIONS = {"Top Right", "Top Left", "Bottom Right", "Bottom Left"}
TRANSITION_STYLES = {"Cut", "Crossfade", "Dip to Black"}
MAX_BRANDING_TEMPLATES = 12
MAX_VIDEO_CLIPS = 12
WAVEFORM_PEAK_BUCKETS = 180


async def save_uploaded_raw_video(project_id: str, upload: UploadFile, role: str = "auto") -> VideoEditorStateResponse:
    ensure_audio_environment()
    original_filename = Path(upload.filename or "untitled").name
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_VIDEO_EXTENSIONS:
        supported = ", ".join(ext[1:].upper() for ext in sorted(ALLOWED_VIDEO_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Unsupported video file type '{extension or 'none'}'. Supported formats: {supported}.")

    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    clips = settings.setdefault("rawVideos", [])
    clip_role = _resolve_clip_upload_role(settings, role)
    existing_primary = _primary_raw_video(settings)
    if len(clips) >= MAX_VIDEO_CLIPS and not (clip_role == "Primary" and existing_primary):
        raise HTTPException(status_code=400, detail=f"You can upload up to {MAX_VIDEO_CLIPS} raw video clips per project.")
    dirs = ensure_project_dirs(project_id)
    raw_dir = dirs["video"] / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = _unique_video_filename(original_filename, raw_dir)
    destination = raw_dir / stored_filename

    try:
        file_size = await _write_upload_file(upload, destination)
        metadata = _probe_video(destination)
    except ValueError as exc:
        if destination.exists():
            destination.unlink()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        if destination.exists():
            destination.unlink()
        raise HTTPException(status_code=500, detail="Could not save the raw video to local storage.") from exc
    except Exception as exc:
        if destination.exists():
            destination.unlink()
        raise HTTPException(status_code=400, detail=str(exc) or "Could not validate this video file.") from exc
    finally:
        await upload.close()

    now = utc_now_iso()
    file_path = display_path(destination)
    clip_record = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "role": clip_role,
        "originalFilename": original_filename,
        "storedFilename": stored_filename,
        "filePath": file_path,
        "fileUrl": _media_url(file_path),
        "fileSize": file_size,
        "uploadedAt": now,
        **metadata,
    }
    if clip_role == "Primary":
        if existing_primary:
            clips = [item for item in clips if item.get("id") != existing_primary.get("id")]
            _delete_previous_raw_video(existing_primary)
        settings["rawVideos"] = [clip_record, *[item for item in clips if item.get("role") != "Primary"]]
    else:
        clips.append(clip_record)
    _sync_primary_raw_video(settings)
    _sync_focus_placements(settings)
    settings["autoSyncResult"] = _default_auto_sync_result()
    settings["previewRender"] = None
    settings["finalExport"] = None
    settings["updatedAt"] = now
    project["updatedAt"] = now
    _apply_default_audio_asset(project, settings)
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Uploaded {clip_role.lower()} raw video {original_filename} as {stored_filename}.")
    return _state_response(project)


def delete_raw_video(project_id: str, clip_id: str) -> VideoEditorStateResponse:
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    clips = settings.setdefault("rawVideos", [])
    clip = next((item for item in clips if item.get("id") == clip_id), None)
    if clip is None:
        raise HTTPException(status_code=404, detail="Raw video clip not found.")
    settings["rawVideos"] = [item for item in clips if item.get("id") != clip_id]
    _delete_previous_raw_video(clip)
    _sync_primary_raw_video(settings)
    _sync_focus_placements(settings)
    now = utc_now_iso()
    settings["autoSyncResult"] = _default_auto_sync_result()
    settings["previewRender"] = None
    settings["finalExport"] = None
    settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Removed raw video clip {clip.get('originalFilename', clip_id)}.")
    return _state_response(project)


async def save_uploaded_watermark_logo(project_id: str, upload: UploadFile) -> VideoEditorStateResponse:
    original_filename = Path(upload.filename or "logo").name
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_VIDEO_LOGO_EXTENSIONS:
        supported = ", ".join(ext[1:].upper() for ext in sorted(ALLOWED_VIDEO_LOGO_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Unsupported logo file type '{extension or 'none'}'. Supported formats: {supported}.")

    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    logo_dir = ensure_project_dirs(project_id)["video"] / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = _unique_video_filename(original_filename, logo_dir)
    destination = logo_dir / stored_filename

    try:
        file_size = await _write_upload_file(upload, destination, max_bytes=MAX_VIDEO_LOGO_UPLOAD_BYTES, label="Logo")
    except ValueError as exc:
        if destination.exists():
            destination.unlink()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        if destination.exists():
            destination.unlink()
        raise HTTPException(status_code=500, detail="Could not save the watermark logo to local storage.") from exc
    finally:
        await upload.close()

    watermark = settings.setdefault("watermark", _default_watermark_settings())
    _delete_previous_raw_video(watermark.get("logo"))
    now = utc_now_iso()
    file_path = display_path(destination)
    watermark["logo"] = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "originalFilename": original_filename,
        "storedFilename": stored_filename,
        "filePath": file_path,
        "fileUrl": _media_url(file_path),
        "fileSize": file_size,
        "uploadedAt": now,
    }
    watermark["enabled"] = True
    settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Uploaded video watermark logo {original_filename} as {stored_filename}.")
    return _state_response(project)


def get_video_editor_state(project_id: str) -> VideoEditorStateResponse:
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    changed = _apply_default_audio_asset(project, settings)
    if changed:
        settings["updatedAt"] = utc_now_iso()
        project["updatedAt"] = settings["updatedAt"]
        store.save(data)
    return _state_response(project)


def update_video_editor_settings(project_id: str, payload: UpdateVideoEditorSettingsRequest) -> VideoEditorStateResponse:
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    fields = payload.model_fields_set

    if "selectedAudioAssetId" in fields:
        selected_id = (payload.selectedAudioAssetId or "").strip()
        if selected_id:
            asset = _find_audio_asset(project, selected_id)
            settings["selectedAudioAssetId"] = asset["id"]
            settings["selectedAudioAssetKind"] = asset["kind"]
            settings["selectedAudioAssetPath"] = asset["filePath"]
        else:
            settings["selectedAudioAssetId"] = None
            settings["selectedAudioAssetKind"] = None
            settings["selectedAudioAssetPath"] = None

    for field in ("useSelectedMasterAudio", "useOriginalVideoAudio"):
        if field in fields:
            settings[field] = bool(getattr(payload, field))

    if "clipOrderIds" in fields and payload.clipOrderIds is not None:
        settings["rawVideos"] = _reorder_raw_videos(settings.get("rawVideos", []), payload.clipOrderIds)
        _sync_primary_raw_video(settings)
        _sync_focus_placements(settings)
        settings["autoSyncResult"] = _default_auto_sync_result()

    for field in ("audioOffsetMs", "trimStartSeconds", "trimEndSeconds", "fadeInSeconds", "fadeOutSeconds"):
        if field in fields:
            value = getattr(payload, field)
            if value is not None:
                settings[field] = int(value) if field == "audioOffsetMs" else round(float(value), 3)

    if "exportPreset" in fields:
        preset = payload.exportPreset or "YouTube 1080p"
        if preset not in EXPORT_PRESETS:
            raise HTTPException(status_code=400, detail="Invalid video export preset.")
        settings["exportPreset"] = preset

    assembly = settings.setdefault("assembly", _default_assembly_settings())
    if "transitionStyle" in fields:
        style = payload.transitionStyle or "Crossfade"
        if style not in TRANSITION_STYLES:
            raise HTTPException(status_code=400, detail="Invalid transition style.")
        assembly["transitionStyle"] = style
    if "transitionDurationSeconds" in fields and payload.transitionDurationSeconds is not None:
        assembly["transitionDurationSeconds"] = round(float(payload.transitionDurationSeconds), 3)
    if "focusPlacements" in fields:
        assembly["focusPlacements"] = _normalize_focus_placements(settings, payload.focusPlacements or [])

    if settings.get("trimEndSeconds", 0) > 0 and settings.get("trimEndSeconds", 0) <= settings.get("trimStartSeconds", 0):
        raise HTTPException(status_code=400, detail="Trim end must be greater than trim start.")

    overlay = settings.setdefault("overlay", {})
    for field in ("songTitle", "artistName", "sessionLabel"):
        if field in fields:
            overlay[field] = _clean_optional(getattr(payload, field))
    if "overlayPosition" in fields:
        position = payload.overlayPosition or "Lower Left"
        if position not in OVERLAY_POSITIONS:
            raise HTTPException(status_code=400, detail="Invalid overlay position.")
        overlay["position"] = position
    if "overlayStyle" in fields:
        style = payload.overlayStyle or "Boxed"
        if style not in OVERLAY_STYLES:
            raise HTTPException(status_code=400, detail="Invalid overlay style.")
        overlay["style"] = style
    if "overlaySize" in fields:
        size = payload.overlaySize or "Medium"
        if size not in OVERLAY_SIZES:
            raise HTTPException(status_code=400, detail="Invalid overlay text size.")
        overlay["size"] = size

    watermark = settings.setdefault("watermark", _default_watermark_settings())
    if "watermarkEnabled" in fields:
        watermark["enabled"] = bool(payload.watermarkEnabled)
    if "watermarkPosition" in fields:
        position = payload.watermarkPosition or "Top Right"
        if position not in WATERMARK_POSITIONS:
            raise HTTPException(status_code=400, detail="Invalid watermark position.")
        watermark["position"] = position
    if "watermarkOpacity" in fields and payload.watermarkOpacity is not None:
        watermark["opacity"] = round(float(payload.watermarkOpacity), 2)
    if "watermarkScale" in fields and payload.watermarkScale is not None:
        watermark["scale"] = round(float(payload.watermarkScale), 3)

    _update_title_card_from_payload(settings.setdefault("introCard", _default_title_card_settings()), "intro", payload, fields)
    _update_title_card_from_payload(settings.setdefault("outroCard", _default_title_card_settings()), "outro", payload, fields)

    if settings.get("useSelectedMasterAudio") and not settings.get("selectedAudioAssetId"):
        _apply_default_audio_asset(project, settings)

    now = utc_now_iso()
    settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], "Updated video editor settings.")
    return _state_response(project)


def create_branding_template(project_id: str, name: str) -> VideoEditorStateResponse:
    template_name = (name or "").strip()
    if not template_name:
        raise HTTPException(status_code=400, detail="Branding template name is required.")

    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    templates = settings.setdefault("brandingTemplates", [])
    if len(templates) >= MAX_BRANDING_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"You can save up to {MAX_BRANDING_TEMPLATES} branding templates per project.")

    now = utc_now_iso()
    template = {
        "id": uuid.uuid4().hex,
        "name": template_name[:80],
        "createdAt": now,
        "updatedAt": now,
        "overlay": deepcopy(settings.get("overlay", {})),
        "watermark": deepcopy(settings.get("watermark", _default_watermark_settings())),
        "introCard": deepcopy(settings.get("introCard", _default_title_card_settings())),
        "outroCard": deepcopy(settings.get("outroCard", _default_title_card_settings())),
    }
    templates.insert(0, template)
    settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Saved video branding template '{template['name']}'.")
    return _state_response(project)


def apply_branding_template(project_id: str, template_id: str) -> VideoEditorStateResponse:
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    template = _find_branding_template(settings, template_id)

    settings["overlay"] = deepcopy(template.get("overlay", {}))
    settings["watermark"] = deepcopy(template.get("watermark", _default_watermark_settings()))
    settings["introCard"] = deepcopy(template.get("introCard", _default_title_card_settings()))
    settings["outroCard"] = deepcopy(template.get("outroCard", _default_title_card_settings()))
    _ensure_video_editor_settings(project)

    now = utc_now_iso()
    settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Applied video branding template '{template.get('name', 'template')}'.")
    return _state_response(project)


def delete_branding_template(project_id: str, template_id: str) -> VideoEditorStateResponse:
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    templates = settings.setdefault("brandingTemplates", [])
    template = _find_branding_template(settings, template_id)
    settings["brandingTemplates"] = [item for item in templates if item.get("id") != template_id]
    now = utc_now_iso()
    settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Deleted video branding template '{template.get('name', 'template')}'.")
    return _state_response(project)


def run_video_auto_sync(project_id: str) -> VideoEditorStateResponse:
    ensure_audio_environment()
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    raw_video = _first_syncable_clip(settings)
    if not raw_video:
        raise HTTPException(status_code=400, detail="Upload a primary video with original audio before running auto-sync.")
    if not settings.get("selectedAudioAssetId"):
        _apply_default_audio_asset(project, settings)
    asset = _find_audio_asset(project, settings.get("selectedAudioAssetId"))

    try:
        video_audio = _decode_alignment_audio(resolve_stored_file_path(raw_video["filePath"]), stream_selector="0:a:0")
        master_audio = _decode_alignment_audio(resolve_stored_file_path(asset["filePath"]), stream_selector="0:a:0")
        offset_ms, confidence = _estimate_audio_offset_ms(video_audio, master_audio)
        message = f"Estimated master offset at {offset_ms:+d} ms with {confidence:.0%} confidence."
        settings["audioOffsetMs"] = offset_ms
        settings["autoSyncResult"] = {
            "status": "Completed",
            "offsetMs": offset_ms,
            "confidence": round(confidence, 3),
            "analyzedAt": utc_now_iso(),
            "message": message,
        }
    except Exception as exc:
        message = str(exc) or "Auto-sync could not estimate an offset."
        settings["autoSyncResult"] = {
            "status": "Failed",
            "offsetMs": None,
            "confidence": None,
            "analyzedAt": utc_now_iso(),
            "message": message,
        }
        store.save(data)
        raise HTTPException(status_code=400, detail=message) from exc

    now = utc_now_iso()
    settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Video auto-sync completed: {message}")
    return _state_response(project)


def get_video_waveforms(project_id: str) -> VideoWaveformStateResponse:
    ensure_audio_environment()
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)

    raw_track = None
    raw_video = _first_syncable_clip(settings)
    if raw_video and raw_video.get("hasAudioTrack"):
        raw_path = resolve_stored_file_path(raw_video.get("filePath", ""))
        if raw_path.exists():
            try:
                peaks, preview_duration = _cached_waveform_peaks(str(raw_path), "0:a:0", raw_path.stat().st_mtime_ns, raw_path.stat().st_size)
                raw_track = {
                    "label": f"{raw_video.get('originalFilename') or 'Primary video audio'} (primary sync reference)",
                    "peaks": peaks,
                    "previewDurationSeconds": preview_duration,
                }
            except Exception:
                raw_track = None

    selected_track = None
    if settings.get("selectedAudioAssetId"):
        try:
            audio_asset = _find_audio_asset(project, settings.get("selectedAudioAssetId"))
            audio_path = resolve_stored_file_path(audio_asset.get("filePath", ""))
            if audio_path.exists():
                peaks, preview_duration = _cached_waveform_peaks(str(audio_path), "0:a:0", audio_path.stat().st_mtime_ns, audio_path.stat().st_size)
                selected_track = {
                    "label": audio_asset.get("label") or "Selected audio",
                    "peaks": peaks,
                    "previewDurationSeconds": preview_duration,
                }
        except Exception:
            selected_track = None

    window_duration = max(
        float(raw_track.get("previewDurationSeconds") or 0) if raw_track else 0,
        float(selected_track.get("previewDurationSeconds") or 0) if selected_track else 0,
    ) or None
    return VideoWaveformStateResponse(
        offsetMs=int(settings.get("audioOffsetMs", 0) or 0),
        windowDurationSeconds=window_duration,
        rawVideo=raw_track,
        selectedAudio=selected_track,
    )


def create_video_render_job(project_id: str) -> ProcessingJob:
    return _create_video_job(project_id, VIDEO_JOB_TYPE, "Video export queued.")


def create_video_preview_job(project_id: str) -> ProcessingJob:
    return _create_video_job(project_id, VIDEO_PREVIEW_JOB_TYPE, "Edited preview queued.")


def _create_video_job(project_id: str, job_type: str, message: str) -> ProcessingJob:
    ensure_audio_environment()
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    _apply_default_audio_asset(project, settings)
    _validate_render_settings(project, settings)

    active_job = _find_active_video_job(project)
    if active_job:
        if active_job.get("type") == job_type:
            append_project_log(project_subdirs(project_id)["logs"], f"Reused active {job_type.lower()} job {active_job['id']}.")
            store.save(data)
            return ProcessingJob(**active_job)
        raise HTTPException(status_code=409, detail=f"{active_job.get('type', 'Video render')} is already running. Wait for it to finish first.")

    now = utc_now_iso()
    job = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "type": job_type,
        "status": "Pending",
        "progress": 0,
        "currentStemId": None,
        "message": message,
        "errors": [],
        "createdAt": now,
        "updatedAt": now,
        "completedAt": None,
    }
    project.setdefault("processingJobs", []).append(job)
    settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"{job_type} job {job['id']} queued.")
    return ProcessingJob(**job)


def get_video_render_job(project_id: str, job_id: str) -> ProcessingJob:
    data = store.load()
    project = _find_project(data, project_id)
    return ProcessingJob(**_find_job(project, job_id))


def delete_video_export(project_id: str, export_id: str) -> VideoEditorStateResponse:
    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    exports = settings.setdefault("finalExports", [])
    export_record = next((item for item in exports if item.get("id") == export_id), None)
    if export_record is None:
        raise HTTPException(status_code=404, detail="Video export was not found.")

    file_path = export_record.get("filePath")
    if file_path:
        resolved = resolve_stored_file_path(file_path)
        if resolved.exists():
            resolved.unlink()

    remaining_exports = [item for item in exports if item.get("id") != export_id]
    settings["finalExports"] = remaining_exports
    settings["finalExport"] = remaining_exports[0] if remaining_exports else None
    now = utc_now_iso()
    settings["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Deleted video export {export_record.get('label', export_id)}.")
    return _state_response(project)


def run_video_render_job(project_id: str, job_id: str) -> None:
    try:
        _run_video_job(project_id, job_id, preview_mode=False)
    except Exception as exc:
        error_message = _error_detail(exc) or "Video render failed."
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
        project["updatedAt"] = now
        store.save(data)
        append_project_log(project_subdirs(project_id)["logs"], f"{job.get('type', 'Video render')} job {job_id} failed: {error_message}")


def run_video_preview_job(project_id: str, job_id: str) -> None:
    try:
        _run_video_job(project_id, job_id, preview_mode=True)
    except Exception as exc:
        error_message = _error_detail(exc) or "Video preview failed."
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
        project["updatedAt"] = now
        store.save(data)
        append_project_log(project_subdirs(project_id)["logs"], f"{job.get('type', 'Video preview')} job {job_id} failed: {error_message}")


def _run_video_job(project_id: str, job_id: str, preview_mode: bool) -> None:
    mode_label = "preview" if preview_mode else "export"
    _update_job(project_id, job_id, status="Processing", progress=3, message=f"Preparing video {mode_label} assets.")
    data = store.load()
    project = _find_project(data, project_id)
    settings = dict(_ensure_video_editor_settings(project))
    _validate_render_settings(project, settings)

    raw_videos = _raw_video_clips(settings)
    video_paths = [resolve_stored_file_path(item["filePath"]) for item in raw_videos]
    audio_asset = _find_audio_asset(project, settings.get("selectedAudioAssetId")) if settings.get("useSelectedMasterAudio") else None
    audio_path = resolve_stored_file_path(audio_asset["filePath"]) if audio_asset else None
    output_dir = project_subdirs(project_id)["video"] / ("previews" if preview_mode else "exports")
    output_dir.mkdir(parents=True, exist_ok=True)
    export_preset = "Lightweight Preview" if preview_mode else settings.get("exportPreset") if settings.get("exportPreset") in EXPORT_PRESETS else "YouTube 1080p"
    if preview_mode:
        output_path = output_dir / "edited_preview.mp4"
        if output_path.exists():
            output_path.unlink()
        version_number = 1
    else:
        output_prefix = EXPORT_PRESETS[export_preset]["labelPrefix"]
        version_number = _next_export_number(output_dir, output_prefix)
        output_path = output_dir / f"{output_prefix}_v{version_number:03d}.mp4"

    _update_job(project_id, job_id, progress=10, message=f"Starting FFmpeg {mode_label} render.")
    render_settings = dict(settings)
    render_settings["exportPreset"] = export_preset
    _render_video(
        video_clips=raw_videos,
        video_paths=video_paths,
        audio_path=audio_path,
        output_path=output_path,
        settings=render_settings,
        progress_callback=lambda fraction, message: _update_job(
            project_id,
            job_id,
            progress=max(12, min(94, int(round(12 + fraction * 82)))),
            message=message,
        ),
    )

    _update_job(project_id, job_id, progress=96, message=f"Saving video {mode_label} metadata.")
    metadata = _probe_video(output_path)
    now = utc_now_iso()
    render_record = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "label": "Edited Preview" if preview_mode else f"{'Preview' if export_preset == 'Lightweight Preview' else 'Final Video'} v{version_number:03d}",
        "createdAt": now,
        "filePath": display_path(output_path),
        "fileUrl": _media_url(display_path(output_path)),
        "sizeBytes": output_path.stat().st_size if output_path.exists() else None,
        "durationSeconds": metadata.get("durationSeconds"),
        "width": metadata.get("width"),
        "height": metadata.get("height"),
        "fps": metadata.get("fps"),
        "sourceVideoFilename": raw_videos[0].get("originalFilename") if raw_videos else None,
        "secondaryVideoFilenames": [item.get("originalFilename") for item in raw_videos[1:] if item.get("originalFilename")],
        "sourceVideoFilenames": [item.get("originalFilename") for item in raw_videos if item.get("originalFilename")],
        "clipCount": len(raw_videos),
        "sourceAudioAssetId": audio_asset.get("id") if audio_asset else None,
        "sourceAudioAssetLabel": audio_asset.get("label") if audio_asset else None,
        "sourceAudioAssetKind": audio_asset.get("kind") if audio_asset else None,
        "exportPreset": export_preset,
        "settings": {
            "useSelectedMasterAudio": bool(render_settings.get("useSelectedMasterAudio")),
            "useOriginalVideoAudio": bool(render_settings.get("useOriginalVideoAudio")),
            "audioOffsetMs": int(render_settings.get("audioOffsetMs", 0) or 0),
            "trimStartSeconds": float(render_settings.get("trimStartSeconds", 0) or 0),
            "trimEndSeconds": float(render_settings.get("trimEndSeconds", 0) or 0),
            "fadeInSeconds": float(render_settings.get("fadeInSeconds", 0) or 0),
            "fadeOutSeconds": float(render_settings.get("fadeOutSeconds", 0) or 0),
            "exportPreset": export_preset,
            "assembly": render_settings.get("assembly", {}),
            "overlay": render_settings.get("overlay", {}),
            "watermark": _watermark_settings_for_record(render_settings.get("watermark", {})),
            "introCard": render_settings.get("introCard", {}),
            "outroCard": render_settings.get("outroCard", {}),
        },
        "warnings": [],
    }

    data = store.load()
    project = _find_project(data, project_id)
    settings = _ensure_video_editor_settings(project)
    if preview_mode:
        settings["previewRender"] = render_record
    else:
        settings.setdefault("finalExports", [])
        settings["finalExports"] = [render_record, *[item for item in settings.get("finalExports", []) if item.get("id") != render_record["id"]]]
        settings["finalExport"] = render_record
    settings["updatedAt"] = now
    project["updatedAt"] = now
    job = _find_job(project, job_id)
    job["status"] = "Completed"
    job["progress"] = 100
    job["message"] = f"{'Video preview' if preview_mode else 'Video export'} completed: {render_record['label']}."
    job["updatedAt"] = now
    job["completedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"{'Video preview' if preview_mode else 'Video export'} saved to {render_record['filePath']}.")


def _render_video(
    video_clips: list[dict[str, Any]],
    video_paths: list[Path],
    audio_path: Path | None,
    output_path: Path,
    settings: dict[str, Any],
    progress_callback,
) -> None:
    ffmpeg = _ffmpeg_exe()
    trim_start = max(0.0, float(settings.get("trimStartSeconds", 0) or 0))
    trim_end = max(0.0, float(settings.get("trimEndSeconds", 0) or 0))
    primary_video = video_clips[0] if video_clips else {}
    assembled_duration = _assembled_visual_duration(video_clips, settings)
    expected_duration = trim_end - trim_start if trim_end > trim_start else max(0.1, assembled_duration - trim_start)
    use_original_audio = bool(settings.get("useOriginalVideoAudio"))
    use_selected_audio = bool(settings.get("useSelectedMasterAudio")) and audio_path is not None
    export_preset_name = settings.get("exportPreset") if settings.get("exportPreset") in EXPORT_PRESETS else "YouTube 1080p"
    export_preset = EXPORT_PRESETS[export_preset_name]
    target_width, target_height = _target_dimensions(primary_video, export_preset)
    fps = _target_fps(primary_video)
    intro_card = settings.get("introCard") or {}
    outro_card = settings.get("outroCard") or {}
    intro_duration = _card_duration(intro_card)
    outro_duration = _card_duration(outro_card)
    watermark = settings.get("watermark") or {}
    logo_path = _watermark_logo_path(watermark)
    total_expected_duration = expected_duration + intro_duration + outro_duration
    fade_in_duration, fade_out_duration = _output_fade_durations(settings, total_expected_duration)

    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]
    for video_path in video_paths:
        command += ["-i", str(video_path)]
    selected_audio_index: int | None = None
    if use_selected_audio:
        selected_audio_index = len(video_paths)
        command += ["-i", str(audio_path)]
    logo_index: int | None = None
    if logo_path is not None:
        logo_index = len(video_paths) + (1 if use_selected_audio else 0)
        command += ["-i", str(logo_path)]

    filter_parts: list[str] = []
    main_video_label = _build_main_video_filters(filter_parts, video_clips, settings, target_width, target_height, fps, logo_index, watermark)
    output_video_label = _build_title_card_filters(filter_parts, main_video_label, intro_card, outro_card, intro_duration, outro_duration, target_width, target_height, fps)
    output_audio_label = _build_audio_filters(
        filter_parts,
        settings=settings,
        video_clips=video_clips,
        selected_audio_index=selected_audio_index,
        use_selected_audio=use_selected_audio,
        use_original_audio=use_original_audio,
        expected_duration=expected_duration,
        intro_duration=intro_duration,
        outro_duration=outro_duration,
    )
    output_video_label = _apply_video_fades(filter_parts, output_video_label, fade_in_duration, fade_out_duration, total_expected_duration)
    output_audio_label = _apply_audio_fades(filter_parts, output_audio_label, fade_in_duration, fade_out_duration, total_expected_duration)
    command += ["-filter_complex", ";".join(filter_parts), "-map", output_video_label]
    if output_audio_label:
        command += ["-map", output_audio_label]
    else:
        command += ["-an"]

    command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(export_preset["crf"]), "-pix_fmt", "yuv420p"]
    if use_selected_audio or use_original_audio:
        command += ["-c:a", "aac", "-b:a", export_preset["audioBitrate"], "-shortest"]
    command += ["-movflags", "+faststart", str(output_path)]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg_with_progress(command, total_expected_duration, progress_callback)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg did not create a final MP4.")


def _build_main_video_filters(
    filter_parts: list[str],
    video_clips: list[dict[str, Any]],
    settings: dict[str, Any],
    target_width: int,
    target_height: int,
    fps: float,
    logo_index: int | None,
    watermark: dict[str, Any],
) -> str:
    for index, _clip in enumerate(video_clips):
        base_filter = _base_video_filter(target_width, target_height, fps)
        filter_parts.append(f"[{index}:v:0]{base_filter}[vclip{index}]")

    current_label = _assemble_video_sequence(filter_parts, video_clips, settings)
    trim_start = max(0.0, float(settings.get("trimStartSeconds", 0) or 0))
    trim_end = max(0.0, float(settings.get("trimEndSeconds", 0) or 0))
    if trim_start > 0 or trim_end > trim_start:
        trim_parts = [f"start={trim_start:.3f}"]
        if trim_end > trim_start:
            trim_parts.append(f"end={trim_end:.3f}")
        filter_parts.append(f"[{current_label}]trim={':'.join(trim_parts)},setpts=PTS-STARTPTS[vtrim]")
        current_label = "vtrim"

    overlay_filter = _overlay_text_filters(settings.get("overlay", {}), target_width, target_height)
    if overlay_filter:
        filter_parts.append(f"[{current_label}]{overlay_filter}[vtext]")
        current_label = "vtext"
    if logo_index is not None:
        logo_height = max(24, int(target_height * float(watermark.get("scale", 0.14) or 0.14)))
        opacity = max(0.05, min(1.0, float(watermark.get("opacity", 0.82) or 0.82)))
        x_expr, y_expr = _corner_position_expr(watermark.get("position", "Top Right"), margin=48)
        filter_parts.append(f"[{logo_index}:v:0]scale=-1:{logo_height},format=rgba,colorchannelmixer=aa={opacity:.2f}[vlogo]")
        filter_parts.append(f"[{current_label}][vlogo]overlay={x_expr}:{y_expr}[vwm]")
        current_label = "vwm"
    filter_parts.append(f"[{current_label}]format=yuv420p,setpts=PTS-STARTPTS[vmain]")
    return "vmain"


def _build_title_card_filters(
    filter_parts: list[str],
    main_video_label: str,
    intro_card: dict[str, Any],
    outro_card: dict[str, Any],
    intro_duration: float,
    outro_duration: float,
    target_width: int,
    target_height: int,
    fps: float,
) -> str:
    video_parts: list[str] = []
    if intro_duration > 0:
        filter_parts.append(_title_card_filter("intro", intro_card, intro_duration, target_width, target_height, fps))
        video_parts.append("[vintro]")
    video_parts.append(f"[{main_video_label}]")
    if outro_duration > 0:
        filter_parts.append(_title_card_filter("outro", outro_card, outro_duration, target_width, target_height, fps))
        video_parts.append("[voutro]")
    if len(video_parts) == 1:
        return f"[{main_video_label}]"
    filter_parts.append(f"{''.join(video_parts)}concat=n={len(video_parts)}:v=1:a=0[vout]")
    return "[vout]"


def _build_audio_filters(
    filter_parts: list[str],
    settings: dict[str, Any],
    video_clips: list[dict[str, Any]],
    selected_audio_index: int | None,
    use_selected_audio: bool,
    use_original_audio: bool,
    expected_duration: float,
    intro_duration: float,
    outro_duration: float,
) -> str | None:
    if not use_selected_audio and not use_original_audio:
        return None

    original_audio_label: str | None = None
    if use_original_audio:
        trim_start = max(0.0, float(settings.get("trimStartSeconds", 0) or 0))
        trim_end = max(0.0, float(settings.get("trimEndSeconds", 0) or 0))
        trim_parts = [f"start={trim_start:.3f}"]
        if trim_end > trim_start:
            trim_parts.append(f"end={trim_end:.3f}")
        filter_parts.append(f"[0:a:0]aformat=sample_rates=44100:channel_layouts=stereo,atrim={':'.join(trim_parts)},asetpts=PTS-STARTPTS[aorigtrim]")
        original_audio_label = "aorigtrim"

    selected_audio_label: str | None = None
    if use_selected_audio and selected_audio_index is not None:
        audio_filter = _selected_audio_filter(int(settings.get("audioOffsetMs", 0) or 0), pad=True)
        filter_parts.append(
            f"[{selected_audio_index}:a:0]{audio_filter},aformat=sample_rates=44100:channel_layouts=stereo,atrim=duration={expected_duration:.3f},asetpts=PTS-STARTPTS[amastertrim]"
        )
        selected_audio_label = "amastertrim"

    if selected_audio_label and original_audio_label:
        filter_parts.append(f"[{original_audio_label}]volume=0.35[aorig]")
        filter_parts.append(f"[{selected_audio_label}]volume=1.0[amaster]")
        filter_parts.append(f"[aorig][amaster]amix=inputs=2:duration=longest:normalize=0,atrim=duration={expected_duration:.3f},asetpts=PTS-STARTPTS[amain]")
    elif selected_audio_label:
        filter_parts.append(f"[{selected_audio_label}]anull[amain]")
    elif original_audio_label:
        filter_parts.append(f"[{original_audio_label}]atrim=duration={expected_duration:.3f},asetpts=PTS-STARTPTS[amain]")
    else:
        return None

    audio_parts: list[str] = []
    if intro_duration > 0:
        filter_parts.append(f"anullsrc=channel_layout=stereo:sample_rate=44100:d={intro_duration:.3f}[aintro]")
        audio_parts.append("[aintro]")
    audio_parts.append("[amain]")
    if outro_duration > 0:
        filter_parts.append(f"anullsrc=channel_layout=stereo:sample_rate=44100:d={outro_duration:.3f}[aoutro]")
        audio_parts.append("[aoutro]")
    if len(audio_parts) == 1:
        return "[amain]"
    filter_parts.append(f"{''.join(audio_parts)}concat=n={len(audio_parts)}:v=0:a=1[aout]")
    return "[aout]"


def _assemble_video_sequence(filter_parts: list[str], video_clips: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    if not video_clips:
        raise RuntimeError("No primary video is available for assembly.")
    if len(video_clips) == 1:
        return "vclip0"

    primary_clip = video_clips[0]
    secondary_clips = video_clips[1:]
    if not secondary_clips:
        return "vclip0"

    transition_style = (settings.get("assembly", {}) or {}).get("transitionStyle", "Crossfade")
    transition_duration = _effective_transition_duration(video_clips, settings)
    plan = _focused_insert_plan(primary_clip, secondary_clips, settings)
    if not plan:
        return "vclip0"

    current_label = "vclip0"
    for plan_index, insert in enumerate(plan):
        input_index = int(insert["inputIndex"])
        insert_start = float(insert["start"])
        insert_duration = float(insert["duration"])
        fade_window = min(transition_duration, max(0.0, insert_duration / 2 - 0.05))
        source_start = float(insert.get("sourceStart", 0.0) or 0.0)
        secondary_parts = [f"[vclip{input_index}]trim=start={source_start:.3f}:duration={insert_duration:.3f}"]
        if transition_style == "Crossfade" and fade_window > 0:
            secondary_parts.extend(
                [
                    "format=rgba",
                    f"fade=t=in:st=0:d={fade_window:.3f}:alpha=1",
                    f"fade=t=out:st={max(0.0, insert_duration - fade_window):.3f}:d={fade_window:.3f}:alpha=1",
                ]
            )
        elif transition_style == "Dip to Black" and fade_window > 0:
            secondary_parts.extend(
                [
                    f"fade=t=in:st=0:d={fade_window:.3f}",
                    f"fade=t=out:st={max(0.0, insert_duration - fade_window):.3f}:d={fade_window:.3f}",
                ]
            )
        secondary_parts.append(f"setpts=PTS-STARTPTS+{insert_start:.3f}/TB")
        secondary_label = f"vfoc{plan_index}"
        filter_parts.append(f"{','.join(secondary_parts)}[{secondary_label}]")
        next_label = f"vins{plan_index}"
        filter_parts.append(
            f"[{current_label}][{secondary_label}]overlay=0:0:enable='between(t,{insert_start:.3f},{insert_start + insert_duration:.3f})':eof_action=pass[{next_label}]"
        )
        current_label = next_label
    return current_label


def _assemble_original_audio_sequence(filter_parts: list[str], video_clips: list[dict[str, Any]], settings: dict[str, Any]) -> str | None:
    clip_labels: list[str] = []
    clip_durations = [max(0.1, float(item.get("durationSeconds") or 0.1)) for item in video_clips]
    for index, clip in enumerate(video_clips):
        label = f"aoclip{index}"
        if clip.get("hasAudioTrack"):
            filter_parts.append(f"[{index}:a:0]aformat=sample_rates=44100:channel_layouts=stereo[{label}]")
        else:
            filter_parts.append(f"anullsrc=channel_layout=stereo:sample_rate=44100:d={clip_durations[index]:.3f}[{label}]")
        clip_labels.append(label)

    if not clip_labels:
        return None
    if len(clip_labels) == 1:
        return clip_labels[0]

    transition_style = (settings.get("assembly", {}) or {}).get("transitionStyle", "Crossfade")
    transition_duration = _effective_transition_duration(video_clips, settings)
    if transition_style == "Cut" or transition_duration <= 0:
        inputs = "".join(f"[{label}]" for label in clip_labels)
        filter_parts.append(f"{inputs}concat=n={len(clip_labels)}:v=0:a=1[aoseq]")
        return "aoseq"

    current_label = clip_labels[0]
    for index in range(1, len(clip_labels)):
        next_label = f"aoxf{index}"
        filter_parts.append(f"[{current_label}][{clip_labels[index]}]acrossfade=d={transition_duration:.3f}:c1=tri:c2=tri[{next_label}]")
        current_label = next_label
    return current_label


def _apply_video_fades(filter_parts: list[str], current_label: str, fade_in_duration: float, fade_out_duration: float, total_duration: float) -> str:
    label_name = current_label[1:-1]
    if fade_in_duration > 0:
        filter_parts.append(f"[{label_name}]fade=t=in:st=0:d={fade_in_duration:.3f}[vfadin]")
        label_name = "vfadin"
    if fade_out_duration > 0:
        fade_start = max(0.0, total_duration - fade_out_duration)
        filter_parts.append(f"[{label_name}]fade=t=out:st={fade_start:.3f}:d={fade_out_duration:.3f}[vfadout]")
        label_name = "vfadout"
    return f"[{label_name}]"


def _apply_audio_fades(filter_parts: list[str], current_label: str | None, fade_in_duration: float, fade_out_duration: float, total_duration: float) -> str | None:
    if not current_label:
        return None
    label_name = current_label[1:-1]
    if fade_in_duration > 0:
        filter_parts.append(f"[{label_name}]afade=t=in:st=0:d={fade_in_duration:.3f}[afadin]")
        label_name = "afadin"
    if fade_out_duration > 0:
        fade_start = max(0.0, total_duration - fade_out_duration)
        filter_parts.append(f"[{label_name}]afade=t=out:st={fade_start:.3f}:d={fade_out_duration:.3f}[afadout]")
        label_name = "afadout"
    return f"[{label_name}]"


def _output_fade_durations(settings: dict[str, Any], total_duration: float) -> tuple[float, float]:
    fade_in = max(0.0, min(8.0, float(settings.get("fadeInSeconds", 0) or 0)))
    fade_out = max(0.0, min(8.0, float(settings.get("fadeOutSeconds", 0) or 0)))
    if total_duration <= 0.1:
        return 0.0, 0.0
    if fade_in + fade_out > max(0.1, total_duration - 0.1):
        scale = max(0.1, total_duration - 0.1) / max(0.1, fade_in + fade_out)
        fade_in *= scale
        fade_out *= scale
    return round(fade_in, 3), round(fade_out, 3)


def _base_video_filter(target_width: int, target_height: int, fps: float) -> str:
    return (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps:.3f},setsar=1"
    )


def _overlay_text_filters(overlay: dict[str, Any], target_width: int, target_height: int) -> str:
    title = _clean_optional(overlay.get("songTitle"))
    artist = _clean_optional(overlay.get("artistName"))
    session = _clean_optional(overlay.get("sessionLabel"))
    text_lines = [line for line in (title, artist, session) if line]
    if not text_lines:
        return ""

    position = overlay.get("position", "Lower Left")
    style = overlay.get("style", "Boxed")
    size_name = overlay.get("size", "Medium")
    title_size, sub_size, line_gap = {
        "Small": (26, 18, 30),
        "Large": (42, 28, 46),
    }.get(size_name, (34, 22, 38))
    margin = 48
    block_height = title_size + max(0, len(text_lines) - 1) * line_gap
    if "Top" in position:
        first_y = margin
    else:
        first_y = f"h-{margin + block_height}"
    filters = []
    for index, text in enumerate(text_lines[:3]):
        size = title_size if index == 0 else sub_size
        line_y = f"{first_y}+{index * line_gap}" if isinstance(first_y, int) else f"{first_y}+{index * line_gap}"
        x_expr = str(margin) if "Left" in position else f"w-tw-{margin}"
        options = _drawtext_style(style)
        filters.append(f"drawtext=text='{_escape_drawtext(text)}':x={x_expr}:y={line_y}:fontsize={size}:{options}")
    return ",".join(filters)


def _drawtext_style(style: str) -> str:
    if style == "Clean":
        return "fontcolor=white:shadowcolor=black@0.65:shadowx=2:shadowy=2"
    if style == "Shadow":
        return "fontcolor=white:shadowcolor=black@0.85:shadowx=3:shadowy=3"
    return "fontcolor=white:box=1:boxcolor=black@0.48:boxborderw=14"


def _title_card_filter(label: str, card: dict[str, Any], duration: float, target_width: int, target_height: int, fps: float) -> str:
    title = _clean_optional(card.get("title")) or ("Live Session" if label == "intro" else "Thanks for watching")
    subtitle = _clean_optional(card.get("subtitle"))
    filters = [
        f"color=c=0x071019:s={target_width}x{target_height}:r={fps:.3f}:d={duration:.3f}",
        "format=yuv420p",
        f"drawtext=text='{_escape_drawtext(title)}':x=(w-tw)/2:y=(h-th)/2-34:fontsize={max(32, int(target_height * 0.045))}:fontcolor=white",
    ]
    if subtitle:
        filters.append(f"drawtext=text='{_escape_drawtext(subtitle)}':x=(w-tw)/2:y=(h-th)/2+32:fontsize={max(20, int(target_height * 0.026))}:fontcolor=0xBFEFF4")
    return f"{','.join(filters)}[v{label}]"


def _target_dimensions(raw_video: dict[str, Any], preset: dict[str, Any]) -> tuple[int, int]:
    if preset.get("width") and preset.get("height"):
        return int(preset["width"]), int(preset["height"])
    width = int(raw_video.get("width") or 1920)
    height = int(raw_video.get("height") or 1080)
    return max(2, width - width % 2), max(2, height - height % 2)


def _target_fps(raw_video: dict[str, Any]) -> float:
    fps = float(raw_video.get("fps") or 30)
    return max(1.0, min(60.0, fps))


def _card_duration(card: dict[str, Any]) -> float:
    if not card.get("enabled"):
        return 0.0
    return max(0.5, min(10.0, float(card.get("durationSeconds", 2.5) or 2.5)))


def _corner_position_expr(position: str, margin: int) -> tuple[str, str]:
    x_expr = str(margin) if "Left" in position else f"W-w-{margin}"
    y_expr = str(margin) if "Top" in position else f"H-h-{margin}"
    return x_expr, y_expr


def _watermark_logo_path(watermark: dict[str, Any]) -> Path | None:
    if not watermark.get("enabled") or not watermark.get("logo"):
        return None
    logo_path = resolve_stored_file_path(watermark["logo"].get("filePath", ""))
    return logo_path if logo_path.exists() else None


def _watermark_settings_for_record(watermark: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(watermark.get("enabled")),
        "logoFilePath": watermark.get("logo", {}).get("filePath") if isinstance(watermark.get("logo"), dict) else None,
        "position": watermark.get("position", "Top Right"),
        "opacity": watermark.get("opacity", 0.82),
        "scale": watermark.get("scale", 0.14),
    }


def _run_ffmpeg_with_progress(command: list[str], expected_duration: float, progress_callback) -> None:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    stderr_lines: list[str] = []
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if line.startswith("out_time_ms="):
            try:
                seconds = int(line.partition("=")[2]) / 1_000_000
                fraction = seconds / expected_duration if expected_duration > 0 else 0
                progress_callback(max(0.0, min(0.98, fraction)), "Rendering final MP4.")
            except ValueError:
                pass
        elif line == "progress=end":
            progress_callback(0.99, "Finalizing MP4.")

    _, stderr = process.communicate()
    if stderr:
        stderr_lines.append(stderr.strip())
    if process.returncode != 0:
        detail = "\n".join(item for item in stderr_lines if item).strip()
        raise RuntimeError(detail or "FFmpeg video export failed.")


def _probe_video(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError("Video file was not saved.")
    ffmpeg = _ffmpeg_exe()
    completed = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=30)
    output = f"{completed.stderr}\n{completed.stdout}"
    video_line = next((line for line in output.splitlines() if " Video:" in line), "")
    if not video_line:
        raise ValueError("Could not find a video stream in this file.")

    duration = _parse_duration(output)
    width, height = _parse_resolution(video_line)
    fps = _parse_fps(video_line)
    return {
        "durationSeconds": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "hasAudioTrack": " Audio:" in output,
    }


def _decode_alignment_audio(path: Path, stream_selector: str) -> np.ndarray:
    ffmpeg = _ffmpeg_exe()
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        stream_selector,
        "-t",
        str(AUDIO_ALIGN_MAX_SECONDS),
        "-ac",
        "1",
        "-ar",
        str(AUDIO_ALIGN_SAMPLE_RATE),
        "-f",
        "s16le",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, timeout=60)
    if completed.returncode != 0:
        raise ValueError((completed.stderr or b"").decode("utf-8", errors="replace").strip() or "Could not decode audio for auto-sync.")
    if not completed.stdout:
        raise ValueError("Decoded audio for auto-sync is empty.")
    audio = np.frombuffer(completed.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size < AUDIO_ALIGN_SAMPLE_RATE:
        raise ValueError("Auto-sync needs at least one second of usable audio.")
    audio = audio - float(np.mean(audio))
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 0.003:
        raise ValueError("Auto-sync could not find enough audible signal.")
    return audio / peak


@lru_cache(maxsize=96)
def _cached_waveform_peaks(path_str: str, stream_selector: str, modified_ns: int, size_bytes: int) -> tuple[list[float], float]:
    del modified_ns, size_bytes
    audio = _decode_alignment_audio(Path(path_str), stream_selector=stream_selector)
    preview_duration = round(audio.size / AUDIO_ALIGN_SAMPLE_RATE, 3)
    return _audio_to_peaks(audio, buckets=WAVEFORM_PEAK_BUCKETS), preview_duration


def _audio_to_peaks(audio: np.ndarray, buckets: int = WAVEFORM_PEAK_BUCKETS) -> list[float]:
    if audio.size == 0:
        return []
    step = max(1, int(np.ceil(audio.size / buckets)))
    peaks: list[float] = []
    for start in range(0, audio.size, step):
        window = audio[start : start + step]
        peaks.append(round(float(np.max(np.abs(window))), 4) if window.size else 0.0)
        if len(peaks) >= buckets:
            break
    if len(peaks) < buckets:
        peaks.extend([0.0] * (buckets - len(peaks)))
    return peaks


def _estimate_audio_offset_ms(video_audio: np.ndarray, master_audio: np.ndarray) -> tuple[int, float]:
    length = min(video_audio.size, master_audio.size)
    if length < AUDIO_ALIGN_SAMPLE_RATE:
        raise ValueError("Auto-sync needs more overlapping audio.")
    video_audio = video_audio[:length]
    master_audio = master_audio[:length]
    max_lag = min(AUDIO_ALIGN_SAMPLE_RATE * 8, length // 2)
    corr = signal.correlate(video_audio, master_audio, mode="full", method="fft")
    center = master_audio.size - 1
    window = corr[center - max_lag : center + max_lag + 1]
    if window.size == 0:
        raise ValueError("Auto-sync correlation failed.")
    best_index = int(np.argmax(np.abs(window)))
    lag_samples = best_index - max_lag
    energy = float(np.linalg.norm(video_audio) * np.linalg.norm(master_audio))
    confidence = min(1.0, abs(float(window[best_index])) / energy) if energy > 0 else 0.0
    offset_ms = int(round(lag_samples / AUDIO_ALIGN_SAMPLE_RATE * 1000))
    return offset_ms, confidence


def _raw_video_clips(settings: dict[str, Any]) -> list[dict[str, Any]]:
    clips = [item for item in settings.get("rawVideos", []) if isinstance(item, dict) and item.get("filePath")]
    if clips:
        primary = [item for item in clips if _clip_role(item) == "Primary"]
        secondary = [item for item in clips if _clip_role(item) == "Secondary"]
        return [*primary[:1], *secondary]
    raw_video = settings.get("rawVideo")
    return [raw_video] if isinstance(raw_video, dict) and raw_video.get("filePath") else []


def _sync_primary_raw_video(settings: dict[str, Any]) -> None:
    raw_video_value = settings.get("rawVideo")
    preferred_primary_id = raw_video_value.get("id") if isinstance(raw_video_value, dict) else None
    clips = [item for item in settings.get("rawVideos", []) if isinstance(item, dict) and item.get("filePath")]
    if not clips and isinstance(raw_video_value, dict) and raw_video_value.get("filePath"):
        migrated = dict(raw_video_value)
        migrated["role"] = "Primary"
        clips = [migrated]

    normalized: list[dict[str, Any]] = []
    primary: dict[str, Any] | None = None
    for clip in clips:
        clip["role"] = _clip_role(clip)
        if clip["role"] == "Primary":
            if primary is None:
                primary = clip
            else:
                clip["role"] = "Secondary"
                normalized.append(clip)
        else:
            normalized.append(clip)

    if primary is None and preferred_primary_id:
        primary = next((item for item in normalized if item.get("id") == preferred_primary_id), None)
        if primary is not None:
            normalized = [item for item in normalized if item.get("id") != preferred_primary_id]
            primary["role"] = "Primary"
    if primary is None and isinstance(raw_video_value, dict) and raw_video_value.get("filePath") and not settings.get("_skip_auto_primary"):
        primary = next((item for item in normalized if item.get("filePath") == raw_video_value.get("filePath")), None)
        if primary is not None:
            normalized = [item for item in normalized if item.get("id") != primary.get("id")]
            primary["role"] = "Primary"
    if primary is None and not raw_video_value and len(normalized) == 1 and not settings.get("_skip_auto_primary"):
        primary = normalized.pop(0)
        primary["role"] = "Primary"

    settings["rawVideos"] = [primary, *normalized] if primary else normalized
    settings["rawVideo"] = primary if primary else None
    settings.pop("_skip_auto_primary", None)


def _reorder_raw_videos(clips: list[dict[str, Any]], clip_order_ids: list[str]) -> list[dict[str, Any]]:
    ordered_ids = [clip_id for clip_id in clip_order_ids if clip_id]
    if not clips:
        return []
    clip_map = {item.get("id"): item for item in clips if item.get("id")}
    missing_ids = [clip_id for clip_id in ordered_ids if clip_id not in clip_map]
    if missing_ids:
        raise HTTPException(status_code=400, detail="Clip reorder request included an unknown raw video clip.")
    ordered = [clip_map[clip_id] for clip_id in ordered_ids if clip_id in clip_map]
    for clip in clips:
        if clip.get("id") not in ordered_ids:
            ordered.append(clip)
    primary = next((item for item in ordered if _clip_role(item) == "Primary"), None)
    secondary = [item for item in ordered if _clip_role(item) != "Primary"]
    return [primary, *secondary] if primary else secondary


def _first_syncable_clip(settings: dict[str, Any]) -> dict[str, Any] | None:
    primary = _primary_raw_video(settings)
    return primary if primary and primary.get("hasAudioTrack") else None


def _clip_role(clip: dict[str, Any] | None) -> str:
    if not isinstance(clip, dict):
        return "Secondary"
    return "Primary" if str(clip.get("role") or "").strip().lower() == "primary" else "Secondary"


def _resolve_clip_upload_role(settings: dict[str, Any], requested_role: str) -> str:
    normalized = str(requested_role or "auto").strip().lower()
    if normalized not in {"auto", "primary", "secondary"}:
        raise HTTPException(status_code=400, detail="Invalid raw video role. Use primary or secondary.")
    if normalized == "auto":
        return "Primary" if _primary_raw_video(settings) is None else "Secondary"
    return "Primary" if normalized == "primary" else "Secondary"


def _primary_raw_video(settings: dict[str, Any]) -> dict[str, Any] | None:
    return next((item for item in _raw_video_clips(settings) if _clip_role(item) == "Primary"), None)


def _secondary_raw_videos(settings: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _raw_video_clips(settings) if _clip_role(item) == "Secondary"]


def _effective_transition_duration(video_clips: list[dict[str, Any]], settings: dict[str, Any]) -> float:
    if len(video_clips) <= 1:
        return 0.0
    assembly = settings.get("assembly", {}) or {}
    style = assembly.get("transitionStyle", "Crossfade")
    if style == "Cut":
        return 0.0
    requested = max(0.0, min(2.0, float(assembly.get("transitionDurationSeconds", 0.45) or 0.45)))
    durations = [max(0.1, float(item.get("durationSeconds") or 0.1)) for item in video_clips[1:]] or [max(0.1, float(video_clips[0].get("durationSeconds") or 0.1))]
    max_transition = min(max(0.0, duration - 0.05) for duration in durations)
    return round(min(requested, max_transition), 3)


def _assembled_visual_duration(video_clips: list[dict[str, Any]], settings: dict[str, Any]) -> float:
    if not video_clips:
        return 0.0
    return max(0.1, round(float(video_clips[0].get("durationSeconds") or 0.1), 3))


def _focused_insert_plan(primary_clip: dict[str, Any], secondary_clips: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, float | int]]:
    manual = _manual_focused_insert_plan(primary_clip, secondary_clips, settings)
    if manual:
        return manual
    return _automatic_focused_insert_plan(primary_clip, secondary_clips, settings)


def _automatic_focused_insert_plan(primary_clip: dict[str, Any], secondary_clips: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, float | int]]:
    primary_duration = max(0.1, float(primary_clip.get("durationSeconds") or 0.1))
    if not secondary_clips:
        return []
    if _uses_full_song_focus_mode(primary_clip, secondary_clips):
        return _automatic_full_song_focus_plan(primary_clip, secondary_clips)

    requested_durations = [max(0.5, float(item.get("durationSeconds") or 0.5)) for item in secondary_clips]
    transition_duration = _effective_transition_duration([primary_clip, *secondary_clips], settings)
    min_gap = max(1.0, transition_duration * 1.5)
    max_insert_total = min(primary_duration * 0.6, max(0.0, primary_duration - min_gap * (len(secondary_clips) + 1)))
    if max_insert_total <= 0:
        return []

    requested_total = sum(requested_durations)
    scale = min(1.0, max_insert_total / requested_total) if requested_total > 0 else 0.0
    inserts: list[tuple[int, float]] = []
    for index, duration in enumerate(requested_durations):
        scaled_duration = round(duration * scale, 3)
        if scaled_duration >= 0.25:
            inserts.append((index, scaled_duration))
    if not inserts:
        return []

    insert_durations = [duration for _index, duration in inserts]
    remaining_time = max(0.0, primary_duration - sum(insert_durations))
    gap = remaining_time / (len(insert_durations) + 1)
    cursor = gap
    plan: list[dict[str, float | int]] = []
    for original_index, duration in inserts:
        plan.append({"inputIndex": original_index + 1, "start": round(cursor, 3), "duration": duration, "sourceStart": 0.0})
        cursor += duration + gap
    return plan


def _uses_full_song_focus_mode(primary_clip: dict[str, Any], secondary_clips: list[dict[str, Any]]) -> bool:
    primary_duration = max(0.1, float(primary_clip.get("durationSeconds") or 0.1))
    return any(float(clip.get("durationSeconds") or 0.0) >= primary_duration * 0.75 for clip in secondary_clips)


def _automatic_full_song_focus_plan(primary_clip: dict[str, Any], secondary_clips: list[dict[str, Any]]) -> list[dict[str, float | int]]:
    primary_duration = max(0.1, float(primary_clip.get("durationSeconds") or 0.1))
    if primary_duration < 8:
        return []
    segment_count = max(3, int(primary_duration // 35))
    segment_count = min(12, max(segment_count, len(secondary_clips) * 2))
    cut_duration = min(10.0, max(5.0, primary_duration / 24.0))
    gap = primary_duration / (segment_count + 1)
    plan: list[dict[str, float | int]] = []
    for index in range(segment_count):
        clip_index = index % len(secondary_clips)
        clip = secondary_clips[clip_index]
        clip_duration = max(0.25, float(clip.get("durationSeconds") or cut_duration))
        duration = min(cut_duration, clip_duration, primary_duration)
        center = gap * (index + 1)
        start = max(0.0, min(primary_duration - duration, center - duration / 2))
        source_start = max(0.0, min(max(0.0, clip_duration - duration), start))
        plan.append(
            {
                "inputIndex": clip_index + 1,
                "start": round(start, 3),
                "duration": round(duration, 3),
                "sourceStart": round(source_start, 3),
            }
        )
    return plan


def _manual_focused_insert_plan(primary_clip: dict[str, Any], secondary_clips: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, float | int]]:
    assembly = settings.get("assembly", {}) or {}
    placements = assembly.get("focusPlacements") or []
    if not placements:
        return []

    primary_duration = max(0.1, float(primary_clip.get("durationSeconds") or 0.1))
    automatic_plan = _automatic_focused_insert_plan(primary_clip, secondary_clips, settings)
    clip_index_by_id = {str(clip.get("id")): index + 1 for index, clip in enumerate(secondary_clips) if clip.get("id")}
    clip_by_id = {str(clip.get("id")): clip for clip in secondary_clips if clip.get("id")}
    plan: list[dict[str, float | int]] = []
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        clip_id = str(placement.get("clipId") or "")
        clip = clip_by_id.get(clip_id)
        input_index = clip_index_by_id.get(clip_id)
        if not clip or input_index is None:
            continue
        raw_duration = placement.get("durationSeconds") if isinstance(placement, dict) else None
        clip_duration = max(0.25, min(primary_duration, float(clip.get("durationSeconds") or 0.25)))
        duration = max(0.25, min(clip_duration, float(raw_duration or clip_duration)))
        max_start = max(0.0, primary_duration - duration)
        start = max(0.0, min(float(placement.get("startSeconds") or 0.0), max_start))
        max_source_start = max(0.0, float(clip.get("durationSeconds") or duration) - duration)
        raw_source_start = placement.get("sourceStartSeconds")
        source_start = max(0.0, min(float(raw_source_start if raw_source_start is not None else start), max_source_start))
        plan.append({"inputIndex": input_index, "start": round(start, 3), "duration": round(duration, 3), "sourceStart": round(source_start, 3)})
    return sorted(plan, key=lambda item: (float(item["start"]), int(item["inputIndex"])))


def _normalize_focus_placements(settings: dict[str, Any], placements: list[Any]) -> list[dict[str, Any]]:
    primary_clip = _primary_raw_video(settings)
    secondary_clips = _secondary_raw_videos(settings)
    if not primary_clip or not secondary_clips or not placements:
        return []

    primary_duration = max(0.1, float(primary_clip.get("durationSeconds") or 0.1))
    clip_by_id = {str(clip.get("id")): clip for clip in secondary_clips if clip.get("id")}
    normalized: list[dict[str, Any]] = []
    for index, placement in enumerate(placements[:64]):
        clip_id = str(getattr(placement, "clipId", None) or (placement.get("clipId") if isinstance(placement, dict) else "") or "")
        if not clip_id or clip_id not in clip_by_id:
            continue
        clip = clip_by_id[clip_id]
        placement_id = str(getattr(placement, "id", None) or (placement.get("id") if isinstance(placement, dict) else "") or f"focus-cut-{uuid.uuid4().hex}")
        start_seconds = getattr(placement, "startSeconds", None)
        if start_seconds is None and isinstance(placement, dict):
            start_seconds = placement.get("startSeconds")
        duration_seconds = getattr(placement, "durationSeconds", None)
        if duration_seconds is None and isinstance(placement, dict):
            duration_seconds = placement.get("durationSeconds")
        clip_duration = max(0.25, min(primary_duration, float(clip.get("durationSeconds") or 0.25)))
        duration = max(0.25, min(clip_duration, float(duration_seconds or clip_duration)))
        max_start = max(0.0, primary_duration - duration)
        start = max(0.0, min(float(start_seconds or 0.0), max_start))
        source_start_seconds = getattr(placement, "sourceStartSeconds", None)
        if source_start_seconds is None and isinstance(placement, dict):
            source_start_seconds = placement.get("sourceStartSeconds")
        max_source_start = max(0.0, float(clip.get("durationSeconds") or duration) - duration)
        source_start = max(0.0, min(float(source_start_seconds if source_start_seconds is not None else start), max_source_start))
        normalized.append(
            {
                "id": placement_id[:80] or f"focus-cut-{index + 1}",
                "clipId": clip_id,
                "startSeconds": round(start, 3),
                "durationSeconds": round(duration, 3),
                "sourceStartSeconds": round(source_start, 3),
            }
        )
    return normalized


def _validate_render_settings(project: dict[str, Any], settings: dict[str, Any]) -> None:
    raw_videos = _raw_video_clips(settings)
    primary_video = _primary_raw_video(settings)
    if not primary_video:
        raise HTTPException(status_code=400, detail="Upload a primary whole-band video before exporting.")
    for clip in raw_videos:
        video_path = resolve_stored_file_path(clip.get("filePath", ""))
        if not video_path.exists():
            raise HTTPException(status_code=404, detail=f"Raw video clip '{clip.get('originalFilename') or 'video'}' is missing from local storage.")
    if settings.get("trimEndSeconds", 0) > 0 and settings.get("trimEndSeconds", 0) <= settings.get("trimStartSeconds", 0):
        raise HTTPException(status_code=400, detail="Trim end must be greater than trim start.")
    if _assembled_visual_duration(raw_videos, settings) <= float(settings.get("trimStartSeconds", 0) or 0):
        raise HTTPException(status_code=400, detail="Trim start must stay within the primary video timeline.")
    if settings.get("exportPreset", "YouTube 1080p") not in EXPORT_PRESETS:
        raise HTTPException(status_code=400, detail="Invalid video export preset.")
    assembly = settings.get("assembly", {}) or {}
    if assembly.get("transitionStyle", "Crossfade") not in TRANSITION_STYLES:
        raise HTTPException(status_code=400, detail="Invalid transition style.")
    if not settings.get("useSelectedMasterAudio") and not settings.get("useOriginalVideoAudio"):
        raise HTTPException(status_code=400, detail="Choose selected master audio, original video audio, or both before exporting.")
    if settings.get("useOriginalVideoAudio") and not primary_video.get("hasAudioTrack"):
        raise HTTPException(status_code=400, detail="The primary video does not include an original audio track.")
    if settings.get("useSelectedMasterAudio"):
        if not settings.get("selectedAudioAssetId"):
            _apply_default_audio_asset(project, settings)
        asset = _find_audio_asset(project, settings.get("selectedAudioAssetId"))
        audio_path = resolve_stored_file_path(asset["filePath"])
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Selected mastered audio file is missing from local storage.")


def _state_response(project: dict[str, Any]) -> VideoEditorStateResponse:
    settings = _ensure_video_editor_settings(project)
    assets = _audio_assets(project)
    return VideoEditorStateResponse(settings=settings, availableAudioAssets=assets)


def _audio_assets(project: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for master in project.get("masteringSettings", {}).get("masterVersions", []):
        assets.append(
            {
                "id": master.get("id"),
                "kind": "Master",
                "label": master.get("label") or "Master",
                "filePath": master.get("filePath"),
                "fileUrl": master.get("fileUrl"),
                "createdAt": master.get("createdAt"),
                "durationSeconds": master.get("report", {}).get("durationSeconds") if isinstance(master.get("report"), dict) else None,
                "outputFormat": master.get("outputFormat"),
            }
        )
    for export_file in project.get("masteringSettings", {}).get("exportFiles", []):
        path = export_file.get("filePath") or ""
        if Path(path).suffix.lower() not in {".wav", ".mp3", ".flac", ".aiff", ".aif"}:
            continue
        assets.append(
            {
                "id": export_file.get("id"),
                "kind": export_file.get("type") or "Export",
                "label": export_file.get("label") or export_file.get("type") or "Audio Export",
                "filePath": export_file.get("filePath"),
                "fileUrl": export_file.get("fileUrl"),
                "createdAt": export_file.get("createdAt"),
                "durationSeconds": None,
                "outputFormat": export_file.get("outputFormat"),
            }
        )
    return [asset for asset in assets if asset.get("id") and asset.get("filePath") and asset.get("fileUrl")]


def _apply_default_audio_asset(project: dict[str, Any], settings: dict[str, Any]) -> bool:
    if settings.get("selectedAudioAssetId") and any(asset["id"] == settings.get("selectedAudioAssetId") for asset in _audio_assets(project)):
        return False
    assets = _audio_assets(project)
    if not assets:
        return False
    latest_master_id = project.get("masteringSettings", {}).get("latestMasterVersionId")
    default_asset = next((asset for asset in assets if asset["id"] == latest_master_id), None) or assets[-1]
    settings["selectedAudioAssetId"] = default_asset["id"]
    settings["selectedAudioAssetKind"] = default_asset["kind"]
    settings["selectedAudioAssetPath"] = default_asset["filePath"]
    return True


def _find_audio_asset(project: dict[str, Any], asset_id: str | None) -> dict[str, Any]:
    asset = next((item for item in _audio_assets(project) if item["id"] == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail="Selected audio asset was not found. Generate a master first or choose another audio export.")
    return asset


def _ensure_video_editor_settings(project: dict[str, Any]) -> dict[str, Any]:
    project.setdefault("videoEditorSettings", {})
    settings = project["videoEditorSettings"]
    settings.setdefault("rawVideo", None)
    settings.setdefault("rawVideos", [])
    if not settings.get("rawVideos") and settings.get("rawVideo"):
        settings["rawVideos"] = [settings["rawVideo"]]
    _sync_primary_raw_video(settings)
    settings.setdefault("selectedAudioAssetId", None)
    settings.setdefault("selectedAudioAssetKind", None)
    settings.setdefault("selectedAudioAssetPath", None)
    settings.setdefault("useSelectedMasterAudio", True)
    settings.setdefault("useOriginalVideoAudio", False)
    settings.setdefault("audioOffsetMs", 0)
    settings.setdefault("trimStartSeconds", 0)
    settings.setdefault("trimEndSeconds", 0)
    settings.setdefault("fadeInSeconds", 0)
    settings.setdefault("fadeOutSeconds", 0)
    settings.setdefault("exportPreset", "YouTube 1080p")
    settings.setdefault("assembly", _default_assembly_settings())
    settings["assembly"].setdefault("transitionStyle", "Crossfade")
    settings["assembly"].setdefault("transitionDurationSeconds", 0.45)
    _sync_focus_placements(settings)
    settings.setdefault("overlay", {})
    settings["overlay"].setdefault("songTitle", None)
    settings["overlay"].setdefault("artistName", None)
    settings["overlay"].setdefault("sessionLabel", None)
    settings["overlay"].setdefault("position", "Lower Left")
    settings["overlay"].setdefault("style", "Boxed")
    settings["overlay"].setdefault("size", "Medium")
    settings.setdefault("watermark", _default_watermark_settings())
    settings["watermark"].setdefault("enabled", False)
    settings["watermark"].setdefault("logo", None)
    settings["watermark"].setdefault("position", "Top Right")
    settings["watermark"].setdefault("opacity", 0.82)
    settings["watermark"].setdefault("scale", 0.14)
    settings.setdefault("introCard", _default_title_card_settings())
    settings["introCard"].setdefault("enabled", False)
    settings["introCard"].setdefault("durationSeconds", 2.5)
    settings["introCard"].setdefault("title", None)
    settings["introCard"].setdefault("subtitle", None)
    settings.setdefault("outroCard", _default_title_card_settings())
    settings["outroCard"].setdefault("enabled", False)
    settings["outroCard"].setdefault("durationSeconds", 2.5)
    settings["outroCard"].setdefault("title", None)
    settings["outroCard"].setdefault("subtitle", None)
    settings.setdefault("autoSyncResult", _default_auto_sync_result())
    settings["autoSyncResult"].setdefault("status", "Not Run")
    settings["autoSyncResult"].setdefault("offsetMs", None)
    settings["autoSyncResult"].setdefault("confidence", None)
    settings["autoSyncResult"].setdefault("analyzedAt", None)
    settings["autoSyncResult"].setdefault("message", None)
    settings.setdefault("brandingTemplates", [])
    settings.setdefault("previewRender", None)
    settings.setdefault("finalExport", None)
    settings.setdefault("finalExports", [])
    if settings.get("finalExport") and not any(item.get("id") == settings["finalExport"].get("id") for item in settings.get("finalExports", [])):
        settings["finalExports"] = [settings["finalExport"], *settings.get("finalExports", [])]
    if settings.get("finalExports") and not settings.get("finalExport"):
        settings["finalExport"] = settings["finalExports"][0]
    settings.setdefault("updatedAt", None)
    return settings


def _update_title_card_from_payload(card: dict[str, Any], prefix: str, payload: UpdateVideoEditorSettingsRequest, fields: set[str]) -> None:
    enabled_field = f"{prefix}Enabled"
    duration_field = f"{prefix}DurationSeconds"
    title_field = f"{prefix}Title"
    subtitle_field = f"{prefix}Subtitle"
    if enabled_field in fields:
        card["enabled"] = bool(getattr(payload, enabled_field))
    if duration_field in fields:
        value = getattr(payload, duration_field)
        if value is not None:
            card["durationSeconds"] = round(float(value), 2)
    if title_field in fields:
        card["title"] = _clean_optional(getattr(payload, title_field))
    if subtitle_field in fields:
        card["subtitle"] = _clean_optional(getattr(payload, subtitle_field))


def _default_watermark_settings() -> dict[str, Any]:
    return {
        "enabled": False,
        "logo": None,
        "position": "Top Right",
        "opacity": 0.82,
        "scale": 0.14,
    }


def _default_title_card_settings() -> dict[str, Any]:
    return {
        "enabled": False,
        "durationSeconds": 2.5,
        "title": None,
        "subtitle": None,
    }


def _default_auto_sync_result() -> dict[str, Any]:
    return {
        "status": "Not Run",
        "offsetMs": None,
        "confidence": None,
        "analyzedAt": None,
        "message": None,
    }


def _default_assembly_settings() -> dict[str, Any]:
    return {
        "transitionStyle": "Crossfade",
        "transitionDurationSeconds": 0.45,
        "focusPlacements": [],
    }


def _sync_focus_placements(settings: dict[str, Any]) -> None:
    assembly = settings.setdefault("assembly", _default_assembly_settings())
    assembly["focusPlacements"] = _normalize_focus_placements(settings, assembly.get("focusPlacements", []))


def _find_branding_template(settings: dict[str, Any], template_id: str) -> dict[str, Any]:
    template = next((item for item in settings.get("brandingTemplates", []) if item.get("id") == template_id), None)
    if template is None:
        raise HTTPException(status_code=404, detail="Branding template was not found.")
    return template


def _find_job(project: dict[str, Any], job_id: str) -> dict[str, Any]:
    job = next((item for item in project.get("processingJobs", []) if item.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Video render job not found.")
    return job


def _find_active_video_job(project: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            job
            for job in reversed(project.get("processingJobs", []))
            if job.get("type") in {VIDEO_JOB_TYPE, VIDEO_PREVIEW_JOB_TYPE} and job.get("status") in ACTIVE_JOB_STATUSES
        ),
        None,
    )


def _update_job(project_id: str, job_id: str, **updates: Any) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    job = _find_job(project, job_id)
    job.update(updates)
    job["updatedAt"] = utc_now_iso()
    store.save(data)


async def _write_upload_file(upload: UploadFile, destination: Path, max_bytes: int = MAX_VIDEO_UPLOAD_BYTES, label: str = "Video") -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = 0
    try:
        with destination.open("xb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise ValueError(f"{label} exceeds the {max_bytes // (1024 * 1024)} MB upload limit.")
                output.write(chunk)
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    if bytes_written == 0:
        if destination.exists():
            destination.unlink()
        raise ValueError("Video file is empty.")
    return bytes_written


def _delete_previous_raw_video(raw_video: dict[str, Any] | None) -> None:
    if not raw_video:
        return
    path_value = raw_video.get("filePath")
    if not path_value:
        return
    path = resolve_stored_file_path(path_value)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _unique_video_filename(original_filename: str, destination_dir: Path) -> str:
    extension = Path(original_filename).suffix.lower()
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_filename).stem.strip() or "raw_video")[:80].strip("._-") or "raw_video"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for _ in range(10):
        candidate = f"{base}_{timestamp}_{uuid.uuid4().hex[:10]}{extension}"
        if not (destination_dir / candidate).exists():
            return candidate
    return f"{base}_{timestamp}_{uuid.uuid4().hex}{extension}"


def _next_export_number(output_dir: Path, prefix: str = "final_video") -> int:
    number = 1
    while (output_dir / f"{prefix}_v{number:03d}.mp4").exists():
        number += 1
    return number


def _video_filter(overlay: dict[str, Any]) -> str:
    filters = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    title = _clean_optional(overlay.get("songTitle"))
    artist = _clean_optional(overlay.get("artistName"))
    session = _clean_optional(overlay.get("sessionLabel"))
    text_lines = [line for line in (title, artist, session) if line]
    if not text_lines:
        return ",".join(filters)
    y_positions = ["h-150", "h-104", "h-66"]
    for index, text in enumerate(text_lines[:3]):
        size = 32 if index == 0 else 22
        y = y_positions[index]
        filters.append(f"drawtext=text='{_escape_drawtext(text)}':x=48:y={y}:fontcolor=white:fontsize={size}:box=1:boxcolor=black@0.45:boxborderw=14")
    return ",".join(filters)


def _selected_audio_filter(offset_ms: int, pad: bool = True) -> str:
    filters: list[str] = []
    if offset_ms > 0:
        filters.append(f"adelay={offset_ms}:all=1")
    elif offset_ms < 0:
        filters.append(f"atrim=start={abs(offset_ms) / 1000:.3f}")
        filters.append("asetpts=PTS-STARTPTS")
    if pad:
        filters.append("apad")
    return ",".join(filters) if filters else "anull"


def _parse_duration(output: str) -> float | None:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)


def _parse_resolution(video_line: str) -> tuple[int | None, int | None]:
    match = re.search(r"(?<![A-Za-z])(\d{2,5})x(\d{2,5})(?![A-Za-z])", video_line)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _parse_fps(video_line: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*fps", video_line)
    return round(float(match.group(1)), 3) if match else None


def _seconds_arg(value: float) -> str:
    return f"{max(0.0, float(value)):.3f}"


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _escape_drawtext(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def _media_url(path_value: str | None) -> str | None:
    if path_value is None:
        return None
    normalized = path_value.replace("\\", "/")
    if normalized.startswith("storage/"):
        normalized = normalized[len("storage/") :]
    return f"/media/{normalized}"


def _ffmpeg_exe() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("ffmpeg is not available. Install imageio-ffmpeg or add ffmpeg to PATH.") from exc


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc)
