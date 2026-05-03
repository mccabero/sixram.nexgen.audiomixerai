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


def make_wav(path: Path, frequency: float, amplitude: float) -> None:
    sample_rate = 44100
    duration_seconds = 1.0
    frames = int(sample_rate * duration_seconds)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        for index in range(frames):
            sample = int(amplitude * 32767 * math.sin(2 * math.pi * frequency * index / sample_rate))
            audio.writeframes(struct.pack("<h", sample))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AUDIO_MIXER_STORAGE_ROOT"] = tmp

        from fastapi.testclient import TestClient

        from app.main import app
        from app.phase2 import create_analysis_job, run_analysis_job

        fixture_dir = Path(tmp) / "fixtures"
        fixture_dir.mkdir()
        lead = fixture_dir / "lead.wav"
        bass = fixture_dir / "bass.wav"
        make_wav(lead, 220, 0.35)
        make_wav(bass, 110, 0.25)

        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "Phase 2 Smoke"}).json()
        project_id = project["id"]

        with lead.open("rb") as first, bass.open("rb") as second:
            upload = client.post(
                f"/api/projects/{project_id}/stems",
                files=[
                    ("files", ("lead.wav", first, "audio/wav")),
                    ("files", ("bass.wav", second, "audio/wav")),
                ],
            )
        assert upload.status_code == 200, upload.text
        stems = upload.json()["uploaded"]

        client.patch(f"/api/projects/{project_id}/stems/{stems[0]['id']}", json={"stemType": "Lead Vocal"})
        client.patch(f"/api/projects/{project_id}/stems/{stems[1]['id']}", json={"stemType": "Bass"})

        blocked = client.post(f"/api/projects/{project_id}/auto-balance")
        assert blocked.status_code == 400, blocked.text

        first_job = create_analysis_job(project_id)
        second_job = create_analysis_job(project_id)
        assert first_job.id == second_job.id
        run_analysis_job(project_id, first_job.id)

        detail = client.get(f"/api/projects/{project_id}").json()
        assert all(stem["analysisStatus"] == "Completed" for stem in detail["stems"]), detail
        assert all(stem["analysisResult"]["integratedLufs"] is not None for stem in detail["stems"]), detail

        balanced = client.post(f"/api/projects/{project_id}/auto-balance")
        assert balanced.status_code == 200, balanced.text
        applied = client.post(f"/api/projects/{project_id}/apply-auto-balance")
        assert applied.status_code == 200, applied.text
        assert all(setting["autoBalanceApplied"] for setting in applied.json()["mixSettings"]["stems"])

        preview = client.post(f"/api/projects/{project_id}/rough-mix")
        assert preview.status_code == 200, preview.text
        wav_path = Path(preview.json()["wavPath"])
        assert wav_path.exists(), wav_path

        delete = client.delete(f"/api/projects/{project_id}/stems/{stems[0]['id']}")
        assert delete.status_code == 200, delete.text
        detail = client.get(f"/api/projects/{project_id}").json()
        assert all(setting["stemId"] != stems[0]["id"] for setting in detail["mixSettings"]["stems"])
        assert detail["mixSettings"]["roughMixWavPath"] is None
        assert detail["mixSettings"]["roughMixMp3Path"] is None

    print("Phase 2 smoke test passed")


if __name__ == "__main__":
    main()
