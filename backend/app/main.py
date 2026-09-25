from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .audio_engine import check_audio_environment
from .config import MAX_UPLOAD_MB, STEM_TYPES, STORAGE_ROOT
from .models import (
    AudioInputDeviceListResponse,
    CreateProjectRequest,
    CreateVideoBrandingTemplateRequest,
    CreateVocalPresetRequest,
    DirectRecordingStatus,
    AttachLyricsRequest,
    ChordSheet,
    ChordSheetJob,
    CreateChordSheetRequest,
    ExportChordSheetRequest,
    ExportFile,
    UpdateSheetChordRequest,
    UpdateSheetViewRequest,
    ExportMixRequest,
    GenerateMasterRequest,
    ImportMasteringReferenceUrlRequest,
    MasterVersion,
    MixVersion,
    ProcessingJob,
    Project,
    ProjectBackupRequest,
    ProjectListItem,
    RoughMixResponse,
    StartDirectRecordingRequest,
    Stem,
    StopDirectRecordingResponse,
    UpdateCleaningSettingsRequest,
    UpdateMixControlsRequest,
    UpdateMixStemRequest,
    UpdateMixVersionRequest,
    UpdateMasteringControlsRequest,
    UpdateVocalEnhancementSettingsRequest,
    UpdateVideoEditorSettingsRequest,
    UpdateProjectRequest,
    UpdateStemRequest,
    UploadResponse,
    VideoEditorStateResponse,
    VideoWaveformStateResponse,
    validate_stem_type,
)
from .cleaning import create_cleaning_job, create_stem_cleaning_job, run_cleaning_job, update_stem_cleaning_settings
from .vocal_enhancer import (
    analyze_project_vocals,
    apply_all_vocal_recommendations,
    apply_vocal_doctor_fix,
    apply_vocal_recommendation,
    create_vocal_enhancement_job,
    create_stem_vocal_enhancement_job,
    create_custom_vocal_preset,
    delete_custom_vocal_preset,
    get_vocal_enhancer_presets,
    list_custom_vocal_presets,
    run_vocal_quality_doctor,
    run_vocal_enhancement_job,
    update_vocal_enhancement_settings,
)
from .phase2 import (
    apply_auto_balance,
    create_analysis_job,
    generate_auto_balance,
    generate_rough_mix_preview,
    get_processing_job,
    run_analysis_job,
    update_mix_stem,
)
from .phase5 import (
    create_advanced_mix_job,
    delete_mix_version,
    generate_advanced_mix_preview,
    get_mix_presets,
    reset_advanced_mix,
    reset_stem_processing,
    run_advanced_mix_job,
    update_mix_controls,
    update_mix_version,
)
from .auto_polish import create_auto_polish_job, run_auto_polish_job
from .phase6 import (
    create_mastering_job,
    create_project_backup,
    export_instrumental,
    export_mix_without_mastering,
    generate_master,
    get_mastering_presets,
    import_mastering_reference_from_url,
    remove_mastering_reference,
    run_mastering_job,
    update_mastering_controls,
    upload_mastering_reference,
)
from .stem_detection import (
    accept_all_confident_detections,
    accept_stem_detection,
    clear_detection_memory,
    detect_project_stems,
    get_detection_memory_summary,
    learn_stem_type_correction,
)
from .storage import abandon_processing_job, create_project, delete_project, delete_stem, get_project, list_projects, mark_interrupted_jobs, read_project_logs, request_processing_job_cancel, save_uploaded_stems, update_project, update_stem_type
from .recording import recording_manager
from .video_editor import (
    apply_branding_template,
    create_branding_template,
    cancel_video_render_job,
    delete_raw_video,
    delete_branding_template,
    delete_video_export,
    get_video_editor_state,
    get_video_render_job,
    get_video_waveforms,
    queue_video_preview_job,
    queue_video_render_job,
    run_video_auto_sync,
    run_video_preview_job,
    run_video_render_job,
    save_uploaded_raw_video,
    save_uploaded_watermark_logo,
    update_video_editor_settings,
)
from .workflow_reset import (
    delete_analysis_results,
    delete_auto_balance,
    delete_cleaned_stem,
    delete_cleaned_stems,
    delete_exports,
    delete_masters,
    delete_mix_versions,
    delete_rough_mix,
    delete_stem_detections,
    delete_vocal_enhancement,
    delete_vocal_enhancements,
)


