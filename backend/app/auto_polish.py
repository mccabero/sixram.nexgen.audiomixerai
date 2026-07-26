"""Auto Polish: one-button pipeline that chains the whole workflow with
recommended settings — analysis, per-stem cleaning, vocal recommendations and
enhancement, advanced mix render, and mastering — under a single processing
job with unified progress. Every stage reuses the existing per-phase engines,
so Auto Polish produces exactly what a careful manual pass through the
workflow would."""

import threading
import uuid
from typing import Any

from fastapi import HTTPException

from .audio_engine import ensure_audio_environment
from .cleaning import create_cleaning_job, run_cleaning_job, update_stem_cleaning_settings
from .logging_utils import append_project_log, utc_now_iso
from .models import GenerateMasterRequest, ProcessingJob, UpdateCleaningSettingsRequest
from .phase2 import create_analysis_job, run_analysis_job
from .phase5 import generate_advanced_mix_preview
from .phase6 import MASTERING_PRESETS, generate_master, _ensure_mastering_controls
from .storage import (
    JobCancelled,
    mark_processing_job_cancelled,
    project_subdirs,
    raise_if_processing_job_cancelled,
    store,
    _find_project,
)
from .vocal_enhancer import (
    analyze_project_vocals,
    apply_all_vocal_recommendations,
    create_vocal_enhancement_job,
    run_vocal_enhancement_job,
    _vocal_candidate_stems,
)

ACTIVE_JOB_STATUSES = {"Pending", "Processing", "Cancelling"}
RUNNING_AUTO_POLISH_JOB_IDS: set[str] = set()
RUNNING_AUTO_POLISH_JOB_LOCK = threading.Lock()

VOCAL_STEM_TYPES = {"Lead Vocal", "Backing Vocal"}


def create_auto_polish_job(project_id: str) -> ProcessingJob:
    try:
        ensure_audio_environment()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    data = store.load()
    project = _find_project(data, project_id)
    if not project.get("stems"):
        raise HTTPException(status_code=400, detail="Upload stems before running Auto Polish.")

    active_job = next(
        (job for job in reversed(project.get("processingJobs", [])) if job.get("type") == "Auto Polish" and job.get("status") in ACTIVE_JOB_STATUSES),
        None,
    )
    if active_job:
        append_project_log(project_subdirs(project_id)["logs"], f"Reused active Auto Polish job {active_job['id']}.")
        return ProcessingJob(**active_job)

    now = utc_now_iso()
    job = {
        "id": uuid.uuid4().hex,
        "projectId": project_id,
        "type": "Auto Polish",
        "status": "Pending",
        "progress": 0,
        "currentStemId": None,
        "message": "Auto Polish queued.",
        "errors": [],
        "createdAt": now,
        "updatedAt": now,
        "completedAt": None,
    }
    project.setdefault("processingJobs", []).append(job)
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Auto Polish job {job['id']} queued.")
    return ProcessingJob(**job)


def run_auto_polish_job(project_id: str, job_id: str) -> None:
    with RUNNING_AUTO_POLISH_JOB_LOCK:
        if job_id in RUNNING_AUTO_POLISH_JOB_IDS:
            append_project_log(project_subdirs(project_id)["logs"], f"Ignored duplicate Auto Polish runner for job {job_id}.")
            return
        RUNNING_AUTO_POLISH_JOB_IDS.add(job_id)
    try:
        _run_auto_polish_job(project_id, job_id)
    except JobCancelled:
        mark_processing_job_cancelled(project_id, job_id)
    finally:
        with RUNNING_AUTO_POLISH_JOB_LOCK:
            RUNNING_AUTO_POLISH_JOB_IDS.discard(job_id)


