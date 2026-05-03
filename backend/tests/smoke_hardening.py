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

        from app.main import app
        from app.storage import mark_interrupted_jobs, store

        client = TestClient(app)
        health = client.get("/api/health")
        assert health.status_code == 200, health.text
        payload = health.json()
        assert payload["audioEnvironment"]["ffmpeg"]["ok"], payload

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

    print("Hardening smoke test passed")


if __name__ == "__main__":
    main()
