import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import imageio_ffmpeg
import librosa  # Imported to keep the Phase 2 audio stack ready for later feature extraction.
import numpy as np
import pyloudnorm as pyln
from scipy import signal


CLIPPING_THRESHOLD = 0.999
SILENCE_THRESHOLD_DBFS = -50.0
ANALYSIS_FALLBACK_SAMPLE_RATE = 44100
ROUGH_MIX_SAMPLE_RATE = 44100
DETECTION_SAMPLE_RATE = 22050
DETECTION_MAX_SECONDS = 60

ProgressCallback = Callable[[float, str], None]


def _progress(progress_callback: ProgressCallback | None, fraction: float, message: str) -> None:
    if progress_callback is None:
        return
    progress_callback(max(0.0, min(1.0, fraction)), message)


@dataclass
class DecodedAudio:
    samples: np.ndarray
    sample_rate: int
    channels: int


@dataclass
class RoughMixResult:
    wav_path: Path
    mp3_path: Path | None
    peak_dbfs: float
    limiter_gain_db: float
    mp3_error: str | None = None


@dataclass
class AdvancedMixResult:
    wav_path: Path
    mp3_path: Path | None
    metadata_path: Path | None
    peak_dbfs: float
    true_peak_dbfs: float
    integrated_lufs: float | None
    limiter_gain_db: float
    source_files: list[dict]
    warnings: list[str]
    errors: list[str]
    mp3_error: str | None = None


@dataclass
class MasteringAudioResult:
    path: Path
    input_metrics: dict
    output_metrics: dict
    dynamic_range_db: float | None
    loudness_gain_db: float
    limiter_gain_db: float
    operations: list[str]
    warnings: list[str]
    errors: list[str]


@dataclass
class CleanedAudioResult:
    path: Path
    peak_dbfs: float
    rms_dbfs: float
    noise_floor_dbfs: float | None
    original_metrics: dict
    cleaned_metrics: dict
    metric_deltas: dict[str, float | None]
    operations: list[str]
    warnings: list[str]


@dataclass
class VocalEnhancementAudioResult:
    path: Path
    peak_dbfs: float
    rms_dbfs: float
    integrated_lufs: float | None
    original_metrics: dict
    enhanced_metrics: dict
    metric_deltas: dict[str, float | None]
    operations: list[str]
    warnings: list[str]


try:
    import noisereduce as nr
except Exception:  # Optional dependency; scipy fallback is used when unavailable.
    nr = None

try:
    import pedalboard as pedalboard_lib  # noqa: F401
except Exception:  # Optional Phase 5 dependency; scipy/native fallback remains available.
    pedalboard_lib = None

try:
    import sounddevice as sounddevice_lib  # noqa: F401
except Exception:  # Optional direct-recording dependency; upload workflows still work without it.
    sounddevice_lib = None


def check_audio_environment() -> dict[str, Any]:
    checks: dict[str, Any] = {
        "ok": True,
        "ffmpeg": {"ok": False, "path": None, "version": None, "error": None},
        "pythonPackages": {},
        "optionalPackages": {},
    }

    try:
        ffmpeg = _ffmpeg_exe()
        completed = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=10)
        version_line = (completed.stdout or completed.stderr).splitlines()[0] if (completed.stdout or completed.stderr) else None
        checks["ffmpeg"] = {
            "ok": completed.returncode == 0,
            "path": ffmpeg,
            "version": version_line,
            "error": None if completed.returncode == 0 else (completed.stderr.strip() or "ffmpeg version check failed."),
        }
    except Exception as exc:
        checks["ffmpeg"]["error"] = str(exc) or "ffmpeg is not available."

    required = {
        "numpy": np,
        "scipy": signal,
        "librosa": librosa,
        "pyloudnorm": pyln,
        "imageio_ffmpeg": imageio_ffmpeg,
    }
    for name, module in required.items():
        checks["pythonPackages"][name] = {
            "ok": True,
            "version": getattr(module, "__version__", None),
        }

    checks["optionalPackages"]["noisereduce"] = {"ok": nr is not None, "version": getattr(nr, "__version__", None) if nr else None}
    checks["optionalPackages"]["pedalboard"] = {
        "ok": pedalboard_lib is not None,
        "version": getattr(pedalboard_lib, "__version__", None) if pedalboard_lib else None,
    }
    checks["optionalPackages"]["sounddevice"] = {
        "ok": sounddevice_lib is not None,
        "version": getattr(sounddevice_lib, "__version__", None) if sounddevice_lib else None,
    }
    checks["ok"] = bool(checks["ffmpeg"]["ok"]) and all(item["ok"] for item in checks["pythonPackages"].values())
    return checks


def ensure_audio_environment() -> None:
    checks = check_audio_environment()
    if not checks["ok"]:
        ffmpeg_error = checks["ffmpeg"].get("error") or "ffmpeg check failed."
        raise RuntimeError(f"Audio engine dependency check failed: {ffmpeg_error}")


def validate_audio_file(path: Path) -> dict[str, int]:
    ensure_audio_environment()
    if not path.exists():
        raise ValueError("Uploaded file was not saved.")
    ffmpeg = _ffmpeg_exe()
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-t",
        "5",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout).strip()
        raise ValueError(error or "ffmpeg could not validate an audio stream in this file.")
    return _probe_audio(path)


def analyze_audio_file(path: Path, progress_callback: ProgressCallback | None = None) -> dict:
    ensure_audio_environment()
    _progress(progress_callback, 0.08, "Probing audio stream")
    info = _probe_audio(path)
    _progress(progress_callback, 0.28, "Decoding audio samples")
    decoded = _decode_audio(path, sample_rate=info["sampleRate"], channels=info["channels"])
    audio = decoded.samples

    if audio.size == 0:
        raise ValueError("Decoded audio is empty.")

    _progress(progress_callback, 0.72, "Measuring loudness and warnings")
    return _analyze_samples(audio, decoded.sample_rate)


