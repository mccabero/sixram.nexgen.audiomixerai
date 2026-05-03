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


def make_wav(path: Path, frequency: float, gain: float = 0.22, seconds: float = 1.0) -> None:
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
        files = [
            ("lead_vocal.wav", "Lead Vocal", 220, 0.2),
            ("bgv_left.wav", "Backing Vocal", 330, 0.11),
            ("bgv_right.wav", "Backing Vocal", 350, 0.11),
            ("kick.wav", "Kick", 70, 0.26),
            ("bass.wav", "Bass", 110, 0.22),
            ("egtr_l.wav", "Electric Guitar", 440, 0.16),
        ]
        for filename, _stem_type, frequency, gain in files:
            make_wav(fixture_dir / filename, frequency, gain)

        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "Phase 5 Smoke"}).json()
        project_id = project["id"]

        upload_files = []
        handles = []
        try:
            for filename, _stem_type, _frequency, _gain in files:
                handle = (fixture_dir / filename).open("rb")
                handles.append(handle)
                upload_files.append(("files", (filename, handle, "audio/wav")))
            upload = client.post(f"/api/projects/{project_id}/stems", files=upload_files)
        finally:
            for handle in handles:
                handle.close()
        assert upload.status_code == 200, upload.text
        stems = upload.json()["uploaded"]

        for stem, (_filename, stem_type, _frequency, _gain) in zip(stems, files):
            typed = client.patch(f"/api/projects/{project_id}/stems/{stem['id']}", json={"stemType": stem_type})
            assert typed.status_code == 200, typed.text

        analysis_job = create_analysis_job(project_id)
        run_analysis_job(project_id, analysis_job.id)

        auto_balance = client.post(f"/api/projects/{project_id}/auto-balance")
        assert auto_balance.status_code == 200, auto_balance.text
        apply_balance = client.post(f"/api/projects/{project_id}/apply-auto-balance")
        assert apply_balance.status_code == 200, apply_balance.text

        presets = client.get("/api/mix-presets")
        assert presets.status_code == 200, presets.text
        assert any(item["name"] == "Rock Band" for item in presets.json()["presets"])

        controls = client.patch(
            f"/api/projects/{project_id}/mix-controls",
            json={"preset": "Rock Band", "vocalBusLevel": 0.5, "vocalGlueAmount": 70, "vocalDelayAmount": 35, "backingVocalWidth": 72},
        )
        assert controls.status_code == 200, controls.text
        assert controls.json()["mixSettings"]["controls"]["preset"] == "Rock Band"
        assert controls.json()["mixSettings"]["controls"]["vocalGlueAmount"] == 70

        reset = client.post(f"/api/projects/{project_id}/reset-advanced-mix")
        assert reset.status_code == 200, reset.text
        first_stem = reset.json()["stems"][0]
        stem_setting = client.patch(
            f"/api/projects/{project_id}/mix-settings/{first_stem['id']}",
            json={"processingChainEnabled": True, "reverbSend": 42, "compressionAmount": 68},
        )
        assert stem_setting.status_code == 200, stem_setting.text

        first_mix = client.post(f"/api/projects/{project_id}/advanced-mix")
        assert first_mix.status_code == 200, first_mix.text
        first_version = first_mix.json()
        assert first_version["versionNumber"] == 1, first_version
        assert first_version["preset"] == "Rock Band", first_version
        assert "processed/mixes/mix_v001.wav" in first_version["wavPath"], first_version
        assert resolve_stored_file_path(first_version["wavPath"]).exists(), first_version
        assert resolve_stored_file_path(first_version["metadataPath"]).exists(), first_version
        assert first_version["sourceFiles"], first_version
        assert any(source["stemType"] == "Backing Vocal" for source in first_version["sourceFiles"]), first_version
        assert first_version["integratedLufs"] is not None, first_version

        renamed = client.patch(f"/api/projects/{project_id}/mix-versions/{first_version['id']}", json={"label": "Rock Balance A"})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["label"] == "Rock Balance A"

        second_job = client.post(f"/api/projects/{project_id}/advanced-mix-job")
        assert second_job.status_code == 200, second_job.text
        completed_job = client.get(f"/api/projects/{project_id}/jobs/{second_job.json()['id']}")
        assert completed_job.status_code == 200, completed_job.text
        assert completed_job.json()["status"] == "Completed", completed_job.json()

        project = client.get(f"/api/projects/{project_id}").json()
        second_version = project["mixSettings"]["mixVersions"][-1]
        assert second_version["versionNumber"] == 2, second_version
        assert "processed/mixes/mix_v002.wav" in second_version["wavPath"], second_version
        assert resolve_stored_file_path(second_version["wavPath"]).exists(), second_version

        instrumental_job = client.post(f"/api/projects/{project_id}/instrumental-mix-job")
        assert instrumental_job.status_code == 200, instrumental_job.text
        completed_instrumental = client.get(f"/api/projects/{project_id}/jobs/{instrumental_job.json()['id']}")
        assert completed_instrumental.status_code == 200, completed_instrumental.text
        assert completed_instrumental.json()["status"] == "Completed", completed_instrumental.json()

        project = client.get(f"/api/projects/{project_id}").json()
        versions = project["mixSettings"]["mixVersions"]
        assert len(versions) == 3, versions
        instrumental_version = versions[-1]
        assert instrumental_version["label"].startswith("Instrumental"), instrumental_version
        assert all(source["stemType"] not in {"Lead Vocal", "Backing Vocal"} for source in instrumental_version["sourceFiles"]), instrumental_version
        assert project["mixSettings"]["latestMixVersionId"] == instrumental_version["id"], project["mixSettings"]

        first_wav = resolve_stored_file_path(first_version["wavPath"])
        deleted = client.delete(f"/api/projects/{project_id}/mix-versions/{first_version['id']}")
        assert deleted.status_code == 200, deleted.text
        assert not first_wav.exists(), first_wav
        project = client.get(f"/api/projects/{project_id}").json()
        assert len(project["mixSettings"]["mixVersions"]) == 2, project["mixSettings"]["mixVersions"]

    print("Phase 5 smoke test passed")


if __name__ == "__main__":
    main()