from .models import CreateSplitRequest, ExportSplitMixRequest, Split, SplitJob
from .stem_splitter import (
    active_split_summary,
    archive_split_stems,
    create_split,
    delete_split,
    export_split_mix,
    get_split,
    get_split_job,
    list_splits,
    mark_interrupted_splits,
    request_split_cancel,
    retry_split,
    run_split,
    separation_environment,
)
from .chord_sheet import (
    active_chord_sheet_summary,
    attach_lyrics,
    clear_lyrics,
    chord_sheet_environment,
    create_chord_sheet,
    delete_chord_sheet,
    export_chord_sheet,
    get_analysis,
    get_chord_sheet,
    get_chord_sheet_job,
    list_chord_sheets,
    mark_interrupted_sheets,
    request_sheet_cancel,
    retry_chord_sheet,
    run_chord_sheet,
    update_sheet_chord,
    update_sheet_view,
)


app = FastAPI(title="Local Stem Mixer AI", version="0.1.0")
AUDIO_ENVIRONMENT: dict = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=STORAGE_ROOT), name="media")


@app.on_event("startup")
def startup_checks() -> None:
    global AUDIO_ENVIRONMENT
    AUDIO_ENVIRONMENT = check_audio_environment()
    mark_interrupted_jobs()
    mark_interrupted_splits()
    mark_interrupted_sheets()


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "Local Stem Mixer AI", "status": "running", "docs": "/docs"}


@app.get("/api/health")
def health() -> dict:
    checks = AUDIO_ENVIRONMENT or check_audio_environment()
    return {
        "status": "ok" if checks.get("ok") else "degraded",
        "maxUploadMb": MAX_UPLOAD_MB,
        "audioEnvironment": checks,
    }


@app.get("/api/stem-types")
def get_stem_types() -> dict[str, list[str]]:
    return {"stemTypes": STEM_TYPES}


@app.get("/api/mix-presets")
def api_get_mix_presets() -> dict[str, list[dict]]:
    return get_mix_presets()


@app.get("/api/mastering-presets")
def api_get_mastering_presets() -> dict[str, list[dict] | float]:
    return get_mastering_presets()


@app.get("/api/detection-memory")
def api_get_detection_memory_summary() -> dict[str, int]:
    return get_detection_memory_summary()


@app.delete("/api/detection-memory")
def api_clear_detection_memory() -> dict[str, int | str]:
    return clear_detection_memory()


@app.get("/api/projects", response_model=list[ProjectListItem])
def api_list_projects() -> list[ProjectListItem]:
    return list_projects()


@app.get("/api/audio-input-devices", response_model=AudioInputDeviceListResponse)
def api_list_audio_input_devices() -> AudioInputDeviceListResponse:
    return AudioInputDeviceListResponse(devices=recording_manager.list_devices())


@app.post("/api/projects", response_model=Project)
def api_create_project(payload: CreateProjectRequest) -> Project:
    return create_project(payload)


@app.get("/api/projects/{project_id}", response_model=Project)
def api_get_project(project_id: str) -> Project:
    return get_project(project_id)


@app.get("/api/projects/{project_id}/logs")
def api_get_project_logs(project_id: str, limit: int = 200) -> dict[str, list[dict[str, str]]]:
    return read_project_logs(project_id, limit=limit)


@app.patch("/api/projects/{project_id}", response_model=Project)
def api_update_project(project_id: str, payload: UpdateProjectRequest) -> Project:
    return update_project(project_id, payload)


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str) -> dict[str, str]:
    return delete_project(project_id)


@app.post("/api/projects/{project_id}/stems", response_model=UploadResponse)
async def api_upload_stems(project_id: str, files: list[UploadFile] = File(...)) -> UploadResponse:
    uploaded, errors = await save_uploaded_stems(project_id, files)
    return UploadResponse(uploaded=uploaded, errors=errors)