def clean_audio_file(path: Path, output_path: Path, stem_type: str, mode: str, hum_removal: bool = False, hum_frequency: int = 60, progress_callback: ProgressCallback | None = None) -> CleanedAudioResult:
    ensure_audio_environment()
    if mode == "Off":
        raise ValueError("Cleaning mode is Off.")

    _progress(progress_callback, 0.05, "Probing source stem")
    info = _probe_audio(path)
    _progress(progress_callback, 0.15, "Decoding source stem")
    decoded = _decode_audio(path, sample_rate=info["sampleRate"], channels=info["channels"])
    audio = decoded.samples.astype(np.float32, copy=True)
    params = _cleaning_parameters(stem_type, mode)
    operations: list[str] = []
    warnings: list[str] = []

    if mode == "Strong":
        warnings.append("Strong cleaning can remove ambience or soften transients; compare against the original.")

    preset_name = stem_type if stem_type != "Unknown" else "general"
    operations.append(f"{mode} {preset_name} cleaning preset")
    _progress(progress_callback, 0.25, "Measuring original noise profile")
    original_metrics = _cleaning_metric_subset(_analyze_samples(audio, decoded.sample_rate))

    if hum_removal:
        _progress(progress_callback, 0.34, "Reducing electrical hum")
        audio = _remove_hum(audio, decoded.sample_rate, hum_frequency, params["humStrength"])
        operations.append(f"{hum_frequency} Hz hum reduction")

    if params["highPassHz"]:
        _progress(progress_callback, 0.42, "Applying high-pass cleanup")
        audio = _high_pass(audio, decoded.sample_rate, params["highPassHz"])
        operations.append(f"high-pass filter at {params['highPassHz']} Hz")

    if params["plosiveReduction"]:
        _progress(progress_callback, 0.50, "Reducing plosives")
        audio = _reduce_plosives(audio, decoded.sample_rate, params["plosiveReduction"])
        operations.append("plosive reduction")

    if params["noiseReduction"]:
        _progress(progress_callback, 0.58, "Building noise reduction profile")
        noise_profile = _noise_profile(audio, decoded.sample_rate)
        _progress(progress_callback, 0.64, "Reducing noise")
        audio = _reduce_noise(audio, decoded.sample_rate, params["noiseReduction"], noise_profile=noise_profile)
        operations.append("profile-based noise reduction" if noise_profile is not None else "adaptive noise reduction")

    if params["noiseGate"]:
        _progress(progress_callback, 0.70, "Applying noise gate")
        audio = _noise_gate(audio, decoded.sample_rate, params["noiseGate"], params["gateFloor"])
        operations.append("noise gate")

    if params["deEss"]:
        _progress(progress_callback, 0.76, "Softening harsh sibilance")
        audio = _de_ess(audio, decoded.sample_rate, params["deEss"])
        operations.append("de-esser")

    if params["compressionPrep"]:
        _progress(progress_callback, 0.82, "Preparing dynamics")
        audio = _compression_prepare(audio, params["compressionPrep"])
        operations.append("light compression preparation")

    if params["clickReduction"]:
        _progress(progress_callback, 0.86, "Reducing clicks and pops")
        audio = _reduce_clicks(audio, params["clickReduction"])
        operations.append("click/pop reduction")

    if params["tailCleanup"]:
        _progress(progress_callback, 0.90, "Cleaning silent tail")
        audio = _cleanup_silent_tail(audio, decoded.sample_rate)
        operations.append("silence tail cleanup")
        warnings.append("Leading silence is preserved so stems stay aligned in the mix.")

    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    audio = np.clip(audio, -0.98, 0.98).astype(np.float32, copy=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _progress(progress_callback, 0.94, "Writing cleaned WAV")
    _encode_float_audio(audio, output_path, codec_args=["-c:a", "pcm_s16le"], sample_rate=decoded.sample_rate)

    _progress(progress_callback, 0.98, "Measuring cleaned stem")
    cleaned_metrics = _cleaning_metric_subset(_analyze_samples(audio, decoded.sample_rate))
    metric_deltas = _metric_deltas(original_metrics, cleaned_metrics)
    return CleanedAudioResult(
        path=output_path,
        peak_dbfs=cleaned_metrics.get("peakDbfs"),
        rms_dbfs=cleaned_metrics.get("rmsDbfs"),
        noise_floor_dbfs=cleaned_metrics.get("noiseFloorDbfs"),
        original_metrics=original_metrics,
        cleaned_metrics=cleaned_metrics,
        metric_deltas=metric_deltas,
        operations=operations,
        warnings=warnings,
    )


def enhance_vocal_file(
    path: Path,
    output_path: Path,
    preset: str,
    pitch_correction: str,
    key: str = "Auto",
    scale: str = "Major",
    fx_style: str = "Dry",
    fx_amount: float = 0,
    body_amount: float = 0,
    presence_amount: float = 0,
    air_amount: float = 0,
    de_ess_amount: float = 50,
    compression_amount: float = 45,
    rider_amount: float = 45,
    saturation_amount: float = 50,
    doubler_amount: float = 50,
    breath_reduction_amount: float = 35,
    mouth_click_reduction_amount: float = 30,
    pitch_strength: float = 50,
    pitch_humanize: float = 60,
    progress_callback: ProgressCallback | None = None,
) -> VocalEnhancementAudioResult:
    ensure_audio_environment()
    _progress(progress_callback, 0.04, "Probing vocal source")
    info = _probe_audio(path)
    _progress(progress_callback, 0.10, "Decoding vocal source")
    decoded = _decode_audio(path, sample_rate=info["sampleRate"], channels=2)
    audio = decoded.samples.astype(np.float32, copy=True)
    params = _vocal_enhancer_parameters(preset)
    operations: list[str] = [f"{preset} vocal enhancer preset"]
    warnings: list[str] = []

    _progress(progress_callback, 0.16, "Measuring original vocal")
    original_metrics = _cleaning_metric_subset(_analyze_samples(audio, decoded.sample_rate))

    _progress(progress_callback, 0.22, "Applying vocal high-pass")
    audio = _high_pass(audio, decoded.sample_rate, params["highPassHz"])
    operations.append(f"vocal high-pass at {params['highPassHz']} Hz")

    if params["noiseReduction"] > 0:
        _progress(progress_callback, 0.28, "Reducing vocal noise")
        noise_profile = _noise_profile(audio, decoded.sample_rate)
        audio = _reduce_noise(audio, decoded.sample_rate, params["noiseReduction"], noise_profile=noise_profile)
        operations.append("light vocal noise reduction")

    mouth_clicks = _scale_preset_amount(params["mouthClickReduction"], mouth_click_reduction_amount, max_value=0.8)
    if mouth_clicks > 0:
        _progress(progress_callback, 0.34, "Softening mouth clicks")
        audio = _reduce_clicks(audio, mouth_clicks)
        operations.append(f"mouth click softener ({int(round(mouth_click_reduction_amount))}%)")

    breath_reduction = _scale_preset_amount(params["breathReduction"], breath_reduction_amount, max_value=0.9)
    if breath_reduction > 0:
        _progress(progress_callback, 0.40, "Softening breaths")
        audio = _reduce_breaths(audio, decoded.sample_rate, breath_reduction)
        operations.append(f"breath softener ({int(round(breath_reduction_amount))}%)")

    if pitch_correction != "Off":
        _progress(progress_callback, 0.48, "Applying pitch polish")
        audio, pitch_operation, pitch_warning = _pitch_polish(audio, decoded.sample_rate, pitch_correction, key, scale, pitch_strength, pitch_humanize)
        operations.append(pitch_operation)
        if pitch_warning:
            warnings.append(pitch_warning)

    de_ess = _scale_preset_amount(params["deEss"], de_ess_amount, max_value=0.95)
    if de_ess > 0:
        _progress(progress_callback, 0.56, "Applying vocal de-esser")
        audio = _de_ess(audio, decoded.sample_rate, de_ess)
        operations.append(f"studio de-esser ({int(round(de_ess_amount))}%)")

    rider = _scale_preset_amount(params["rider"], rider_amount, max_value=0.95)
    if rider > 0:
        _progress(progress_callback, 0.62, "Leveling vocal dynamics")
        audio = _vocal_rider(audio, decoded.sample_rate, rider)
        operations.append(f"automatic vocal rider ({int(round(rider_amount))}%)")

    body_db = params["bodyDb"] + max(-50.0, min(50.0, body_amount)) / 50.0 * 1.6
    if body_db:
        _progress(progress_callback, 0.68, "Shaping vocal body")
        audio = _eq_band(audio, decoded.sample_rate, 160, 360, body_db)
        operations.append(f"vocal body EQ ({body_db:+.1f} dB)")

    presence_db = params["presenceDb"] + max(-50.0, min(50.0, presence_amount)) / 50.0 * 2.0
    if presence_db:
        _progress(progress_callback, 0.72, "Adding vocal presence")
        audio = _eq_band(audio, decoded.sample_rate, 2500, 5600, presence_db)
        operations.append(f"vocal presence EQ ({presence_db:+.1f} dB)")

    air_db = params["airDb"] + max(-50.0, min(50.0, air_amount)) / 50.0 * 2.2
    if air_db:
        _progress(progress_callback, 0.76, "Adding vocal air")
        audio = _eq_band(audio, decoded.sample_rate, 7200, min(15000, decoded.sample_rate / 2 - 200), air_db)
        operations.append(f"vocal air enhancer ({air_db:+.1f} dB)")

    compression = _scale_preset_amount(params["compression"], compression_amount, max_value=0.95)
    if compression > 0:
        _progress(progress_callback, 0.80, "Compressing vocal")
        threshold_adjust = (50.0 - max(0.0, min(100.0, compression_amount))) / 100.0 * 4.0
        audio = _compress_audio(audio, threshold_db=params["compressionThresholdDb"] + threshold_adjust, ratio=params["compressionRatio"], mix=compression)
        operations.append(f"studio vocal compression ({int(round(compression_amount))}%)")

    saturation = _scale_preset_amount(params["saturation"], saturation_amount, max_value=0.22)
    if saturation > 0:
        _progress(progress_callback, 0.84, "Adding subtle saturation")
        audio = _saturate(audio, drive=1.08 + saturation * 3.5, mix=saturation)
        operations.append(f"subtle vocal saturation ({int(round(saturation_amount))}%)")

    doubler = max(0.0, min(0.35, params["doubler"] + (max(0.0, min(100.0, doubler_amount)) - 50.0) / 50.0 * 0.12))
    if doubler > 0:
        _progress(progress_callback, 0.87, "Applying vocal doubler")
        audio = _vocal_doubler(audio, decoded.sample_rate, doubler)
        operations.append(f"subtle vocal doubler ({int(round(doubler_amount))}%)")

    if params["width"] != 0:
        _progress(progress_callback, 0.90, "Polishing stereo image")
        audio = _apply_width(audio, params["width"])
        operations.append("vocal stereo polish")

    if fx_style != "Dry" and fx_amount > 0:
        _progress(progress_callback, 0.92, "Adding vocal effects")
        audio = _apply_vocal_fx(audio, decoded.sample_rate, fx_style, fx_amount)
        operations.append(f"{fx_style} vocal FX send at {int(round(fx_amount))}%")

    _progress(progress_callback, 0.94, "Applying vocal safety level")
    audio = _final_vocal_level(audio, target_peak_db=-1.6)
    operations.append("vocal safety level")
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    audio = np.clip(audio, -0.98, 0.98).astype(np.float32, copy=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _progress(progress_callback, 0.96, "Writing enhanced vocal")
    _encode_float_audio(audio, output_path, codec_args=["-c:a", "pcm_s16le"], sample_rate=decoded.sample_rate)

    _progress(progress_callback, 0.99, "Measuring enhanced vocal")
    enhanced_metrics = _cleaning_metric_subset(_analyze_samples(audio, decoded.sample_rate))
    metric_deltas = _metric_deltas(original_metrics, enhanced_metrics)
    if doubler > 0:
        warnings.append("Doubler adds width; keep lead vocals mostly centered in the mixer for clarity.")
    if pitch_correction == "Strong":
        warnings.append("Strong pitch polish can sound artificial on live vocals; compare before mixing.")

    return VocalEnhancementAudioResult(
        path=output_path,
        peak_dbfs=enhanced_metrics.get("peakDbfs"),
        rms_dbfs=enhanced_metrics.get("rmsDbfs"),
        integrated_lufs=enhanced_metrics.get("integratedLufs"),
        original_metrics=original_metrics,
        enhanced_metrics=enhanced_metrics,
        metric_deltas=metric_deltas,
        operations=operations,
        warnings=warnings,
    )


def extract_stem_detection_features(path: Path) -> dict[str, float | int | None]:
    ensure_audio_environment()
    info = _probe_audio(path)
    decoded = _decode_audio(path, sample_rate=DETECTION_SAMPLE_RATE, channels=min(info["channels"], 2))
    audio = decoded.samples
    max_samples = DETECTION_SAMPLE_RATE * DETECTION_MAX_SECONDS
    if audio.shape[0] > max_samples:
        audio = audio[:max_samples]

    mono = np.mean(audio, axis=1).astype(np.float32, copy=False)
    duration_seconds = mono.shape[0] / DETECTION_SAMPLE_RATE
    if mono.size < 1024:
        raise ValueError("Not enough audio for stem detection.")

    rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
    peak = float(np.max(np.abs(mono)))

    spectral_centroid = librosa.feature.spectral_centroid(y=mono, sr=DETECTION_SAMPLE_RATE)
    zero_crossing_rate = librosa.feature.zero_crossing_rate(mono)
    onset_env = librosa.onset.onset_strength(y=mono, sr=DETECTION_SAMPLE_RATE)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=DETECTION_SAMPLE_RATE, units="time")
    transient_density = len(onsets) / max(duration_seconds, 0.001)

    stft = np.abs(librosa.stft(mono, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=DETECTION_SAMPLE_RATE, n_fft=2048)
    power = np.square(stft)
    total_energy = float(np.sum(power)) + 1e-12

    sub_ratio = _band_energy_ratio(power, freqs, 20, 80, total_energy)
    bass_ratio = _band_energy_ratio(power, freqs, 80, 250, total_energy)
    low_mid_ratio = _band_energy_ratio(power, freqs, 250, 700, total_energy)
    mid_ratio = _band_energy_ratio(power, freqs, 700, 4000, total_energy)
    high_ratio = _band_energy_ratio(power, freqs, 4000, 10000, total_energy)

    harmonic_ratio = None
    percussive_ratio = None
    try:
        harmonic, percussive = librosa.effects.hpss(mono)
        harmonic_rms = float(np.sqrt(np.mean(np.square(harmonic, dtype=np.float64))))
        percussive_rms = float(np.sqrt(np.mean(np.square(percussive, dtype=np.float64))))
        total_hp = harmonic_rms + percussive_rms + 1e-12
        harmonic_ratio = harmonic_rms / total_hp
        percussive_ratio = percussive_rms / total_hp
    except Exception:
        pass

    stereo_width = 0.0
    stereo_correlation = 1.0
    if audio.shape[1] == 2:
        left = audio[:, 0]
        right = audio[:, 1]
        mid = (left + right) * 0.5
        side = (left - right) * 0.5
        mid_rms = float(np.sqrt(np.mean(np.square(mid, dtype=np.float64)))) + 1e-12
        side_rms = float(np.sqrt(np.mean(np.square(side, dtype=np.float64))))
        stereo_width = min(1.0, side_rms / mid_rms)
        if np.std(left) > 1e-6 and np.std(right) > 1e-6:
            stereo_correlation = float(np.corrcoef(left, right)[0, 1])

    return {
        "durationSeconds": _round(duration_seconds),
        "channels": int(info["channels"]),
        "rmsDbfs": _round(_linear_to_db(rms)),
        "peakDbfs": _round(_linear_to_db(peak)),
        "spectralCentroidHz": _round(float(np.mean(spectral_centroid))),
        "zeroCrossingRate": _round(float(np.mean(zero_crossing_rate)), 5),
        "transientDensity": _round(float(transient_density)),
        "subEnergyRatio": _round(sub_ratio, 5),
        "bassEnergyRatio": _round(bass_ratio, 5),
        "lowFrequencyEnergyRatio": _round(sub_ratio + bass_ratio, 5),
        "lowMidEnergyRatio": _round(low_mid_ratio, 5),
        "midEnergyRatio": _round(mid_ratio, 5),
        "highEnergyRatio": _round(high_ratio, 5),
        "harmonicRatio": _round(harmonic_ratio, 5),
        "percussiveRatio": _round(percussive_ratio, 5),
        "stereoWidth": _round(stereo_width, 5),
        "stereoCorrelation": _round(stereo_correlation, 5),
    }


def analyze_vocal_file(path: Path) -> dict[str, Any]:
    ensure_audio_environment()
    info = _probe_audio(path)
    decoded = _decode_audio(path, sample_rate=info["sampleRate"], channels=min(info["channels"], 2))
    audio = decoded.samples.astype(np.float32, copy=False)
    metrics = _cleaning_metric_subset(_analyze_samples(audio, decoded.sample_rate))

    analysis_sample_rate = min(DETECTION_SAMPLE_RATE, decoded.sample_rate)
    analysis_audio = audio
    if decoded.sample_rate != analysis_sample_rate:
        analysis_audio = signal.resample_poly(audio, up=analysis_sample_rate, down=decoded.sample_rate, axis=0).astype(np.float32, copy=False)

    max_samples = analysis_sample_rate * DETECTION_MAX_SECONDS
    if analysis_audio.shape[0] > max_samples:
        analysis_audio = analysis_audio[:max_samples]

    mono = np.mean(analysis_audio, axis=1).astype(np.float32, copy=False)
    if mono.size < 1024:
        raise ValueError("Not enough audio to analyze vocal tone.")

    stft = np.abs(librosa.stft(mono, n_fft=2048, hop_length=512))
    power = np.square(stft)
    total_energy = float(np.sum(power)) + 1e-12
    freqs = librosa.fft_frequencies(sr=analysis_sample_rate, n_fft=2048)

    frame_rms = librosa.feature.rms(y=mono, frame_length=2048, hop_length=512)[0]
    audible = frame_rms[frame_rms > _db_to_linear(-55)]
    if audible.size:
        frame_db = np.array([_linear_to_db(float(value)) for value in audible])
        level_spread_db = float(np.percentile(frame_db, 95) - np.percentile(frame_db, 20))
    else:
        level_spread_db = 0.0

    harmonic_ratio = None
    try:
        harmonic, percussive = librosa.effects.hpss(mono)
        harmonic_rms = float(np.sqrt(np.mean(np.square(harmonic, dtype=np.float64))))
        percussive_rms = float(np.sqrt(np.mean(np.square(percussive, dtype=np.float64))))
        harmonic_ratio = harmonic_rms / (harmonic_rms + percussive_rms + 1e-12)
    except Exception:
        pass

    spectral_centroid = librosa.feature.spectral_centroid(S=stft, sr=analysis_sample_rate)
    spectral_flatness = librosa.feature.spectral_flatness(S=np.maximum(stft, 1e-12))
    zero_crossing_rate = librosa.feature.zero_crossing_rate(mono)

    stereo_width = 0.0
    if analysis_audio.shape[1] == 2:
        left = analysis_audio[:, 0]
        right = analysis_audio[:, 1]
        mid = (left + right) * 0.5
        side = (left - right) * 0.5
        mid_rms = float(np.sqrt(np.mean(np.square(mid, dtype=np.float64)))) + 1e-12
        side_rms = float(np.sqrt(np.mean(np.square(side, dtype=np.float64))))
        stereo_width = min(1.0, side_rms / mid_rms)

    body_ratio = _band_energy_ratio(power, freqs, 120, 320, total_energy)
    mud_ratio = _band_energy_ratio(power, freqs, 180, 520, total_energy)
    presence_ratio = _band_energy_ratio(power, freqs, 2400, 5600, total_energy)
    harshness_ratio = _band_energy_ratio(power, freqs, 3200, 7200, total_energy)
    sibilance_ratio = _band_energy_ratio(power, freqs, 5500, 9500, total_energy)
    air_ratio = _band_energy_ratio(power, freqs, 9500, min(15000, analysis_sample_rate / 2), total_energy)
    low_rumble_ratio = _band_energy_ratio(power, freqs, 20, 100, total_energy)
    estimated_key, estimated_scale, key_confidence = _estimate_key_and_scale(mono, analysis_sample_rate)

    return {
        **metrics,
        "spectralCentroidHz": _round(float(np.mean(spectral_centroid))),
        "spectralFlatness": _round(float(np.mean(spectral_flatness)), 5),
        "zeroCrossingRate": _round(float(np.mean(zero_crossing_rate)), 5),
        "harmonicRatio": _round(harmonic_ratio, 5),
        "levelSpreadDb": _round(level_spread_db),
        "bodyRatio": _round(body_ratio, 5),
        "mudRatio": _round(mud_ratio, 5),
        "presenceRatio": _round(presence_ratio, 5),
        "harshnessRatio": _round(harshness_ratio, 5),
        "sibilanceRatio": _round(sibilance_ratio, 5),
        "airRatio": _round(air_ratio, 5),
        "lowRumbleRatio": _round(low_rumble_ratio, 5),
        "stereoWidth": _round(stereo_width, 5),
        "estimatedKey": estimated_key,
        "estimatedScale": estimated_scale,
        "keyConfidence": _round(key_confidence),
    }


def generate_rough_mix(stem_inputs: list[dict], output_dir: Path) -> RoughMixResult:
    ensure_audio_environment()
    if not stem_inputs:
        raise ValueError("No audible stems are available for rough mix generation.")

    output_dir.mkdir(parents=True, exist_ok=True)
    decoded_tracks: list[tuple[np.ndarray, dict]] = []
    max_length = 0

    for item in stem_inputs:
        decoded = _decode_audio(item["path"], sample_rate=ROUGH_MIX_SAMPLE_RATE, channels=2)
        audio = decoded.samples.astype(np.float32, copy=False)
        audio = _apply_gain(audio, item.get("gainDb", 0))
        audio = _apply_pan(audio, item.get("pan", 0))
        decoded_tracks.append((audio, item))
        max_length = max(max_length, audio.shape[0])

    if max_length == 0:
        raise ValueError("Decoded stems contain no audio samples.")

    mix = np.zeros((max_length, 2), dtype=np.float32)
    for audio, _item in decoded_tracks:
        mix[: audio.shape[0], :] += audio

    peak_before = float(np.max(np.abs(mix))) if mix.size else 0
    limiter_gain_db = 0.0
    if peak_before > 0.98:
        scale = 0.98 / peak_before
        mix *= scale
        limiter_gain_db = _linear_to_db(scale)

    peak_after = float(np.max(np.abs(mix))) if mix.size else 0
    version_number = _next_numbered_audio_file(output_dir, "rough_mix", ".wav")
    label = f"rough_mix_v{version_number:03d}"
    wav_path = output_dir / f"{label}.wav"
    mp3_path = output_dir / f"{label}.mp3"

    _encode_float_audio(mix, wav_path, codec_args=["-c:a", "pcm_s16le"])

    mp3_error = None
    try:
        _encode_float_audio(mix, mp3_path, codec_args=["-c:a", "libmp3lame", "-q:a", "2"])
    except Exception as exc:
        mp3_error = str(exc) or "MP3 encode failed."
        mp3_path = None

    return RoughMixResult(
        wav_path=wav_path,
        mp3_path=mp3_path,
        peak_dbfs=_round(_linear_to_db(peak_after)),
        limiter_gain_db=_round(limiter_gain_db),
        mp3_error=mp3_error,
    )


def generate_advanced_mix(stem_inputs: list[dict], output_dir: Path, version_number: int, controls: dict, progress_callback: ProgressCallback | None = None) -> AdvancedMixResult:
    ensure_audio_environment()
    if not stem_inputs:
        raise ValueError("No audible stems are available for advanced mix generation.")

    _progress(progress_callback, 0.03, "Preparing mix render")
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_tracks: list[tuple[np.ndarray, np.ndarray, dict]] = []
    source_files: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []
    max_length = 0

    total_inputs = len(stem_inputs)
    for index, item in enumerate(stem_inputs, start=1):
        filename = item.get("filename", "stem")
        try:
            _progress(progress_callback, 0.05 + ((index - 1) / total_inputs) * 0.40, f"Processing stem {filename}")
            decoded = _decode_audio(item["path"], sample_rate=ROUGH_MIX_SAMPLE_RATE, channels=2)
            dry, send = _process_advanced_stem(decoded.samples.astype(np.float32, copy=False), decoded.sample_rate, item, controls, warnings)
            if dry.size == 0:
                raise ValueError("Decoded stem contains no usable audio.")
            processed_tracks.append((dry, send, item))
            max_length = max(max_length, dry.shape[0], send.shape[0])
            source_files.append(
                {
                    "stemId": item.get("stemId", ""),
                    "filename": filename,
                    "stemType": item.get("stemType", "Unknown"),
                    "sourceFilePath": item.get("sourceFilePath", str(item["path"])),
                    "sourceKind": item.get("sourceKind", "Original"),
                    "gainDb": _round(float(item.get("gainDb", 0))),
                    "pan": _round(float(item.get("pan", 0))),
                    "processingChainEnabled": bool(item.get("processingChainEnabled", True)) and not _should_bypass_vocal_channel_strip(item),
                    "reverbSend": _round(float(item.get("reverbSend", 35))),
                    "delaySend": _round(float(item.get("delaySend", 0))),
                    "presenceAmount": _round(float(item.get("presenceAmount", 0))),
                    "compressionAmount": _round(float(item.get("compressionAmount", 50))),
                }
            )
            _progress(progress_callback, 0.05 + (index / total_inputs) * 0.40, f"Processed stem {filename}")
        except Exception as exc:
            message = f"{filename}: {str(exc) or 'processing failed'}"
            errors.append(message)
            warnings.append(f"Skipped {filename}; the rest of the mix can still render.")

    if not processed_tracks or max_length == 0:
        raise ValueError("No stems could be processed for the advanced mix.")

    _progress(progress_callback, 0.50, "Building mix buses")
    mix = np.zeros((max_length, 2), dtype=np.float32)
    vocal_send = np.zeros_like(mix)
    drum_send = np.zeros_like(mix)
    space_send = np.zeros_like(mix)
    vocal_focus_bus = np.zeros_like(mix)
    vocal_bus = np.zeros_like(mix)

    for dry, _send, item in processed_tracks:
        if item.get("stemType") == "Lead Vocal":
            _add_to_bus(vocal_focus_bus, dry)

    for index, (dry, send, item) in enumerate(processed_tracks, start=1):
        _progress(progress_callback, 0.55 + ((index - 1) / len(processed_tracks)) * 0.18, f"Summing {item.get('filename', 'stem')}")
        stem_type = item.get("stemType", "Unknown")
        if stem_type in {"Electric Guitar", "Acoustic Guitar", "Keys/Piano", "Pads/Strings", "FX/Ambience"} and np.any(vocal_focus_bus):
            duck_amount = 0.95 + max(0.0, float(controls.get("vocalBoost", 0))) * 0.22
            dry = _apply_vocal_ducking(dry, vocal_focus_bus[: dry.shape[0]], ROUGH_MIX_SAMPLE_RATE, duck_amount)
            send = _apply_vocal_ducking(send, vocal_focus_bus[: send.shape[0]], ROUGH_MIX_SAMPLE_RATE, duck_amount * 0.55)
        if stem_type in {"Lead Vocal", "Backing Vocal"}:
            _add_to_bus(vocal_bus, dry)
            _add_to_bus(vocal_send, send)
            delay_amount = _stem_delay_amount(stem_type, float(item.get("delaySend", 0)), controls)
            if delay_amount > 0.01:
                _add_to_bus(mix, _delay_effect(dry, ROUGH_MIX_SAMPLE_RATE, delay_seconds=0.24, feedback=0.22, amount=delay_amount))
        elif stem_type in {"Drums", "Kick", "Snare"}:
            _add_to_bus(mix, dry)
            _add_to_bus(drum_send, send)
        else:
            _add_to_bus(mix, dry)
            _add_to_bus(space_send, send)
            delay_amount = _stem_delay_amount(stem_type, float(item.get("delaySend", 0)), controls)
            if delay_amount > 0.01:
                delay_seconds = 0.18 if stem_type in {"Electric Guitar", "Acoustic Guitar"} else 0.31
                _add_to_bus(space_send, _delay_effect(dry, ROUGH_MIX_SAMPLE_RATE, delay_seconds=delay_seconds, feedback=0.18, amount=delay_amount))

    _progress(progress_callback, 0.74, "Processing vocal bus and sends")
    if np.any(vocal_bus):
        _add_to_bus(mix, _process_vocal_mix_bus(vocal_bus, ROUGH_MIX_SAMPLE_RATE, controls, warnings))

    _progress(progress_callback, 0.80, "Adding shared space effects")
    room_size = _control_ratio(controls, "roomSize")
    global_reverb = _control_ratio(controls, "reverbAmount")
    vocal_reverb = _control_ratio(controls, "vocalReverbAmount")
    _add_to_bus(mix, _simple_reverb(vocal_send, ROUGH_MIX_SAMPLE_RATE, amount=0.22 * global_reverb + 0.28 * vocal_reverb, room_size=0.45 + room_size * 0.45))
    _add_to_bus(mix, _simple_reverb(drum_send, ROUGH_MIX_SAMPLE_RATE, amount=0.13 * global_reverb, room_size=0.25 + room_size * 0.25))
    _add_to_bus(mix, _simple_reverb(space_send, ROUGH_MIX_SAMPLE_RATE, amount=0.24 * global_reverb, room_size=0.55 + room_size * 0.55))

    _progress(progress_callback, 0.84, "Applying mix tone and safety")
    mix = _apply_master_tone(mix, ROUGH_MIX_SAMPLE_RATE, controls)
    mix = np.nan_to_num(mix, nan=0.0, posinf=0.0, neginf=0.0)

    peak_before = float(np.max(np.abs(mix))) if mix.size else 0
    limiter_gain_db = 0.0
    if peak_before > 0.98:
        scale = 0.98 / peak_before
        mix *= scale
        limiter_gain_db = _linear_to_db(scale)
        warnings.append("Mix-stage safety gain was applied to prevent clipping; final limiting belongs to mastering.")

    mix = np.clip(mix, -0.98, 0.98).astype(np.float32, copy=False)
    label = f"mix_v{version_number:03d}"
    wav_path = output_dir / f"{label}.wav"
    mp3_path = output_dir / f"{label}.mp3"
    metadata_path = output_dir / f"{label}.json"

    _progress(progress_callback, 0.90, "Writing mix WAV")
    _encode_float_audio(mix, wav_path, codec_args=["-c:a", "pcm_s16le"])

    mp3_error = None
    try:
        _progress(progress_callback, 0.95, "Writing mix MP3")
        _encode_float_audio(mix, mp3_path, codec_args=["-c:a", "libmp3lame", "-q:a", "2"])
    except Exception as exc:
        mp3_error = str(exc) or "MP3 encode failed."
        mp3_path = None

    _progress(progress_callback, 0.98, "Measuring finished mix")
    metrics = _analyze_samples(mix, ROUGH_MIX_SAMPLE_RATE)
    return AdvancedMixResult(
        wav_path=wav_path,
        mp3_path=mp3_path,
        metadata_path=metadata_path,
        peak_dbfs=_round(metrics.get("peakDbfs")),
        true_peak_dbfs=_round(metrics.get("truePeakDbfs")),
        integrated_lufs=_round(metrics.get("integratedLufs")),
        limiter_gain_db=_round(limiter_gain_db),
        source_files=source_files,
        warnings=warnings,
        errors=errors,
        mp3_error=mp3_error,
    )


def master_audio_file(input_path: Path, output_path: Path, output_format: str, controls: dict, target_lufs: float, true_peak_ceiling_db: float = -1.0, progress_callback: ProgressCallback | None = None) -> MasteringAudioResult:
    ensure_audio_environment()
    _progress(progress_callback, 0.04, "Probing selected mix")
    info = _probe_audio(input_path)
    _progress(progress_callback, 0.12, "Decoding selected mix")
    decoded = _decode_audio(input_path, sample_rate=info["sampleRate"], channels=2)
    audio = decoded.samples.astype(np.float32, copy=True)
    operations: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    try:
        trim_start_seconds = float(controls.get("trimStartSeconds", 0) or 0)
        trim_end_seconds = float(controls.get("trimEndSeconds", 0) or 0)
        if trim_start_seconds > 0 or trim_end_seconds > 0:
            _progress(progress_callback, 0.18, "Applying crop")
            audio, trim_operations = _apply_time_trim(audio, decoded.sample_rate, trim_start_seconds, trim_end_seconds)
            operations.extend(trim_operations)
    except Exception as exc:
        raise ValueError(str(exc) or "Crop failed.") from exc

    _progress(progress_callback, 0.22, "Measuring input loudness")
    input_metrics = _analyze_samples(audio, decoded.sample_rate)
    preset = str(controls.get("preset", "Streaming"))
    if target_lufs >= -9:
        warnings.append("Loud mastering targets can reduce dynamics and may reveal distortion.")
    if target_lufs >= -7.5:
        warnings.append("Very Loud mastering is aggressive; compare carefully against the unmastered mix.")

    try:
        _progress(progress_callback, 0.34, "Applying master cleanup")
        audio = _high_pass(audio, decoded.sample_rate, 24)
        operations.append("subsonic cleanup high-pass")
    except Exception as exc:
        errors.append(f"Master high-pass failed: {str(exc) or 'unknown error'}")

    try:
        _progress(progress_callback, 0.44, "Applying master EQ")
        warmth = float(controls.get("warmth", 0)) / 50.0
        brightness = float(controls.get("brightness", 0)) / 50.0
        if abs(warmth) > 0.02:
            audio = _eq_band(audio, decoded.sample_rate, 90, 260, warmth * 1.1)
            operations.append("master warmth EQ")
        if abs(brightness) > 0.02:
            audio = _eq_band(audio, decoded.sample_rate, 6800, min(14000, decoded.sample_rate / 2 - 200), brightness * 1.2)
            operations.append("master brightness EQ")
    except Exception as exc:
        errors.append(f"Master EQ failed: {str(exc) or 'unknown error'}")

    try:
        _progress(progress_callback, 0.56, "Applying glue compression")
        compression_amount = max(0.0, min(1.0, float(controls.get("compressionAmount", 45)) / 100.0))
        if compression_amount > 0:
            ratio = 1.4 + compression_amount * 2.4
            mix = 0.12 + compression_amount * 0.32
            threshold = -19.0 + compression_amount * 3.5
            audio = _compress_audio(audio, threshold_db=threshold, ratio=ratio, mix=mix)
            operations.append("glue compression")
    except Exception as exc:
        errors.append(f"Glue compression failed: {str(exc) or 'unknown error'}")

    try:
        _progress(progress_callback, 0.64, "Adjusting stereo width")
        width = (float(controls.get("stereoWidth", 55)) - 50.0) / 100.0
        if abs(width) > 0.02:
            audio = _apply_width(audio, width * 0.8)
            operations.append("stereo width adjustment")
    except Exception as exc:
        errors.append(f"Stereo width failed: {str(exc) or 'unknown error'}")

    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)
    _progress(progress_callback, 0.72, "Checking pre-limiter loudness")
    pre_loudness_metrics = _analyze_samples(audio, decoded.sample_rate)
    current_lufs = pre_loudness_metrics.get("integratedLufs")
    loudness_gain_db = 0.0
    if isinstance(current_lufs, (int, float)) and math.isfinite(current_lufs):
        loudness_gain_db = _round(target_lufs - float(current_lufs)) or 0.0
        max_gain = 14.0 if preset == "Very Loud" else 10.0
        if loudness_gain_db > max_gain:
            warnings.append(f"Loudness gain was capped at {max_gain:.1f} dB for safety.")
            loudness_gain_db = max_gain
        audio = _apply_gain(audio, loudness_gain_db)
        operations.append(f"loudness normalization toward {target_lufs:.1f} LUFS")
    else:
        warnings.append("Integrated LUFS could not be measured; mastering used peak safety only.")

    limiter_gain_db = 0.0
    try:
        _progress(progress_callback, 0.82, "Applying limiter and peak safety")
        limiter_strength = max(0.0, min(1.0, float(controls.get("limiterStrength", 55)) / 100.0))
        audio = _soft_limit(audio, true_peak_ceiling_db, limiter_strength)
        operations.append("mix-safe limiter")
    except Exception as exc:
        errors.append(f"Limiter failed: {str(exc) or 'unknown error'}")

    true_peak = _calculate_true_peak(audio)
    ceiling_linear = _db_to_linear(true_peak_ceiling_db)
    if true_peak > ceiling_linear:
        scale = ceiling_linear / max(true_peak, 1e-12)
        audio *= scale
        limiter_gain_db += _linear_to_db(scale)
        operations.append(f"true peak ceiling at {true_peak_ceiling_db:.1f} dBTP")

    audio = np.clip(audio, -ceiling_linear, ceiling_linear).astype(np.float32, copy=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _progress(progress_callback, 0.90, "Writing master file")
    _encode_float_audio(audio, output_path, codec_args=_codec_args_for_format(output_format), sample_rate=decoded.sample_rate)

    _progress(progress_callback, 0.96, "Measuring finished master")
    output_metrics = _analyze_samples(audio, decoded.sample_rate)
    dynamic_range_db = _dynamic_range_estimate(audio, decoded.sample_rate)
    if isinstance(output_metrics.get("integratedLufs"), (int, float)) and abs(float(output_metrics["integratedLufs"]) - target_lufs) > 1.5:
        warnings.append("Final LUFS differs from target because true-peak safety took priority.")

    return MasteringAudioResult(
        path=output_path,
        input_metrics=input_metrics,
        output_metrics=output_metrics,
        dynamic_range_db=dynamic_range_db,
        loudness_gain_db=_round(loudness_gain_db) or 0.0,
        limiter_gain_db=_round(limiter_gain_db) or 0.0,
        operations=operations,
        warnings=warnings,
        errors=errors,
    )


def export_audio_file(input_path: Path, output_path: Path, output_format: str, trim_start_seconds: float = 0.0, trim_end_seconds: float = 0.0) -> dict:
    ensure_audio_environment()
    info = _probe_audio(input_path)
    decoded = _decode_audio(input_path, sample_rate=info["sampleRate"], channels=info["channels"])
    audio = decoded.samples.astype(np.float32, copy=True)
    operations: list[str] = []
    if trim_start_seconds > 0 or trim_end_seconds > 0:
        audio, operations = _apply_time_trim(audio, decoded.sample_rate, trim_start_seconds, trim_end_seconds)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _encode_float_audio(audio.astype(np.float32, copy=False), output_path, codec_args=_codec_args_for_format(output_format), sample_rate=decoded.sample_rate)
    metrics = _analyze_samples(audio, decoded.sample_rate)
    metrics["dynamicRangeDb"] = _dynamic_range_estimate(audio, decoded.sample_rate)
    metrics["operations"] = operations
    return metrics


def _apply_time_trim(audio: np.ndarray, sample_rate: int, trim_start_seconds: float = 0.0, trim_end_seconds: float = 0.0) -> tuple[np.ndarray, list[str]]:
    start_seconds = max(0.0, float(trim_start_seconds or 0.0))
    end_seconds = max(0.0, float(trim_end_seconds or 0.0))
    if start_seconds <= 0.0 and end_seconds <= 0.0:
        return audio, []

    total_frames = int(audio.shape[0]) if audio.ndim > 1 else int(audio.size)
    if total_frames <= 0:
        raise ValueError("Selected mix contains no audio samples to crop.")

    start_frames = int(round(start_seconds * sample_rate))
    end_frames = int(round(end_seconds * sample_rate))
    if start_frames >= total_frames:
        raise ValueError("Crop start removes the entire song.")

    end_index = total_frames - end_frames if end_frames > 0 else total_frames
    if end_index <= start_frames:
        raise ValueError("Crop settings remove the entire song.")

    remaining_seconds = (end_index - start_frames) / max(1, sample_rate)
    if remaining_seconds < 0.5:
        raise ValueError("Crop settings leave less than 0.5 seconds of audio.")

    trimmed = audio[start_frames:end_index].copy()
    operations: list[str] = []
    if start_frames > 0:
        operations.append(f"cropped {_format_seconds_label(start_seconds)} from intro")
    if end_frames > 0:
        operations.append(f"cropped {_format_seconds_label(end_seconds)} from outro")
    return trimmed, operations


def _format_seconds_label(value: float) -> str:
    formatted = f"{max(0.0, float(value)):.2f}".rstrip("0").rstrip(".")
    return f"{formatted or '0'}s"


def _probe_audio(path: Path) -> dict[str, int]:
    ffmpeg = _ffmpeg_exe()
    command = [ffmpeg, "-hide_banner", "-i", str(path)]
    completed = subprocess.run(command, capture_output=True, text=True)
    output = f"{completed.stderr}\n{completed.stdout}"

    sample_rate_match = re.search(r"(\d+)\s*Hz", output)
    sample_rate = int(sample_rate_match.group(1)) if sample_rate_match else ANALYSIS_FALLBACK_SAMPLE_RATE

    channels = 2
    lowered = output.lower()
    if " mono" in lowered:
        channels = 1
    elif " stereo" in lowered:
        channels = 2
    else:
        channel_match = re.search(r"(\d+)\s*channels", lowered)
        if channel_match:
            channels = max(1, min(int(channel_match.group(1)), 2))

    return {"sampleRate": sample_rate, "channels": channels}


def _decode_audio(path: Path, sample_rate: int, channels: int) -> DecodedAudio:
    ffmpeg = _ffmpeg_exe()
    channel_count = max(1, min(int(channels), 2))
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channel_count),
        "pipe:1",
    ]
    completed = subprocess.run(command, capture_output=True)
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(error or "ffmpeg could not decode this audio file.")

    samples = np.frombuffer(completed.stdout, dtype=np.float32)
    if samples.size == 0:
        raise ValueError("ffmpeg decoded zero samples.")

    usable = samples.size - (samples.size % channel_count)
    samples = samples[:usable].reshape(-1, channel_count)
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    samples = np.clip(samples, -1.0, 1.0)
    return DecodedAudio(samples=samples, sample_rate=int(sample_rate), channels=channel_count)


