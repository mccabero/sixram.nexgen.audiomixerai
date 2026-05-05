import json
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from .audio_engine import validate_audio_file
from .config import ALLOWED_EXTENSIONS, BASE_DIR, DB_PATH, MAX_UPLOAD_BYTES, PROJECTS_ROOT, STEM_TYPES, STORAGE_ROOT
from .logging_utils import append_project_log, utc_now_iso
from .models import CreateProjectRequest, ProcessingJob, Project, ProjectListItem, Stem, StemMetadata, UpdateProjectRequest


class JsonStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ensure_storage()

    def ensure_storage(self) -> None:
        STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
        PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
        if not DB_PATH.exists():
            self._write_unlocked({"projects": []})

    def load(self) -> dict[str, Any]:
        self.ensure_storage()
        with self._lock:
            try:
                with DB_PATH.open("r", encoding="utf-8") as db_file:
                    data = json.load(db_file)
                    _ensure_data_defaults(data)
                    return data
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=500, detail="Metadata database is invalid JSON.") from exc

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._write_unlocked(data)

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = DB_PATH.with_name(f"{DB_PATH.stem}.{uuid.uuid4().hex}.tmp")
        with temp_path.open("w", encoding="utf-8") as db_file:
            json.dump(data, db_file, indent=2)
            db_file.flush()

        last_error: PermissionError | None = None
        for attempt in range(10):
            try:
                temp_path.replace(DB_PATH)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.05 * (attempt + 1))

        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise HTTPException(
            status_code=500,
            detail="Could not save local metadata because app_data.json is locked. Close duplicate backend windows and retry.",
        ) from last_error


store = JsonStore()
STEM_TYPE_MEMORY_VALUES = set(STEM_TYPES) - {"Unknown"}
ACTIVE_PROCESSING_JOB_STATUSES = {"Pending", "Processing", "Cancelling"}


class JobCancelled(Exception):
    """Raised inside background workers when the user requests a stop."""

    def __init__(self, message: str = "Job was stopped by the user.") -> None:
        super().__init__(message)
        self.message = message


def project_dir(project_id: str) -> Path:
    return PROJECTS_ROOT / project_id


def project_subdirs(project_id: str) -> dict[str, Path]:
    root = project_dir(project_id)
    return {
        "root": root,
        "original": root / "original",
        "processed": root / "processed",
        "exports": root / "exports",
        "video": root / "video",
        "logs": root / "logs",
    }


def ensure_project_dirs(project_id: str) -> dict[str, Path]:
    dirs = project_subdirs(project_id)
    for folder in dirs.values():
        folder.mkdir(parents=True, exist_ok=True)
    return dirs


def list_projects() -> list[ProjectListItem]:
    data = store.load()
    projects = []
    for project in data["projects"]:
        projects.append(
            ProjectListItem(
                id=project["id"],
                name=project["name"],
                artistName=project.get("artistName"),
                songTitle=project.get("songTitle"),
                createdAt=project["createdAt"],
                updatedAt=project["updatedAt"],
                status=project["status"],
                stemCount=len(project.get("stems", [])),
            )
        )
    return sorted(projects, key=lambda item: item.updatedAt, reverse=True)


def create_project(payload: CreateProjectRequest) -> Project:
    now = utc_now_iso()
    project_id = uuid.uuid4().hex
    ensure_project_dirs(project_id)
    project = Project(
        id=project_id,
        name=payload.name.strip(),
        artistName=_clean_optional(payload.artistName),
        songTitle=_clean_optional(payload.songTitle),
        notes=_clean_optional(payload.notes),
        createdAt=now,
        updatedAt=now,
        status="Created",
        stems=[],
    )

    data = store.load()
    data["projects"].append(project.model_dump())
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], "Project created.")
    return project


def get_project(project_id: str) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    _ensure_project_defaults(project)
    store.save(data)
    ensure_project_dirs(project_id)
    return Project(**project)


def update_project(project_id: str, payload: UpdateProjectRequest) -> Project:
    data = store.load()
    project = _find_project(data, project_id)
    previous_name = project.get("name", "Untitled")
    project["name"] = payload.name.strip()
    project["artistName"] = _clean_optional(payload.artistName)
    project["songTitle"] = _clean_optional(payload.songTitle)
    project["notes"] = _clean_optional(payload.notes)
    project["updatedAt"] = utc_now_iso()
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Updated project details for {previous_name}.")
    return Project(**project)


