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
    frames = sample_rate
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
        from app.stem_detection import _detect_from_filename, _detect_from_memory
        from app.storage import remember_filename_correction

        fixture_dir = Path(tmp) / "fixtures"
        fixture_dir.mkdir()
        bass = fixture_dir / "bass DI.wav"
        learned_left = fixture_dir / "CustomTone L.wav"
        learned_right = fixture_dir / "CustomTone R.wav"
        make_wav(bass, 82, 0.35)
        make_wav(learned_left, 330, 0.2)
        make_wav(learned_right, 440, 0.2)

        assert _detect_from_filename("Sige - 2 - Fender (A).wav")[0] == "Electric Guitar"
        assert _detect_from_filename("Sige - 3 - Laney (B).wav")[0] == "Electric Guitar"
        assert _detect_from_filename("Sige - 4 - Hartke (3).wav")[0] == "Bass"

        memory_data = {"projects": []}
        remember_filename_correction(memory_data, "SharedName - Guitar.wav", "Electric Guitar")
        remember_filename_correction(memory_data, "SharedName - Drums.wav", "Drums")
        assert memory_data["detectionMemory"]["filenamePatterns"]["sharedname"]["ambiguous"] is True
        assert _detect_from_memory("SharedName - Keys.wav", memory_data["detectionMemory"], set()) is None

        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "Phase 3 Smoke"}).json()
        project_id = project["id"]

        with bass.open("rb") as file:
            upload = client.post(f"/api/projects/{project_id}/stems", files=[("files", ("bass DI.wav", file, "audio/wav"))])
        assert upload.status_code == 200, upload.text
        bass_stem = upload.json()["uploaded"][0]

        detected = client.post(f"/api/projects/{project_id}/detect-stems")
        assert detected.status_code == 200, detected.text
        bass_detail = detected.json()["stems"][0]
        assert bass_detail["detectionResult"]["suggestedStemType"] == "Bass", bass_detail
        assert bass_detail["detectionResult"]["confidence"] >= 60, bass_detail

        accepted_all = client.post(f"/api/projects/{project_id}/accept-all-detections")
        assert accepted_all.status_code == 200, accepted_all.text
        bass_detail = accepted_all.json()["stems"][0]
        assert bass_detail["stemType"] == "Bass"
        assert bass_detail["stemTypeSource"] == "Detected"
        assert accepted_all.json()["detectionSummary"]["confidentPendingCount"] == 0

        with learned_left.open("rb") as file:
            upload = client.post(f"/api/projects/{project_id}/stems", files=[("files", ("CustomTone L.wav", file, "audio/wav"))])
        assert upload.status_code == 200, upload.text
        learned_left_stem = upload.json()["uploaded"][0]
        correction = client.patch(f"/api/projects/{project_id}/stems/{learned_left_stem['id']}", json={"stemType": "Electric Guitar"})
        assert correction.status_code == 200, correction.text
        assert correction.json()["stemTypeSource"] == "Manual"
        memory = client.get("/api/detection-memory")
        assert memory.status_code == 200, memory.text
        assert memory.json()["learnedPatternCount"] > 0, memory.json()

        with learned_right.open("rb") as file:
            upload = client.post(f"/api/projects/{project_id}/stems", files=[("files", ("CustomTone R.wav", file, "audio/wav"))])
        assert upload.status_code == 200, upload.text
        learned_right_stem = upload.json()["uploaded"][0]

        detected = client.post(f"/api/projects/{project_id}/detect-stems")
        assert detected.status_code == 200, detected.text
        right_detail = next(stem for stem in detected.json()["stems"] if stem["id"] == learned_right_stem["id"])
        assert right_detail["detectionResult"]["suggestedStemType"] == "Electric Guitar", right_detail
        assert right_detail["detectionResult"]["method"] == "memory", right_detail

        accept_right = client.post(f"/api/projects/{project_id}/accept-all-detections")
        assert accept_right.status_code == 200, accept_right.text

        job = create_analysis_job(project_id)
        run_analysis_job(project_id, job.id)
        balanced = client.post(f"/api/projects/{project_id}/auto-balance")
        assert balanced.status_code == 200, balanced.text
        stems = balanced.json()["stems"]
        bass_suggestion = next(stem["autoBalanceSuggestion"] for stem in stems if stem["id"] == bass_stem["id"])
        guitar_suggestion = next(stem["autoBalanceSuggestion"] for stem in stems if stem["id"] == learned_right_stem["id"])
        assert bass_suggestion["targetLufs"] == -20.5, bass_suggestion
        assert guitar_suggestion["targetLufs"] == -23.5, guitar_suggestion

        clear_memory = client.delete("/api/detection-memory")
        assert clear_memory.status_code == 200, clear_memory.text
        assert clear_memory.json()["clearedPatternCount"] > 0, clear_memory.json()
        assert client.get("/api/detection-memory").json()["learnedPatternCount"] == 0

    print("Phase 3 smoke test passed")


if __name__ == "__main__":
    main()