def _encode_float_audio(audio: np.ndarray, output_path: Path, codec_args: list[str], sample_rate: int = ROUGH_MIX_SAMPLE_RATE) -> None:
    ffmpeg = _ffmpeg_exe()
    channel_count = 1 if audio.ndim == 1 else max(1, min(int(audio.shape[1]), 2))
    encoded_audio = audio.reshape(-1, channel_count) if audio.ndim == 1 else audio[:, :channel_count]
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-f",
        "f32le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channel_count),
        "-i",
        "pipe:0",
        *codec_args,
        str(output_path),
    ]
    completed = subprocess.run(command, input=encoded_audio.astype(np.float32).tobytes(), capture_output=True)
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(error or f"Could not write {output_path.name}.")


def _cleaning_parameters(stem_type: str, mode: str) -> dict[str, float | int | bool]:
    intensity = {"Light": 0.28, "Medium": 0.5, "Strong": 0.68}.get(mode, 0.0)
    params: dict[str, float | int | bool] = {
        "noiseReduction": intensity * 0.38,
        "highPassHz": 45,
        "noiseGate": intensity * 0.25,
        "gateFloor": 0.62,
        "clickReduction": intensity * 0.8,
        "deEss": 0.0,
        "plosiveReduction": 0.0,
        "compressionPrep": 0.0,
        "humStrength": 0.5 + intensity * 0.28,
        "tailCleanup": mode in {"Medium", "Strong"},
    }

    if stem_type == "Lead Vocal":
        params.update({"noiseReduction": intensity * 0.62, "highPassHz": 82, "deEss": intensity * 0.82, "plosiveReduction": intensity * 0.62, "compressionPrep": intensity * 0.25, "noiseGate": intensity * 0.32})
    elif stem_type == "Backing Vocal":
        params.update({"noiseReduction": intensity * 0.55, "highPassHz": 92, "deEss": intensity * 0.72, "compressionPrep": intensity * 0.16, "noiseGate": intensity * 0.3})
    elif stem_type in {"Drums", "Kick", "Snare"}:
        params.update({"noiseReduction": intensity * 0.12, "highPassHz": 0 if stem_type == "Kick" else 32, "noiseGate": intensity * 0.08, "gateFloor": 0.82, "tailCleanup": False})
    elif stem_type == "Bass":
        params.update({"noiseReduction": intensity * 0.2, "highPassHz": 26, "noiseGate": intensity * 0.18, "gateFloor": 0.76})
    elif stem_type in {"Electric Guitar", "Acoustic Guitar"}:
        params.update({"noiseReduction": intensity * 0.4, "highPassHz": 68 if stem_type == "Electric Guitar" else 82, "noiseGate": intensity * 0.34, "gateFloor": 0.62})
    elif stem_type in {"Keys/Piano", "Pads/Strings"}:
        params.update({"noiseReduction": intensity * 0.22, "highPassHz": 42, "noiseGate": intensity * 0.06, "gateFloor": 0.9, "tailCleanup": False})
    elif stem_type == "FX/Ambience":
        params.update({"noiseReduction": intensity * 0.08, "highPassHz": 24, "noiseGate": 0.0, "clickReduction": intensity * 0.25, "tailCleanup": False})

    return params


