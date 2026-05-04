from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .audio_engine import check_audio_environment
from .config import MAX_UPLOAD_MB, STEM_TYPES, STORAGE_ROOT
from .models import (
    AudioInputDeviceListResponse,
    CreateProjectRequest,
    CreateVocalPresetRequest,
    DirectRecordingStatus,
    ExportFile,
    ExportMixRequest,
    GenerateMasterRequest,
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
    UpdateProjectRequest,
    UpdateStemRequest,
    UploadResponse,
    validate_stem_type,
)
from .cleaning import create_cleaning_job, run_cleaning_job, update_stem_cleaning_settings
from .vocal_enhancer import (
    analyze_project_vocals,
    apply_all_vocal_recommendations,
    apply_vocal_doctor_fix,
    apply_vocal_recommendation,
    create_vocal_enhancement_job,
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
from .phase6 import (
    create_mastering_job,
    create_project_backup,
    export_instrumental,
    export_mix_without_mastering,
    generate_master,
    get_mastering_presets,
    run_mastering_job,
    update_mastering_controls,
)
from .stem_detection import (
    accept_all_confident_detections,
    accept_stem_detection,
    clear_detection_memory,
    detect_project_stems,
    get_detection_memory_summary,
    learn_stem_type_correction,
)
from .storage import abandon_processing_job, create_project, delete_project, delete_stem, get_project, list_projects, mark_interrupted_jobs, read_project_logs, save_uploaded_stems, update_project, update_stem_type
from .recording import recording_manager
from .workflow_reset import (
    delete_analysis_results,
    delete_auto_balance,
    delete_cleaned_stems,
    delete_exports,
    delete_masters,
    delete_mix_versions,
    delete_rough_mix,
    delete_stem_detections,
    delete_vocal_enhancements,
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


@app.delete("/api/projects/{project_id}/vocal-enhancements", response_model=Project)
def api_delete_vocal_enhancements(project_id: str) -> Project:
    return delete_vocal_enhancements(project_id)


@app.get("/api/projects/{project_id}/jobs/{job_id}", response_model=ProcessingJob)
def api_get_processing_job(project_id: str, job_id: str) -> ProcessingJob:
    return get_processing_job(project_id, job_id)


@app.post("/api/projects/{project_id}/jobs/{job_id}/abandon", response_model=ProcessingJob)
def api_abandon_processing_job(project_id: str, job_id: str) -> ProcessingJob:
    return abandon_processing_job(project_id, job_id)


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


@app.post("/api/projects/{project_id}/masters", response_model=MasterVersion)
def api_generate_master(project_id: str, payload: GenerateMasterRequest) -> MasterVersion:
    return generate_master(project_id, payload)


@app.post("/api/projects/{project_id}/masters-job", response_model=ProcessingJob)
def api_start_mastering_job(project_id: str, payload: GenerateMasterRequest, background_tasks: BackgroundTasks) -> ProcessingJob:
    job = create_mastering_job(project_id, payload)
    background_tasks.add_task(run_mastering_job, project_id, job.id, payload)
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