def delete_project(project_id: str) -> dict[str, str]:
    data = store.load()
    projects = data.get("projects", [])
    index = next((idx for idx, item in enumerate(projects) if item.get("id") == project_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    project = projects[index]
    active_job = next((job for job in project.get("processingJobs", []) if job.get("status") in ACTIVE_PROCESSING_JOB_STATUSES), None)
    if active_job:
        raise HTTPException(status_code=400, detail="Stop or abandon running jobs before deleting this project.")

    root = _safe_project_root(project_id)
    if root.exists():
        _remove_project_tree(root)

    deleted_name = project.get("name", project_id)
    projects.pop(index)
    store.save(data)
    return {"message": f"Project '{deleted_name}' and all local project files were deleted."}


async def save_uploaded_stems(project_id: str, files: list[UploadFile]) -> tuple[list[Stem], list[dict[str, str]]]:
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    data = store.load()
    project = _find_project(data, project_id)
    dirs = ensure_project_dirs(project_id)
    uploaded: list[Stem] = []
    errors: list[dict[str, str]] = []

    for upload in files:
        original_filename = Path(upload.filename or "untitled").name
        extension = Path(original_filename).suffix.lower()

        if extension not in ALLOWED_EXTENSIONS:
            supported_formats = ", ".join(ext[1:].upper() for ext in sorted(ALLOWED_EXTENSIONS))
            error = f"Unsupported file type '{extension or 'none'}'. Supported formats: {supported_formats}."
            errors.append({"filename": original_filename, "error": error})
            append_project_log(dirs["logs"], f"Upload failed for {original_filename}: {error}")
            await upload.close()
            continue

        stored_filename = _unique_stored_filename(original_filename, dirs["original"])
        destination = dirs["original"] / stored_filename

        try:
            file_size = await _write_upload_file(upload, destination)
            validate_audio_file(destination)
        except (RuntimeError, ValueError) as exc:
            if destination.exists():
                destination.unlink()
            errors.append({"filename": original_filename, "error": str(exc)})
            append_project_log(dirs["logs"], f"Upload failed for {original_filename}: {exc}")
            continue
        except OSError as exc:
            if destination.exists():
                destination.unlink()
            errors.append({"filename": original_filename, "error": "Could not save file to local storage."})
            append_project_log(dirs["logs"], f"Upload failed for {original_filename}: {exc}")
            continue
        except Exception as exc:
            if destination.exists():
                destination.unlink()
            errors.append({"filename": original_filename, "error": "Could not validate this audio file."})
            append_project_log(dirs["logs"], f"Upload failed for {original_filename}: {exc}")
            continue
        finally:
            await upload.close()

        now = utc_now_iso()
        stem = Stem(
            id=uuid.uuid4().hex,
            projectId=project_id,
            originalFilename=original_filename,
            storedFilename=stored_filename,
            filePath=_display_path(destination),
            fileExtension=extension,
            fileSize=file_size,
            uploadedAt=now,
            status="Uploaded",
            stemType="Unknown",
            metadata=StemMetadata(),
        )
        uploaded.append(stem)
        project.setdefault("stems", []).append(stem.model_dump())
        project["updatedAt"] = now
        project["status"] = "Stems Uploaded"
        append_project_log(dirs["logs"], f"Uploaded stem {original_filename} as {stored_filename}.")

    if uploaded:
        store.save(data)

    return uploaded, errors


def register_recorded_stems(project_id: str, file_paths: list[Path]) -> list[Stem]:
    if not file_paths:
        return []

    data = store.load()
    project = _find_project(data, project_id)
    ensure_project_dirs(project_id)
    now = utc_now_iso()
    uploaded: list[Stem] = []

    for path in file_paths:
        if not path.exists():
            raise HTTPException(status_code=500, detail=f"Recorded stem file is missing: {path.name}")

        extension = path.suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Recorded stem file has unsupported extension: {extension}")

        stem = Stem(
            id=uuid.uuid4().hex,
            projectId=project_id,
            originalFilename=path.name,
            storedFilename=path.name,
            filePath=_display_path(path),
            fileExtension=extension,
            fileSize=path.stat().st_size,
            uploadedAt=now,
            status="Uploaded",
            stemType="Unknown",
            metadata=StemMetadata(),
        )
        uploaded.append(stem)
        project.setdefault("stems", []).append(stem.model_dump())
        append_project_log(project_subdirs(project_id)["logs"], f"Registered recorded stem {path.name}.")

    project["updatedAt"] = now
    project["status"] = "Stems Uploaded"
    store.save(data)
    return uploaded


def update_stem_type(project_id: str, stem_id: str, stem_type: str) -> Stem:
    data = store.load()
    project = _find_project(data, project_id)
    stem = _find_stem(project, stem_id)
    previous_type = stem.get("stemType", "Unknown")
    stem["stemType"] = stem_type
    stem["stemTypeSource"] = "Manual" if stem_type != "Unknown" else "Unknown"
    if stem.get("detectionResult"):
        stem["detectionResult"]["accepted"] = stem["detectionResult"].get("suggestedStemType") == stem_type and stem_type != "Unknown"
    if stem_type != "Unknown":
        remember_filename_correction(data, stem.get("originalFilename", ""), stem_type)
    _mark_type_dependent_mix_stale(project, stem_id)
    _refresh_detection_summary(project, data)
    project["updatedAt"] = utc_now_iso()
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Updated stem type for {stem['originalFilename']} from {previous_type} to {stem_type}.")
    return Stem(**stem)


def delete_stem(project_id: str, stem_id: str) -> dict[str, str]:
    data = store.load()
    project = _find_project(data, project_id)
    stems = project.get("stems", [])
    index = next((idx for idx, stem in enumerate(stems) if stem["id"] == stem_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Stem not found.")

    stem = stems.pop(index)
    file_path = _resolve_stored_file_path(stem.get("filePath", ""))
    if file_path.exists():
        file_path.unlink()

    now = utc_now_iso()
    mix_settings = project.get("mixSettings")
    if mix_settings:
        mix_settings["stems"] = [setting for setting in mix_settings.get("stems", []) if setting.get("stemId") != stem_id]
        mix_settings["roughMixWavPath"] = None
        mix_settings["roughMixMp3Path"] = None
        mix_settings["roughMixWavUrl"] = None
        mix_settings["roughMixMp3Url"] = None
        mix_settings["updatedAt"] = now
    project["updatedAt"] = now
    if len(stems) == 0:
        project["status"] = "Created"
    _refresh_detection_summary(project, data)
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Deleted stem {stem['originalFilename']}.")
    return {"message": "Stem deleted."}


def mark_interrupted_jobs() -> int:
    data = store.load()
    interrupted = 0
    now = utc_now_iso()
    for project in data.get("projects", []):
        _ensure_project_defaults(project)
        logs_dir = project_subdirs(project["id"])["logs"]
        for job in project.get("processingJobs", []):
            if job.get("status") in ACTIVE_PROCESSING_JOB_STATUSES:
                job["status"] = "Failed"
                job["progress"] = 100
                job["currentStemId"] = None
                job["message"] = "Job was interrupted by an app restart. Start it again if needed."
                job.setdefault("errors", []).append({"stemId": None, "filename": None, "error": job["message"]})
                job["updatedAt"] = now
                job["completedAt"] = now
                project["updatedAt"] = now
                if job.get("type") == "Cleaning":
                    _mark_interrupted_cleaning_stems(project)
                if job.get("type") == "Vocal Enhancement":
                    _mark_interrupted_vocal_stems(project)
                interrupted += 1
                append_project_log(logs_dir, f"Marked interrupted {job.get('type', 'processing')} job {job.get('id')} as failed after app startup.")
    if interrupted:
        store.save(data)
    return interrupted


def abandon_processing_job(project_id: str, job_id: str) -> ProcessingJob:
    data = store.load()
    project = _find_project(data, project_id)
    job = next((item for item in project.get("processingJobs", []) if item.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")

    if job.get("status") not in ACTIVE_PROCESSING_JOB_STATUSES:
        return ProcessingJob(**job)

    now = utc_now_iso()
    message = "Job was marked failed so it can be retried."
    job["status"] = "Failed"
    job["progress"] = 100
    job["currentStemId"] = None
    job["message"] = message
    job.setdefault("errors", []).append({"stemId": None, "filename": None, "error": message})
    job["updatedAt"] = now
    job["completedAt"] = now
    project["updatedAt"] = now
    if job.get("type") == "Cleaning":
        _mark_interrupted_cleaning_stems(project)
    if job.get("type") == "Vocal Enhancement":
        _mark_interrupted_vocal_stems(project)
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Marked {job.get('type', 'processing')} job {job_id} as failed for retry.")
    return ProcessingJob(**job)


def request_processing_job_cancel(project_id: str, job_id: str) -> ProcessingJob:
    data = store.load()
    project = _find_project(data, project_id)
    job = next((item for item in project.get("processingJobs", []) if item.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")

    if job.get("status") not in ACTIVE_PROCESSING_JOB_STATUSES:
        return ProcessingJob(**job)

    if job.get("status") == "Cancelling":
        return ProcessingJob(**job)

    now = utc_now_iso()
    job["status"] = "Cancelling"
    job["message"] = "Stop requested. Finishing the current safe checkpoint..."
    job["updatedAt"] = now
    project["updatedAt"] = now
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Stop requested for {job.get('type', 'processing')} job {job_id}.")
    return ProcessingJob(**job)


def raise_if_processing_job_cancelled(project_id: str, job_id: str) -> None:
    data = store.load()
    project = _find_project(data, project_id)
    job = next((item for item in project.get("processingJobs", []) if item.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    if job.get("status") in {"Cancelling", "Cancelled"}:
        raise JobCancelled(job.get("message") or "Job was stopped by the user.")


def mark_processing_job_cancelled(project_id: str, job_id: str) -> ProcessingJob:
    data = store.load()
    project = _find_project(data, project_id)
    job = next((item for item in project.get("processingJobs", []) if item.get("id") == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")

    if job.get("status") == "Cancelled":
        return ProcessingJob(**job)

    now = utc_now_iso()
    message = "Job stopped by user."
    job["status"] = "Cancelled"
    job["progress"] = 100
    job["currentStemId"] = None
    job["message"] = message
    job["updatedAt"] = now
    job["completedAt"] = now
    project["updatedAt"] = now
    if job.get("type") == "Cleaning":
        _mark_interrupted_cleaning_stems(project)
    if job.get("type") == "Vocal Enhancement":
        _mark_interrupted_vocal_stems(project)
    store.save(data)
    append_project_log(project_subdirs(project_id)["logs"], f"Stopped {job.get('type', 'processing')} job {job_id}.")
    return ProcessingJob(**job)


def _mark_interrupted_cleaning_stems(project: dict[str, Any]) -> None:
    for stem in project.get("stems", []):
        settings = stem.setdefault("cleaningSettings", {})
        settings.setdefault("enabled", False)
        settings.setdefault("mode", "Off")
        result = stem.get("cleaningResult") or {}
        result_matches = (
            result.get("status") == "Completed"
            and result.get("mode") == settings.get("mode")
            and bool(result.get("humRemoval")) == bool(settings.get("humRemoval"))
            and int(result.get("humFrequency", 60)) == int(settings.get("humFrequency", 60))
            and bool(result.get("cleanedFilePath"))
        )
        if not settings.get("enabled") or settings.get("mode") == "Off":
            stem["cleaningStatus"] = "Disabled"
        elif result_matches:
            stem["cleaningStatus"] = "Completed"
        elif stem.get("cleaningStatus") in {"Processing", "Pending"}:
            stem["cleaningStatus"] = "Pending"


def _mark_interrupted_vocal_stems(project: dict[str, Any]) -> None:
    for stem in project.get("stems", []):
        settings = stem.setdefault("vocalEnhancementSettings", {})
        settings.setdefault("enabled", False)
        settings.setdefault("preset", "AI Pop Clean")
        settings.setdefault("pitchCorrection", "Off")
        settings.setdefault("key", "Auto")
        settings.setdefault("scale", "Major")
        settings.setdefault("fxStyle", "Dry")
        settings.setdefault("fxAmount", 0)
        settings.setdefault("bodyAmount", 0)
        settings.setdefault("presenceAmount", 0)
        settings.setdefault("airAmount", 0)
        settings.setdefault("deEssAmount", 50)
        settings.setdefault("compressionAmount", 40)
        settings.setdefault("riderAmount", 36)
        settings.setdefault("saturationAmount", 18)
        settings.setdefault("doublerAmount", 16)
        settings.setdefault("breathReductionAmount", 35)
        settings.setdefault("mouthClickReductionAmount", 30)
        settings.setdefault("pitchStrength", 42)
        settings.setdefault("pitchHumanize", 72)
        settings.setdefault("useEnhancedInMix", True)
        result = stem.get("vocalEnhancementResult") or {}
        result_matches = (
            result.get("status") == "Completed"
            and result.get("preset") == settings.get("preset")
            and result.get("pitchCorrection") == settings.get("pitchCorrection")
            and result.get("key") == settings.get("key")
            and result.get("scale") == settings.get("scale")
            and result.get("fxStyle", "Dry") == settings.get("fxStyle")
            and float(result.get("fxAmount", 0)) == float(settings.get("fxAmount", 0))
            and _vocal_result_controls_match(result, settings)
            and bool(result.get("enhancedFilePath"))
        )
        if not settings.get("enabled"):
            stem["vocalEnhancementStatus"] = "Disabled"
        elif result_matches:
            stem["vocalEnhancementStatus"] = "Completed"
        elif stem.get("vocalEnhancementStatus") in {"Processing", "Pending"}:
            stem["vocalEnhancementStatus"] = "Pending"


def _vocal_result_controls_match(result: dict[str, Any], settings: dict[str, Any]) -> bool:
    defaults = {
        "bodyAmount": 0,
        "presenceAmount": 0,
        "airAmount": 0,
        "deEssAmount": 50,
        "compressionAmount": 40,
        "riderAmount": 36,
        "saturationAmount": 18,
        "doublerAmount": 16,
        "breathReductionAmount": 35,
        "mouthClickReductionAmount": 30,
        "pitchStrength": 42,
        "pitchHumanize": 72,
    }
    return all(float(result.get(key, default)) == float(settings.get(key, default)) for key, default in defaults.items())


def read_project_logs(project_id: str, limit: int = 200) -> dict[str, list[dict[str, str]]]:
    data = store.load()
    _find_project(data, project_id)
    safe_limit = max(1, min(int(limit), 1000))
    logs_dir = project_subdirs(project_id)["logs"]
    log_path = logs_dir / "processing.log"
    if not log_path.exists():
        log_path = logs_dir / "phase1.log"
    if not log_path.exists():
        return {"lines": []}

    raw_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-safe_limit:]
    lines = []
    for raw in raw_lines:
        timestamp, _, message = raw.partition(" ")
        lines.append({"timestamp": timestamp, "message": message or raw, "raw": raw})
    return {"lines": lines}


def _find_project(data: dict[str, Any], project_id: str) -> dict[str, Any]:
    project = next((item for item in data.get("projects", []) if item["id"] == project_id), None)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    _ensure_project_defaults(project)
    return project


def _find_stem(project: dict[str, Any], stem_id: str) -> dict[str, Any]:
    stem = next((item for item in project.get("stems", []) if item["id"] == stem_id), None)
    if stem is None:
        raise HTTPException(status_code=404, detail="Stem not found.")
    return stem


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _safe_stem_name(filename: str) -> str:
    stem = Path(filename).stem.strip() or "stem"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
    return stem[:80].strip("._-") or "stem"


def _unique_stored_filename(original_filename: str, destination_dir: Path) -> str:
    extension = Path(original_filename).suffix.lower()
    base = _safe_stem_name(original_filename)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    for _ in range(10):
        suffix = uuid.uuid4().hex[:10]
        candidate = f"{base}_{timestamp}_{suffix}{extension}"
        if not (destination_dir / candidate).exists():
            return candidate

    return f"{base}_{timestamp}_{uuid.uuid4().hex}{extension}"


async def _write_upload_file(upload: UploadFile, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = 0
    try:
        with destination.open("xb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    raise ValueError(f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.")
                output.write(chunk)
    except Exception:
        if destination.exists():
            destination.unlink()
        raise

    if bytes_written == 0:
        if destination.exists():
            destination.unlink()
        raise ValueError("File is empty.")

    return bytes_written


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _resolve_stored_file_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _safe_project_root(project_id: str) -> Path:
    root = project_dir(project_id).resolve()
    projects_root = PROJECTS_ROOT.resolve()
    if root == projects_root:
        raise HTTPException(status_code=500, detail="Refusing to delete the projects root folder.")
    try:
        inside_projects_root = root.is_relative_to(projects_root)
    except AttributeError:
        inside_projects_root = str(root).startswith(str(projects_root) + "\\") or str(root).startswith(str(projects_root) + "/")
    if not inside_projects_root:
        raise HTTPException(status_code=500, detail="Refusing to delete a project folder outside local storage.")
    return root


def _remove_project_tree(root: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            shutil.rmtree(root)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.08 * (attempt + 1))
        except OSError as exc:
            last_error = exc
            time.sleep(0.08 * (attempt + 1))
    raise HTTPException(
        status_code=500,
        detail="Could not delete all project files. Close audio players or Explorer windows opened inside this project folder and retry.",
    ) from last_error


def _ensure_data_defaults(data: dict[str, Any]) -> None:
    data.setdefault("projects", [])
    data.setdefault("detectionMemory", {"filenamePatterns": {}})
    data["detectionMemory"].setdefault("filenamePatterns", {})
    data.setdefault("vocalPresetLibrary", {"presets": []})
    data["vocalPresetLibrary"].setdefault("presets", [])


def _ensure_project_defaults(project: dict[str, Any]) -> None:
    project.setdefault("processingJobs", [])
    project.setdefault(
        "mixSettings",
        {
            "stems": [],
            "controls": _default_mix_controls(),
            "autoBalanceGeneratedAt": None,
            "autoBalanceAppliedAt": None,
            "roughMixWavPath": None,
            "roughMixMp3Path": None,
            "roughMixWavUrl": None,
            "roughMixMp3Url": None,
            "mixVersions": [],
            "latestMixVersionId": None,
            "updatedAt": None,
        },
    )
    project["mixSettings"].setdefault("stems", [])
    project["mixSettings"].setdefault("controls", _default_mix_controls())
    for key, value in _default_mix_controls().items():
        project["mixSettings"]["controls"].setdefault(key, value)
    project["mixSettings"].setdefault("autoBalanceGeneratedAt", None)
    project["mixSettings"].setdefault("autoBalanceAppliedAt", None)
    project["mixSettings"].setdefault("roughMixWavPath", None)
    project["mixSettings"].setdefault("roughMixMp3Path", None)
    project["mixSettings"].setdefault("roughMixWavUrl", None)
    project["mixSettings"].setdefault("roughMixMp3Url", None)
    project["mixSettings"].setdefault("mixVersions", [])
    project["mixSettings"].setdefault("latestMixVersionId", None)
    project["mixSettings"].setdefault("updatedAt", None)
    for setting in project["mixSettings"]["stems"]:
        setting.setdefault("processingChainEnabled", True)
        setting.setdefault("reverbSend", 35)
        setting.setdefault("delaySend", 0)
        setting.setdefault("presenceAmount", 0)
        setting.setdefault("compressionAmount", 50)
    for version in project["mixSettings"]["mixVersions"]:
        for source in version.get("sourceFiles", []):
            source.setdefault("delaySend", 0)
            source.setdefault("presenceAmount", 0)
            source.setdefault("compressionAmount", 50)
    project.setdefault(
        "masteringSettings",
        {
            "controls": _default_mastering_controls(),
            "masterVersions": [],
            "latestMasterVersionId": None,
            "exportFiles": [],
            "updatedAt": None,
        },
    )
    project["masteringSettings"].setdefault("controls", _default_mastering_controls())
    for key, value in _default_mastering_controls().items():
        project["masteringSettings"]["controls"].setdefault(key, value)
    project["masteringSettings"].setdefault("masterVersions", [])
    project["masteringSettings"].setdefault("latestMasterVersionId", None)
    project["masteringSettings"].setdefault("exportFiles", [])
    project["masteringSettings"].setdefault("updatedAt", None)
    project.setdefault("videoEditorSettings", _default_video_editor_settings())
    video_settings = project["videoEditorSettings"]
    video_defaults = _default_video_editor_settings()
    for key, value in video_defaults.items():
        video_settings.setdefault(key, value)
    video_settings.setdefault("overlay", {})
    video_settings["overlay"].setdefault("songTitle", None)
    video_settings["overlay"].setdefault("artistName", None)
    video_settings["overlay"].setdefault("sessionLabel", None)
    video_settings["overlay"].setdefault("position", "Lower Left")
    video_settings["overlay"].setdefault("style", "Boxed")
    video_settings["overlay"].setdefault("size", "Medium")
    video_settings.setdefault("watermark", video_defaults["watermark"])
    video_settings["watermark"].setdefault("enabled", False)
    video_settings["watermark"].setdefault("logo", None)
    video_settings["watermark"].setdefault("position", "Top Right")
    video_settings["watermark"].setdefault("opacity", 0.82)
    video_settings["watermark"].setdefault("scale", 0.14)
    video_settings.setdefault("introCard", video_defaults["introCard"])
    video_settings["introCard"].setdefault("enabled", False)
    video_settings["introCard"].setdefault("durationSeconds", 2.5)
    video_settings["introCard"].setdefault("title", None)
    video_settings["introCard"].setdefault("subtitle", None)
    video_settings.setdefault("outroCard", video_defaults["outroCard"])
    video_settings["outroCard"].setdefault("enabled", False)
    video_settings["outroCard"].setdefault("durationSeconds", 2.5)
    video_settings["outroCard"].setdefault("title", None)
    video_settings["outroCard"].setdefault("subtitle", None)
    video_settings.setdefault("autoSyncResult", video_defaults["autoSyncResult"])
    video_settings["autoSyncResult"].setdefault("status", "Not Run")
    video_settings["autoSyncResult"].setdefault("offsetMs", None)
    video_settings["autoSyncResult"].setdefault("confidence", None)
    video_settings["autoSyncResult"].setdefault("analyzedAt", None)
    video_settings["autoSyncResult"].setdefault("message", None)
    project.setdefault("detectionSummary", {"learnedPatternCount": 0, "confidentPendingCount": 0, "acceptedCount": 0})
    project["detectionSummary"].setdefault("learnedPatternCount", 0)
    project["detectionSummary"].setdefault("confidentPendingCount", 0)
    project["detectionSummary"].setdefault("acceptedCount", 0)

    for stem in project.get("stems", []):
        stem.setdefault("analysisStatus", "Pending")
        stem.setdefault("analysisResult", None)
        if stem.get("analysisResult") is not None:
            stem["analysisResult"].setdefault("warnings", [])
        stem.setdefault("autoBalanceSuggestion", None)
        stem.setdefault("detectionResult", None)
        stem.setdefault(
            "cleaningSettings",
            {
                "enabled": False,
                "mode": "Off",
                "humRemoval": False,
                "humFrequency": 60,
                "useCleanedInMix": True,
            },
        )
        stem["cleaningSettings"].setdefault("enabled", False)
        stem["cleaningSettings"].setdefault("mode", "Off")
        stem["cleaningSettings"].setdefault("humRemoval", False)
        stem["cleaningSettings"].setdefault("humFrequency", 60)
        stem["cleaningSettings"].setdefault("useCleanedInMix", True)
        stem.setdefault("cleaningStatus", "Not Cleaned")
        stem.setdefault("cleaningResult", None)
        stem.setdefault(
            "vocalEnhancementSettings",
            {
                "enabled": False,
                "preset": "AI Pop Clean",
                "pitchCorrection": "Off",
                "key": "Auto",
                "scale": "Major",
                "fxStyle": "Dry",
                "fxAmount": 0,
                "bodyAmount": 0,
                "presenceAmount": 0,
                "airAmount": 0,
                "deEssAmount": 50,
                "compressionAmount": 40,
                "riderAmount": 36,
                "saturationAmount": 18,
                "doublerAmount": 16,
                "pitchStrength": 42,
                "pitchHumanize": 72,
                "useEnhancedInMix": True,
            },
        )
        stem["vocalEnhancementSettings"].setdefault("enabled", False)
        stem["vocalEnhancementSettings"].setdefault("preset", "AI Pop Clean")
        stem["vocalEnhancementSettings"].setdefault("pitchCorrection", "Off")
        stem["vocalEnhancementSettings"].setdefault("key", "Auto")
        stem["vocalEnhancementSettings"].setdefault("scale", "Major")
        stem["vocalEnhancementSettings"].setdefault("fxStyle", "Dry")
        stem["vocalEnhancementSettings"].setdefault("fxAmount", 0)
        stem["vocalEnhancementSettings"].setdefault("bodyAmount", 0)
        stem["vocalEnhancementSettings"].setdefault("presenceAmount", 0)
        stem["vocalEnhancementSettings"].setdefault("airAmount", 0)
        stem["vocalEnhancementSettings"].setdefault("deEssAmount", 50)
        stem["vocalEnhancementSettings"].setdefault("compressionAmount", 40)
        stem["vocalEnhancementSettings"].setdefault("riderAmount", 36)
        stem["vocalEnhancementSettings"].setdefault("saturationAmount", 18)
        stem["vocalEnhancementSettings"].setdefault("doublerAmount", 16)
        stem["vocalEnhancementSettings"].setdefault("breathReductionAmount", 35)
        stem["vocalEnhancementSettings"].setdefault("mouthClickReductionAmount", 30)
        stem["vocalEnhancementSettings"].setdefault("pitchStrength", 42)
        stem["vocalEnhancementSettings"].setdefault("pitchHumanize", 72)
        stem["vocalEnhancementSettings"].setdefault("useEnhancedInMix", True)
        stem.setdefault("vocalEnhancementStatus", "Not Enhanced")
        stem.setdefault("vocalEnhancementResult", None)
        stem.setdefault("vocalAnalysisResult", None)
        if "stemTypeSource" not in stem:
            stem["stemTypeSource"] = "Manual" if stem.get("stemType", "Unknown") != "Unknown" else "Unknown"
        stem.setdefault(
            "metadata",
            {
                "durationSeconds": None,
                "sampleRate": None,
                "channels": None,
            },
        )


def display_path(path: Path) -> str:
    return _display_path(path)


def resolve_stored_file_path(path_value: str) -> Path:
    return _resolve_stored_file_path(path_value)


def remember_filename_correction(data: dict[str, Any], filename: str, stem_type: str) -> None:
    if stem_type == "Unknown":
        return
    _ensure_data_defaults(data)
    now = utc_now_iso()
    patterns = data["detectionMemory"]["filenamePatterns"]
    for token in filename_learning_tokens(filename):
        entry = patterns.get(token, {"stemType": stem_type, "count": 0, "createdAt": now, "typeCounts": {}})
        type_counts = entry.setdefault("typeCounts", {})
        if not type_counts and entry.get("stemType") in STEM_TYPE_MEMORY_VALUES:
            type_counts[entry["stemType"]] = int(entry.get("count", 0))
        type_counts[stem_type] = int(type_counts.get(stem_type, 0)) + 1
        sorted_counts = sorted(type_counts.items(), key=lambda item: item[1], reverse=True)
        entry["stemType"] = sorted_counts[0][0]
        entry["ambiguous"] = len(type_counts) > 1
        entry["count"] = sum(int(count) for count in type_counts.values())
        entry["updatedAt"] = now
        patterns[token] = entry


def filename_learning_tokens(filename: str) -> list[str]:
    base = Path(filename).stem.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", base) if token]
    compact = re.sub(r"[^a-z0-9]+", "", base)
    ignored = {"l", "r", "left", "right", "mono", "stereo", "stem", "track", "tracks", "mix", "take", "final", "wav", "mp3", "flac", "aiff", "dry", "wet"}
    learned = []
    for token in [*tokens, compact]:
        if len(token) < 2 or token.isdigit() or token in ignored:
            continue
        if token not in learned:
            learned.append(token)
    return learned[:8]


def _mark_type_dependent_mix_stale(project: dict[str, Any], stem_id: str) -> None:
    stem = next((item for item in project.get("stems", []) if item.get("id") == stem_id), None)
    if stem:
        stem["autoBalanceSuggestion"] = None
    mix_settings = project.get("mixSettings")
    if not mix_settings:
        return
    for setting in mix_settings.get("stems", []):
        if setting.get("stemId") == stem_id:
            setting["autoBalanceApplied"] = False
    mix_settings["autoBalanceGeneratedAt"] = None
    mix_settings["autoBalanceAppliedAt"] = None
    mix_settings["roughMixWavPath"] = None
    mix_settings["roughMixMp3Path"] = None
    mix_settings["roughMixWavUrl"] = None
    mix_settings["roughMixMp3Url"] = None
    mix_settings["updatedAt"] = utc_now_iso()


def _refresh_detection_summary(project: dict[str, Any], data: dict[str, Any]) -> None:
    patterns = data.setdefault("detectionMemory", {}).setdefault("filenamePatterns", {})
    confident_pending = 0
    accepted = 0
    for stem in project.get("stems", []):
        detection = stem.get("detectionResult")
        if not detection:
            continue
        if stem.get("stemTypeSource") == "Manual" and stem.get("stemType") != "Unknown":
            continue
        if detection.get("accepted"):
            accepted += 1
        elif detection.get("suggestedStemType") != "Unknown" and int(detection.get("confidence", 0)) >= 60:
            confident_pending += 1
    project["detectionSummary"] = {
        "learnedPatternCount": len(patterns),
        "confidentPendingCount": confident_pending,
        "acceptedCount": accepted,
    }


def _default_mix_controls() -> dict[str, float | str]:
    return {
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
    }


def _default_mastering_controls() -> dict[str, float | str | None]:
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


def _default_video_editor_settings() -> dict[str, Any]:
    return {
        "rawVideo": None,
        "rawVideos": [],
        "selectedAudioAssetId": None,
        "selectedAudioAssetKind": None,
        "selectedAudioAssetPath": None,
        "useSelectedMasterAudio": True,
        "useOriginalVideoAudio": False,
        "audioOffsetMs": 0,
        "trimStartSeconds": 0,
        "trimEndSeconds": 0,
        "fadeInSeconds": 0,
        "fadeOutSeconds": 0,
        "exportPreset": "YouTube 1080p",
        "assembly": {
            "transitionStyle": "Crossfade",
            "transitionDurationSeconds": 0.45,
        },
        "overlay": {
            "songTitle": None,
            "artistName": None,
            "sessionLabel": None,
            "position": "Lower Left",
            "style": "Boxed",
            "size": "Medium",
        },
        "watermark": {
            "enabled": False,
            "logo": None,
            "position": "Top Right",
            "opacity": 0.82,
            "scale": 0.14,
        },
        "introCard": {
            "enabled": False,
            "durationSeconds": 2.5,
            "title": None,
            "subtitle": None,
        },
        "outroCard": {
            "enabled": False,
            "durationSeconds": 2.5,
            "title": None,
            "subtitle": None,
        },
        "autoSyncResult": {
            "status": "Not Run",
            "offsetMs": None,
            "confidence": None,
            "analyzedAt": None,
            "message": None,
        },
        "brandingTemplates": [],
        "previewRender": None,
        "finalExport": None,
        "finalExports": [],
        "updatedAt": None,
    }
