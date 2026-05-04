from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STORAGE_ROOT = BASE_DIR / "storage"

STORAGE_ROOT = Path(os.getenv("AUDIO_MIXER_STORAGE_ROOT", DEFAULT_STORAGE_ROOT)).resolve()
PROJECTS_ROOT = STORAGE_ROOT / "projects"
DB_PATH = STORAGE_ROOT / "app_data.json"

MAX_UPLOAD_MB = int(os.getenv("AUDIO_MIXER_MAX_UPLOAD_MB", "500"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff", ".aif", ".webm"}

STEM_TYPES = [
    "Unknown",
    "Lead Vocal",
    "Backing Vocal",
    "Drums",
    "Kick",
    "Snare",
    "Bass",
    "Electric Guitar",
    "Acoustic Guitar",
    "Keys/Piano",
    "Pads/Strings",
    "FX/Ambience",
    "Other",
]