def _recommended_cleaning_mode(stem: dict[str, Any]) -> str:
    """Pick a cleaning strength from the stem's analysis. Conservative for
    instruments (their '10th percentile level' is usually content, not noise);
    vocals default to Medium because breaths/noise are what cleaning is for."""
    stem_type = stem.get("stemType", "Unknown")
    analysis = stem.get("analysisResult") or {}
    noise_floor = analysis.get("noiseFloorDbfs")
    is_vocal = stem_type in VOCAL_STEM_TYPES
    if is_vocal:
        if isinstance(noise_floor, (int, float)):
            if noise_floor > -48.0:
                return "Strong"
            if noise_floor < -65.0:
                return "Light"
        return "Medium"
    if stem_type in {"Drums", "Kick", "Snare", "Keys/Piano", "Pads/Strings", "FX/Ambience"}:
        return "Light"
    if isinstance(noise_floor, (int, float)) and noise_floor > -38.0:
        return "Medium"
    return "Light"


def _update_job(project_id: str, job_id: str, **updates: Any) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    job = next((item for item in project.get("processingJobs", []) if item.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    if job.get("status") in {"Cancelling", "Cancelled"}:
        raise JobCancelled(job.get("message") or "Auto Polish was stopped by the user.")
    job.update(updates)
    job["updatedAt"] = utc_now_iso()
    store.save(data)


def _finish_job(project_id: str, job_id: str, status: str, message: str, errors: list[dict[str, Any]] | None = None) -> None:
    now = utc_now_iso()
    data = store.load()
    project = _find_project(data, project_id)
    job = next((item for item in project.get("processingJobs", []) if item.get("id") == job_id), None)
    if job is None:
        return
    job["status"] = status
    job["progress"] = 100
    job["currentStemId"] = None
    job["message"] = message
    if errors:
        job["errors"] = errors
    job["updatedAt"] = now
    job["completedAt"] = now
    store.save(data)


def _scaled(fraction: float, start: int, end: int) -> int:
    safe = max(0.0, min(1.0, float(fraction)))
    return max(start, min(end, int(round(start + safe * (end - start)))))


def _run_auto_polish_job(project_id: str, job_id: str) -> None:
    stage_notes: list[str] = []
    soft_errors: list[dict[str, Any]] = []
    try:
        # Stage 1 (0-10%): make sure every stem has analysis metrics.
        _update_job(project_id, job_id, status="Processing", progress=2, message="Auto Polish: checking stem analysis.")
        data = store.load()
        project = _find_project(data, project_id)
        stems = project.get("stems", [])
        needs_analysis = any(stem.get("analysisStatus") != "Completed" for stem in stems)
        if needs_analysis:
            _update_job(project_id, job_id, progress=4, message="Auto Polish: analyzing stems.")
            try:
                analysis_job = create_analysis_job(project_id)
                run_analysis_job(project_id, analysis_job.id)
                stage_notes.append("analyzed stems")
            except Exception as exc:
                soft_errors.append({"stemId": None, "filename": None, "error": f"Stem analysis skipped: {str(exc) or 'failed'}"})
        raise_if_processing_job_cancelled(project_id, job_id)

        # Stage 2 (10-35%): recommended cleaning per stem, then run cleaning.
        _update_job(project_id, job_id, progress=10, message="Auto Polish: applying recommended cleaning per stem.")
        data = store.load()
        project = _find_project(data, project_id)
        cleaned_count = 0
        for stem in project.get("stems", []):
            mode = _recommended_cleaning_mode(stem)
            try:
                update_stem_cleaning_settings(
                    project_id,
                    stem["id"],
                    UpdateCleaningSettingsRequest(enabled=True, mode=mode, useCleanedInMix=True),
                )
                cleaned_count += 1
            except Exception as exc:
                soft_errors.append({"stemId": stem.get("id"), "filename": stem.get("originalFilename"), "error": f"Cleaning settings failed: {str(exc) or 'failed'}"})
        if cleaned_count:
            _update_job(project_id, job_id, progress=14, message=f"Auto Polish: cleaning {cleaned_count} stems.")
            try:
                cleaning_job = create_cleaning_job(project_id)
                run_cleaning_job(project_id, cleaning_job.id)
                stage_notes.append(f"cleaned {cleaned_count} stems")
            except Exception as exc:
                soft_errors.append({"stemId": None, "filename": None, "error": f"Cleaning pass failed: {str(exc) or 'failed'}"})
        raise_if_processing_job_cancelled(project_id, job_id)

        # Stage 3 (35-60%): vocal recommendations, apply all, render enhanced vocals.
        data = store.load()
        project = _find_project(data, project_id)
        vocal_stems = _vocal_candidate_stems(project)
        if vocal_stems:
            _update_job(project_id, job_id, progress=36, message=f"Auto Polish: analyzing {len(vocal_stems)} vocal stems.")
            try:
                analyze_project_vocals(project_id)
                apply_all_vocal_recommendations(project_id)
                _update_job(project_id, job_id, progress=44, message="Auto Polish: rendering enhanced vocals.")
                vocal_job = create_vocal_enhancement_job(project_id)
                run_vocal_enhancement_job(project_id, vocal_job.id)
                stage_notes.append(f"enhanced {len(vocal_stems)} vocal stems")
            except HTTPException as exc:
                soft_errors.append({"stemId": None, "filename": None, "error": f"Vocal pass skipped: {exc.detail}"})
            except Exception as exc:
                soft_errors.append({"stemId": None, "filename": None, "error": f"Vocal pass failed: {str(exc) or 'failed'}"})
        raise_if_processing_job_cancelled(project_id, job_id)

        # Stage 4 (60-80%): advanced mix with the project's current preset/controls.
        _update_job(project_id, job_id, progress=60, message="Auto Polish: rendering the mix.")
        mix_version = generate_advanced_mix_preview(
            project_id,
            progress_callback=lambda fraction, message: _update_job(
                project_id, job_id, progress=_scaled(fraction, 60, 79), message=f"Auto Polish mix: {message}"
            ),
        )
        stage_notes.append(f"mixed {mix_version.label or f'v{mix_version.versionNumber:03d}'}")
        raise_if_processing_job_cancelled(project_id, job_id)

        # Stage 5 (80-98%): master with current mastering controls + reference.
        _update_job(project_id, job_id, progress=80, message="Auto Polish: mastering.")
        data = store.load()
        project = _find_project(data, project_id)
        controls = _ensure_mastering_controls(project)
        preset = controls.get("preset") if controls.get("preset") in MASTERING_PRESETS else "Streaming"
        master_payload = GenerateMasterRequest(
            selectedMixVersionId=mix_version.id,
            preset=preset,
            outputFormat=controls.get("outputFormat") or "WAV 16-bit",
            brightness=float(controls.get("brightness", 0) or 0),
            warmth=float(controls.get("warmth", 0) or 0),
            compressionAmount=float(controls.get("compressionAmount", 45) or 45),
            limiterStrength=float(controls.get("limiterStrength", 55) or 55),
            stereoWidth=float(controls.get("stereoWidth", 55) or 55),
            useReference=True,
            referenceMatchAmount=float(controls.get("referenceMatchAmount", 70) or 70),
            matchReferenceLoudness=bool(controls.get("matchReferenceLoudness", False)),
        )
        master = generate_master(
            project_id,
            master_payload,
            progress_callback=lambda fraction, message: _update_job(
                project_id, job_id, progress=_scaled(fraction, 80, 98), message=f"Auto Polish master: {message}"
            ),
        )
        stage_notes.append(f"mastered {master.label}")

        summary = "Auto Polish complete: " + ", ".join(stage_notes) + "."
        if soft_errors:
            summary += f" {len(soft_errors)} step(s) were skipped."
        _finish_job(project_id, job_id, "Completed", summary, soft_errors)
        append_project_log(project_subdirs(project_id)["logs"], f"Auto Polish job {job_id} completed. {summary}")
    except JobCancelled:
        raise
    except Exception as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else (str(exc) or "Auto Polish failed.")
        soft_errors.append({"stemId": None, "filename": None, "error": str(detail)})
        _finish_job(project_id, job_id, "Failed", f"Auto Polish failed: {detail}", soft_errors)
        append_project_log(project_subdirs(project_id)["logs"], f"Auto Polish job {job_id} failed: {detail}")
