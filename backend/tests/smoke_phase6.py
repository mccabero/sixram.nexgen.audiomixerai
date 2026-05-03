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


def make_wav(path: Path, frequency: float, gain: float = 0.2, seconds: float = 1.2) -> None:
    sample_rate = 44100
    frames = int(sample_rate * seconds)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        for index in range(frames):
            sample = gain * math.sin(2 * math.pi * frequency * index / sample_rate)
            audio.writeframes(struct.pack("<h", int(max(-0.95, min(0.95, sample)) * 32767)))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AUDIO_MIXER_STORAGE_ROOT"] = tmp

        from fastapi.testclient import TestClient

        from app.main import app
        from app.phase2 import create_analysis_job, run_analysis_job
        from app.storage import resolve_stored_file_path

        fixture_dir = Path(tmp) / "fixtures"
        fixture_dir.mkdir()
        fixtures = [
            ("lead_vocal.wav", "Lead Vocal", 220, 0.2),
            ("drums.wav", "Drums", 90, 0.24),
            ("bass.wav", "Bass", 110, 0.22),
            ("egtr.wav", "Electric Guitar", 440, 0.15),
        ]
        for filename, _stem_type, frequency, gain in fixtures:
            make_wav(fixture_dir / filename, frequency, gain)

        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "Phase 6 Smoke"}).json()
        project_id = project["id"]

        handles = []
        upload_files = []
        try:
            for filename, _stem_type, _frequency, _gain in fixtures:
                handle = (fixture_dir / filename).open("rb")
                handles.append(handle)
                upload_files.append(("files", (filename, handle, "audio/wav")))
            upload = client.post(f"/api/projects/{project_id}/stems", files=upload_files)
        finally:
            for handle in handles:
                handle.close()
        assert upload.status_code == 200, upload.text
        stems = upload.json()["uploaded"]

        for stem, (_filename, stem_type, _frequency, _gain) in zip(stems, fixtures):
            typed = client.patch(f"/api/projects/{project_id}/stems/{stem['id']}", json={"stemType": stem_type})
            assert typed.status_code == 200, typed.text

        analysis_job = create_analysis_job(project_id)
        run_analysis_job(project_id, analysis_job.id)
        assert client.post(f"/api/projects/{project_id}/auto-balance").status_code == 200
        assert client.post(f"/api/projects/{project_id}/apply-auto-balance").status_code == 200

        assert client.patch(f"/api/projects/{project_id}/mix-controls", json={"preset": "Balanced"}).status_code == 200
        mix_one = client.post(f"/api/projects/{project_id}/advanced-mix")
        assert mix_one.status_code == 200, mix_one.text
        assert mix_one.json()["versionNumber"] == 1

        assert client.patch(f"/api/projects/{project_id}/mix-controls", json={"preset": "Rock Band"}).status_code == 200
        mix_two = client.post(f"/api/projects/{project_id}/advanced-mix")
        assert mix_two.status_code == 200, mix_two.text
        mix_two_payload = mix_two.json()
        assert mix_two_payload["versionNumber"] == 2

        presets = client.get("/api/mastering-presets")
        assert presets.status_code == 200, presets.text
        assert any(item["name"] == "Streaming" for item in presets.json()["presets"])

        controls = client.patch(
            f"/api/projects/{project_id}/mastering-controls",
            json={"selectedMixVersionId": mix_two_payload["id"], "preset": "Streaming", "outputFormat": "WAV 16-bit"},
        )
        assert controls.status_code == 200, controls.text

        master_wav = client.post(
            f"/api/projects/{project_id}/masters",
            json={
                "selectedMixVersionId": mix_two_payload["id"],
                "preset": "Streaming",
                "outputFormat": "WAV 16-bit",
                "brightness": 3,
                "warmth": 4,
                "compressionAmount": 45,
                "limiterStrength": 55,
                "stereoWidth": 56,
            },
        )
        assert master_wav.status_code == 200, master_wav.text
        master_one = master_wav.json()
        assert master_one["versionNumber"] == 1, master_one
        assert "exports/masters/master_v001.wav" in master_one["filePath"], master_one
        assert resolve_stored_file_path(master_one["filePath"]).exists(), master_one
        assert resolve_stored_file_path(master_one["reportJsonPath"]).exists(), master_one
        assert resolve_stored_file_path(master_one["reportTxtPath"]).exists(), master_one
        assert master_one["report"]["preset"] == "Streaming", master_one
        assert master_one["report"]["outputFormat"] == "WAV 16-bit", master_one

        master_mp3_job = client.post(
            f"/api/projects/{project_id}/masters-job",
            json={
                "selectedMixVersionId": mix_two_payload["id"],
                "preset": "Streaming",
                "outputFormat": "MP3 320kbps",
                "brightness": 0,
                "warmth": 0,
                "compressionAmount": 40,
                "limiterStrength": 55,
                "stereoWidth": 55,
            },
        )
        assert master_mp3_job.status_code == 200, master_mp3_job.text
        master_job = client.get(f"/api/projects/{project_id}/jobs/{master_mp3_job.json()['id']}")
        assert master_job.status_code == 200, master_job.text
        assert master_job.json()["status"] == "Completed", master_job.json()
        project_after_master_job = client.get(f"/api/projects/{project_id}").json()
        master_two = project_after_master_job["masteringSettings"]["masterVersions"][-1]
        assert "exports/masters/master_v002.mp3" in master_two["filePath"], master_two
        assert resolve_stored_file_path(master_two["filePath"]).exists(), master_two

        unmastered = client.post(
            f"/api/projects/{project_id}/exports/mix",
            json={"selectedMixVersionId": mix_two_payload["id"], "outputFormat": "FLAC"},
        )
        assert unmastered.status_code == 200, unmastered.text
        assert resolve_stored_file_path(unmastered.json()["filePath"]).exists(), unmastered.json()

        vocal_stem = next(stem for stem in stems if stem["originalFilename"] == "lead_vocal.wav")
        assert client.patch(f"/api/projects/{project_id}/mix-settings/{vocal_stem['id']}", json={"mute": True}).status_code == 200
        instrumental_mix = client.post(f"/api/projects/{project_id}/advanced-mix")
        assert instrumental_mix.status_code == 200, instrumental_mix.text
        instrumental = client.post(
            f"/api/projects/{project_id}/exports/instrumental",
            json={"selectedMixVersionId": instrumental_mix.json()["id"], "outputFormat": "WAV 24-bit"},
        )
        assert instrumental.status_code == 200, instrumental.text
        assert resolve_stored_file_path(instrumental.json()["filePath"]).exists(), instrumental.json()

        backup = client.post(f"/api/projects/{project_id}/exports/backup", json={"includeOriginalStems": False})
        assert backup.status_code == 200, backup.text
        assert backup.json()["filePath"].endswith(".zip"), backup.json()
        assert resolve_stored_file_path(backup.json()["filePath"]).exists(), backup.json()

        project = client.get(f"/api/projects/{project_id}").json()
        assert len(project["masteringSettings"]["masterVersions"]) == 2
        assert len(project["masteringSettings"]["exportFiles"]) >= 3
        assert project["status"] in {"Exported", "Master Ready"}

    print("Phase 6 smoke test passed")


if __name__ == "__main__":
    main()
