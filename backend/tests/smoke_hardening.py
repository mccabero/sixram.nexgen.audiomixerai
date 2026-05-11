import io
import os
import sys
import tempfile
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AUDIO_MIXER_STORAGE_ROOT"] = tmp

        from fastapi.testclient import TestClient
        import numpy as np

        from app.main import app
        from app.storage import mark_interrupted_jobs, store
        from app.video_editor import AUDIO_ALIGN_SAMPLE_RATE, _estimate_audio_offset_ms, _synced_focus_source_start, queue_video_preview_job

        client = TestClient(app)
        health = client.get("/api/health")
        assert health.status_code == 200, health.text
        payload = health.json()
        assert payload["audioEnvironment"]["ffmpeg"]["ok"], payload

        sr = AUDIO_ALIGN_SAMPLE_RATE
        master_audio = np.zeros(sr * 4, dtype=np.float32)
        video_audio = np.zeros_like(master_audio)
        pattern = np.sin(np.linspace(0, np.pi * 18, sr // 2, dtype=np.float32))
        master_audio[sr : sr + pattern.size] = pattern
        video_audio[sr + sr // 2 : sr + sr // 2 + pattern.size] = pattern
        offset_ms, confidence = _estimate_audio_offset_ms(video_audio, master_audio)
        assert offset_ms == 500, offset_ms
        assert confidence > 0.1, confidence

        long_master = np.zeros(sr * 30, dtype=np.float32)
        long_video = np.zeros_like(long_master)
        long_master[sr * 3 : sr * 3 + pattern.size] = pattern
        long_video[sr * 15 : sr * 15 + pattern.size] = pattern
        long_offset_ms, long_confidence = _estimate_audio_offset_ms(long_video, long_master)
        assert long_offset_ms == 12000, long_offset_ms
        assert long_confidence > 0.1, long_confidence

        primary_clip = {"audioOffsetMs": 49188, "durationSeconds": 311.03}
        focus_clip = {"audioOffsetMs": 1278, "durationSeconds": 261.46}
        assert _synced_focus_source_start(primary_clip, focus_clip, {"sourceStart": 29.559, "duration": 10.0}) is None
        synced_source = _synced_focus_source_start(primary_clip, focus_clip, {"sourceStart": 64.118, "duration": 10.0})
        assert synced_source == 16.208, synced_source

        project = client.post("/api/projects", json={"name": "Hardening Smoke"}).json()
        project_id = project["id"]
        logs = client.get(f"/api/projects/{project_id}/logs")
        assert logs.status_code == 200, logs.text
        assert logs.json()["lines"], logs.json()

        upload = client.post(
            f"/api/projects/{project_id}/stems",
            files=[("files", ("not-a-real-stem.wav", io.BytesIO(b"this is not audio"), "audio/wav"))],
        )
        assert upload.status_code == 200, upload.text
        upload_payload = upload.json()
        assert upload_payload["uploaded"] == [], upload_payload
        assert upload_payload["errors"], upload_payload

        detail = client.get(f"/api/projects/{project_id}").json()
        assert detail["stems"] == [], detail
        original_dir = Path(tmp) / "projects" / project_id / "original"
        assert not list(original_dir.glob("*")), list(original_dir.glob("*"))

        data = store.load()
        stored_project = next(item for item in data["projects"] if item["id"] == project_id)
        stored_project["processingJobs"].append(
            {
                "id": "interrupted-job",
                "projectId": project_id,
                "type": "Analysis",
                "status": "Processing",
                "progress": 12,
                "currentStemId": None,
                "message": "Synthetic running job.",
                "errors": [],
                "createdAt": "2026-05-03T00:00:00+00:00",
                "updatedAt": "2026-05-03T00:00:00+00:00",
                "completedAt": None,
            }
        )
        store.save(data)
        assert mark_interrupted_jobs() == 1
        detail = client.get(f"/api/projects/{project_id}").json()
        job = next(item for item in detail["processingJobs"] if item["id"] == "interrupted-job")
        assert job["status"] == "Failed", job
        assert job["errors"], job

        project_root = Path(tmp) / "projects" / project_id
        raw_video_path = project_root / "video" / "raw" / "primary.mov"
        raw_video_path.parent.mkdir(parents=True, exist_ok=True)
        raw_video_path.write_bytes(b"placeholder video")
        master_path = project_root / "exports" / "masters" / "master.wav"
        master_path.parent.mkdir(parents=True, exist_ok=True)
        master_path.write_bytes(b"placeholder audio")
        raw_video = {
            "id": "primary-video",
            "projectId": project_id,
            "role": "Primary",
            "originalFilename": "primary.mov",
            "storedFilename": "primary.mov",
            "filePath": str(raw_video_path),
            "fileUrl": f"/media/projects/{project_id}/video/raw/primary.mov",
            "fileSize": raw_video_path.stat().st_size,
            "uploadedAt": "2026-05-03T00:00:00+00:00",
            "durationSeconds": 12.0,
            "width": 1280,
            "height": 720,
            "fps": 30.0,
            "hasAudioTrack": True,
        }
        data = store.load()
        stored_project = next(item for item in data["projects"] if item["id"] == project_id)
        stored_project["masteringSettings"]["masterVersions"].append(
            {
                "id": "master-audio",
                "label": "Master",
                "createdAt": "2026-05-03T00:00:00+00:00",
                "filePath": str(master_path),
                "fileUrl": f"/media/projects/{project_id}/exports/masters/master.wav",
                "sizeBytes": master_path.stat().st_size,
                "report": {"durationSeconds": 12.0},
                "outputFormat": "WAV 16-bit",
            }
        )
        settings = stored_project["videoEditorSettings"]
        settings["rawVideo"] = raw_video
        settings["rawVideos"] = [raw_video]
        settings["selectedAudioAssetId"] = "master-audio"
        settings["useSelectedMasterAudio"] = True
        settings["useOriginalVideoAudio"] = False
        store.save(data)

        first_video_job = queue_video_preview_job(project_id)
        second_video_job = queue_video_preview_job(project_id)
        assert first_video_job.should_start is True, first_video_job
        assert second_video_job.should_start is False, second_video_job
        assert second_video_job.job.id == first_video_job.job.id
        assert mark_interrupted_jobs() == 1

        export_marker = project_root / "exports" / "delete-me.txt"
        export_marker.parent.mkdir(parents=True, exist_ok=True)
        export_marker.write_text("generated project file", encoding="utf-8")
        assert export_marker.exists()

        deleted = client.delete(f"/api/projects/{project_id}")
        assert deleted.status_code == 200, deleted.text
        assert not project_root.exists(), project_root
        assert all(item["id"] != project_id for item in client.get("/api/projects").json())
        missing = client.get(f"/api/projects/{project_id}")
        assert missing.status_code == 404, missing.text

    print("Hardening smoke test passed")


if __name__ == "__main__":
    main()
