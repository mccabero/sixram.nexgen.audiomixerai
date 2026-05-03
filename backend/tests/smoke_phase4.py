import math
import os
import random
import struct
import sys
import tempfile
import wave
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def make_noisy_wav(path: Path) -> None:
    sample_rate = 44100
    frames = sample_rate
    random.seed(4)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        for index in range(frames):
            vocal = 0.18 * math.sin(2 * math.pi * 220 * index / sample_rate)
            hum = 0.04 * math.sin(2 * math.pi * 60 * index / sample_rate)
            noise = random.uniform(-0.025, 0.025)
            sample = max(-0.95, min(0.95, vocal + hum + noise))
            audio.writeframes(struct.pack("<h", int(sample * 32767)))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AUDIO_MIXER_STORAGE_ROOT"] = tmp

        from fastapi.testclient import TestClient

        from app.cleaning import create_cleaning_job, run_cleaning_job
        from app.main import app
        from app.phase2 import _rough_mix_inputs
        from app.storage import resolve_stored_file_path, store

        fixture_dir = Path(tmp) / "fixtures"
        fixture_dir.mkdir()
        vocal = fixture_dir / "lead_vocal_noisy.wav"
        make_noisy_wav(vocal)

        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "Phase 4 Smoke"}).json()
        project_id = project["id"]
        updated_project = client.patch(
            f"/api/projects/{project_id}",
            json={"name": "Phase 4 Smoke Edited", "artistName": "Local Band", "songTitle": "Noisy Test", "notes": "Updated locally."},
        )
        assert updated_project.status_code == 200, updated_project.text
        assert updated_project.json()["name"] == "Phase 4 Smoke Edited"
        assert updated_project.json()["artistName"] == "Local Band"

        with vocal.open("rb") as file:
            upload = client.post(f"/api/projects/{project_id}/stems", files=[("files", ("lead_vocal_noisy.wav", file, "audio/wav"))])
        assert upload.status_code == 200, upload.text
        stem = upload.json()["uploaded"][0]

        typed = client.patch(f"/api/projects/{project_id}/stems/{stem['id']}", json={"stemType": "Lead Vocal"})
        assert typed.status_code == 200, typed.text

        settings = client.patch(
            f"/api/projects/{project_id}/stems/{stem['id']}/cleaning",
            json={"enabled": True, "mode": "Medium", "humRemoval": True, "humFrequency": 60, "useCleanedInMix": True},
        )
        assert settings.status_code == 200, settings.text
        assert settings.json()["cleaningSettings"]["mode"] == "Medium"

        job = create_cleaning_job(project_id)
        run_cleaning_job(project_id, job.id)

        project = client.get(f"/api/projects/{project_id}").json()
        cleaned_stem = project["stems"][0]
        result = cleaned_stem["cleaningResult"]
        assert result["status"] == "Completed", result
        assert "processed/cleaned" in result["cleanedFilePath"], result
        assert resolve_stored_file_path(result["cleanedFilePath"]).exists(), result
        assert result["originalMetrics"]["peakDbfs"] is not None, result
        assert result["cleanedMetrics"]["peakDbfs"] is not None, result
        assert "noiseFloorDbfs" in result["metricDeltas"], result

        data = store.load()
        stored_project = data["projects"][0]
        inputs = _rough_mix_inputs(stored_project)
        assert "processed\\cleaned" in str(inputs[0]["path"]) or "processed/cleaned" in str(inputs[0]["path"]), inputs

        rough = client.post(f"/api/projects/{project_id}/rough-mix")
        assert rough.status_code == 200, rough.text

    print("Phase 4 smoke test passed")


if __name__ == "__main__":
    main()