@app.get("/api/projects/{project_id}/direct-recording", response_model=DirectRecordingStatus)
def api_get_direct_recording_status(project_id: str) -> DirectRecordingStatus:
    return recording_manager.get_status(project_id)


@app.post("/api/projects/{project_id}/direct-recording/start", response_model=DirectRecordingStatus)
def api_start_direct_recording(project_id: str, payload: StartDirectRecordingRequest) -> DirectRecordingStatus:
    return recording_manager.start(project_id, payload)


@app.post("/api/projects/{project_id}/direct-recording/stop", response_model=StopDirectRecordingResponse)
def api_stop_direct_recording(project_id: str) -> StopDirectRecordingResponse:
    return recording_manager.stop(project_id)


@app.get("/api/projects/{project_id}/video-editor", response_model=VideoEditorStateResponse)
def api_get_video_editor_state(project_id: str) -> VideoEditorStateResponse:
    return get_video_editor_state(project_id)


@app.post("/api/projects/{project_id}/video-editor/raw-video", response_model=VideoEditorStateResponse)
async def api_upload_raw_video(project_id: str, role: str = "auto", file: UploadFile = File(...)) -> VideoEditorStateResponse:
    return await save_uploaded_raw_video(project_id, file, role=role)


@app.delete("/api/projects/{project_id}/video-editor/raw-videos/{clip_id}", response_model=VideoEditorStateResponse)
def api_delete_raw_video(project_id: str, clip_id: str) -> VideoEditorStateResponse:
    return delete_raw_video(project_id, clip_id)


@app.post("/api/projects/{project_id}/video-editor/watermark-logo", response_model=VideoEditorStateResponse)
async def api_upload_video_watermark_logo(project_id: str, file: UploadFile = File(...)) -> VideoEditorStateResponse:
    return await save_uploaded_watermark_logo(project_id, file)


@app.patch("/api/projects/{project_id}/video-editor/settings", response_model=VideoEditorStateResponse)
def api_update_video_editor_settings(project_id: str, payload: UpdateVideoEditorSettingsRequest) -> VideoEditorStateResponse:
    return update_video_editor_settings(project_id, payload)


@app.get("/api/projects/{project_id}/video-editor/waveforms", response_model=VideoWaveformStateResponse)
def api_get_video_waveforms(project_id: str) -> VideoWaveformStateResponse:
    return get_video_waveforms(project_id)


@app.post("/api/projects/{project_id}/video-editor/templates", response_model=VideoEditorStateResponse)
def api_create_video_branding_template(project_id: str, payload: CreateVideoBrandingTemplateRequest) -> VideoEditorStateResponse:
    return create_branding_template(project_id, payload.name)


@app.post("/api/projects/{project_id}/video-editor/templates/{template_id}/apply", response_model=VideoEditorStateResponse)
def api_apply_video_branding_template(project_id: str, template_id: str) -> VideoEditorStateResponse:
    return apply_branding_template(project_id, template_id)


@app.delete("/api/projects/{project_id}/video-editor/templates/{template_id}", response_model=VideoEditorStateResponse)
def api_delete_video_branding_template(project_id: str, template_id: str) -> VideoEditorStateResponse:
    return delete_branding_template(project_id, template_id)


@app.post("/api/projects/{project_id}/video-editor/auto-sync", response_model=VideoEditorStateResponse)
def api_run_video_auto_sync(project_id: str) -> VideoEditorStateResponse:
    return run_video_auto_sync(project_id)