def _high_pass(audio: np.ndarray, sample_rate: int, cutoff_hz: float) -> np.ndarray:
    if cutoff_hz <= 0 or cutoff_hz >= sample_rate / 2:
        return audio
    sos = signal.butter(3, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
    return _safe_sos_filter(sos, audio)


def _low_pass(audio: np.ndarray, sample_rate: int, cutoff_hz: float) -> np.ndarray:
    sos = signal.butter(3, cutoff_hz, btype="lowpass", fs=sample_rate, output="sos")
    return _safe_sos_filter(sos, audio)


def _band_pass(audio: np.ndarray, sample_rate: int, low_hz: float, high_hz: float) -> np.ndarray:
    sos = signal.butter(3, [low_hz, high_hz], btype="bandpass", fs=sample_rate, output="sos")
    return _safe_sos_filter(sos, audio)


def _safe_sos_filter(sos: np.ndarray, audio: np.ndarray) -> np.ndarray:
    try:
        if audio.shape[0] > 64:
            return signal.sosfiltfilt(sos, audio, axis=0).astype(np.float32, copy=False)
    except Exception:
        pass
    return signal.sosfilt(sos, audio, axis=0).astype(np.float32, copy=False)


def _remove_hum(audio: np.ndarray, sample_rate: int, frequency: int, strength: float) -> np.ndarray:
    cleaned = audio
    base = 50 if int(frequency) == 50 else 60
    harmonics = [base * index for index in range(1, 8) if base * index < sample_rate / 2 - 50]
    q = max(18.0, 42.0 - strength * 18.0)
    for harmonic in harmonics:
        b, a = signal.iirnotch(harmonic, q, sample_rate)
        try:
            if cleaned.shape[0] > 64:
                filtered = signal.filtfilt(b, a, cleaned, axis=0)
            else:
                filtered = signal.lfilter(b, a, cleaned, axis=0)
        except Exception:
            filtered = signal.lfilter(b, a, cleaned, axis=0)
        cleaned = (cleaned * (1.0 - strength) + filtered * strength).astype(np.float32, copy=False)
    return cleaned


def _reduce_noise(audio: np.ndarray, sample_rate: int, strength: float, noise_profile: np.ndarray | None = None) -> np.ndarray:
    strength = max(0.0, min(0.9, strength))
    if strength <= 0:
        return audio
    if nr is not None:
        try:
            channels = []
            for channel_index in range(audio.shape[1]):
                y_noise = noise_profile[:, channel_index] if noise_profile is not None and noise_profile.size else None
                reduced = nr.reduce_noise(y=audio[:, channel_index], sr=sample_rate, y_noise=y_noise, prop_decrease=strength, stationary=False)
                channels.append(reduced)
            return np.stack(channels, axis=1).astype(np.float32, copy=False)
        except Exception:
            pass
    return _spectral_noise_reduction(audio, sample_rate, strength)


def _noise_profile(audio: np.ndarray, sample_rate: int) -> np.ndarray | None:
    frame_size = max(512, int(sample_rate * 0.05))
    if audio.shape[0] < frame_size * 4:
        return None
    mono = np.mean(audio, axis=1)
    frame_count = mono.shape[0] // frame_size
    frames = mono[: frame_count * frame_size].reshape(frame_count, frame_size)
    frame_rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    quiet_threshold = np.percentile(frame_rms, 20)
    quiet_indexes = np.where(frame_rms <= quiet_threshold)[0][:20]
    if quiet_indexes.size == 0:
        return None
    segments = []
    for index in quiet_indexes:
        start = index * frame_size
        segments.append(audio[start : start + frame_size])
    return np.concatenate(segments, axis=0)


def _spectral_noise_reduction(audio: np.ndarray, sample_rate: int, strength: float) -> np.ndarray:
    reduced_channels = []
    for channel_index in range(audio.shape[1]):
        channel = audio[:, channel_index]
        freqs, times, stft = signal.stft(channel, fs=sample_rate, nperseg=2048, noverlap=1536)
        magnitude = np.abs(stft)
        if magnitude.size == 0:
            reduced_channels.append(channel)
            continue
        frame_energy = np.mean(magnitude, axis=0)
        quiet = frame_energy <= np.percentile(frame_energy, 25)
        noise = np.median(magnitude[:, quiet], axis=1, keepdims=True) if np.any(quiet) else np.median(magnitude, axis=1, keepdims=True)
        threshold = noise * (1.15 + strength * 2.4)
        attenuation = 1.0 - strength * 0.75
        gain = np.where(magnitude < threshold, attenuation, 1.0)
        _freqs, cleaned = signal.istft(stft * gain, fs=sample_rate, nperseg=2048, noverlap=1536)
        reduced_channels.append(_match_length(cleaned, channel.shape[0]))
    return np.stack(reduced_channels, axis=1).astype(np.float32, copy=False)


def _noise_gate(audio: np.ndarray, sample_rate: int, strength: float, floor: float) -> np.ndarray:
    strength = max(0.0, min(1.0, strength))
    if strength <= 0:
        return audio
    frame_size = max(256, int(sample_rate * 0.025))
    hop = max(128, frame_size // 2)
    mono = np.mean(np.abs(audio), axis=1)
    if mono.shape[0] < frame_size:
        return audio
    starts = np.arange(0, mono.shape[0] - frame_size + 1, hop)
    rms = np.array([np.sqrt(np.mean(np.square(mono[start : start + frame_size], dtype=np.float64))) for start in starts])
    threshold = max(_db_to_linear(-58), np.percentile(rms, 20) * (1.4 + strength * 2.0))
    open_amount = np.clip((rms - threshold) / (threshold + 1e-9), 0.0, 1.0)
    gate_floor = max(0.05, min(0.95, floor))
    gain_frames = gate_floor + (1.0 - gate_floor) * open_amount
    gain_frames = 1.0 - (1.0 - gain_frames) * strength
    sample_positions = starts + frame_size // 2
    envelope = np.interp(np.arange(audio.shape[0]), sample_positions, gain_frames, left=gain_frames[0], right=gain_frames[-1])
    envelope = signal.savgol_filter(envelope, min(501, max(5, (len(envelope) // 100) * 2 + 1)), 2) if len(envelope) > 501 else envelope
    return (audio * envelope[:, None]).astype(np.float32, copy=False)


def _de_ess(audio: np.ndarray, sample_rate: int, strength: float) -> np.ndarray:
    if strength <= 0 or sample_rate < 16000:
        return audio
    high = _band_pass(audio, sample_rate, 5200, min(10500, sample_rate / 2 - 200))
    rest = audio - high
    envelope = np.mean(np.abs(high), axis=1)
    threshold = np.percentile(envelope, 86)
    if threshold <= 1e-8:
        return audio
    reduction = np.where(envelope > threshold, 1.0 - min(0.7, strength * 0.55), 1.0)
    reduction = _smooth_envelope(reduction, sample_rate, 0.012)
    return (rest + high * reduction[:, None]).astype(np.float32, copy=False)


def _reduce_plosives(audio: np.ndarray, sample_rate: int, strength: float) -> np.ndarray:
    if strength <= 0:
        return audio
    low = _low_pass(audio, sample_rate, 170)
    rest = audio - low
    envelope = np.mean(np.abs(low), axis=1)
    threshold = np.percentile(envelope, 94)
    if threshold <= 1e-8:
        return audio
    reduction = np.where(envelope > threshold, 1.0 - min(0.65, strength * 0.55), 1.0)
    reduction = _smooth_envelope(reduction, sample_rate, 0.025)
    return (rest + low * reduction[:, None]).astype(np.float32, copy=False)


def _reduce_clicks(audio: np.ndarray, strength: float) -> np.ndarray:
    if strength <= 0:
        return audio
    cleaned = audio.copy()
    for channel_index in range(cleaned.shape[1]):
        channel = cleaned[:, channel_index]
        diff = np.abs(np.diff(channel, prepend=channel[0]))
        threshold = max(0.2, np.percentile(diff, 99.85) * (1.0 + (1.0 - strength)))
        spike_indexes = np.where(diff > threshold)[0]
        for index in spike_indexes[:5000]:
            if 2 <= index < len(channel) - 2:
                channel[index] = np.median(channel[index - 2 : index + 3])
        cleaned[:, channel_index] = channel
    return cleaned.astype(np.float32, copy=False)


def _reduce_breaths(audio: np.ndarray, sample_rate: int, strength: float) -> np.ndarray:
    strength = max(0.0, min(1.0, strength))
    if strength <= 0 or audio.size == 0 or sample_rate < 12000:
        return audio
    mono = np.mean(np.abs(audio), axis=1)
    envelope = _smooth_envelope(mono, sample_rate, 0.035)
    high = _band_pass(audio, sample_rate, 4500, min(11000, sample_rate / 2 - 200))
    high_env = _smooth_envelope(np.mean(np.abs(high), axis=1), sample_rate, 0.025)
    audible = envelope[envelope > _db_to_linear(-58)]
    if audible.size < 8:
        return audio
    quiet_threshold = float(np.percentile(audible, 46))
    high_threshold = float(np.percentile(high_env, 62))
    breath_like = (envelope < quiet_threshold) & (envelope > _db_to_linear(-55)) & (high_env > high_threshold)
    if not np.any(breath_like):
        return audio
    mask = _smooth_envelope(breath_like.astype(np.float32), sample_rate, 0.045)
    gain = 1.0 - mask * min(0.72, 0.18 + strength * 0.55)
    return (audio * gain[:, None]).astype(np.float32, copy=False)


def _compression_prepare(audio: np.ndarray, strength: float) -> np.ndarray:
    strength = max(0.0, min(0.7, strength))
    if strength <= 0:
        return audio
    threshold = np.percentile(np.abs(audio), 96)
    if threshold <= 1e-6:
        return audio
    amount = 1.0 + strength * 2.5
    magnitude = np.abs(audio)
    reduced = np.where(magnitude > threshold, threshold + (magnitude - threshold) / amount, magnitude)
    return (np.sign(audio) * reduced).astype(np.float32, copy=False)


def _cleanup_silent_tail(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    frame_size = max(256, int(sample_rate * 0.05))
    mono = np.mean(np.abs(audio), axis=1)
    if mono.shape[0] < frame_size * 4:
        return audio
    frame_count = mono.shape[0] // frame_size
    frames = mono[: frame_count * frame_size].reshape(frame_count, frame_size)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    audible = np.where(rms > _db_to_linear(-55))[0]
    if audible.size == 0:
        return audio
    last = int((audible[-1] + 1) * frame_size)
    keep_until = min(audio.shape[0], last + int(sample_rate * 0.25))
    if audio.shape[0] - keep_until < sample_rate * 0.5:
        return audio
    cleaned = audio.copy()
    fade_len = min(int(sample_rate * 0.08), audio.shape[0] - keep_until)
    if fade_len > 0:
        fade = np.linspace(1.0, 0.0, fade_len)
        cleaned[keep_until : keep_until + fade_len] *= fade[:, None]
    cleaned[keep_until + fade_len :] = 0
    return cleaned


def _smooth_envelope(envelope: np.ndarray, sample_rate: int, seconds: float) -> np.ndarray:
    window = max(3, int(sample_rate * seconds))
    if window % 2 == 0:
        window += 1
    if envelope.size <= window:
        return envelope
    kernel = np.ones(window) / window
    return np.convolve(envelope, kernel, mode="same")


def _match_length(audio: np.ndarray, length: int) -> np.ndarray:
    if audio.shape[0] == length:
        return audio
    if audio.shape[0] > length:
        return audio[:length]
    return np.pad(audio, (0, length - audio.shape[0]))


def _codec_args_for_format(output_format: str) -> list[str]:
    if output_format == "WAV 16-bit":
        return ["-c:a", "pcm_s16le"]
    if output_format == "WAV 24-bit":
        return ["-c:a", "pcm_s24le"]
    if output_format == "MP3 320kbps":
        return ["-c:a", "libmp3lame", "-b:a", "320k"]
    if output_format == "FLAC":
        return ["-c:a", "flac", "-compression_level", "5"]
    raise ValueError("Unsupported output format.")


def _soft_limit(audio: np.ndarray, ceiling_db: float, strength: float) -> np.ndarray:
    strength = max(0.0, min(1.0, strength))
    if strength <= 0:
        return audio
    ceiling = _db_to_linear(ceiling_db)
    magnitude = np.abs(audio)
    sign = np.sign(audio)
    threshold = ceiling * (0.86 - strength * 0.16)
    knee = max(1e-6, ceiling - threshold)
    curve = threshold + knee * np.tanh((magnitude - threshold) / knee * (1.0 + strength * 2.5))
    limited = np.where(magnitude > threshold, curve, magnitude)
    return (sign * np.minimum(limited, ceiling)).astype(np.float32, copy=False)


def _dynamic_range_estimate(audio: np.ndarray, sample_rate: int) -> float | None:
    mono = np.mean(audio, axis=1) if audio.ndim == 2 else audio
    frame_size = max(256, int(sample_rate * 0.4))
    if mono.shape[0] < frame_size * 2:
        return None
    frame_count = mono.shape[0] // frame_size
    frames = mono[: frame_count * frame_size].reshape(frame_count, frame_size)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    rms_db = np.array([_linear_to_db(float(value)) for value in rms if value > 1e-9])
    if rms_db.size < 2:
        return None
    return _round(float(np.percentile(rms_db, 95) - np.percentile(rms_db, 10)))


def _process_advanced_stem(audio: np.ndarray, sample_rate: int, item: dict, controls: dict, warnings: list[str]) -> tuple[np.ndarray, np.ndarray]:
    stem_type = item.get("stemType", "Unknown")
    processing_enabled = bool(item.get("processingChainEnabled", True))
    vocal_channel_strip_enabled = processing_enabled and not _should_bypass_vocal_channel_strip(item)
    compression_amount = max(0.0, min(1.0, float(item.get("compressionAmount", 50)) / 100.0))
    dry = audio.astype(np.float32, copy=True)

    if vocal_channel_strip_enabled:
        for label, processor in _advanced_chain(stem_type, sample_rate, controls, compression_amount):
            try:
                dry = processor(dry)
            except Exception as exc:
                warnings.append(f"{item.get('filename', 'Stem')}: skipped {label} ({str(exc) or 'failed'}).")
                continue
        try:
            dry = _apply_stem_presence(dry, sample_rate, stem_type, float(item.get("presenceAmount", 0)))
        except Exception as exc:
            warnings.append(f"{item.get('filename', 'Stem')}: skipped presence control ({str(exc) or 'failed'}).")

    total_gain = float(item.get("gainDb", 0)) + float(item.get("presetGainDb", 0))
    if stem_type == "Lead Vocal":
        total_gain += float(controls.get("vocalBoost", 0))
    dry = _apply_gain(dry, total_gain)
    dry = _apply_pan(dry, float(item.get("pan", 0)))

    send_amount = _stem_reverb_amount(stem_type, float(item.get("reverbSend", 35)), controls)
    send = dry * send_amount
    dry = np.clip(dry, -1.2, 1.2).astype(np.float32, copy=False)
    send = np.clip(send, -1.0, 1.0).astype(np.float32, copy=False)
    return dry, send


def _should_bypass_vocal_channel_strip(item: dict) -> bool:
    # Enhanced vocals already have their own shaping, so re-running the mix strip
    # tends to over-compress and over-brighten them.
    return item.get("sourceKind") == "Enhanced Vocal" and item.get("stemType") in {"Lead Vocal", "Backing Vocal"}


def _advanced_chain(stem_type: str, sample_rate: int, controls: dict, compression_amount: float) -> list[tuple[str, Any]]:
    brightness = float(controls.get("brightness", 0)) / 50.0
    warmth = float(controls.get("warmth", 0)) / 50.0
    drum_punch = _control_ratio(controls, "drumPunch")
    bass_weight = _control_ratio(controls, "bassWeight")
    width = _control_ratio(controls, "width")
    backing_width = _control_ratio(controls, "backingVocalWidth")

    def tone(audio: np.ndarray) -> np.ndarray:
        return _apply_stem_tone(audio, sample_rate, brightness, warmth)

    if stem_type == "Lead Vocal":
        return [
            ("vocal high-pass", lambda audio: _high_pass(audio, sample_rate, 85)),
            ("vocal cleanup EQ", lambda audio: _eq_band(audio, sample_rate, 220, 420, -1.8)),
            ("vocal presence EQ", lambda audio: _eq_band(audio, sample_rate, 2500, 5200, 1.4 + brightness * 1.2)),
            ("vocal de-esser", lambda audio: _de_ess(audio, sample_rate, 0.45 + compression_amount * 0.3)),
            ("vocal compressor", lambda audio: _compress_audio(audio, threshold_db=-22, ratio=3.2, mix=0.45 + compression_amount * 0.4)),
            ("vocal tone", tone),
        ]
    if stem_type == "Backing Vocal":
        return [
            ("backing vocal high-pass", lambda audio: _high_pass(audio, sample_rate, 100)),
            ("backing vocal cleanup EQ", lambda audio: _eq_band(audio, sample_rate, 250, 500, -1.5)),
            ("backing vocal compressor", lambda audio: _compress_audio(audio, threshold_db=-24, ratio=3.0, mix=0.4 + compression_amount * 0.35)),
            ("backing vocal spread", lambda audio: _apply_width(audio, 0.08 + width * 0.16 + backing_width * 0.28)),
            ("backing vocal tone", tone),
        ]
    if stem_type == "Drums":
        return [
            ("drum low-end cleanup", lambda audio: _high_pass(audio, sample_rate, 28)),
            ("drum mud control", lambda audio: _eq_band(audio, sample_rate, 260, 520, -1.0)),
            ("drum bus compression", lambda audio: _compress_audio(audio, threshold_db=-18, ratio=2.2 + drum_punch * 1.4, mix=0.18 + compression_amount * 0.22)),
            ("drum transient tone", lambda audio: _eq_band(audio, sample_rate, 4500, 9000, drum_punch * 1.0 + brightness * 0.8)),
            ("drum tone", tone),
        ]
    if stem_type == "Kick":
        return [
            ("kick rumble cleanup", lambda audio: _high_pass(audio, sample_rate, 24)),
            ("kick low-end control", lambda audio: _eq_band(audio, sample_rate, 180, 360, -1.2)),
            ("kick weight", lambda audio: _eq_band(audio, sample_rate, 45, 90, -0.5 + bass_weight * 1.2)),
            ("kick compression", lambda audio: _compress_audio(audio, threshold_db=-17, ratio=3.4, mix=0.25 + compression_amount * 0.28)),
        ]
    if stem_type == "Snare":
        return [
            ("snare high-pass", lambda audio: _high_pass(audio, sample_rate, 70)),
            ("snare body control", lambda audio: _eq_band(audio, sample_rate, 350, 700, -0.8)),
            ("snare crack", lambda audio: _eq_band(audio, sample_rate, 3000, 6500, 0.8 + drum_punch * 1.0)),
            ("snare compression", lambda audio: _compress_audio(audio, threshold_db=-19, ratio=2.8, mix=0.2 + compression_amount * 0.25)),
        ]
    if stem_type == "Bass":
        return [
            ("bass sub cleanup", lambda audio: _high_pass(audio, sample_rate, 28)),
            ("bass low-end control", lambda audio: _eq_band(audio, sample_rate, 45, 110, -0.4 + bass_weight * 1.4)),
            ("bass mud control", lambda audio: _eq_band(audio, sample_rate, 180, 420, -1.0)),
            ("bass compression", lambda audio: _compress_audio(audio, threshold_db=-21, ratio=3.8, mix=0.35 + compression_amount * 0.38)),
            ("bass saturation", lambda audio: _saturate(audio, drive=1.15 + bass_weight * 0.45, mix=0.08 + bass_weight * 0.08)),
            ("bass mono focus", lambda audio: _apply_width(audio, -0.35)),
        ]
    if stem_type == "Electric Guitar":
        return [
            ("electric guitar high-pass", lambda audio: _high_pass(audio, sample_rate, 72)),
            ("electric guitar mud control", lambda audio: _eq_band(audio, sample_rate, 220, 520, -1.8)),
            ("electric guitar bite", lambda audio: _eq_band(audio, sample_rate, 2200, 5200, 0.5 + brightness * 0.9)),
            ("electric guitar compression", lambda audio: _compress_audio(audio, threshold_db=-20, ratio=2.4, mix=0.16 + compression_amount * 0.22)),
            ("electric guitar width", lambda audio: _apply_width(audio, width * 0.18)),
            ("electric guitar tone", tone),
        ]
    if stem_type == "Acoustic Guitar":
        return [
            ("acoustic high-pass", lambda audio: _high_pass(audio, sample_rate, 86)),
            ("acoustic boom control", lambda audio: _eq_band(audio, sample_rate, 140, 320, -1.6)),
            ("acoustic presence", lambda audio: _eq_band(audio, sample_rate, 2500, 6500, 0.7 + brightness * 0.8)),
            ("acoustic compression", lambda audio: _compress_audio(audio, threshold_db=-22, ratio=2.2, mix=0.18 + compression_amount * 0.2)),
            ("acoustic tone", tone),
        ]
    if stem_type == "Keys/Piano":
        return [
            ("keys high-pass", lambda audio: _high_pass(audio, sample_rate, 58)),
            ("keys vocal-space EQ", lambda audio: _eq_band(audio, sample_rate, 1800, 4200, -0.7)),
            ("keys width", lambda audio: _apply_width(audio, width * 0.22)),
            ("keys light compression", lambda audio: _compress_audio(audio, threshold_db=-24, ratio=1.8, mix=0.08 + compression_amount * 0.14)),
            ("keys tone", tone),
        ]
    if stem_type == "Pads/Strings":
        return [
            ("pad high-pass", lambda audio: _high_pass(audio, sample_rate, 70)),
            ("pad background EQ", lambda audio: _eq_band(audio, sample_rate, 1200, 3600, -0.8)),
            ("pad width", lambda audio: _apply_width(audio, 0.16 + width * 0.3)),
            ("pad tone", tone),
        ]
    if stem_type == "FX/Ambience":
        return [
            ("ambience high-pass", lambda audio: _high_pass(audio, sample_rate, 35)),
            ("ambience width", lambda audio: _apply_width(audio, 0.22 + width * 0.32)),
            ("ambience tone", tone),
        ]
    return [
        ("general high-pass", lambda audio: _high_pass(audio, sample_rate, 50)),
        ("general cleanup EQ", lambda audio: _eq_band(audio, sample_rate, 250, 500, -0.8)),
        ("general compression", lambda audio: _compress_audio(audio, threshold_db=-22, ratio=2.0, mix=0.1 + compression_amount * 0.16)),
        ("general tone", tone),
    ]


def _eq_band(audio: np.ndarray, sample_rate: int, low_hz: float, high_hz: float, gain_db: float) -> np.ndarray:
    if abs(gain_db) < 0.05 or high_hz <= low_hz or low_hz >= sample_rate / 2:
        return audio
    high = min(high_hz, sample_rate / 2 - 100)
    if high <= low_hz:
        return audio
    band = _band_pass(audio, sample_rate, low_hz, high)
    return (audio + band * (_db_to_linear(gain_db) - 1.0)).astype(np.float32, copy=False)


def _compress_audio(audio: np.ndarray, threshold_db: float, ratio: float, mix: float) -> np.ndarray:
    mix = max(0.0, min(1.0, mix))
    if mix <= 0:
        return audio
    threshold = _db_to_linear(threshold_db)
    ratio = max(1.0, ratio)
    magnitude = np.abs(audio)
    over = magnitude > threshold
    compressed_mag = np.where(over, threshold + (magnitude - threshold) / ratio, magnitude)
    compressed = np.sign(audio) * compressed_mag
    return (audio * (1.0 - mix) + compressed * mix).astype(np.float32, copy=False)


def _saturate(audio: np.ndarray, drive: float, mix: float) -> np.ndarray:
    mix = max(0.0, min(1.0, mix))
    drive = max(1.0, drive)
    if mix <= 0:
        return audio
    saturated = np.tanh(audio * drive) / np.tanh(drive)
    return (audio * (1.0 - mix) + saturated * mix).astype(np.float32, copy=False)


def _apply_width(audio: np.ndarray, amount: float) -> np.ndarray:
    if audio.ndim != 2 or audio.shape[1] < 2 or abs(amount) < 0.01:
        return audio
    left = audio[:, 0]
    right = audio[:, 1]
    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    side *= max(0.0, 1.0 + amount)
    widened = np.stack([mid + side, mid - side], axis=1)
    return np.clip(widened, -1.2, 1.2).astype(np.float32, copy=False)


def _apply_stem_tone(audio: np.ndarray, sample_rate: int, brightness: float, warmth: float) -> np.ndarray:
    toned = audio
    if abs(warmth) > 0.02:
        toned = _eq_band(toned, sample_rate, 120, 360, warmth * 1.1)
    if abs(brightness) > 0.02:
        toned = _eq_band(toned, sample_rate, 5200, min(12000, sample_rate / 2 - 200), brightness * 1.2)
    return toned


def _apply_stem_presence(audio: np.ndarray, sample_rate: int, stem_type: str, amount: float) -> np.ndarray:
    amount = max(-1.0, min(1.0, amount / 50.0))
    if abs(amount) < 0.02:
        return audio
    bands = {
        "Lead Vocal": (2400, 5400, 2.0),
        "Backing Vocal": (2200, 5000, 1.5),
        "Snare": (3000, 7000, 1.6),
        "Electric Guitar": (2100, 5600, 1.4),
        "Acoustic Guitar": (2600, 7200, 1.4),
        "Keys/Piano": (1600, 4200, 1.0),
        "Pads/Strings": (1400, 4200, 0.8),
        "FX/Ambience": (1800, 6800, 0.9),
        "Bass": (650, 1400, 0.8),
    }
    low_hz, high_hz, scale = bands.get(stem_type, (2200, 5200, 1.0))
    return _eq_band(audio, sample_rate, low_hz, high_hz, amount * scale)


def _vocal_enhancer_parameters(preset: str) -> dict[str, float]:
    presets = {
        "Natural Clean": {
            "highPassHz": 88,
            "noiseReduction": 0.12,
            "deEss": 0.36,
            "rider": 0.42,
            "bodyDb": 0.2,
            "presenceDb": 0.9,
            "airDb": 0.7,
            "compression": 0.48,
            "compressionThresholdDb": -23,
            "compressionRatio": 2.6,
            "saturation": 0.04,
            "doubler": 0.0,
            "width": 0.0,
        },
        "Pop Vocal": {
            "highPassHz": 95,
            "noiseReduction": 0.14,
            "deEss": 0.52,
            "rider": 0.58,
            "bodyDb": -0.1,
            "presenceDb": 1.5,
            "airDb": 1.4,
            "compression": 0.66,
            "compressionThresholdDb": -24,
            "compressionRatio": 3.2,
            "saturation": 0.075,
            "doubler": 0.10,
            "width": 0.04,
        },
        "Worship Lead": {
            "highPassHz": 90,
            "noiseReduction": 0.14,
            "deEss": 0.46,
            "rider": 0.56,
            "bodyDb": 0.3,
            "presenceDb": 1.1,
            "airDb": 1.0,
            "compression": 0.58,
            "compressionThresholdDb": -24,
            "compressionRatio": 2.9,
            "saturation": 0.05,
            "doubler": 0.08,
            "width": 0.03,
        },
        "Live Vocal Fix": {
            "highPassHz": 105,
            "noiseReduction": 0.22,
            "deEss": 0.48,
            "rider": 0.62,
            "bodyDb": -0.2,
            "presenceDb": 0.8,
            "airDb": 0.4,
            "compression": 0.56,
            "compressionThresholdDb": -24,
            "compressionRatio": 3.0,
            "saturation": 0.035,
            "doubler": 0.0,
            "width": 0.0,
        },
        "Bright AI Polish": {
            "highPassHz": 100,
            "noiseReduction": 0.18,
            "deEss": 0.62,
            "rider": 0.68,
            "bodyDb": -0.3,
            "presenceDb": 1.9,
            "airDb": 2.1,
            "compression": 0.72,
            "compressionThresholdDb": -25,
            "compressionRatio": 3.6,
            "saturation": 0.09,
            "doubler": 0.12,
            "width": 0.05,
        },
        "Warm Ballad": {
            "highPassHz": 82,
            "noiseReduction": 0.12,
            "deEss": 0.38,
            "rider": 0.50,
            "bodyDb": 0.8,
            "presenceDb": 0.7,
            "airDb": 0.6,
            "compression": 0.54,
            "compressionThresholdDb": -23,
            "compressionRatio": 2.7,
            "saturation": 0.08,
            "doubler": 0.04,
            "width": 0.02,
        },
        "Backing Vocal Wide": {
            "highPassHz": 115,
            "noiseReduction": 0.14,
            "deEss": 0.44,
            "rider": 0.48,
            "bodyDb": -0.2,
            "presenceDb": 0.8,
            "airDb": 1.0,
            "compression": 0.52,
            "compressionThresholdDb": -24,
            "compressionRatio": 2.8,
            "saturation": 0.045,
            "doubler": 0.20,
            "width": 0.16,
        },
    }
    params = dict(presets.get(preset, presets["Natural Clean"]))
    params.setdefault("breathReduction", 0.18)
    params.setdefault("mouthClickReduction", 0.16)
    return params


def _scale_preset_amount(base_value: float, amount: float, max_value: float = 1.0) -> float:
    amount = max(0.0, min(100.0, amount))
    factor = 0.25 + (amount / 50.0) * 0.75
    return max(0.0, min(max_value, base_value * factor))


def _pitch_polish(audio: np.ndarray, sample_rate: int, mode: str, key: str, scale: str, strength: float = 50, humanize: float = 60) -> tuple[np.ndarray, str, str | None]:
    try:
        mono = np.mean(audio, axis=1).astype(np.float32, copy=False)
        if mono.size < sample_rate:
            return audio, f"{mode} pitch polish skipped", "Vocal is too short for pitch estimation."
        max_samples = min(mono.shape[0], sample_rate * 90)
        analysis_audio = mono[:max_samples]
        f0, _, _ = librosa.pyin(
            analysis_audio,
            fmin=librosa.note_to_hz("C2"),
            fmax=librosa.note_to_hz("C6"),
            sr=sample_rate,
            frame_length=2048,
            hop_length=512,
        )
        voiced = f0[np.isfinite(f0)]
        if voiced.size < 8:
            return audio, f"{mode} pitch polish skipped", "Could not find enough voiced vocal frames for pitch polish."
        median_midi = float(np.median(librosa.hz_to_midi(voiced)))
        target_midi = _nearest_target_midi(median_midi, key, scale)
        semitones = target_midi - median_midi
        strength_ratio = max(0.0, min(1.0, strength / 100.0))
        humanize_ratio = max(0.0, min(1.0, humanize / 100.0))
        max_shift = {"Natural": 0.2, "Medium": 0.45, "Strong": 0.8}.get(mode, 0.0)
        max_shift *= 0.45 + strength_ratio * 1.25
        semitones = max(-max_shift, min(max_shift, semitones))
        semitones *= 1.0 - humanize_ratio * 0.55
        if abs(semitones) < 0.025:
            return audio, f"{mode} pitch polish checked", None
        shifted = np.zeros_like(audio)
        for channel in range(audio.shape[1]):
            shifted[:, channel] = librosa.effects.pitch_shift(y=audio[:, channel], sr=sample_rate, n_steps=semitones)
        return shifted.astype(np.float32, copy=False), f"{mode} key-center pitch polish ({semitones:+.2f} st, strength {int(round(strength))}%, humanize {int(round(humanize))}%)", None
    except Exception as exc:
        return audio, f"{mode} pitch polish skipped", f"Pitch polish unavailable: {str(exc) or 'analysis failed'}."


def _nearest_target_midi(midi_value: float, key: str, scale: str) -> float:
    if key == "Auto" or scale == "Chromatic":
        return round(midi_value)
    key_offsets = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    scale_steps = {
        "Major": {0, 2, 4, 5, 7, 9, 11},
        "Minor": {0, 2, 3, 5, 7, 8, 10},
    }.get(scale, set(range(12)))
    root = key_offsets.get(key, 0)
    candidates = []
    base_octave = math.floor(midi_value / 12) * 12
    for octave in range(-1, 2):
        for step in scale_steps:
            candidates.append(base_octave + octave * 12 + root + step)
    return float(min(candidates, key=lambda candidate: abs(candidate - midi_value)))


def _estimate_key_and_scale(mono: np.ndarray, sample_rate: int) -> tuple[str, str, float]:
    try:
        if mono.size < sample_rate:
            return "Auto", "Major", 0.0
        chroma = librosa.feature.chroma_stft(y=mono, sr=sample_rate, n_fft=4096, hop_length=1024)
        profile = np.mean(chroma, axis=1)
        if not np.any(profile):
            return "Auto", "Major", 0.0
        profile = profile / (np.linalg.norm(profile) + 1e-9)
        major_template = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88], dtype=np.float64)
        minor_template = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17], dtype=np.float64)
        templates = [("Major", major_template / np.linalg.norm(major_template)), ("Minor", minor_template / np.linalg.norm(minor_template))]
        key_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        scores: list[tuple[float, str, str]] = []
        for scale, template in templates:
            for shift, key in enumerate(key_names):
                scores.append((float(np.dot(profile, np.roll(template, shift))), key, scale))
        scores.sort(reverse=True, key=lambda item: item[0])
        best_score, key, scale = scores[0]
        second_score = scores[1][0] if len(scores) > 1 else 0.0
        confidence = max(0.0, min(95.0, 45.0 + (best_score - second_score) * 260.0 + (best_score - 0.65) * 55.0))
        return key, scale, confidence
    except Exception:
        return "Auto", "Major", 0.0


def _vocal_rider(audio: np.ndarray, sample_rate: int, strength: float) -> np.ndarray:
    strength = max(0.0, min(1.0, strength))
    if strength <= 0 or audio.size == 0:
        return audio
    mono = np.mean(np.abs(audio), axis=1)
    envelope = _smooth_envelope(mono, sample_rate, 0.11)
    active = envelope > max(np.percentile(envelope, 45), _db_to_linear(-48))
    if not np.any(active):
        return audio
    target = float(np.percentile(envelope[active], 68))
    gain = np.ones_like(envelope, dtype=np.float32)
    gain[active] = np.sqrt(target / np.maximum(envelope[active], 1e-6))
    gain = np.clip(gain, _db_to_linear(-5.5 * strength), _db_to_linear(5.0 * strength))
    gain = _smooth_envelope(gain, sample_rate, 0.18)
    ridden = audio * (1.0 + (gain[:, None] - 1.0) * strength)
    return np.clip(ridden, -1.2, 1.2).astype(np.float32, copy=False)


def _vocal_doubler(audio: np.ndarray, sample_rate: int, amount: float) -> np.ndarray:
    amount = max(0.0, min(0.35, amount))
    if amount <= 0 or audio.size == 0:
        return audio
    delay = max(1, int(sample_rate * 0.018))
    doubled = audio.copy()
    delayed = np.zeros_like(audio)
    if delay < audio.shape[0]:
        delayed[delay:, 0] = audio[:-delay, 1] if audio.shape[1] > 1 else audio[:-delay, 0]
        delayed[delay:, 1] = audio[:-delay, 0] if audio.shape[1] > 1 else audio[:-delay, 0]
    doubled[:, 0] += delayed[:, 0] * amount
    doubled[:, 1] -= delayed[:, 1] * amount * 0.65
    return np.clip(doubled, -1.2, 1.2).astype(np.float32, copy=False)


def _apply_vocal_fx(audio: np.ndarray, sample_rate: int, style: str, amount: float) -> np.ndarray:
    amount_ratio = max(0.0, min(1.0, amount / 100.0))
    if amount_ratio <= 0:
        return audio
    if style == "Natural Plate":
        wet = _simple_reverb(audio, sample_rate, amount=0.18 * amount_ratio, room_size=0.52)
        mixed = audio + wet
    elif style == "Small Hall":
        wet = _simple_reverb(audio, sample_rate, amount=0.25 * amount_ratio, room_size=0.82)
        mixed = audio + wet
    elif style == "Slap Delay":
        wet = _delay_effect(audio, sample_rate, delay_seconds=0.105, feedback=0.10, amount=0.20 * amount_ratio)
        mixed = audio + wet
    elif style == "Quarter Delay":
        wet = _delay_effect(audio, sample_rate, delay_seconds=0.32, feedback=0.26, amount=0.16 * amount_ratio)
        mixed = audio + wet
    elif style == "Worship Wide":
        reverb = _simple_reverb(audio, sample_rate, amount=0.24 * amount_ratio, room_size=0.95)
        delay = _delay_effect(audio, sample_rate, delay_seconds=0.28, feedback=0.28, amount=0.14 * amount_ratio)
        spread = _apply_width(delay + reverb, 0.26)
        mixed = audio + spread
    else:
        mixed = audio
    return np.clip(mixed, -1.2, 1.2).astype(np.float32, copy=False)


def _final_vocal_level(audio: np.ndarray, target_peak_db: float) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 1e-8:
        return audio
    target = _db_to_linear(target_peak_db)
    if peak > target:
        return (audio * (target / peak)).astype(np.float32, copy=False)
    return audio.astype(np.float32, copy=False)


def _apply_master_tone(audio: np.ndarray, sample_rate: int, controls: dict) -> np.ndarray:
    width = (_control_ratio(controls, "width") - 0.5) * 0.45
    warmth = float(controls.get("warmth", 0)) / 50.0
    brightness = float(controls.get("brightness", 0)) / 50.0
    toned = _apply_width(audio, width)
    if abs(warmth) > 0.02:
        toned = _eq_band(toned, sample_rate, 90, 260, warmth * 0.8)
    if abs(brightness) > 0.02:
        toned = _eq_band(toned, sample_rate, 7000, min(14000, sample_rate / 2 - 200), brightness * 0.9)
    return toned


def _process_vocal_mix_bus(audio: np.ndarray, sample_rate: int, controls: dict, warnings: list[str]) -> np.ndarray:
    if audio.size == 0:
        return audio
    vocal_bus = audio.astype(np.float32, copy=True)
    glue = _control_ratio(controls, "vocalGlueAmount")
    if glue > 0.01:
        vocal_bus = _compress_audio(vocal_bus, threshold_db=-21.5 + (0.5 - glue) * 4.0, ratio=1.5 + glue * 2.0, mix=0.12 + glue * 0.30)
    delay_amount = _control_ratio(controls, "vocalDelayAmount")
    if delay_amount > 0.01:
        vocal_bus = vocal_bus + _delay_effect(vocal_bus, sample_rate, delay_seconds=0.285, feedback=0.18 + delay_amount * 0.12, amount=0.02 + delay_amount * 0.055)
    level = float(controls.get("vocalBusLevel", 0))
    if abs(level) > 0.01:
        vocal_bus = _apply_gain(vocal_bus, level)
    if glue > 0.82:
        warnings.append("High vocal bus glue can reduce vocal dynamics; compare the mix version against the previous one.")
    if delay_amount > 0.75:
        warnings.append("High vocal delay can blur lyrics; reduce Vocal Delay if the lead feels less direct.")
    return np.clip(vocal_bus, -1.2, 1.2).astype(np.float32, copy=False)


def _stem_reverb_amount(stem_type: str, reverb_send: float, controls: dict) -> float:
    send = max(0.0, min(1.0, reverb_send / 100.0))
    global_amount = _control_ratio(controls, "reverbAmount")
    vocal_amount = _control_ratio(controls, "vocalReverbAmount")
    type_factor = {
        "Lead Vocal": 0.42 + vocal_amount * 0.22,
        "Backing Vocal": 0.62 + vocal_amount * 0.16,
        "Drums": 0.32,
        "Kick": 0.04,
        "Snare": 0.36,
        "Bass": 0.04,
        "Electric Guitar": 0.42,
        "Acoustic Guitar": 0.48,
        "Keys/Piano": 0.45,
        "Pads/Strings": 0.72,
        "FX/Ambience": 0.82,
    }.get(stem_type, 0.35)
    return send * global_amount * type_factor


def _stem_delay_amount(stem_type: str, delay_send: float, controls: dict) -> float:
    send = max(0.0, min(1.0, delay_send / 100.0))
    if send <= 0:
        return 0.0
    global_amount = _control_ratio(controls, "reverbAmount")
    vocal_amount = _control_ratio(controls, "vocalReverbAmount")
    vocal_delay = _control_ratio(controls, "vocalDelayAmount")
    type_factor = {
        "Lead Vocal": 0.025 + vocal_amount * 0.025 + vocal_delay * 0.05,
        "Backing Vocal": 0.02 + vocal_amount * 0.02 + vocal_delay * 0.04,
        "Electric Guitar": 0.035,
        "Acoustic Guitar": 0.03,
        "Keys/Piano": 0.025,
        "Pads/Strings": 0.018,
        "FX/Ambience": 0.025,
    }.get(stem_type, 0.0)
    return send * global_amount * type_factor


def _simple_reverb(audio: np.ndarray, sample_rate: int, amount: float, room_size: float) -> np.ndarray:
    amount = max(0.0, min(0.8, amount))
    if amount <= 0 or audio.size == 0:
        return np.zeros_like(audio)
    room_size = max(0.1, min(1.2, room_size))
    reverbed = np.zeros_like(audio)
    taps = [(0.023, 0.42), (0.037, 0.34), (0.053, 0.28), (0.071, 0.22), (0.097, 0.16)]
    for seconds, gain in taps:
        delay = max(1, int(sample_rate * seconds * (0.65 + room_size)))
        if delay >= audio.shape[0]:
            continue
        reverbed[delay:] += audio[:-delay] * gain
    try:
        reverbed = _low_pass(reverbed, sample_rate, 7800 - min(3600, room_size * 2200))
    except Exception:
        pass
    return np.clip(reverbed * amount, -0.8, 0.8).astype(np.float32, copy=False)


def _delay_effect(audio: np.ndarray, sample_rate: int, delay_seconds: float, feedback: float, amount: float) -> np.ndarray:
    amount = max(0.0, min(0.5, amount))
    delay = max(1, int(sample_rate * delay_seconds))
    if amount <= 0 or delay >= audio.shape[0]:
        return np.zeros_like(audio)
    delayed = np.zeros_like(audio)
    delayed[delay:] += audio[:-delay]
    second_delay = delay * 2
    if second_delay < audio.shape[0]:
        delayed[second_delay:] += audio[:-second_delay] * max(0.0, min(0.8, feedback))
    return np.clip(delayed * amount, -0.7, 0.7).astype(np.float32, copy=False)


def _apply_vocal_ducking(audio: np.ndarray, vocal_bus: np.ndarray, sample_rate: int, amount_db: float) -> np.ndarray:
    if audio.size == 0 or vocal_bus.size == 0 or amount_db <= 0:
        return audio
    length = min(audio.shape[0], vocal_bus.shape[0])
    if length <= 0:
        return audio
    vocal_mono = np.mean(np.abs(vocal_bus[:length]), axis=1)
    frame_size = max(256, int(sample_rate * 0.035))
    if vocal_mono.shape[0] < frame_size:
        return audio
    envelope = _smooth_envelope(vocal_mono, sample_rate, 0.08)
    threshold = max(float(np.percentile(envelope, 65)), _db_to_linear(-38))
    if threshold <= 1e-8:
        return audio
    activity = np.clip((envelope - threshold) / (threshold * 3.0), 0.0, 1.0)
    gain_db = -amount_db * activity
    gain = np.power(10.0, gain_db / 20.0).astype(np.float32, copy=False)
    ducked = audio.copy()
    ducked[:length] *= gain[:, None]
    return ducked.astype(np.float32, copy=False)


def _add_to_bus(bus: np.ndarray, audio: np.ndarray) -> None:
    length = min(bus.shape[0], audio.shape[0])
    if length > 0:
        bus[:length] += audio[:length]


def _control_ratio(controls: dict, key: str) -> float:
    return max(0.0, min(1.0, float(controls.get(key, 50)) / 100.0))


def _analyze_samples(audio: np.ndarray, sample_rate: int) -> dict:
    duration_seconds = audio.shape[0] / sample_rate
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))) if audio.size else 0.0
    clipping_mask = np.abs(audio) >= CLIPPING_THRESHOLD
    clipping_count = int(np.count_nonzero(clipping_mask))
    clipping_percentage = float(clipping_count / audio.size * 100) if audio.size else 0.0

    try:
        meter = pyln.Meter(sample_rate)
        integrated_lufs = float(meter.integrated_loudness(audio))
        if not math.isfinite(integrated_lufs):
            integrated_lufs = None
    except Exception:
        integrated_lufs = None

    true_peak = _calculate_true_peak(audio)
    silence_percentage, noise_floor_dbfs = _silence_and_noise_floor(audio, sample_rate)

    return {
        "durationSeconds": _round(duration_seconds),
        "sampleRate": int(sample_rate),
        "channels": int(audio.shape[1]) if audio.ndim == 2 else 1,
        "peakDbfs": _round(_linear_to_db(peak)),
        "rmsDbfs": _round(_linear_to_db(rms)),
        "integratedLufs": _round(integrated_lufs),
        "truePeakDbfs": _round(_linear_to_db(true_peak)),
        "clippingDetected": clipping_count > 0,
        "clippingSampleCount": clipping_count,
        "clippingPercentage": _round(clipping_percentage, 4),
        "silencePercentage": _round(silence_percentage),
        "noiseFloorDbfs": _round(noise_floor_dbfs),
    }


