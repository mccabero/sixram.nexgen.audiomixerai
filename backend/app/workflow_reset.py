import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .logging_utils import append_project_log, utc_now_iso
from .models import Project
from .storage import _find_project, project_subdirs, resolve_stored_file_path, store


ACTIVE_JOB_STATUSES = {"Pending", "Processing"}


def delete_analysis_results(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_no_active_jobs(project)
    _delete_mixer_outputs(project_id, project)
    _clear_auto_balance(project)
    for stem in project.get("stems", []):
        stem["analysisStatus"] = "Pending"
        stem["analysisResult"] = None
        stem["autoBalanceSuggestion"] = None
        metadata = stem.setdefault("metadata", {})
        metadata["durationSeconds"] = None
        metadata["sampleRate"] = None
        metadata["channels"] = None
    _finish_reset(project_id, data, project, "Stems Uploaded", "Deleted analysis results and downstream mix/master outputs.")
    return Project(**project)


def delete_stem_detections(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_no_active_jobs(project)
    _delete_cleaning_outputs(project_id, project)
    for stem in project.get("stems", []):
        stem["detectionResult"] = None
        if stem.get("stemTypeSource") == "Detected":
            stem["stemType"] = "Unknown"
            stem["stemTypeSource"] = "Unknown"
    project["detectionSummary"] = {"learnedPatternCount": project.get("detectionSummary", {}).get("learnedPatternCount", 0), "confidentPendingCount": 0, "acceptedCount": 0}
    _finish_reset(project_id, data, project, _status_after_analysis(project), "Deleted stem detection results and downstream generated files.")
    return Project(**project)


def delete_auto_balance(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_no_active_jobs(project)
    _delete_mixer_outputs(project_id, project)
    _clear_auto_balance(project)
    _finish_reset(project_id, data, project, _status_after_analysis(project), "Deleted auto-balance suggestions and mix/master outputs.")
    return Project(**project)


def delete_cleaned_stems(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_no_active_jobs(project)
    _delete_cleaning_outputs(project_id, project)
    _finish_reset(project_id, data, project, "Auto Balance Ready" if any(stem.get("autoBalanceSuggestion") for stem in project.get("stems", [])) else _status_after_analysis(project), "Deleted cleaned stems and downstream generated files.")
    return Project(**project)


def delete_vocal_enhancements(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_no_active_jobs(project)
    _delete_vocal_outputs(project_id, project)
    _finish_reset(project_id, data, project, "Cleaned" if any((stem.get("cleaningResult") or {}).get("status") == "Completed" for stem in project.get("stems", [])) else _status_after_analysis(project), "Deleted vocal enhancement outputs and downstream mix/master files.")
    return Project(**project)


def delete_rough_mix(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_no_active_jobs(project)
    _delete_tree(project_id, project_subdirs(project_id)["processed"] / "rough_mix")
    _clear_rough_mix(project)
    _finish_reset(project_id, data, project, _status_after_mix_reset(project), "Deleted rough mix preview.")
    return Project(**project)


def delete_mix_versions(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_no_active_jobs(project)
    _delete_mixer_outputs(project_id, project)
    _finish_reset(project_id, data, project, "Auto Balanced" if _auto_balance_applied(project) else _status_after_analysis(project), "Deleted mix versions, rough preview, masters, and exports.")
    return Project(**project)


def delete_masters(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_no_active_jobs(project)
    _delete_master_outputs(project_id, project, include_exports=False)
    _finish_reset(project_id, data, project, "Advanced Mix Ready" if _has_mix_versions(project) else _status_after_analysis(project), "Deleted master versions and loudness reports.")
    return Project(**project)


def delete_exports(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _require_no_active_jobs(project)
    _delete_export_outputs(project_id, project)
    _finish_reset(project_id, data, project, "Master Ready" if _has_master_versions(project) else ("Advanced Mix Ready" if _has_mix_versions(project) else _status_after_analysis(project)), "Deleted exported mix, instrumental, and backup files.")
    return Project(**project)


def _delete_cleaning_outputs(project_id: str, project: dict[str, Any]) -> None:
    _delete_vocal_outputs(project_id, project)
    for stem in project.get("stems", []):
        result = stem.get("cleaningResult") or {}
        _delete_file(project_id, result.get("cleanedFilePath"))
        stem["cleaningResult"] = None
        settings = stem.get("cleaningSettings") or {}
        if settings.get("enabled") and settings.get("mode") != "Off":
            stem["cleaningStatus"] = "Pending"
        elif settings.get("enabled") is False or settings.get("mode") == "Off":
            stem["cleaningStatus"] = "Disabled" if settings.get("mode") == "Off" else "Not Cleaned"
        else:
            stem["cleaningStatus"] = "Not Cleaned"
    _delete_tree(project_id, project_subdirs(project_id)["processed"] / "cleaned")


def _delete_vocal_outputs(project_id: str, project: dict[str, Any]) -> None:
    _delete_mixer_outputs(project_id, project)
    for stem in project.get("stems", []):
        result = stem.get("vocalEnhancementResult") or {}
        _delete_file(project_id, result.get("enhancedFilePath"))
        stem["vocalEnhancementResult"] = None
        stem["vocalQualityDoctorResult"] = None
        settings = stem.get("vocalEnhancementSettings") or {}
        stem["vocalEnhancementStatus"] = "Pending" if settings.get("enabled") else "Not Enhanced"
    _delete_tree(project_id, project_subdirs(project_id)["processed"] / "vocals")


def _delete_mixer_outputs(project_id: str, project: dict[str, Any]) -> None:
    _delete_master_outputs(project_id, project, include_exports=True)
    mix_settings = project.setdefault("mixSettings", {})
    for key in ["roughMixWavPath", "roughMixMp3Path"]:
        _delete_file(project_id, mix_settings.get(key))
    for version in mix_settings.get("mixVersions", []):
        for key in ["wavPath", "mp3Path", "metadataPath"]:
            _delete_file(project_id, version.get(key))
    _delete_tree(project_id, project_subdirs(project_id)["processed"] / "rough_mix")
    _delete_tree(project_id, project_subdirs(project_id)["processed"] / "mixes")
    _clear_rough_mix(project)
    mix_settings["mixVersions"] = []
    mix_settings["latestMixVersionId"] = None
    mix_settings["updatedAt"] = utc_now_iso()
    mastering_controls = project.setdefault("masteringSettings", {}).setdefault("controls", {})
    mastering_controls["selectedMixVersionId"] = None


def _delete_master_outputs(project_id: str, project: dict[str, Any], include_exports: bool) -> None:
    if include_exports:
        _delete_export_outputs(project_id, project)
    settings = project.setdefault("masteringSettings", {})
    for master in settings.get("masterVersions", []):
        for key in ["filePath", "reportJsonPath", "reportTxtPath"]:
            _delete_file(project_id, master.get(key))
    _delete_tree(project_id, project_subdirs(project_id)["exports"] / "masters")
    _delete_tree(project_id, project_subdirs(project_id)["exports"] / "reports")
    settings["masterVersions"] = []
    settings["latestMasterVersionId"] = None
    settings["updatedAt"] = utc_now_iso()


def _delete_export_outputs(project_id: str, project: dict[str, Any]) -> None:
    settings = project.setdefault("masteringSettings", {})
    for export_file in settings.get("exportFiles", []):
        _delete_file(project_id, export_file.get("filePath"))
    for folder in ["mixes", "instrumentals", "backups"]:
        _delete_tree(project_id, project_subdirs(project_id)["exports"] / folder)
    settings["exportFiles"] = []
    settings["updatedAt"] = utc_now_iso()


def _clear_auto_balance(project: dict[str, Any]) -> None:
    mix_settings = project.setdefault("mixSettings", {})
    for stem in project.get("stems", []):
        stem["autoBalanceSuggestion"] = None
    for setting in mix_settings.get("stems", []):
        setting["autoBalanceApplied"] = False
    mix_settings["autoBalanceGeneratedAt"] = None
    mix_settings["autoBalanceAppliedAt"] = None
    mix_settings["updatedAt"] = utc_now_iso()


def _clear_rough_mix(project: dict[str, Any]) -> None:
    mix_settings = project.setdefault("mixSettings", {})
    mix_settings["roughMixWavPath"] = None
    mix_settings["roughMixMp3Path"] = None
    mix_settings["roughMixWavUrl"] = None
    mix_settings["roughMixMp3Url"] = None
    mix_settings["updatedAt"] = utc_now_iso()


def _finish_reset(project_id: str, data: dict[str, Any], project: dict[str, Any], status: str, log_message: str) -> None:
    ensure_dirs = project_subdirs(project_id)
    for key in ["root", "original", "processed", "exports", "logs"]:
        ensure_dirs[key].mkdir(parents=True, exist_ok=True)
    project["status"] = status
    project["updatedAt"] = utc_now_iso()
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], log_message)


def _delete_file(project_id: str, path_value: str | None) -> None:
    if not path_value:
        return
    path = resolve_stored_file_path(path_value)
    if not path.exists() or not _is_inside_project(project_id, path):
        return
    _unlink_with_retries(path)


def _delete_tree(project_id: str, path: Path) -> None:
    if not path.exists() or not _is_inside_project(project_id, path):
        return
    root = project_subdirs(project_id)["root"].resolve()
    if path.resolve() == root:
        raise HTTPException(status_code=500, detail="Refusing to delete the project root folder.")
    _rmtree_with_retries(path)


def _is_inside_project(project_id: str, path: Path) -> bool:
    try:
        resolved = path.resolve()
        root = project_subdirs(project_id)["root"].resolve()
        return resolved == root or resolved.is_relative_to(root)
    except OSError:
        return False


def _unlink_with_retries(path: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    raise HTTPException(status_code=500, detail=f"Could not delete generated file. Close any audio player using {path.name} and retry.") from last_error


def _rmtree_with_retries(path: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.07 * (attempt + 1))
    raise HTTPException(status_code=500, detail=f"Could not delete generated folder {path.name}. Close any audio player or Explorer window using it and retry.") from last_error


def _require_no_active_jobs(project: dict[str, Any]) -> None:
    active = next((job for job in project.get("processingJobs", []) if job.get("status") in ACTIVE_JOB_STATUSES), None)
    if active:
        raise HTTPException(status_code=400, detail=f"Wait for the active {active.get('type', 'processing')} job to finish or abandon it before deleting generated files.")


def _status_after_analysis(project: dict[str, Any]) -> str:
    if project.get("stems") and all(stem.get("analysisStatus") == "Completed" for stem in project.get("stems", [])):
        return "Analyzed"
    return "Stems Uploaded" if project.get("stems") else "Created"


def _status_after_mix_reset(project: dict[str, Any]) -> str:
    if _auto_balance_applied(project):
        return "Auto Balanced"
    if any(stem.get("autoBalanceSuggestion") for stem in project.get("stems", [])):
        return "Auto Balance Ready"
    return _status_after_analysis(project)


def _auto_balance_applied(project: dict[str, Any]) -> bool:
    return any(setting.get("autoBalanceApplied") for setting in project.get("mixSettings", {}).get("stems", []))


def _has_mix_versions(project: dict[str, Any]) -> bool:
    return bool(project.get("mixSettings", {}).get("mixVersions"))


def _has_master_versions(project: dict[str, Any]) -> bool:
    return bool(project.get("masteringSettings", {}).get("masterVersions"))
