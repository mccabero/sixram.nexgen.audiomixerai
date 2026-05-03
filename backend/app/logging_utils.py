from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_project_log(logs_dir: Path, message: str) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    line = f"{utc_now_iso()} {message}\n"
    for filename in ("processing.log", "phase1.log"):
        with (logs_dir / filename).open("a", encoding="utf-8") as log_file:
            log_file.write(line)
