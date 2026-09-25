from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STORAGE_ROOT = BASE_DIR / "storage"

STORAGE_ROOT = Path(os.getenv("AUDIO_MIXER_STORAGE_ROOT", DEFAULT_STORAGE_ROOT)).resolve()
PROJECTS_ROOT = STORAGE_ROOT / "projects"
DB_PATH = STORAGE_ROOT / "app_data.json"

MAX_UPLOAD_MB = int(os.getenv("AUDIO_MIXER_MAX_UPLOAD_MB", "500"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_VIDEO_UPLOAD_MB = int(os.getenv("AUDIO_MIXER_MAX_VIDEO_UPLOAD_MB", "2048"))
MAX_VIDEO_UPLOAD_BYTES = MAX_VIDEO_UPLOAD_MB * 1024 * 1024
MAX_VIDEO_LOGO_UPLOAD_MB = int(os.getenv("AUDIO_MIXER_MAX_VIDEO_LOGO_UPLOAD_MB", "25"))
MAX_VIDEO_LOGO_UPLOAD_BYTES = MAX_VIDEO_LOGO_UPLOAD_MB * 1024 * 1024

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff", ".aif", ".webm"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
ALLOWED_VIDEO_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

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

# --- Phase 8: Stem Splitter -------------------------------------------------

SPLITS_ROOT = STORAGE_ROOT / "splits"

# A hard ceiling so a CPU separation cannot run away on a two-hour upload.
MAX_SPLIT_SECONDS = int(os.getenv("AUDIO_MIXER_MAX_SPLIT_SECONDS", "900"))

SPLIT_MODELS = {
    "6": "htdemucs_6s",
    "4": "htdemucs",
}

SPLIT_STEM_ORDER = ["vocals", "drums", "bass", "guitar", "piano", "other"]

# quality: how much to trust the stem. The UI warns on "limited".
SPLIT_STEM_PRESENTATION = {
    "vocals": {"label": "Vocals", "note": "lead + backing", "color": "#2dd4bf", "quality": "good"},
    "drums": {"label": "Drums", "note": "full kit", "color": "#f59e0b", "quality": "good"},
    "bass": {"label": "Bass", "note": "bass guitar", "color": "#a78bfa", "quality": "good"},
    "guitar": {"label": "Guitar", "note": "electric + acoustic", "color": "#f472b6", "quality": "fair"},
    "piano": {"label": "Piano", "note": "keys - expect bleed", "color": "#60a5fa", "quality": "limited"},
    "other": {"label": "Other", "note": "strings, fx, leftovers", "color": "#94a3b8", "quality": "fair"},
}

# --- Phase 9: Chord Sheets --------------------------------------------------

CHORDSHEETS_ROOT = STORAGE_ROOT / "chordsheets"

# Analysis runs well below the audio's own rate: chroma does not benefit from
# 44.1 kHz and the CQT is the expensive step.
ANALYSIS_SR = 22050
ANALYSIS_HOP = 512
BEATS_PER_BAR = 4

# Below this the UI dims the chord and marks it for checking. Calibrated so the
# flags land on genuinely ambiguous spots rather than on a third of the song.
LOW_CONFIDENCE = float(os.getenv("AUDIO_MIXER_CHORD_LOW_CONFIDENCE", "0.62"))

# Stems that carry harmony; a 4-stem split just contributes bass + other.
CHORD_HARMONY_STEMS = ("bass", "other", "guitar", "piano")

# Shapes a beginner can play open. Used only to rank tuning and capo options.
OPEN_SHAPES = {"E", "A", "D", "G", "C", "Em", "Am", "Dm"}

TUNING_LABELS = {
    0: "E Standard",
    1: "Eb Standard (half step down)",
    2: "D Standard (whole step down)",
    3: "C# Standard",
}

# Chord analysis rides on a split, so it inherits that ceiling.
MAX_CHORD_SHEET_SECONDS = int(os.getenv("AUDIO_MIXER_MAX_CHORD_SHEET_SECONDS", str(MAX_SPLIT_SECONDS)))