def _cleaning_metric_subset(metrics: dict) -> dict:
    keys = [
        "durationSeconds",
        "sampleRate",
        "channels",
        "peakDbfs",
        "rmsDbfs",
        "integratedLufs",
        "truePeakDbfs",
        "silencePercentage",
        "noiseFloorDbfs",
    ]
    return {key: metrics.get(key) for key in keys}


def _metric_deltas(original: dict, cleaned: dict) -> dict[str, float | None]:
    deltas: dict[str, float | None] = {}
    for key in ["peakDbfs", "rmsDbfs", "integratedLufs", "truePeakDbfs", "silencePercentage", "noiseFloorDbfs"]:
        before = original.get(key)
        after = cleaned.get(key)
        deltas[key] = _round(after - before) if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None
    return deltas


def _calculate_true_peak(audio: np.ndarray) -> float:
    peak = float(np.max(np.abs(audio)))
    try:
        if audio.shape[0] > 5_000_000:
            return peak
        oversampled = signal.resample_poly(audio, up=4, down=1, axis=0)
        return max(peak, float(np.max(np.abs(oversampled))))
    except Exception:
        return peak


def _silence_and_noise_floor(audio: np.ndarray, sample_rate: int) -> tuple[float, float | None]:
    mono = np.mean(audio, axis=1)
    frame_size = max(1, int(sample_rate * 0.05))
    if mono.shape[0] < frame_size:
        frame_rms = np.array([float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))])
    else:
        frame_count = mono.shape[0] // frame_size
        frames = mono[: frame_count * frame_size].reshape(frame_count, frame_size)
        frame_rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))

    threshold = _db_to_linear(SILENCE_THRESHOLD_DBFS)
    silence_percentage = float(np.count_nonzero(frame_rms < threshold) / frame_rms.size * 100)
    audible = frame_rms[frame_rms >= threshold]
    if audible.size == 0:
        return silence_percentage, None
    noise_floor = float(np.percentile(audible, 10))
    return silence_percentage, _linear_to_db(noise_floor)