@app.post("/api/projects/{project_id}/video-editor/export-job", response_model=ProcessingJob)
def api_start_video_export_job(project_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    result = queue_video_render_job(project_id)
    if result.should_start:
        background_tasks.add_task(run_video_render_job, project_id, result.job.id)
    return result.job


@app.post("/api/projects/{project_id}/video-editor/preview-job", response_model=ProcessingJob)
def api_start_video_preview_job(project_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    result = queue_video_preview_job(project_id)
    if result.should_start:
        background_tasks.add_task(run_video_preview_job, project_id, result.job.id)
    return result.job


@app.get("/api/projects/{project_id}/video-editor/jobs/{job_id}", response_model=ProcessingJob)
def api_get_video_export_job(project_id: str, job_id: str) -> ProcessingJob:
    return get_video_render_job(project_id, job_id)


@app.post("/api/projects/{project_id}/video-editor/jobs/{job_id}/cancel", response_model=ProcessingJob)
def api_cancel_video_export_job(project_id: str, job_id: str) -> ProcessingJob:
    return cancel_video_render_job(project_id, job_id)


@app.delete("/api/projects/{project_id}/video-editor/exports/{export_id}", response_model=VideoEditorStateResponse)
def api_delete_video_export(project_id: str, export_id: str) -> VideoEditorStateResponse:
    return delete_video_export(project_id, export_id)


@app.patch("/api/projects/{project_id}/stems/{stem_id}")
def api_update_stem(project_id: str, stem_id: str, payload: UpdateStemRequest):
    if not validate_stem_type(payload.stemType):
        raise HTTPException(status_code=400, detail="Invalid stem type.")
    return update_stem_type(project_id, stem_id, payload.stemType)


@app.delete("/api/projects/{project_id}/stems/{stem_id}")
def api_delete_stem(project_id: str, stem_id: str) -> dict[str, str]:
    return delete_stem(project_id, stem_id)


@app.post("/api/projects/{project_id}/detect-stems", response_model=Project)
def api_detect_stems(project_id: str) -> Project:
    return detect_project_stems(project_id)


@app.post("/api/projects/{project_id}/accept-all-detections", response_model=Project)
def api_accept_all_stem_detections(project_id: str) -> Project:
    return accept_all_confident_detections(project_id)


@app.post("/api/projects/{project_id}/stems/{stem_id}/accept-detection")
def api_accept_stem_detection(project_id: str, stem_id: str):
    return accept_stem_detection(project_id, stem_id)


@app.post("/api/projects/{project_id}/stems/{stem_id}/correction")
def api_learn_stem_type_correction(project_id: str, stem_id: str, payload: UpdateStemRequest):
    if not validate_stem_type(payload.stemType):
        raise HTTPException(status_code=400, detail="Invalid stem type.")
    return learn_stem_type_correction(project_id, stem_id, payload.stemType)


@app.post("/api/projects/{project_id}/analyze", response_model=ProcessingJob)
def api_start_analysis(project_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_analysis_job(project_id)
    background_tasks.add_task(run_analysis_job, project_id, job.id)
    return job


@app.delete("/api/projects/{project_id}/analysis-results", response_model=Project)
def api_delete_analysis_results(project_id: str) -> Project:
    return delete_analysis_results(project_id)


@app.delete("/api/projects/{project_id}/stem-detections", response_model=Project)
def api_delete_stem_detections(project_id: str) -> Project:
    return delete_stem_detections(project_id)


@app.delete("/api/projects/{project_id}/auto-balance", response_model=Project)
def api_delete_auto_balance(project_id: str) -> Project:
    return delete_auto_balance(project_id)


@app.patch("/api/projects/{project_id}/stems/{stem_id}/cleaning", response_model=Stem)
def api_update_cleaning_settings(project_id: str, stem_id: str, payload: UpdateCleaningSettingsRequest) -> Stem:
    return update_stem_cleaning_settings(project_id, stem_id, payload)


@app.post("/api/projects/{project_id}/clean-stems", response_model=ProcessingJob)
def api_start_cleaning(project_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_cleaning_job(project_id)
    background_tasks.add_task(run_cleaning_job, project_id, job.id)
    return job


@app.post("/api/projects/{project_id}/stems/{stem_id}/cleaning-job", response_model=ProcessingJob)
def api_start_stem_cleaning(project_id: str, stem_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_stem_cleaning_job(project_id, stem_id)
    background_tasks.add_task(run_cleaning_job, project_id, job.id)
    return job


@app.delete("/api/projects/{project_id}/stems/{stem_id}/cleaned-stem", response_model=Project)
def api_delete_cleaned_stem(project_id: str, stem_id: str) -> Project:
    return delete_cleaned_stem(project_id, stem_id)


@app.delete("/api/projects/{project_id}/cleaned-stems", response_model=Project)
def api_delete_cleaned_stems(project_id: str) -> Project:
    return delete_cleaned_stems(project_id)


@app.get("/api/vocal-enhancer-presets")
def api_get_vocal_enhancer_presets() -> dict[str, list[str]]:
    return get_vocal_enhancer_presets()


@app.get("/api/vocal-custom-presets")
def api_list_custom_vocal_presets() -> dict[str, list[dict]]:
    return list_custom_vocal_presets()


@app.post("/api/vocal-custom-presets")
def api_create_custom_vocal_preset(payload: CreateVocalPresetRequest) -> dict:
    return create_custom_vocal_preset(payload)


@app.delete("/api/vocal-custom-presets/{preset_id}")
def api_delete_custom_vocal_preset(preset_id: str) -> dict[str, str]:
    return delete_custom_vocal_preset(preset_id)


@app.patch("/api/projects/{project_id}/stems/{stem_id}/vocal-enhancement", response_model=Stem)
def api_update_vocal_enhancement_settings(project_id: str, stem_id: str, payload: UpdateVocalEnhancementSettingsRequest) -> Stem:
    return update_vocal_enhancement_settings(project_id, stem_id, payload)


@app.post("/api/projects/{project_id}/analyze-vocals", response_model=Project)
def api_analyze_project_vocals(project_id: str) -> Project:
    return analyze_project_vocals(project_id)


@app.post("/api/projects/{project_id}/stems/{stem_id}/apply-vocal-recommendation", response_model=Stem)
def api_apply_vocal_recommendation(project_id: str, stem_id: str) -> Stem:
    return apply_vocal_recommendation(project_id, stem_id)


@app.post("/api/projects/{project_id}/apply-vocal-recommendations", response_model=Project)
def api_apply_all_vocal_recommendations(project_id: str) -> Project:
    return apply_all_vocal_recommendations(project_id)


@app.post("/api/projects/{project_id}/vocal-quality-doctor", response_model=Project)
def api_run_vocal_quality_doctor(project_id: str) -> Project:
    return run_vocal_quality_doctor(project_id)


@app.post("/api/projects/{project_id}/stems/{stem_id}/apply-vocal-doctor-fix", response_model=Project)
def api_apply_vocal_doctor_fix(project_id: str, stem_id: str) -> Project:
    return apply_vocal_doctor_fix(project_id, stem_id)


@app.post("/api/projects/{project_id}/enhance-vocals", response_model=ProcessingJob)
def api_start_vocal_enhancement(project_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_vocal_enhancement_job(project_id)
    background_tasks.add_task(run_vocal_enhancement_job, project_id, job.id)
    return job


@app.post("/api/projects/{project_id}/stems/{stem_id}/vocal-enhancement-job", response_model=ProcessingJob)
def api_start_stem_vocal_enhancement(project_id: str, stem_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_stem_vocal_enhancement_job(project_id, stem_id)
    background_tasks.add_task(run_vocal_enhancement_job, project_id, job.id)
    return job


@app.delete("/api/projects/{project_id}/stems/{stem_id}/vocal-enhancement", response_model=Project)
def api_delete_vocal_enhancement(project_id: str, stem_id: str) -> Project:
    return delete_vocal_enhancement(project_id, stem_id)


@app.delete("/api/projects/{project_id}/vocal-enhancements", response_model=Project)
def api_delete_vocal_enhancements(project_id: str) -> Project:
    return delete_vocal_enhancements(project_id)


@app.get("/api/projects/{project_id}/jobs/{job_id}", response_model=ProcessingJob)
def api_get_processing_job(project_id: str, job_id: str) -> ProcessingJob:
    return get_processing_job(project_id, job_id)


@app.post("/api/projects/{project_id}/jobs/{job_id}/abandon", response_model=ProcessingJob)
def api_abandon_processing_job(project_id: str, job_id: str) -> ProcessingJob:
    return abandon_processing_job(project_id, job_id)


@app.post("/api/projects/{project_id}/jobs/{job_id}/cancel", response_model=ProcessingJob)
def api_cancel_processing_job(project_id: str, job_id: str) -> ProcessingJob:
    job = get_processing_job(project_id, job_id)
    if job.type in {"Video Export", "Video Preview"}:
        return cancel_video_render_job(project_id, job_id)
    return request_processing_job_cancel(project_id, job_id)


@app.post("/api/projects/{project_id}/auto-balance", response_model=Project)
def api_generate_auto_balance(project_id: str) -> Project:
    return generate_auto_balance(project_id)


@app.post("/api/projects/{project_id}/apply-auto-balance", response_model=Project)
def api_apply_auto_balance(project_id: str) -> Project:
    return apply_auto_balance(project_id)


@app.patch("/api/projects/{project_id}/mix-settings/{stem_id}", response_model=Project)
def api_update_mix_stem(project_id: str, stem_id: str, payload: UpdateMixStemRequest) -> Project:
    return update_mix_stem(project_id, stem_id, payload)


@app.patch("/api/projects/{project_id}/mix-controls", response_model=Project)
def api_update_mix_controls(project_id: str, payload: UpdateMixControlsRequest) -> Project:
    return update_mix_controls(project_id, payload)


@app.post("/api/projects/{project_id}/reset-advanced-mix", response_model=Project)
def api_reset_advanced_mix(project_id: str) -> Project:
    return reset_advanced_mix(project_id)


@app.post("/api/projects/{project_id}/reset-stem-processing", response_model=Project)
def api_reset_stem_processing(project_id: str) -> Project:
    return reset_stem_processing(project_id)


@app.post("/api/projects/{project_id}/rough-mix", response_model=RoughMixResponse)
def api_generate_rough_mix(project_id: str) -> RoughMixResponse:
    return generate_rough_mix_preview(project_id)


@app.delete("/api/projects/{project_id}/rough-mix", response_model=Project)
def api_delete_rough_mix(project_id: str) -> Project:
    return delete_rough_mix(project_id)


@app.post("/api/projects/{project_id}/advanced-mix", response_model=MixVersion)
def api_generate_advanced_mix(project_id: str) -> MixVersion:
    return generate_advanced_mix_preview(project_id)


@app.post("/api/projects/{project_id}/advanced-mix-job", response_model=ProcessingJob)
def api_start_advanced_mix(project_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_advanced_mix_job(project_id, instrumental=False)
    background_tasks.add_task(run_advanced_mix_job, project_id, job.id, False)
    return job


@app.post("/api/projects/{project_id}/instrumental-mix", response_model=MixVersion)
def api_generate_instrumental_mix(project_id: str) -> MixVersion:
    return generate_advanced_mix_preview(project_id, instrumental=True)


@app.post("/api/projects/{project_id}/instrumental-mix-job", response_model=ProcessingJob)
def api_start_instrumental_mix(project_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_advanced_mix_job(project_id, instrumental=True)
    background_tasks.add_task(run_advanced_mix_job, project_id, job.id, True)
    return job


@app.patch("/api/projects/{project_id}/mix-versions/{version_id}", response_model=MixVersion)
def api_update_mix_version(project_id: str, version_id: str, payload: UpdateMixVersionRequest) -> MixVersion:
    return update_mix_version(project_id, version_id, payload)


@app.delete("/api/projects/{project_id}/mix-versions/{version_id}")
def api_delete_mix_version(project_id: str, version_id: str) -> dict[str, str]:
    return delete_mix_version(project_id, version_id)


@app.delete("/api/projects/{project_id}/mix-versions", response_model=Project)
def api_delete_mix_versions(project_id: str) -> Project:
    return delete_mix_versions(project_id)


@app.patch("/api/projects/{project_id}/mastering-controls", response_model=Project)
def api_update_mastering_controls(project_id: str, payload: UpdateMasteringControlsRequest) -> Project:
    return update_mastering_controls(project_id, payload)


@app.post("/api/projects/{project_id}/mastering-reference", response_model=Project)
async def api_upload_mastering_reference(project_id: str, file: UploadFile = File(...)) -> Project:
    return await upload_mastering_reference(project_id, file)


@app.post("/api/projects/{project_id}/mastering-reference/url", response_model=Project)
def api_import_mastering_reference_url(project_id: str, payload: ImportMasteringReferenceUrlRequest) -> Project:
    return import_mastering_reference_from_url(project_id, payload)


@app.delete("/api/projects/{project_id}/mastering-reference", response_model=Project)
def api_remove_mastering_reference(project_id: str) -> Project:
    return remove_mastering_reference(project_id)


@app.post("/api/projects/{project_id}/masters", response_model=MasterVersion)
def api_generate_master(project_id: str, payload: GenerateMasterRequest) -> MasterVersion:
    return generate_master(project_id, payload)


@app.post("/api/projects/{project_id}/masters-job", response_model=ProcessingJob)
def api_start_mastering_job(project_id: str, payload: GenerateMasterRequest, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_mastering_job(project_id, payload)
    background_tasks.add_task(run_mastering_job, project_id, job.id, payload)
    return job


@app.post("/api/projects/{project_id}/auto-polish", response_model=ProcessingJob)
def api_start_auto_polish(project_id: str, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_auto_polish_job(project_id)
    background_tasks.add_task(run_auto_polish_job, project_id, job.id)
    return job


@app.post("/api/projects/{project_id}/exports/mix", response_model=ExportFile)
def api_export_mix_without_mastering(project_id: str, payload: ExportMixRequest) -> ExportFile:
    return export_mix_without_mastering(project_id, payload)


@app.post("/api/projects/{project_id}/exports/instrumental", response_model=ExportFile)
def api_export_instrumental(project_id: str, payload: ExportMixRequest) -> ExportFile:
    return export_instrumental(project_id, payload)


@app.post("/api/projects/{project_id}/exports/backup", response_model=ExportFile)
def api_create_project_backup(project_id: str, payload: ProjectBackupRequest) -> ExportFile:
    return create_project_backup(project_id, payload)


@app.delete("/api/projects/{project_id}/masters", response_model=Project)
def api_delete_masters(project_id: str) -> Project:
    return delete_masters(project_id)


@app.delete("/api/projects/{project_id}/exports", response_model=Project)
def api_delete_exports(project_id: str) -> Project:
    return delete_exports(project_id)


# --- Phase 8: Stem Splitter -------------------------------------------------
# A standalone module. These routes never touch project state; splits live in
# their own storage tree and their own slice of app_data.json.


@app.get("/api/splits/environment")
def api_split_environment() -> dict:
    return separation_environment()


@app.get("/api/splits/active")
def api_active_split() -> dict:
    return {"active": active_split_summary()}


@app.get("/api/splits", response_model=list[Split])
def api_list_splits() -> list[Split]:
    return list_splits()


@app.post("/api/splits", response_model=Split)
def api_create_split(payload: CreateSplitRequest, background_tasks: BackgroundTasks) -> Split:
    split = create_split(payload)
    # A cached result comes back Ready and needs no worker.
    if split.status == "Pending":
        background_tasks.add_task(run_split, split.id)
    return split


@app.get("/api/splits/{split_id}", response_model=Split)
def api_get_split(split_id: str) -> Split:
    return get_split(split_id)


@app.get("/api/splits/{split_id}/job", response_model=SplitJob)
def api_get_split_job(split_id: str) -> SplitJob:
    return get_split_job(split_id)


@app.post("/api/splits/{split_id}/cancel", response_model=Split)
def api_cancel_split(split_id: str) -> Split:
    return request_split_cancel(split_id)


@app.delete("/api/splits/{split_id}")
def api_delete_split(split_id: str) -> dict:
    return delete_split(split_id)


@app.post("/api/splits/{split_id}/retry", response_model=Split)
def api_retry_split(split_id: str, background_tasks: BackgroundTasks) -> Split:
    split = retry_split(split_id)
    background_tasks.add_task(run_split, split.id)
    return split


@app.post("/api/splits/{split_id}/archive")
def api_archive_split_stems(split_id: str) -> dict:
    return archive_split_stems(split_id)


@app.post("/api/splits/{split_id}/exports")
def api_export_split_mix(split_id: str, payload: ExportSplitMixRequest) -> dict:
    return export_split_mix(split_id, payload)


# --- Phase 9: Chord Sheets --------------------------------------------------
# A consumer of the Phase 8 splitter: a sheet holds a splitId and reads the
# stems that split already produced. Nothing here touches project state.


@app.get("/api/chord-sheets/environment")
def api_chord_sheet_environment() -> dict:
    return chord_sheet_environment()


@app.get("/api/chord-sheets/active")
def api_active_chord_sheet() -> dict:
    return {"active": active_chord_sheet_summary()}


@app.get("/api/chord-sheets", response_model=list[ChordSheet])
def api_list_chord_sheets() -> list[ChordSheet]:
    return list_chord_sheets()


@app.post("/api/chord-sheets", response_model=ChordSheet)
def api_create_chord_sheet(payload: CreateChordSheetRequest, background_tasks: BackgroundTasks) -> ChordSheet:
    sheet = create_chord_sheet(payload)
    # An existing sheet for the same split comes back Ready and needs no worker.
    if sheet.status == "Pending":
        background_tasks.add_task(run_chord_sheet, sheet.id)
    return sheet


@app.get("/api/chord-sheets/{sheet_id}", response_model=ChordSheet)
def api_get_chord_sheet(sheet_id: str) -> ChordSheet:
    return get_chord_sheet(sheet_id)


@app.get("/api/chord-sheets/{sheet_id}/job", response_model=ChordSheetJob)
def api_get_chord_sheet_job(sheet_id: str) -> ChordSheetJob:
    return get_chord_sheet_job(sheet_id)


@app.get("/api/chord-sheets/{sheet_id}/analysis")
def api_get_chord_sheet_analysis(sheet_id: str) -> dict:
    return get_analysis(sheet_id)


@app.post("/api/chord-sheets/{sheet_id}/cancel", response_model=ChordSheet)
def api_cancel_chord_sheet(sheet_id: str) -> ChordSheet:
    return request_sheet_cancel(sheet_id)


@app.post("/api/chord-sheets/{sheet_id}/retry", response_model=ChordSheet)
def api_retry_chord_sheet(sheet_id: str, background_tasks: BackgroundTasks) -> ChordSheet:
    sheet = retry_chord_sheet(sheet_id)
    background_tasks.add_task(run_chord_sheet, sheet.id)
    return sheet


@app.delete("/api/chord-sheets/{sheet_id}")
def api_delete_chord_sheet(sheet_id: str) -> dict:
    return delete_chord_sheet(sheet_id)


@app.patch("/api/chord-sheets/{sheet_id}/view")
def api_update_chord_sheet_view(sheet_id: str, payload: UpdateSheetViewRequest) -> dict:
    return update_sheet_view(sheet_id, payload.transpose, payload.capo, payload.tuningShift)


@app.patch("/api/chord-sheets/{sheet_id}/chord")
def api_update_chord_sheet_chord(sheet_id: str, payload: UpdateSheetChordRequest) -> dict:
    return update_sheet_chord(sheet_id, payload.bar, payload.startSeconds, payload.label)


@app.post("/api/chord-sheets/{sheet_id}/exports")
def api_export_chord_sheet(sheet_id: str, payload: ExportChordSheetRequest) -> dict:
    return export_chord_sheet(sheet_id, payload.format)



@app.post("/api/chord-sheets/{sheet_id}/lyrics")
def api_attach_chord_sheet_lyrics(sheet_id: str, payload: AttachLyricsRequest) -> dict:
    return attach_lyrics(sheet_id, payload.source, payload.text, payload.artist, payload.track)


@app.delete("/api/chord-sheets/{sheet_id}/lyrics")
def api_clear_chord_sheet_lyrics(sheet_id: str) -> dict:
    return clear_lyrics(sheet_id)
