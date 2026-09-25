"""Smoke test for Phase 8 - Stem Splitter.

Two things matter here and neither needs a real separation run:

1. The splitter degrades safely. With torch/demucs absent the backend must still
   boot and every existing project endpoint must behave exactly as before.
2. The audio maths the module owns (WAV round-trip, level metering) is correct.

A real separation takes minutes on CPU, so it is deliberately out of scope.
"""

import math
import os
import struct
import sys
import tempfile
import wave
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{label} failed. {detail}".strip())
    print(f"  ok  {label}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AUDIO_MIXER_STORAGE_ROOT"] = tmp

        import numpy as np
        from fastapi.testclient import TestClient

        from app.main import app
        from app.stem_splitter import _levels, _read_wav, _write_wav, separation_environment

        client = TestClient(app)

        print("environment")
        env = client.get("/api/splits/environment")
        check("environment endpoint answers", env.status_code == 200, str(env.status_code))
        env_body = env.json()
        check("environment reports a models list", isinstance(env_body.get("models"), list))
        separation_ready = bool(env_body.get("ok"))
        print(f"  ..  separation available: {separation_ready}")

        print("splits collection")
        listing = client.get("/api/splits")
        check("splits list answers", listing.status_code == 200, str(listing.status_code))
        check("splits list starts empty", listing.json() == [], str(listing.json()))

        missing = client.get("/api/splits/does-not-exist")
        check("unknown split is 404", missing.status_code == 404, str(missing.status_code))

        active = client.get("/api/splits/active")
        check("active split endpoint answers", active.status_code == 200, str(active.status_code))
        check("nothing is active", active.json().get("active") is None, str(active.json()))

        retry_missing = client.post("/api/splits/does-not-exist/retry")
        check("retry of unknown split is 404", retry_missing.status_code == 404, str(retry_missing.status_code))

        archive_missing = client.post("/api/splits/does-not-exist/archive")
        check("archive of unknown split is 404", archive_missing.status_code == 404, str(archive_missing.status_code))

        print("input validation")
        bad_url = client.post("/api/splits", json={"url": "not-a-url", "stemSet": "6"})
        if separation_ready:
            check("bad URL rejected", bad_url.status_code == 400, str(bad_url.status_code))
        else:
            # Without torch the dependency check fires first, which is the point.
            check("splitting unavailable is 503", bad_url.status_code == 503, str(bad_url.status_code))
            check(
                "503 explains how to install",
                "pip install" in bad_url.json().get("detail", ""),
                bad_url.json().get("detail", ""),
            )

        print("isolation from the mix and mastering flow")
        health = client.get("/api/health")
        check("health still answers", health.status_code == 200, str(health.status_code))

        created = client.post("/api/projects", json={"name": "Phase 8 isolation check"})
        check("project creation still works", created.status_code == 200, str(created.status_code))
        project_id = created.json()["id"]

        projects = client.get("/api/projects")
        check("project listing still works", projects.status_code == 200)
        check("created project is listed", any(item["id"] == project_id for item in projects.json()))

        detail = client.get(f"/api/projects/{project_id}")
        check("project detail still works", detail.status_code == 200)
        check("project has no split fields leaking in", "splits" not in detail.json())

        stem_types = client.get("/api/stem-types")
        check("stem types still answer", stem_types.status_code == 200)

        removed = client.delete(f"/api/projects/{project_id}")
        check("project deletion still works", removed.status_code == 200, str(removed.status_code))

        print("metadata shape")
        db_path = Path(tmp) / "app_data.json"
        check("database file exists", db_path.exists())
        import json

        data = json.loads(db_path.read_text(encoding="utf-8"))
        check("splits key present", "splits" in data, str(list(data.keys())))
        check("projects key untouched", isinstance(data.get("projects"), list))

        print("audio helpers")
        sample_rate = 44100
        seconds = 0.5
        frames = int(sample_rate * seconds)
        tone = np.zeros((2, frames), dtype=np.float32)
        for index in range(frames):
            tone[0][index] = 0.5 * math.sin(2 * math.pi * 440 * index / sample_rate)
            tone[1][index] = 0.5 * math.sin(2 * math.pi * 440 * index / sample_rate)

        round_trip = Path(tmp) / "tone.wav"
        _write_wav(round_trip, tone, sample_rate)
        check("wav written", round_trip.exists())

        restored, restored_rate = _read_wav(round_trip)
        check("sample rate preserved", restored_rate == sample_rate, str(restored_rate))
        check("channel count preserved", restored.shape[0] == 2, str(restored.shape))
        check("frame count preserved", abs(restored.shape[1] - frames) <= 1, str(restored.shape))
        drift = float(np.max(np.abs(restored[:, :frames] - tone)))
        check("round trip is sample accurate", drift < 0.001, f"max drift {drift}")

        peak_db, rms_db = _levels(tone)
        # A 0.5 amplitude sine: peak -6 dBFS, RMS 3 dB below that.
        check("peak level correct", abs(peak_db - (-6.0)) < 0.2, f"got {peak_db}")
        check("rms level correct", abs(rms_db - (-9.0)) < 0.3, f"got {rms_db}")

        silence = np.zeros((2, 128), dtype=np.float32)
        silent_peak, silent_rms = _levels(silence)
        check("silence does not blow up", silent_peak == -99.0 and silent_rms == -99.0)

        print("environment helper")
        direct = separation_environment()
        check("helper agrees with endpoint", bool(direct["ok"]) == separation_ready)
        check("helper lists missing packages", isinstance(direct["missing"], list))

    print("\nphase 8 smoke passed")


if __name__ == "__main__":
    main()