def _band_energy_ratio(power: np.ndarray, freqs: np.ndarray, low_hz: float, high_hz: float, total_energy: float) -> float:
    mask = (freqs >= low_hz) & (freqs < high_hz)
    if not np.any(mask):
        return 0.0
    return float(np.sum(power[mask, :]) / total_energy)


def _apply_gain(audio: np.ndarray, gain_db: float) -> np.ndarray:
    return audio * _db_to_linear(gain_db)


def _apply_pan(audio: np.ndarray, pan: float) -> np.ndarray:
    pan_norm = max(-1.0, min(1.0, pan / 100.0))
    left_gain = 1.0
    right_gain = 1.0
    if pan_norm < 0:
        right_gain = 1.0 + pan_norm
    elif pan_norm > 0:
        left_gain = 1.0 - pan_norm
    panned = audio.copy()
    panned[:, 0] *= left_gain
    panned[:, 1] *= right_gain
    return panned


def _ffmpeg_exe() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("ffmpeg is not available. Install imageio-ffmpeg or add ffmpeg to PATH.") from exc


def _next_numbered_audio_file(output_dir: Path, prefix: str, extension: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    number = 1
    while (output_dir / f"{prefix}_v{number:03d}{extension}").exists():
        number += 1
    return number


def _linear_to_db(value: float | None) -> float:
    if value is None or value <= 0 or not math.isfinite(value):
        return -120.0
    return 20.0 * math.log10(value)


def _db_to_linear(value: float) -> float:
    return 10.0 ** (value / 20.0)


def _round(value: float | None, digits: int = 3) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)
