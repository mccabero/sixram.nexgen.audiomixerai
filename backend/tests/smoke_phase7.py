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


def make_vocal_wav(path: Path) -> None:
    sample_rate = 44100
    frames = sample_rate
    random.seed(7)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        for index in range(frames):
            tone = 0.18 * math.sin(2 * math.pi * 220 * index / sample_rate)
            harmonic = 0.07 * math.sin(2 * math.pi * 440 * index / sample_rate)
            noise = random.uniform(-0.015, 0.015)
            sample = max(-0.95, min(0.95, tone + harmonic + noise))
            audio.writeframes(struct.pack("<h", int(sample * 32767)))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AUDIO_MIXER_STORAGE_ROOT"] = tmp

        from fastapi.testclient import TestClient

        from app.main import app
        from app.phase2 import _rough_mix_inputs
        from app.storage import resolve_stored_file_path, store
        from app.vocal_enhancer import create_vocal_enhancement_job, run_vocal_enhancement_job

        fixture_dir = Path(tmp) / "fixtures"
        fixture_dir.mkdir()
        vocal = fixture_dir / "lead_vocal.wav"
        make_vocal_wav(vocal)

        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "Phase 7 Smoke"}).json()
        project_id = project["id"]

        with vocal.open("rb") as file:
            upload = client.post(f"/api/projects/{project_id}/stems", files=[("files", ("lead_vocal.wav", file, "audio/wav"))])
        assert upload.status_code == 200, upload.text
        stem = upload.json()["uploaded"][0]

        typed = client.patch(f"/api/projects/{project_id}/stems/{stem['id']}", json={"stemType": "Lead Vocal"})
        assert typed.status_code == 200, typed.text

        recommendations = client.post(f"/api/projects/{project_id}/analyze-vocals")
        assert recommendations.status_code == 200, recommendations.text
        recommended_stem = recommendations.json()["stems"][0]
        vocal_analysis = recommended_stem["vocalAnalysisResult"]
        assert vocal_analysis["status"] == "Completed", vocal_analysis
        assert vocal_analysis["recommendedSettings"]["enabled"] is True, vocal_analysis
        assert vocal_analysis["recommendedSettings"]["preset"] in {"Natural Clean", "Pop Vocal", "Bright AI Polish", "Live Vocal Fix"}, vocal_analysis
        assert "key" in vocal_analysis["recommendedSettings"], vocal_analysis

        applied_all = client.post(f"/api/projects/{project_id}/apply-vocal-recommendations")
        assert applied_all.status_code == 200, applied_all.text
        assert applied_all.json()["stems"][0]["vocalEnhancementSettings"]["enabled"] is True

        applied = client.post(f"/api/projects/{project_id}/stems/{stem['id']}/apply-vocal-recommendation")
        assert applied.status_code == 200, applied.text
        assert applied.json()["vocalEnhancementSettings"]["enabled"] is True

        presets = client.get("/api/vocal-enhancer-presets")
        assert presets.status_code == 200, presets.text
        assert "Bright AI Polish" in presets.json()["presets"], presets.json()

        custom_preset = client.post(
            "/api/vocal-custom-presets",
            json={
                "name": "Smoke Vocal Preset",
                "settings": {
                    "preset": "Warm Ballad",
                    "fxStyle": "Natural Plate",
                    "fxAmount": 24,
                    "bodyAmount": 8,
                    "presenceAmount": 4,
                    "breathReductionAmount": 40,
                    "mouthClickReductionAmount": 35,
                },
            },
        )
        assert custom_preset.status_code == 200, custom_preset.text
        custom_id = custom_preset.json()["id"]
        custom_list = client.get("/api/vocal-custom-presets")
        assert custom_list.status_code == 200, custom_list.text
        assert any(preset["id"] == custom_id for preset in custom_list.json()["presets"])

        settings = client.patch(
            f"/api/projects/{project_id}/stems/{stem['id']}/vocal-enhancement",
            json={
                "enabled": True,
                "preset": "Pop Vocal",
                "pitchCorrection": "Off",
                "key": "Auto",
                "scale": "Major",
                "fxStyle": "Slap Delay",
                "fxAmount": 35,
                "bodyAmount": 10,
                "presenceAmount": 15,
                "airAmount": 20,
                "deEssAmount": 60,
                "compressionAmount": 65,
                "riderAmount": 70,
                "saturationAmount": 55,
                "doublerAmount": 75,
                "breathReductionAmount": 65,
                "mouthClickReductionAmount": 58,
                "pitchStrength": 55,
                "pitchHumanize": 70,
                "useEnhancedInMix": True,
            },
        )
        assert settings.status_code == 200, settings.text
        assert settings.json()["vocalEnhancementSettings"]["preset"] == "Pop Vocal"
        assert settings.json()["vocalEnhancementSettings"]["fxStyle"] == "Slap Delay"

        doctor = client.post(f"/api/projects/{project_id}/vocal-quality-doctor")
        assert doctor.status_code == 200, doctor.text
        doctor_stem = doctor.json()["stems"][0]
        doctor_result = doctor_stem["vocalQualityDoctorResult"]
        assert doctor_result["status"] == "Completed", doctor_result
        assert doctor_result["score"] <= 100, doctor_result
        assert doctor_result["recommendedSettings"], doctor_result

        doctor_fix = client.post(f"/api/projects/{project_id}/stems/{stem['id']}/apply-vocal-doctor-fix")
        assert doctor_fix.status_code == 200, doctor_fix.text
        fixed_settings = doctor_fix.json()["stems"][0]["vocalEnhancementSettings"]
        assert fixed_settings["enabled"] is True
        assert fixed_settings["useEnhancedInMix"] is True
        assert fixed_settings["doublerAmount"] <= 35
        assert fixed_settings["fxStyle"] == "Dry"
        assert fixed_settings["fxAmount"] == 0

        job = create_vocal_enhancement_job(project_id)
        run_vocal_enhancement_job(project_id, job.id)

        project = client.get(f"/api/projects/{project_id}").json()
        enhanced_stem = project["stems"][0]
        result = enhanced_stem["vocalEnhancementResult"]
        assert result["status"] == "Completed", result
        assert "processed/vocals" in result["enhancedFilePath"], result
        assert resolve_stored_file_path(result["enhancedFilePath"]).exists(), result
        assert result["enhancedMetrics"]["peakDbfs"] is not None, result
        assert result["preset"] in {"Pop Vocal", "Bright AI Polish", "Live Vocal Fix"}, result
        assert result["fxStyle"] == "Dry", result
        assert result["fxAmount"] == 0, result
        assert result["presenceAmount"] >= 10, result
        assert result["doublerAmount"] <= 35, result
        assert result["breathReductionAmount"] == 65, result
        assert result["mouthClickReductionAmount"] == 58, result
        assert result["report"]["summary"], result

        deleted_preset = client.delete(f"/api/vocal-custom-presets/{custom_id}")
        assert deleted_preset.status_code == 200, deleted_preset.text

        data = store.load()
        stored_project = data["projects"][0]
        inputs = _rough_mix_inputs(stored_project)
        assert "processed\\vocals" in str(inputs[0]["path"]) or "processed/vocals" in str(inputs[0]["path"]), inputs

        rough = client.post(f"/api/projects/{project_id}/rough-mix")
        assert rough.status_code == 200, rough.text
        rough_path = resolve_stored_file_path(rough.json()["wavPath"])
        assert rough_path.exists(), rough.json()

        reset_vocals = client.delete(f"/api/projects/{project_id}/vocal-enhancements")
        assert reset_vocals.status_code == 200, reset_vocals.text
        reset_project = reset_vocals.json()
        assert reset_project["stems"][0]["vocalEnhancementResult"] is None
        assert not resolve_stored_file_path(result["enhancedFilePath"]).exists(), result
        assert not rough_path.exists(), rough.json()

        reset_analysis = client.delete(f"/api/projects/{project_id}/analysis-results")
        assert reset_analysis.status_code == 200, reset_analysis.text
        reset_stem = reset_analysis.json()["stems"][0]
        assert reset_stem["analysisResult"] is None
        assert reset_stem["analysisStatus"] == "Pending"

    print("Phase 7 smoke test passed")


if __name__ == "__main__":
    main()
