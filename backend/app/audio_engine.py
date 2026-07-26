import math
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import imageio_ffmpeg
import librosa  # Imported to keep the Phase 2 audio stack ready for later feature extraction.
import numpy as np
import pyloudnorm as pyln
from scipy import signal
from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d


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
    tempo_bpm: float | None = None


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

try:
    import pyworld as pw  # WORLD vocoder: highest-quality formant-preserving pitch shift.
except Exception:  # Optional; the spectral-envelope-restoration fallback is always available.
    pw = None


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
    audio = _sanitize_audio(decoded.samples.astype(np.float32, copy=True))
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
        audio = _sanitize_audio(_remove_hum(audio, decoded.sample_rate, hum_frequency, params["humStrength"]))
        operations.append(f"{hum_frequency} Hz hum reduction")

    if params["highPassHz"]:
        _progress(progress_callback, 0.42, "Applying high-pass cleanup")
        audio = _sanitize_audio(_high_pass(audio, decoded.sample_rate, params["highPassHz"]))
        operations.append(f"high-pass filter at {params['highPassHz']} Hz")

    if params["plosiveReduction"]:
        _progress(progress_callback, 0.50, "Reducing plosives")
        audio = _sanitize_audio(_reduce_plosives(audio, decoded.sample_rate, params["plosiveReduction"]))
        operations.append("plosive reduction")

    if params["noiseReduction"]:
        _progress(progress_callback, 0.58, "Building noise reduction profile")
        noise_profile = _noise_profile(audio, decoded.sample_rate)
        _progress(progress_callback, 0.64, "Reducing noise")
        audio = _sanitize_audio(_reduce_noise(audio, decoded.sample_rate, params["noiseReduction"], noise_profile=noise_profile))
        operations.append("profile-based noise reduction" if noise_profile is not None else "adaptive noise reduction")

    if params["noiseGate"]:
        _progress(progress_callback, 0.70, "Applying noise gate")
        audio = _sanitize_audio(_noise_gate(audio, decoded.sample_rate, params["noiseGate"], params["gateFloor"]))
        operations.append("noise gate")

    if params["deEss"]:
        _progress(progress_callback, 0.76, "Softening harsh sibilance")
        audio = _sanitize_audio(_de_ess(audio, decoded.sample_rate, params["deEss"]))
        operations.append("de-esser")

    if params["compressionPrep"]:
        _progress(progress_callback, 0.82, "Preparing dynamics")
        audio = _sanitize_audio(_compression_prepare(audio, params["compressionPrep"]))
        operations.append("light compression preparation")

    if params["clickReduction"]:
        _progress(progress_callback, 0.86, "Reducing clicks and pops")
        audio = _sanitize_audio(_reduce_clicks(audio, params["clickReduction"]))
        operations.append("click/pop reduction")

    try:
        hf_cutoff = _detect_hf_cutoff(audio, decoded.sample_rate)
        if hf_cutoff:
            _progress(progress_callback, 0.88, "Restoring lost high frequencies")
            audio, hf_applied = _restore_high_frequencies(audio, decoded.sample_rate, hf_cutoff, strength=0.75)
            if hf_applied:
                audio = _sanitize_audio(audio)
                operations.append(f"high-frequency restoration above {hf_cutoff / 1000.0:.1f} kHz (lossy source detected)")
    except Exception:
        warnings.append("High-frequency restoration was skipped because spectrum analysis failed.")

    if params["tailCleanup"]:
        _progress(progress_callback, 0.90, "Cleaning silent tail")
        audio = _sanitize_audio(_cleanup_silent_tail(audio, decoded.sample_rate))
        operations.append("silence tail cleanup")
        warnings.append("Leading silence is preserved so stems stay aligned in the mix.")

    # Transparent gain trim instead of a hard clip if cleanup pushed peaks up.
    audio = _sanitize_audio(audio)
    audio = _peak_limit(audio, ceiling=0.98)

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
    compression_amount: float = 40,
    rider_amount: float = 36,
    saturation_amount: float = 18,
    doubler_amount: float = 16,
    breath_reduction_amount: float = 35,
    mouth_click_reduction_amount: float = 30,
    pitch_strength: float = 42,
    pitch_humanize: float = 72,
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
        audio = _compress_audio(audio, threshold_db=params["compressionThresholdDb"] + threshold_adjust, ratio=params["compressionRatio"], mix=compression, sample_rate=decoded.sample_rate)
        operations.append(f"studio vocal compression ({int(round(compression_amount))}%)")

    audio, headroom_trim_db = _trim_peak_to_target(audio, target_peak_db=-7.5)
    if headroom_trim_db < -0.1:
        operations.append(f"pre-harmonic headroom trim ({headroom_trim_db:.1f} dB)")

    saturation = _scale_preset_amount(params["saturation"], saturation_amount, max_value=0.22)
    if saturation > 0:
        _progress(progress_callback, 0.84, "Adding subtle saturation")
        audio = _saturate(audio, drive=1.08 + saturation * 3.5, mix=saturation)
        operations.append(f"subtle vocal saturation ({int(round(saturation_amount))}%)")

    # De-ess after the presence/air boosts and saturation: those stages are the
    # ones that push sibilance forward, so controlling esses afterwards keeps
    # the top end bright without the spit.
    de_ess = _scale_preset_amount(params["deEss"], de_ess_amount, max_value=0.95)
    if de_ess > 0:
        _progress(progress_callback, 0.86, "Applying vocal de-esser")
        audio = _de_ess(audio, decoded.sample_rate, de_ess)
        operations.append(f"studio de-esser ({int(round(de_ess_amount))}%)")

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
    audio = _final_vocal_level(audio, target_peak_db=-3.0)
    operations.append("vocal safety level")
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _progress(progress_callback, 0.96, "Writing enhanced vocal")
    _encode_float_audio(audio, output_path, codec_args=["-c:a", "pcm_s24le"], sample_rate=decoded.sample_rate)

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

    _progress(progress_callback, 0.47, "Detecting song tempo")
    tempo_bpm = None
    try:
        tempo_source = np.zeros((max_length, 2), dtype=np.float32)
        drum_tracks = [dry for dry, _send, item in processed_tracks if item.get("stemType") in {"Drums", "Kick", "Snare"}]
        for dry in (drum_tracks or [dry for dry, _send, _item in processed_tracks]):
            _add_to_bus(tempo_source, dry)
        tempo_bpm = _estimate_tempo(tempo_source, ROUGH_MIX_SAMPLE_RATE)
        del tempo_source
    except Exception:
        tempo_bpm = None

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
                _add_to_bus(mix, _delay_effect(dry, ROUGH_MIX_SAMPLE_RATE, delay_seconds=_synced_delay_seconds(tempo_bpm, 0.24), feedback=0.22, amount=delay_amount))
        elif stem_type in {"Drums", "Kick", "Snare"}:
            _add_to_bus(mix, dry)
            _add_to_bus(drum_send, send)
        else:
            _add_to_bus(mix, dry)
            _add_to_bus(space_send, send)
            delay_amount = _stem_delay_amount(stem_type, float(item.get("delaySend", 0)), controls)
            if delay_amount > 0.01:
                delay_seconds = _synced_delay_seconds(tempo_bpm, 0.18 if stem_type in {"Electric Guitar", "Acoustic Guitar"} else 0.31)
                _add_to_bus(space_send, _delay_effect(dry, ROUGH_MIX_SAMPLE_RATE, delay_seconds=delay_seconds, feedback=0.18, amount=delay_amount))

    _progress(progress_callback, 0.74, "Processing vocal bus and sends")
    if np.any(vocal_bus):
        _add_to_bus(mix, _process_vocal_mix_bus(vocal_bus, ROUGH_MIX_SAMPLE_RATE, controls, warnings, tempo_bpm=tempo_bpm))

    _progress(progress_callback, 0.80, "Adding shared space effects")
    room_size = _control_ratio(controls, "roomSize")
    global_reverb = _control_ratio(controls, "reverbAmount")
    vocal_reverb = _control_ratio(controls, "vocalReverbAmount")
    # Vocal reverb is the star of the "finished" sound: audible, lush, wide.
    vocal_reverb_amount = 0.18 + 0.85 * vocal_reverb + 0.32 * global_reverb
    reverb_returns = [
        (_simple_reverb(vocal_send, ROUGH_MIX_SAMPLE_RATE, amount=vocal_reverb_amount, room_size=0.60 + room_size * 0.55), True),
        (_simple_reverb(drum_send, ROUGH_MIX_SAMPLE_RATE, amount=0.10 + 0.30 * global_reverb, room_size=0.25 + room_size * 0.25), False),
        (_simple_reverb(space_send, ROUGH_MIX_SAMPLE_RATE, amount=0.15 + 0.55 * global_reverb, room_size=0.55 + room_size * 0.55), True),
    ]
    for wet, duck_under_vocal in reverb_returns:
        if not np.any(wet):
            continue
        # Classic return hygiene: high-pass so the tail doesn't stack low-mid
        # mud on the mix bus, gentle low-pass so it sits behind the sources.
        wet = _high_pass(wet, ROUGH_MIX_SAMPLE_RATE, 170)
        wet = _low_pass(wet, ROUGH_MIX_SAMPLE_RATE, 10500)
        if duck_under_vocal and np.any(vocal_focus_bus):
            # Sidechain the tail out of the way while the lead is singing; it
            # blooms back in the gaps, which keeps lyrics intelligible with a
            # lush, audible reverb.
            wet = _apply_vocal_ducking(wet, vocal_focus_bus[: wet.shape[0]], ROUGH_MIX_SAMPLE_RATE, 2.8)
        _add_to_bus(mix, wet)

    _progress(progress_callback, 0.84, "Applying mix tone and bus glue")
    mix = _apply_master_tone(mix, ROUGH_MIX_SAMPLE_RATE, controls)
    mix = np.nan_to_num(mix, nan=0.0, posinf=0.0, neginf=0.0)

    # 2-bus glue: a slow, wide-knee compressor at ~1-2 dB of reduction with a
    # bass-blind detector, then a whisper of tape-style saturation. This is the
    # stage that makes separate stems read as one record.
    if mix.size:
        bus_rms = float(np.sqrt(np.mean(np.square(mix, dtype=np.float64))))
        if bus_rms > 1e-6:
            glue_threshold_db = _linear_to_db(bus_rms) + 4.0
            mix = _compress_audio(
                mix,
                threshold_db=glue_threshold_db,
                ratio=1.6,
                mix=0.4,
                sample_rate=ROUGH_MIX_SAMPLE_RATE,
                attack_ms=22.0,
                release_ms=160.0,
                knee_db=9.0,
                sidechain_hpf_hz=110.0,
            )
            mix = _saturate(mix, drive=1.12, mix=0.10)

    limiter_gain_db = 0.0
    mix_true_peak = _calculate_true_peak(mix) if mix.size else 0.0
    if mix_true_peak > 0.98:
        scale = 0.98 / mix_true_peak
        mix *= scale
        limiter_gain_db = _linear_to_db(scale)
        warnings.append("Mix-stage safety gain was applied to prevent clipping; final limiting belongs to mastering.")

    mix = mix.astype(np.float32, copy=False)
    label = f"mix_v{version_number:03d}"
    wav_path = output_dir / f"{label}.wav"
    mp3_path = output_dir / f"{label}.mp3"
    metadata_path = output_dir / f"{label}.json"

    _progress(progress_callback, 0.90, "Writing mix WAV")
    # 24-bit intermediate so mastering starts from full mix resolution.
    _encode_float_audio(mix, wav_path, codec_args=["-c:a", "pcm_s24le"])

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
        tempo_bpm=_round(tempo_bpm, 1),
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
        _progress(progress_callback, 0.30, "Checking source bandwidth")
        hf_cutoff = _detect_hf_cutoff(audio, decoded.sample_rate)
        if hf_cutoff:
            audio, hf_applied = _restore_high_frequencies(audio, decoded.sample_rate, hf_cutoff, strength=0.6)
            if hf_applied:
                operations.append(f"high-frequency restoration above {hf_cutoff / 1000.0:.1f} kHz (lossy source detected)")
    except Exception:
        warnings.append("High-frequency restoration was skipped because spectrum analysis failed.")

    try:
        _progress(progress_callback, 0.34, "Applying master cleanup")
        audio = _high_pass(audio, decoded.sample_rate, 24)
        operations.append("subsonic cleanup high-pass")
    except Exception as exc:
        errors.append(f"Master high-pass failed: {str(exc) or 'unknown error'}")

    reference_path = controls.get("referencePath")
    if reference_path:
        try:
            reference_file = Path(str(reference_path))
            if not reference_file.exists():
                raise ValueError("The reference track file is missing.")
            _progress(progress_callback, 0.40, "Matching reference track")
            reference_decoded = _decode_audio(reference_file, sample_rate=decoded.sample_rate, channels=2)
            match_amount = max(0.0, min(1.0, float(controls.get("referenceMatchAmount", 70) or 0) / 100.0))
            audio, match_operations, match_warnings = _match_reference(
                audio, decoded.sample_rate, reference_decoded.samples.astype(np.float32, copy=False), match_amount
            )
            operations.extend(match_operations)
            warnings.extend(match_warnings)
            if bool(controls.get("matchReferenceLoudness")):
                reference_lufs = _measure_lufs(reference_decoded.samples, decoded.sample_rate)
                if reference_lufs is not None:
                    target_lufs = max(-20.0, min(-6.0, reference_lufs))
                    operations.append(f"loudness target taken from reference ({target_lufs:.1f} LUFS)")
                else:
                    warnings.append("Reference loudness could not be measured; preset loudness target kept.")
        except Exception as exc:
            warnings.append(f"Reference matching skipped: {str(exc) or 'reference could not be analyzed'}")

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

    compression_amount = max(0.0, min(1.0, float(controls.get("compressionAmount", 45)) / 100.0))
    try:
        _progress(progress_callback, 0.52, "Applying glue compression")
        if compression_amount > 0:
            ratio = 1.4 + compression_amount * 2.4
            mix = 0.12 + compression_amount * 0.32
            threshold = -19.0 + compression_amount * 3.5
            # Bass-blind detector: kick/bass energy no longer pumps the whole master.
            audio = _compress_audio(
                audio,
                threshold_db=threshold,
                ratio=ratio,
                mix=mix,
                sample_rate=decoded.sample_rate,
                attack_ms=25.0,
                release_ms=180.0,
                knee_db=8.0,
                sidechain_hpf_hz=110.0,
            )
            operations.append("glue compression")
    except Exception as exc:
        errors.append(f"Glue compression failed: {str(exc) or 'unknown error'}")

    try:
        _progress(progress_callback, 0.58, "Balancing band dynamics")
        if compression_amount > 0:
            audio = _multiband_compress(audio, decoded.sample_rate, 0.35 + compression_amount * 0.45)
            operations.append("multiband dynamics balancing")
    except Exception as exc:
        errors.append(f"Multiband compression failed: {str(exc) or 'unknown error'}")

    try:
        _progress(progress_callback, 0.62, "Adding harmonic glue")
        audio = _saturate(audio, drive=1.10, mix=0.08)
        operations.append("subtle harmonic glue")
    except Exception as exc:
        errors.append(f"Harmonic stage failed: {str(exc) or 'unknown error'}")

    try:
        _progress(progress_callback, 0.66, "Adjusting stereo width")
        width = (float(controls.get("stereoWidth", 55)) - 50.0) / 100.0
        if abs(width) > 0.02:
            audio = _apply_width(audio, width * 0.8)
            operations.append("stereo width adjustment")
    except Exception as exc:
        errors.append(f"Stereo width failed: {str(exc) or 'unknown error'}")

    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)

    # Lossy encoders inflate inter-sample peaks; leave the codec extra headroom.
    effective_ceiling_db = min(true_peak_ceiling_db, -1.5) if output_format == "MP3 320kbps" else true_peak_ceiling_db
    if effective_ceiling_db < true_peak_ceiling_db:
        operations.append(f"MP3 encode headroom (ceiling lowered to {effective_ceiling_db:.1f} dBTP)")

    limiter_strength = max(0.0, min(1.0, float(controls.get("limiterStrength", 55)) / 100.0))
    limiter_release_ms = 150.0 - limiter_strength * 95.0

    _progress(progress_callback, 0.72, "Checking pre-limiter loudness")
    current_lufs = _measure_lufs(audio, decoded.sample_rate)
    loudness_gain_db = 0.0
    limiter_gain_db = 0.0
    try:
        if current_lufs is not None:
            loudness_gain_db = _round(target_lufs - current_lufs) or 0.0
            max_gain = 14.0 if preset == "Very Loud" else 10.0
            if loudness_gain_db > max_gain:
                warnings.append(f"Loudness gain was capped at {max_gain:.1f} dB for safety.")
                loudness_gain_db = max_gain
            audio = _apply_gain(audio, loudness_gain_db)
            operations.append(f"loudness normalization toward {target_lufs:.1f} LUFS")

        _progress(progress_callback, 0.78, "Applying lookahead true-peak limiter")
        pre_limit_tp_db = _linear_to_db(_calculate_true_peak(audio))
        audio = _lookahead_limit(audio, decoded.sample_rate, effective_ceiling_db, release_ms=limiter_release_ms)
        limiter_gain_db = min(0.0, _round(effective_ceiling_db - pre_limit_tp_db) or 0.0)
        operations.append(f"lookahead true-peak limiter at {effective_ceiling_db:.1f} dBTP")

        if current_lufs is not None:
            # Closed loop: limiting eats level, so re-measure and correct until
            # the master actually lands on target (max two passes).
            _progress(progress_callback, 0.84, "Verifying loudness target")
            for _ in range(2):
                measured = _measure_lufs(audio, decoded.sample_rate)
                if measured is None:
                    break
                residual = target_lufs - measured
                if not (0.25 < residual <= 4.0):
                    break
                audio = _apply_gain(audio, residual)
                audio = _lookahead_limit(audio, decoded.sample_rate, effective_ceiling_db, release_ms=limiter_release_ms)
                loudness_gain_db = (_round(loudness_gain_db + residual) or 0.0)
                operations.append(f"loudness correction pass (+{residual:.1f} dB)")
        else:
            warnings.append("Integrated LUFS could not be measured; mastering used peak safety only.")
    except Exception as exc:
        errors.append(f"Limiter failed: {str(exc) or 'unknown error'}")

    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)
    if output_format == "WAV 16-bit":
        audio = _tpdf_dither_16bit(audio)
        operations.append("TPDF dither for 16-bit output")

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
    # No hard clip here: float sources legitimately carry inter-sample or
    # over-full-scale content, and downstream limiting handles peaks cleanly.
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
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


def _sanitize_audio(audio: np.ndarray, clip: float | None = None) -> np.ndarray:
    """Replace NaN/inf. Clipping is opt-in and reserved for file-write
    boundaries — hard-clipping between chain stages bakes distortion into the
    signal before the mastering limiter ever sees it."""
    cleaned = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    if clip is not None:
        limit = max(0.1, min(1.5, float(clip)))
        cleaned = np.clip(cleaned, -limit, limit)
    return cleaned.astype(np.float32, copy=False)


def _safe_sos_filter(sos: np.ndarray, audio: np.ndarray) -> np.ndarray:
    audio = _sanitize_audio(audio)
    try:
        if audio.shape[0] > 64:
            return _sanitize_audio(signal.sosfiltfilt(sos, audio, axis=0))
    except Exception:
        pass
    return _sanitize_audio(signal.sosfilt(sos, audio, axis=0))


def _remove_hum(audio: np.ndarray, sample_rate: int, frequency: int, strength: float) -> np.ndarray:
    cleaned = _sanitize_audio(audio)
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
        cleaned = _sanitize_audio(cleaned * (1.0 - strength) + filtered * strength)
    return cleaned


def _reduce_noise(audio: np.ndarray, sample_rate: int, strength: float, noise_profile: np.ndarray | None = None) -> np.ndarray:
    audio = _sanitize_audio(audio)
    if noise_profile is not None:
        noise_profile = _sanitize_audio(noise_profile)
    strength = max(0.0, min(0.9, strength))
    if strength <= 0:
        return audio
    if nr is not None:
        try:
            have_profile = noise_profile is not None and noise_profile.size > 0
            channels = []
            for channel_index in range(audio.shape[1]):
                y_noise = noise_profile[:, channel_index] if have_profile else None
                reduced = nr.reduce_noise(
                    y=audio[:, channel_index],
                    sr=sample_rate,
                    y_noise=y_noise,
                    prop_decrease=strength,
                    # A measured noise clip is a stationary floor (hiss/hum residue);
                    # stationary spectral subtraction against it is cleaner and avoids
                    # the musical-noise artifacts the non-stationary estimator adds on
                    # tonal material. Fall back to adaptive mode with no profile.
                    stationary=have_profile,
                    n_std_thresh_stationary=1.5,
                    freq_mask_smooth_hz=500,
                    time_mask_smooth_ms=64,
                )
                channels.append(reduced)
            return _sanitize_audio(np.stack(channels, axis=1))
        except Exception:
            pass
    return _spectral_noise_reduction(audio, sample_rate, strength)


def _noise_profile(audio: np.ndarray, sample_rate: int) -> np.ndarray | None:
    """Collect the quietest frames as a noise fingerprint — but only hand them
    to the noise reducer if they actually look like noise. Quiet *music*
    (reverb tails, sustained pads, soft intros) is tonal: subtracting its
    spectrum notches real harmonics out of the whole track and dulls the mix."""
    audio = _sanitize_audio(audio)
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
    candidate = np.concatenate(segments, axis=0)

    # Validation 1: the candidate must sit well below the program level.
    overall_rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
    candidate_rms = float(np.sqrt(np.mean(np.square(candidate, dtype=np.float64))))
    if overall_rms > 1e-9 and candidate_rms > overall_rms * _db_to_linear(-8.0):
        return None
    # Validation 2: noise is spectrally flat; tonal material is not.
    try:
        candidate_mono = np.mean(candidate, axis=1).astype(np.float32, copy=False)
        flatness = librosa.feature.spectral_flatness(y=candidate_mono, n_fft=2048, hop_length=1024)
        if float(np.median(flatness)) < 0.08:
            return None
    except Exception:
        pass
    return candidate


def _spectral_noise_reduction(audio: np.ndarray, sample_rate: int, strength: float) -> np.ndarray:
    audio = _sanitize_audio(audio)
    strength = max(0.0, min(0.9, strength))
    if strength <= 0:
        return audio
    reduced_channels = []
    nperseg = 2048
    noverlap = 1536
    # Oversubtraction and a residual spectral floor: attenuating noise bins to a
    # floor rather than zero, then smoothing the gain mask, avoids the "musical
    # noise" (warbly birdies) a hard binary gate produces.
    oversub = 1.0 + strength * 1.4
    spectral_floor = max(0.03, 1.0 - strength * 0.92)
    for channel_index in range(audio.shape[1]):
        channel = audio[:, channel_index]
        freqs, times, stft = signal.stft(channel, fs=sample_rate, nperseg=nperseg, noverlap=noverlap)
        magnitude = np.abs(stft)
        if magnitude.size == 0:
            reduced_channels.append(channel)
            continue
        phase = np.angle(stft)
        frame_energy = np.mean(magnitude, axis=0)
        quiet = frame_energy <= np.percentile(frame_energy, 25)
        noise = np.median(magnitude[:, quiet], axis=1, keepdims=True) if np.any(quiet) else np.median(magnitude, axis=1, keepdims=True)
        power = magnitude ** 2
        noise_power = (noise * oversub) ** 2
        gain = np.sqrt(np.maximum(power - noise_power, 0.0) / (power + 1e-10))
        gain = spectral_floor + (1.0 - spectral_floor) * gain
        gain = _smooth_spectral_gain(gain)
        _freqs, cleaned = signal.istft(magnitude * gain * np.exp(1j * phase), fs=sample_rate, nperseg=nperseg, noverlap=noverlap)
        reduced_channels.append(_match_length(cleaned, channel.shape[0]))
    return _sanitize_audio(np.stack(reduced_channels, axis=1))


def _smooth_spectral_gain(gain: np.ndarray) -> np.ndarray:
    """Box-smooth a time-frequency gain mask over both axes to suppress isolated
    bin flicker (the source of musical-noise artifacts)."""
    if gain.ndim != 2 or gain.size == 0:
        return gain
    try:
        from scipy.ndimage import uniform_filter

        return uniform_filter(gain, size=(3, 3), mode="nearest")
    except Exception:
        return gain


def _noise_gate(audio: np.ndarray, sample_rate: int, strength: float, floor: float) -> np.ndarray:
    """Downward expander with hysteresis and real attack/release. Separate
    open/close thresholds stop the gate chattering on material hovering at the
    threshold; a fast attack keeps transients intact while a slow release lets
    decays breathe. Depth scales with strength to a level that is actually
    audible (the old version topped out under 1 dB)."""
    strength = max(0.0, min(1.0, strength))
    if strength <= 0:
        return audio
    frame_size = max(256, int(sample_rate * 0.025))
    hop = max(128, frame_size // 2)
    mono = np.mean(np.abs(audio), axis=1)
    if mono.shape[0] < frame_size:
        return audio
    starts = np.arange(0, mono.shape[0] - frame_size + 1, hop)
    frames = np.lib.stride_tricks.sliding_window_view(mono, frame_size)[::hop][: starts.shape[0]]
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    open_threshold = max(_db_to_linear(-58), float(np.percentile(rms, 20)) * (1.4 + strength * 2.0))
    close_threshold = open_threshold * 0.7  # hysteresis: open easily, close reluctantly
    gate_floor = max(0.05, min(0.95, floor))
    depth_db = (3.0 + strength * 15.0) * (1.0 - gate_floor * 0.55)
    closed_gain = _db_to_linear(-depth_db)

    state_open = True
    target = np.empty(rms.shape[0], dtype=np.float32)
    for index in range(rms.shape[0]):
        level = rms[index]
        if state_open and level < close_threshold:
            state_open = False
        elif not state_open and level > open_threshold:
            state_open = True
        target[index] = 1.0 if state_open else closed_gain
    frame_rate = sample_rate / hop
    smoothed = _asym_envelope(target, frame_rate, attack_seconds=0.003, release_seconds=0.18)

    sample_positions = starts + frame_size // 2
    envelope = np.interp(np.arange(audio.shape[0]), sample_positions, smoothed, left=smoothed[0], right=smoothed[-1])
    return (audio * envelope[:, None]).astype(np.float32, copy=False)


def _de_ess(audio: np.ndarray, sample_rate: int, strength: float) -> np.ndarray:
    """Split-band de-esser: the sibilance band is compressed proportionally to
    how far it rises above its own typical level (a ratio, not an on/off gate),
    with fast attack and a slower release. Loud esses get pulled down hard,
    borderline ones only slightly — the binary version made 'th'/'s' pumping
    obvious on exposed vocals."""
    if strength <= 0 or sample_rate < 16000:
        return audio
    high = _band_pass(audio, sample_rate, 4800, min(10800, sample_rate / 2 - 200))
    rest = audio - high
    detector = np.mean(np.abs(high), axis=1).astype(np.float32, copy=False)
    block = max(8, int(sample_rate * 0.001))
    blocks = _control_blocks(detector, block)
    control_rate = sample_rate / block
    envelope = _asym_envelope(blocks, control_rate, attack_seconds=0.002, release_seconds=0.045)
    audible = envelope[envelope > 1e-6]
    if audible.size < 8:
        return audio
    threshold = float(np.percentile(audible, 72))
    if threshold <= 1e-8:
        return audio
    over_db = 20.0 * np.log10(np.maximum(envelope, 1e-9) / threshold)
    max_reduction_db = 3.0 + strength * 9.0
    reduction_db = np.clip(np.maximum(over_db, 0.0) * (0.5 + strength * 0.4), 0.0, max_reduction_db)
    gain_blocks = np.power(10.0, -reduction_db / 20.0).astype(np.float32)
    gain = _expand_control_gain(gain_blocks, block, audio.shape[0])
    return (rest + high * gain[:, None]).astype(np.float32, copy=False)


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
    """Repair clicks by interpolating across the damaged region from clean
    material on both sides (RX-style), instead of nudging a single sample —
    real clicks span several samples, and a one-sample median leaves the
    remainder of the transient audible."""
    if strength <= 0:
        return audio
    cleaned = audio.copy()
    half_window = 3
    for channel_index in range(cleaned.shape[1]):
        channel = cleaned[:, channel_index]
        diff = np.abs(np.diff(channel, prepend=channel[0]))
        threshold = max(0.2, np.percentile(diff, 99.85) * (1.0 + (1.0 - strength)))
        spike_indexes = np.where(diff > threshold)[0]
        last_end = -1
        for index in spike_indexes[:5000]:
            start = max(0, index - half_window)
            end = min(len(channel), index + half_window + 1)
            if start <= last_end:  # merged with the previous repair region
                continue
            left = start - 1
            right = end
            if left < 0 or right >= len(channel):
                continue
            span = np.linspace(channel[left], channel[right], end - start + 2)[1:-1]
            channel[start:end] = span.astype(np.float32)
            last_end = end
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
    # Voicing guard: breaths carry almost no low-mid energy, while quiet
    # consonant tails inside words do. Requiring a low 200-1500 Hz level keeps
    # word endings ("...s", "...t") from being swallowed with the breaths.
    voiced_band = _band_pass(audio, sample_rate, 200, 1500)
    voiced_env = _smooth_envelope(np.mean(np.abs(voiced_band), axis=1), sample_rate, 0.035)
    audible = envelope[envelope > _db_to_linear(-58)]
    if audible.size < 8:
        return audio
    quiet_threshold = float(np.percentile(audible, 46))
    high_threshold = float(np.percentile(high_env, 62))
    voiced_threshold = float(np.percentile(voiced_env[voiced_env > 1e-7], 40)) if np.any(voiced_env > 1e-7) else 0.0
    breath_like = (
        (envelope < quiet_threshold)
        & (envelope > _db_to_linear(-55))
        & (high_env > high_threshold)
        & (voiced_env < voiced_threshold)
    )
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


def _true_peak_envelope(work: np.ndarray, sample_rate: int) -> np.ndarray:
    """Per-sample true-peak magnitude: the max of the 4x-oversampled signal
    folded back onto the original sample grid, so limiting decisions see
    inter-sample overshoot instead of only sample peaks."""
    length = work.shape[0]
    envelope = np.empty(length, dtype=np.float32)
    chunk = 1_000_000
    overlap = 256
    for start in range(0, length, chunk):
        stop = min(length, start + chunk)
        lo = max(0, start - overlap)
        block = work[lo: min(length, stop + overlap)]
        oversampled = signal.resample_poly(block, up=4, down=1, axis=0)
        magnitude = np.max(np.abs(oversampled), axis=1) if oversampled.ndim == 2 else np.abs(oversampled)
        usable = magnitude[: (magnitude.shape[0] // 4) * 4].reshape(-1, 4).max(axis=1)
        segment = usable[start - lo: start - lo + (stop - start)]
        if segment.shape[0] < stop - start:
            segment = np.pad(segment, (0, (stop - start) - segment.shape[0]), mode="edge")
        envelope[start:stop] = segment
    sample_mag = np.max(np.abs(work), axis=1) if work.ndim == 2 else np.abs(work)
    return np.maximum(envelope, sample_mag.astype(np.float32, copy=False))


def _lookahead_limit(audio: np.ndarray, sample_rate: int, ceiling_db: float, lookahead_ms: float = 2.0, release_ms: float = 90.0) -> np.ndarray:
    """Transparent brickwall limiter: true-peak detection, a forward sliding
    minimum over the lookahead window (gain reaches the required reduction
    before the peak arrives), a causal averaging ramp for the attack shape,
    and a one-pole release. Unlike a waveshaper this adds no harmonic
    distortion — loud masters stay clean instead of getting gritty."""
    if audio.size == 0:
        return audio
    work = audio if audio.ndim == 2 else audio.reshape(-1, 1)
    ceiling = _db_to_linear(ceiling_db)
    peak_env = _true_peak_envelope(work, sample_rate)
    if float(np.max(peak_env)) <= ceiling:
        return audio
    target_gain = np.minimum(1.0, ceiling / np.maximum(peak_env, 1e-9)).astype(np.float32)
    look = max(4, int(sample_rate * lookahead_ms / 1000.0))
    # Sliding minimum over [n-look, n+look]: the gain starts moving toward the
    # required reduction a full lookahead window before the peak arrives.
    eroded = minimum_filter1d(target_gain, size=2 * look + 1, mode="nearest")
    # Causal moving average over the previous `look` samples: every value being
    # averaged already accounts for the upcoming peak, so the smoothed gain
    # never overshoots the required reduction at the peak instant.
    kernel = np.full(look, 1.0 / look, dtype=np.float32)
    padded = np.concatenate([np.full(look - 1, eroded[0], dtype=np.float32), eroded])
    smoothed = np.convolve(padded, kernel, mode="valid").astype(np.float32)
    # One-pole release on the reduction amount so gain recovers gradually.
    release_coeff = math.exp(-1.0 / max(1.0, sample_rate * release_ms / 1000.0))
    reduction = 1.0 - smoothed
    released = signal.lfilter([1.0 - release_coeff], [1.0, -release_coeff], reduction).astype(np.float32)
    gain = 1.0 - np.maximum(reduction, released)
    limited = work * gain[:, None]
    # Belt-and-braces: catch any residual inter-sample overs from the gain
    # modulation itself with a tiny static trim rather than a clip.
    residual = _calculate_true_peak(limited)
    if residual > ceiling:
        limited *= ceiling / residual
    limited = limited if audio.ndim == 2 else limited.reshape(-1)
    return limited.astype(np.float32, copy=False)


def _measure_lufs(audio: np.ndarray, sample_rate: int) -> float | None:
    try:
        meter = pyln.Meter(sample_rate)
        value = float(meter.integrated_loudness(audio))
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _split_three_bands(audio: np.ndarray, sample_rate: int, low_hz: float = 180.0, high_hz: float = 3800.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Complementary 3-band split: bands are derived by subtraction, so they
    sum back to the input bit-exactly (no crossover ripple or phase holes)."""
    low_sos = signal.butter(2, low_hz, btype="lowpass", fs=sample_rate, output="sos")
    low = signal.sosfilt(low_sos, audio, axis=0).astype(np.float32)
    rest = audio - low
    mid_sos = signal.butter(2, high_hz, btype="lowpass", fs=sample_rate, output="sos")
    mid = signal.sosfilt(mid_sos, rest, axis=0).astype(np.float32)
    high = (rest - mid).astype(np.float32)
    return low, mid, high


def _multiband_compress(audio: np.ndarray, sample_rate: int, amount: float) -> np.ndarray:
    """Gentle 3-band mastering compressor with per-band adaptive thresholds.
    Evens out frequency-dependent dynamics a broadband compressor cannot touch
    (a bass-heavy chorus no longer forces the vocals down with it) — the main
    structural difference between a bus mix and a finished master."""
    amount = max(0.0, min(1.0, amount))
    if amount <= 0 or audio.size == 0:
        return audio
    low, mid, high = _split_three_bands(audio, sample_rate)
    processed = []
    for band, (ratio, threshold_offset_db, attack_ms, release_ms) in zip(
        (low, mid, high),
        ((1.7, 3.5, 30.0, 220.0), (1.5, 4.5, 18.0, 150.0), (1.6, 4.0, 8.0, 110.0)),
    ):
        band_rms = float(np.sqrt(np.mean(np.square(band, dtype=np.float64))))
        if band_rms <= 1e-7:
            processed.append(band)
            continue
        processed.append(
            _compress_audio(
                band,
                threshold_db=_linear_to_db(band_rms) + threshold_offset_db,
                ratio=1.0 + (ratio - 1.0) * amount,
                mix=0.6,
                sample_rate=sample_rate,
                attack_ms=attack_ms,
                release_ms=release_ms,
                knee_db=8.0,
            )
        )
    return (processed[0] + processed[1] + processed[2]).astype(np.float32, copy=False)


def _band_spectrum_db(audio: np.ndarray, sample_rate: int, band_centers: np.ndarray) -> np.ndarray | None:
    """Average power per log-spaced band (dB) from a Welch PSD of the mono sum.
    This is the 'tonal balance fingerprint' used for reference matching."""
    mono = np.mean(audio, axis=1) if audio.ndim == 2 else audio
    if mono.shape[0] < sample_rate:
        return None
    freqs, psd = signal.welch(mono.astype(np.float64, copy=False), fs=sample_rate, nperseg=8192, noverlap=4096)
    band_edges = np.sqrt(band_centers[:-1] * band_centers[1:])
    band_edges = np.concatenate([[band_centers[0] / 1.2], band_edges, [band_centers[-1] * 1.2]])
    levels = np.empty(band_centers.shape[0])
    for index in range(band_centers.shape[0]):
        mask = (freqs >= band_edges[index]) & (freqs < band_edges[index + 1])
        if not np.any(mask):
            return None
        levels[index] = 10.0 * math.log10(float(np.mean(psd[mask])) + 1e-18)
    return levels


def _width_ratio(audio: np.ndarray) -> float | None:
    """Side/mid RMS ratio — a simple, robust stereo-width fingerprint."""
    if audio.ndim != 2 or audio.shape[1] < 2:
        return None
    mid = (audio[:, 0] + audio[:, 1]) * 0.5
    side = (audio[:, 0] - audio[:, 1]) * 0.5
    mid_rms = float(np.sqrt(np.mean(np.square(mid, dtype=np.float64))))
    side_rms = float(np.sqrt(np.mean(np.square(side, dtype=np.float64))))
    if mid_rms <= 1e-9:
        return None
    return side_rms / mid_rms


def _reference_analysis_window(reference: np.ndarray, sample_rate: int, max_seconds: float = 150.0) -> np.ndarray:
    """Analyze the middle of the reference (skip intro/outro fades) so quiet
    bookends don't skew the tonal/width fingerprint."""
    max_samples = int(max_seconds * sample_rate)
    if reference.shape[0] <= max_samples:
        return reference
    start = (reference.shape[0] - max_samples) // 2
    return reference[start: start + max_samples]


def _match_reference(audio: np.ndarray, sample_rate: int, reference: np.ndarray, amount: float) -> tuple[np.ndarray, list[str], list[str]]:
    """Matchering-style reference matching: shape the mix's tonal balance
    toward a commercial reference with a smoothed linear-phase matching EQ,
    then match stereo width. Broadband level is deliberately excluded (the
    LUFS/limiter stage owns loudness). Returns (audio, operations, warnings)."""
    operations: list[str] = []
    warnings: list[str] = []
    amount = max(0.0, min(1.0, amount))
    if amount <= 0 or audio.size == 0 or reference.size == 0:
        return audio, operations, warnings

    reference_window = _reference_analysis_window(reference, sample_rate)
    nyquist = sample_rate / 2.0
    band_centers = np.geomspace(30.0, min(16000.0, nyquist - 1500.0), 31)
    mix_spectrum = _band_spectrum_db(audio, sample_rate, band_centers)
    ref_spectrum = _band_spectrum_db(reference_window, sample_rate, band_centers)
    if mix_spectrum is None or ref_spectrum is None:
        warnings.append("Reference matching skipped: material too short for spectrum analysis.")
        return audio, operations, warnings

    gain_db = ref_spectrum - mix_spectrum
    # Tone only: remove the loudness-weighted average difference so the curve
    # reshapes balance without smuggling in a broadband level change.
    weights = np.clip(mix_spectrum - float(np.max(mix_spectrum)) + 60.0, 0.0, None)
    if float(np.sum(weights)) > 1e-9:
        gain_db -= float(np.average(gain_db, weights=weights))
    else:
        gain_db -= float(np.mean(gain_db))
    # Smooth across bands, clamp to a musical range, scale by match amount.
    gain_db = np.convolve(gain_db, np.array([0.25, 0.5, 0.25]), mode="same")
    gain_db = np.clip(gain_db, -8.0, 8.0) * amount

    # Linear-phase matching FIR from the band curve (delay-compensated).
    taps = 4097
    freq_points = np.concatenate([[0.0], band_centers, [nyquist]])
    gain_points = np.concatenate([[gain_db[0]], gain_db, [gain_db[-1]]])
    fir = signal.firwin2(taps, freq_points / nyquist, np.power(10.0, gain_points / 20.0))
    delay = taps // 2
    matched = np.empty_like(audio)
    work = audio if audio.ndim == 2 else audio.reshape(-1, 1)
    out = matched if audio.ndim == 2 else matched.reshape(-1, 1)
    for channel in range(work.shape[1]):
        filtered = signal.oaconvolve(work[:, channel].astype(np.float64, copy=False), fir)
        out[:, channel] = filtered[delay: delay + work.shape[0]].astype(np.float32)
    audio = matched
    strongest = float(np.max(np.abs(gain_db)))
    operations.append(f"reference tonal match (max {strongest:.1f} dB band move, {int(round(amount * 100))}% amount)")

    # Stereo width toward the reference's side/mid balance.
    mix_width = _width_ratio(audio)
    ref_width = _width_ratio(reference_window)
    if mix_width is not None and ref_width is not None and mix_width > 1e-4:
        width_change = max(-0.4, min(0.6, (ref_width / mix_width - 1.0) * amount * 0.7))
        if abs(width_change) > 0.03:
            audio = _apply_width(audio, width_change)
            operations.append(f"reference width match ({width_change:+.2f} side adjustment)")

    return audio.astype(np.float32, copy=False), operations, warnings


def _detect_hf_cutoff(audio: np.ndarray, sample_rate: int) -> float | None:
    """Find the lossy-codec brickwall: the frequency where the spectrum falls
    off a cliff into silence (MP3/AAC encoders discard everything above
    ~11-16 kHz at typical bitrates — Suno's default export included).
    Returns None when the material is full-bandwidth or too ambiguous, so
    restoration is a guaranteed no-op on clean WAV sources."""
    nyquist = sample_rate / 2.0
    if nyquist < 16000:
        return None
    mono = np.mean(audio, axis=1) if audio.ndim == 2 else audio
    if mono.shape[0] < sample_rate:
        return None
    try:
        freqs, psd = signal.welch(mono.astype(np.float64, copy=False), fs=sample_rate, nperseg=8192)
    except Exception:
        return None
    level_db = 10.0 * np.log10(psd + 1e-20)
    level_db = uniform_filter1d(level_db, size=9, mode="nearest")

    reference_band = (freqs >= 4000) & (freqs <= 10000)
    if not np.any(reference_band):
        return None
    reference_db = float(np.median(level_db[reference_band]))
    if reference_db < -110.0:
        return None  # effectively silent material

    # Highest frequency still carrying real content relative to the mids.
    active = freqs[(level_db > reference_db - 32.0) & (freqs > 1000)]
    if active.size == 0:
        return None
    upper = float(np.max(active))
    if upper >= min(19000.0, nyquist - 800.0) or upper < 8000.0:
        return None

    # Confirm it is a cliff (codec brickwall), not a gentle natural rolloff.
    just_below = (freqs >= upper * 0.88) & (freqs <= upper)
    just_above = (freqs > upper * 1.04) & (freqs <= min(upper * 1.3, nyquist - 200.0))
    if not np.any(just_below) or not np.any(just_above):
        return None
    drop_db = float(np.mean(level_db[just_below]) - np.mean(level_db[just_above]))
    if drop_db < 18.0:
        return None
    return upper


def _restore_high_frequencies(audio: np.ndarray, sample_rate: int, cutoff_hz: float, strength: float = 0.7) -> tuple[np.ndarray, bool]:
    """Spectral band replication above a codec cutoff: translate the top band
    of surviving content up past the cutoff, level-shaped to continue the
    track's own measured rolloff (program-dependent: cymbal hits regain
    shimmer, quiet passages stay quiet). Restores the 'air' that makes lossy
    sources read as sealed and dull next to a commercial master."""
    strength = max(0.0, min(1.0, strength))
    if strength <= 0 or audio.size == 0:
        return audio, False
    nyquist = sample_rate / 2.0
    dest_top = min(nyquist - 300.0, 20500.0)
    band_hz = dest_top - cutoff_hz
    if band_hz < 800.0:
        return audio, False

    work = audio if audio.ndim == 2 else audio.reshape(-1, 1)
    n_fft = 4096
    hop = 1024
    if work.shape[0] < n_fft * 2:
        return audio, False
    bin_hz = sample_rate / n_fft

    # Measure the source's own rolloff just below the cutoff so the synthetic
    # band continues the same trend instead of adding a bright shelf.
    mono = np.mean(work, axis=1)
    freqs, psd = signal.welch(mono.astype(np.float64, copy=False), fs=sample_rate, nperseg=8192)
    level_db = 10.0 * np.log10(psd + 1e-20)
    low_probe = (freqs >= cutoff_hz * 0.55) & (freqs <= cutoff_hz * 0.65)
    high_probe = (freqs >= cutoff_hz * 0.85) & (freqs <= cutoff_hz * 0.95)
    if not np.any(low_probe) or not np.any(high_probe):
        return audio, False
    slope_db_per_hz = (float(np.mean(level_db[high_probe])) - float(np.mean(level_db[low_probe]))) / (cutoff_hz * 0.30)
    slope_db_per_hz = max(-0.006, min(0.0, slope_db_per_hz))

    cutoff_bin = int(cutoff_hz / bin_hz)
    # The translation distance must be a multiple of n_fft/hop bins: then the
    # copied band's phase advance per hop is an exact multiple of 2*pi and the
    # overlapped frames add coherently. An arbitrary offset makes consecutive
    # frames partially cancel in the overlap-add (~10+ dB of lost level).
    frames_per_fft = n_fft // hop
    band_bins = (int(band_hz / bin_hz) // frames_per_fft) * frames_per_fft
    source_lo = cutoff_bin - band_bins
    if band_bins < frames_per_fft or source_lo <= 4:
        return audio, False

    # Per-bin gain for the copied band: continue the measured slope over the
    # +band_hz translation, taper a few extra dB toward the top, fade in over
    # the first ~400 Hz so the seam at the cutoff is invisible.
    offsets_hz = (np.arange(band_bins) * bin_hz).astype(np.float64)
    gain_db = slope_db_per_hz * band_hz - 2.0 - 4.0 * (offsets_hz / band_hz)
    gain = np.power(10.0, gain_db / 20.0) * strength
    fade_bins = max(2, int(400.0 / bin_hz))
    fade = np.ones(band_bins)
    fade[:fade_bins] = np.sin(np.linspace(0.0, math.pi / 2.0, fade_bins)) ** 2
    gain *= fade
    gain = np.minimum(gain, 1.0)

    restored = np.empty_like(work)
    for channel in range(work.shape[1]):
        _f, _t, stft_channel = signal.stft(work[:, channel], fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop)
        stft_channel[cutoff_bin: cutoff_bin + band_bins, :] += stft_channel[source_lo: source_lo + band_bins, :] * gain[:, None]
        _t, rebuilt = signal.istft(stft_channel, fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop)
        restored[:, channel] = _match_length(rebuilt, work.shape[0]).astype(np.float32)

    result = restored if audio.ndim == 2 else restored.reshape(-1)
    return result.astype(np.float32, copy=False), True


def _tpdf_dither_16bit(audio: np.ndarray) -> np.ndarray:
    """Triangular-PDF dither at one 16-bit LSB, applied before the float ->
    16-bit conversion so quantization error becomes benign noise instead of
    correlated distortion on fades and reverb tails."""
    lsb = 1.0 / 32768.0
    rng = np.random.default_rng(90210)
    noise = (rng.random(audio.shape) - rng.random(audio.shape)).astype(np.float32) * lsb
    return (audio + noise).astype(np.float32, copy=False)


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


_STEM_REFERENCE_LUFS: dict[str, float] = {
    "Lead Vocal": -18.0,
    "Backing Vocal": -20.0,
    "Drums": -18.0,
    "Kick": -18.0,
    "Snare": -18.0,
    "Bass": -19.0,
}


def _normalize_stem_level(audio: np.ndarray, sample_rate: int, stem_type: str) -> tuple[np.ndarray, float]:
    """Bring a stem to its reference loudness before the channel strip. Every
    compressor threshold downstream is a fixed dBFS value, so without this the
    amount of compression (and the whole mix balance) depends on however hot
    each incoming file happens to be."""
    reference = _STEM_REFERENCE_LUFS.get(stem_type, -20.0)
    try:
        meter = pyln.Meter(sample_rate)
        loudness = float(meter.integrated_loudness(audio))
        if not math.isfinite(loudness) or loudness < -60.0:
            return audio, 0.0
        gain_db = max(-12.0, min(12.0, reference - loudness))
        if abs(gain_db) < 0.25:
            return audio, 0.0
        return _apply_gain(audio, gain_db).astype(np.float32, copy=False), gain_db
    except Exception:
        return audio, 0.0


def _process_advanced_stem(audio: np.ndarray, sample_rate: int, item: dict, controls: dict, warnings: list[str]) -> tuple[np.ndarray, np.ndarray]:
    stem_type = item.get("stemType", "Unknown")
    processing_enabled = bool(item.get("processingChainEnabled", True))
    vocal_channel_strip_enabled = processing_enabled and not _should_bypass_vocal_channel_strip(item)
    compression_amount = max(0.0, min(1.0, float(item.get("compressionAmount", 50)) / 100.0))
    dry = audio.astype(np.float32, copy=True)

    dry, _normalize_gain_db = _normalize_stem_level(dry, sample_rate, stem_type)

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
    send = (dry * send_amount).astype(np.float32, copy=False)
    dry = np.nan_to_num(dry, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)
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
            ("vocal compressor", lambda audio: _compress_audio(audio, threshold_db=-22, ratio=3.2, mix=0.45 + compression_amount * 0.4, sample_rate=sample_rate)),
            ("vocal tone", tone),
        ]
    if stem_type == "Backing Vocal":
        return [
            ("backing vocal high-pass", lambda audio: _high_pass(audio, sample_rate, 100)),
            ("backing vocal cleanup EQ", lambda audio: _eq_band(audio, sample_rate, 250, 500, -1.5)),
            ("backing vocal compressor", lambda audio: _compress_audio(audio, threshold_db=-24, ratio=3.0, mix=0.4 + compression_amount * 0.35, sample_rate=sample_rate)),
            ("backing vocal spread", lambda audio: _apply_width(audio, 0.08 + width * 0.16 + backing_width * 0.28)),
            ("backing vocal tone", tone),
        ]
    if stem_type == "Drums":
        return [
            ("drum low-end cleanup", lambda audio: _high_pass(audio, sample_rate, 28)),
            ("drum mud control", lambda audio: _eq_band(audio, sample_rate, 260, 520, -1.0)),
            ("drum bus compression", lambda audio: _compress_audio(audio, threshold_db=-18, ratio=2.2 + drum_punch * 1.4, mix=0.18 + compression_amount * 0.22, sample_rate=sample_rate)),
            ("drum transient tone", lambda audio: _eq_band(audio, sample_rate, 4500, 9000, drum_punch * 1.0 + brightness * 0.8)),
            ("drum tone", tone),
        ]
    if stem_type == "Kick":
        return [
            ("kick rumble cleanup", lambda audio: _high_pass(audio, sample_rate, 24)),
            ("kick low-end control", lambda audio: _eq_band(audio, sample_rate, 180, 360, -1.2)),
            ("kick weight", lambda audio: _eq_band(audio, sample_rate, 45, 90, -0.5 + bass_weight * 1.2)),
            ("kick compression", lambda audio: _compress_audio(audio, threshold_db=-17, ratio=3.4, mix=0.25 + compression_amount * 0.28, sample_rate=sample_rate)),
        ]
    if stem_type == "Snare":
        return [
            ("snare high-pass", lambda audio: _high_pass(audio, sample_rate, 70)),
            ("snare body control", lambda audio: _eq_band(audio, sample_rate, 350, 700, -0.8)),
            ("snare crack", lambda audio: _eq_band(audio, sample_rate, 3000, 6500, 0.8 + drum_punch * 1.0)),
            ("snare compression", lambda audio: _compress_audio(audio, threshold_db=-19, ratio=2.8, mix=0.2 + compression_amount * 0.25, sample_rate=sample_rate)),
        ]
    if stem_type == "Bass":
        return [
            ("bass sub cleanup", lambda audio: _high_pass(audio, sample_rate, 28)),
            ("bass low-end control", lambda audio: _eq_band(audio, sample_rate, 45, 110, -0.4 + bass_weight * 1.4)),
            ("bass mud control", lambda audio: _eq_band(audio, sample_rate, 180, 420, -1.0)),
            ("bass compression", lambda audio: _compress_audio(audio, threshold_db=-21, ratio=3.8, mix=0.35 + compression_amount * 0.38, sample_rate=sample_rate)),
            ("bass saturation", lambda audio: _saturate(audio, drive=1.15 + bass_weight * 0.45, mix=0.08 + bass_weight * 0.08)),
            ("bass mono focus", lambda audio: _apply_width(audio, -0.35)),
        ]
    if stem_type == "Electric Guitar":
        return [
            ("electric guitar high-pass", lambda audio: _high_pass(audio, sample_rate, 72)),
            ("electric guitar mud control", lambda audio: _eq_band(audio, sample_rate, 220, 520, -1.8)),
            ("electric guitar bite", lambda audio: _eq_band(audio, sample_rate, 2200, 5200, 0.5 + brightness * 0.9)),
            ("electric guitar compression", lambda audio: _compress_audio(audio, threshold_db=-20, ratio=2.4, mix=0.16 + compression_amount * 0.22, sample_rate=sample_rate)),
            ("electric guitar width", lambda audio: _apply_width(audio, width * 0.18)),
            ("electric guitar tone", tone),
        ]
    if stem_type == "Acoustic Guitar":
        return [
            ("acoustic high-pass", lambda audio: _high_pass(audio, sample_rate, 86)),
            ("acoustic boom control", lambda audio: _eq_band(audio, sample_rate, 140, 320, -1.6)),
            ("acoustic presence", lambda audio: _eq_band(audio, sample_rate, 2500, 6500, 0.7 + brightness * 0.8)),
            ("acoustic compression", lambda audio: _compress_audio(audio, threshold_db=-22, ratio=2.2, mix=0.18 + compression_amount * 0.2, sample_rate=sample_rate)),
            ("acoustic tone", tone),
        ]
    if stem_type == "Keys/Piano":
        return [
            ("keys high-pass", lambda audio: _high_pass(audio, sample_rate, 58)),
            ("keys vocal-space EQ", lambda audio: _eq_band(audio, sample_rate, 1800, 4200, -0.7)),
            ("keys width", lambda audio: _apply_width(audio, width * 0.22)),
            ("keys light compression", lambda audio: _compress_audio(audio, threshold_db=-24, ratio=1.8, mix=0.08 + compression_amount * 0.14, sample_rate=sample_rate)),
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
        ("general compression", lambda audio: _compress_audio(audio, threshold_db=-22, ratio=2.0, mix=0.1 + compression_amount * 0.16, sample_rate=sample_rate)),
        ("general tone", tone),
    ]


def _rbj_biquad_sos(sample_rate: int, kind: str, f0: float, q: float, gain_db: float) -> np.ndarray:
    """RBJ audio-EQ-cookbook peaking/shelf biquad as a single SOS section."""
    a_lin = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * f0 / sample_rate
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * max(0.05, q))
    if kind == "peak":
        b = [1.0 + alpha * a_lin, -2.0 * cos_w0, 1.0 - alpha * a_lin]
        a = [1.0 + alpha / a_lin, -2.0 * cos_w0, 1.0 - alpha / a_lin]
    else:
        beta = 2.0 * math.sqrt(a_lin) * alpha
        if kind == "lowshelf":
            b = [a_lin * ((a_lin + 1) - (a_lin - 1) * cos_w0 + beta), 2 * a_lin * ((a_lin - 1) - (a_lin + 1) * cos_w0), a_lin * ((a_lin + 1) - (a_lin - 1) * cos_w0 - beta)]
            a = [(a_lin + 1) + (a_lin - 1) * cos_w0 + beta, -2 * ((a_lin - 1) + (a_lin + 1) * cos_w0), (a_lin + 1) + (a_lin - 1) * cos_w0 - beta]
        else:  # highshelf
            b = [a_lin * ((a_lin + 1) + (a_lin - 1) * cos_w0 + beta), -2 * a_lin * ((a_lin - 1) + (a_lin + 1) * cos_w0), a_lin * ((a_lin + 1) + (a_lin - 1) * cos_w0 - beta)]
            a = [(a_lin + 1) - (a_lin - 1) * cos_w0 + beta, 2 * ((a_lin - 1) - (a_lin + 1) * cos_w0), (a_lin + 1) - (a_lin - 1) * cos_w0 - beta]
    a0 = a[0]
    return np.array([[b[0] / a0, b[1] / a0, b[2] / a0, 1.0, a[1] / a0, a[2] / a0]], dtype=np.float64)


def _eq_band(audio: np.ndarray, sample_rate: int, low_hz: float, high_hz: float, gain_db: float) -> np.ndarray:
    """Bell/shelf EQ over the given band. Bands that reach the spectrum edges
    become shelves; interior bands become an RBJ peaking bell at the band's
    geometric center. Filters run causally (minimum-phase, like an analog EQ)
    so transients keep their attack instead of picking up filtfilt pre-ring."""
    if abs(gain_db) < 0.05 or high_hz <= low_hz or low_hz >= sample_rate / 2:
        return audio
    high = min(high_hz, sample_rate / 2 - 100)
    if high <= low_hz:
        return audio
    if high >= sample_rate * 0.30:
        sos = _rbj_biquad_sos(sample_rate, "highshelf", max(200.0, low_hz), 0.707, gain_db)
    elif low_hz <= 60.0:
        sos = _rbj_biquad_sos(sample_rate, "lowshelf", high, 0.707, gain_db)
    else:
        center = math.sqrt(low_hz * high)
        q = max(0.4, min(4.0, center / max(1.0, high - low_hz)))
        sos = _rbj_biquad_sos(sample_rate, "peak", center, q, gain_db)
    try:
        return signal.sosfilt(sos, audio, axis=0).astype(np.float32, copy=False)
    except Exception:
        return audio


def _asym_envelope(values: np.ndarray, rate_hz: float, attack_seconds: float, release_seconds: float) -> np.ndarray:
    """One-pole envelope follower with independent attack/release, run at the
    (low) control rate so the Python loop stays short."""
    attack_coeff = math.exp(-1.0 / max(1.0, rate_hz * max(1e-4, attack_seconds)))
    release_coeff = math.exp(-1.0 / max(1.0, rate_hz * max(1e-4, release_seconds)))
    out = np.empty(values.shape[0], dtype=np.float32)
    previous = float(values[0]) if values.size else 0.0
    for index in range(values.shape[0]):
        sample = float(values[index])
        coeff = attack_coeff if sample > previous else release_coeff
        previous = coeff * previous + (1.0 - coeff) * sample
        out[index] = previous
    return out


def _control_blocks(detector: np.ndarray, block: int) -> np.ndarray:
    """Max-pool a per-sample detector down to control-rate blocks."""
    count = (detector.shape[0] + block - 1) // block
    padded = np.pad(detector, (0, count * block - detector.shape[0]), mode="edge")
    return padded.reshape(count, block).max(axis=1)


def _expand_control_gain(gain_blocks: np.ndarray, block: int, length: int) -> np.ndarray:
    """Linear-interpolate control-rate gains back to sample rate (no zipper)."""
    positions = np.arange(gain_blocks.shape[0]) * block + block // 2
    return np.interp(np.arange(length), positions, gain_blocks, left=gain_blocks[0], right=gain_blocks[-1]).astype(np.float32)


def _compress_audio(
    audio: np.ndarray,
    threshold_db: float,
    ratio: float,
    mix: float,
    sample_rate: int = 44100,
    attack_ms: float = 8.0,
    release_ms: float = 90.0,
    knee_db: float = 6.0,
    sidechain_hpf_hz: float = 0.0,
    makeup_db: float = 0.0,
) -> np.ndarray:
    """Soft-knee compressor with a control-rate detector (~1 ms blocks). The
    envelope loop runs ~1000x slower than audio rate, and the resulting gain is
    interpolated back up, which both speeds rendering up massively and smooths
    the gain signal (no per-sample staircase)."""
    mix = max(0.0, min(1.0, mix))
    if mix <= 0:
        return audio
    sample_rate = max(8000, int(sample_rate))
    ratio = max(1.0, float(ratio))
    knee_db = max(0.0, float(knee_db))
    detector_source = audio
    if sidechain_hpf_hz > 0:
        try:
            detector_source = _high_pass(audio, sample_rate, sidechain_hpf_hz)
        except Exception:
            detector_source = audio
    detector = np.max(np.abs(detector_source), axis=1) if detector_source.ndim == 2 else np.abs(detector_source)
    block = max(8, int(sample_rate * 0.001))
    blocks = _control_blocks(detector.astype(np.float32, copy=False), block)
    control_rate = sample_rate / block
    envelope = _asym_envelope(blocks, control_rate, attack_ms / 1000.0, release_ms / 1000.0)
    envelope_db = 20.0 * np.log10(np.maximum(envelope, 1e-9))
    over_db = envelope_db - float(threshold_db)
    slope = 1.0 - 1.0 / ratio
    if knee_db > 0:
        half = knee_db / 2.0
        reduction_db = np.where(
            over_db <= -half,
            0.0,
            np.where(over_db >= half, over_db * slope, slope * np.square(over_db + half) / (2.0 * knee_db)),
        )
    else:
        reduction_db = np.maximum(over_db, 0.0) * slope
    gain_blocks = np.power(10.0, (-reduction_db + float(makeup_db)) / 20.0).astype(np.float32)
    gain = _expand_control_gain(gain_blocks, block, audio.shape[0])
    compressed = audio * gain[:, None] if audio.ndim == 2 else audio * gain
    return (audio * (1.0 - mix) + compressed * mix).astype(np.float32, copy=False)


def _trim_peak_to_target(audio: np.ndarray, target_peak_db: float) -> tuple[np.ndarray, float]:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 1e-8:
        return audio.astype(np.float32, copy=False), 0.0
    target = _db_to_linear(target_peak_db)
    if peak <= target:
        return audio.astype(np.float32, copy=False), 0.0
    gain = target / peak
    return (audio * gain).astype(np.float32, copy=False), _round(_linear_to_db(gain))


def _peak_limit(audio: np.ndarray, ceiling: float = 0.98) -> np.ndarray:
    ceiling = max(0.1, min(0.999, float(ceiling)))
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= ceiling or peak <= 1e-8:
        return audio.astype(np.float32, copy=False)
    return (audio * (ceiling / peak)).astype(np.float32, copy=False)


def _saturate(audio: np.ndarray, drive: float, mix: float) -> np.ndarray:
    """Tanh saturation run at 4x oversampling: the harmonics the waveshaper
    creates above Nyquist land in the oversampled band and are filtered out on
    the way back down instead of aliasing into the audible range as inharmonic
    grit (most audible on vocal sibilance and cymbals)."""
    mix = max(0.0, min(1.0, mix))
    drive = max(1.0, drive)
    if mix <= 0:
        return audio
    length = audio.shape[0]
    try:
        upsampled = signal.resample_poly(audio, up=4, down=1, axis=0)
        saturated = np.tanh(upsampled * drive) / np.tanh(drive)
        saturated = signal.resample_poly(saturated, up=1, down=4, axis=0)
        saturated = saturated[:length] if saturated.shape[0] >= length else np.pad(saturated, ((0, length - saturated.shape[0]),) + ((0, 0),) * (audio.ndim - 1))
    except Exception:
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
    return widened.astype(np.float32, copy=False)


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
        "AI Pop Clean": {
            "highPassHz": 92,
            "noiseReduction": 0.10,
            "deEss": 0.42,
            "rider": 0.30,
            "bodyDb": 0.1,
            "presenceDb": 1.1,
            "airDb": 0.9,
            "compression": 0.38,
            "compressionThresholdDb": -22,
            "compressionRatio": 2.2,
            "saturation": 0.018,
            "doubler": 0.025,
            "width": 0.01,
        },
        "AI Studio Clear": {
            "highPassHz": 96,
            "noiseReduction": 0.16,
            "deEss": 0.50,
            "rider": 0.54,
            "bodyDb": 0.0,
            "presenceDb": 1.35,
            "airDb": 1.15,
            "compression": 0.56,
            "compressionThresholdDb": -23.5,
            "compressionRatio": 3.0,
            "saturation": 0.035,
            "doubler": 0.035,
            "width": 0.01,
            "breathReduction": 0.22,
            "mouthClickReduction": 0.20,
        },
        "Suno-Style Lead": {
            "highPassHz": 100,
            "noiseReduction": 0.18,
            "deEss": 0.62,
            "rider": 0.72,
            "bodyDb": -0.1,
            "presenceDb": 2.25,
            "airDb": 2.20,
            "compression": 0.74,
            "compressionThresholdDb": -25,
            "compressionRatio": 3.9,
            "saturation": 0.085,
            "doubler": 0.05,
            "width": 0.02,
            "breathReduction": 0.24,
            "mouthClickReduction": 0.22,
        },
        "Suno Clean Dry": {
            "highPassHz": 98,
            "noiseReduction": 0.16,
            "deEss": 0.54,
            "rider": 0.58,
            "bodyDb": 0.0,
            "presenceDb": 1.45,
            "airDb": 1.25,
            "compression": 0.58,
            "compressionThresholdDb": -23.5,
            "compressionRatio": 3.1,
            "saturation": 0.035,
            "doubler": 0.0,
            "width": 0.0,
            "breathReduction": 0.24,
            "mouthClickReduction": 0.22,
        },
        "Natural Clean": {
            "highPassHz": 88,
            "noiseReduction": 0.12,
            "deEss": 0.36,
            "rider": 0.34,
            "bodyDb": 0.2,
            "presenceDb": 0.9,
            "airDb": 0.7,
            "compression": 0.40,
            "compressionThresholdDb": -23,
            "compressionRatio": 2.4,
            "saturation": 0.022,
            "doubler": 0.0,
            "width": 0.0,
        },
        "Pop Vocal": {
            "highPassHz": 95,
            "noiseReduction": 0.14,
            "deEss": 0.48,
            "rider": 0.46,
            "bodyDb": -0.1,
            "presenceDb": 1.2,
            "airDb": 1.1,
            "compression": 0.54,
            "compressionThresholdDb": -23,
            "compressionRatio": 2.8,
            "saturation": 0.045,
            "doubler": 0.05,
            "width": 0.02,
        },
        "Worship Lead": {
            "highPassHz": 90,
            "noiseReduction": 0.14,
            "deEss": 0.44,
            "rider": 0.48,
            "bodyDb": 0.3,
            "presenceDb": 1.1,
            "airDb": 1.0,
            "compression": 0.50,
            "compressionThresholdDb": -24,
            "compressionRatio": 2.7,
            "saturation": 0.03,
            "doubler": 0.04,
            "width": 0.02,
        },
        "Live Vocal Fix": {
            "highPassHz": 105,
            "noiseReduction": 0.22,
            "deEss": 0.48,
            "rider": 0.50,
            "bodyDb": -0.2,
            "presenceDb": 0.8,
            "airDb": 0.4,
            "compression": 0.46,
            "compressionThresholdDb": -24,
            "compressionRatio": 2.7,
            "saturation": 0.02,
            "doubler": 0.0,
            "width": 0.0,
        },
        "Bright AI Polish": {
            "highPassHz": 100,
            "noiseReduction": 0.18,
            "deEss": 0.56,
            "rider": 0.50,
            "bodyDb": -0.3,
            "presenceDb": 1.4,
            "airDb": 1.5,
            "compression": 0.58,
            "compressionThresholdDb": -23.5,
            "compressionRatio": 3.0,
            "saturation": 0.04,
            "doubler": 0.04,
            "width": 0.01,
        },
        "Warm Ballad": {
            "highPassHz": 82,
            "noiseReduction": 0.12,
            "deEss": 0.38,
            "rider": 0.40,
            "bodyDb": 0.8,
            "presenceDb": 0.7,
            "airDb": 0.6,
            "compression": 0.46,
            "compressionThresholdDb": -23,
            "compressionRatio": 2.7,
            "saturation": 0.045,
            "doubler": 0.02,
            "width": 0.01,
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


def _log_spectral_envelope(log_magnitude: np.ndarray, f0_hz: float, sample_rate: int, n_fft: int) -> np.ndarray:
    """Formant envelope of a log-magnitude STFT (bins x frames): a maximum
    filter roughly one harmonic spacing wide rides the harmonic PEAKS (the
    samples of the vocal-tract envelope), then a light smooth removes the
    staircase. Plain averaging is wrong here — it dips between harmonics and
    flattens formants, which made the restoration barely act."""
    bins_per_hz = n_fft / sample_rate
    spacing_bins = int(max(3, min(64, 1.6 * max(60.0, f0_hz) * bins_per_hz))) | 1
    envelope = maximum_filter1d(log_magnitude, size=spacing_bins, axis=0, mode="nearest")
    smooth_bins = max(3, spacing_bins // 2) | 1
    return uniform_filter1d(envelope, size=smooth_bins, axis=0, mode="nearest")


def _restore_spectral_envelope(processed: np.ndarray, original: np.ndarray, sample_rate: int, f0_hz: float) -> np.ndarray:
    """Restore the original's spectral envelope onto the processed signal.
    A phase-vocoder pitch shift moves the formants along with the pitch (the
    'chipmunk' color change); dividing out the processed envelope and applying
    the original one per frame puts the vocal-tract resonances back where the
    singer's voice had them."""
    n_fft = 2048
    hop = 512
    if processed.shape[0] < n_fft or original.shape[0] < n_fft:
        return processed
    _f, _t, stft_processed = signal.stft(processed, fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop)
    _f, _t, stft_original = signal.stft(original, fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop)
    frames = min(stft_processed.shape[1], stft_original.shape[1])
    stft_processed = stft_processed[:, :frames]
    stft_original = stft_original[:, :frames]

    envelope_original = _log_spectral_envelope(np.log(np.abs(stft_original) + 1e-9), f0_hz, sample_rate, n_fft)
    log_processed = np.log(np.abs(stft_processed) + 1e-9)
    # One pass under-corrects (both envelope estimates are biased the same
    # way), so iterate: re-estimate the corrected signal's envelope and fix
    # the residual until the envelopes line up.
    total_log_gain = np.zeros_like(log_processed)
    for _ in range(3):
        envelope_now = _log_spectral_envelope(log_processed + total_log_gain, f0_hz, sample_rate, n_fft)
        total_log_gain = np.clip(total_log_gain + (envelope_original - envelope_now), -2.6, 2.6)
    gain = np.exp(total_log_gain)
    _t, restored = signal.istft(stft_processed * gain, fs=sample_rate, nperseg=n_fft, noverlap=n_fft - hop)
    return _match_length(restored, processed.shape[0]).astype(np.float32, copy=False)


def _shift_note_formant_preserving(channel: np.ndarray, start: int, end: int, sample_rate: int, semitones: float, f0_hz: float = 160.0) -> np.ndarray | None:
    """Pitch-shift channel[start:end] by `semitones` while keeping the vocal's
    formants in place. Analyzes with real surrounding context (padding) so the
    shift has no synthetic edges, then returns only the note's samples.
    Uses the WORLD vocoder when installed (pitch and vocal-tract envelope are
    modeled separately, so formants are untouched by construction); otherwise
    falls back to a phase-vocoder shift with spectral-envelope restoration."""
    pad = int(sample_rate * 0.06)
    padded_start = max(0, start - pad)
    padded_end = min(channel.shape[0], end + pad)
    segment = channel[padded_start:padded_end]
    if segment.shape[0] < int(sample_rate * 0.03):
        return None
    offset = start - padded_start
    length = end - start

    if pw is not None:
        try:
            x = segment.astype(np.float64)
            f0, time_axis = pw.dio(x, sample_rate, frame_period=5.0)
            f0 = pw.stonemask(x, f0, time_axis, sample_rate)
            envelope = pw.cheaptrick(x, f0, time_axis, sample_rate)
            aperiodicity = pw.d4c(x, f0, time_axis, sample_rate)
            shifted_f0 = f0 * (2.0 ** (semitones / 12.0))
            synthesized = pw.synthesize(shifted_f0, envelope, aperiodicity, sample_rate, frame_period=5.0)
            synthesized = _match_length(synthesized.astype(np.float32), segment.shape[0])
            return synthesized[offset: offset + length]
        except Exception:
            pass  # fall through to the spectral fallback

    try:
        shifted = librosa.effects.pitch_shift(y=segment.astype(np.float32, copy=False), sr=sample_rate, n_steps=float(semitones))
        shifted = _match_length(shifted, segment.shape[0]).astype(np.float32, copy=False)
        restored = _restore_spectral_envelope(shifted, segment.astype(np.float32, copy=False), sample_rate, f0_hz)
        return restored[offset: offset + length]
    except Exception:
        return None


def _pitch_polish(audio: np.ndarray, sample_rate: int, mode: str, key: str, scale: str, strength: float = 50, humanize: float = 60) -> tuple[np.ndarray, str, str | None]:
    """Per-note pitch correction. Tracks pitch over time, segments the take into
    individual notes, and retunes each note toward the nearest scale degree
    (autotune-style) instead of shifting the whole clip by one amount. This is
    what gives the "locked", produced pitch feel; `humanize` backs off the snap
    and preserves within-note vibrato, `strength` scales how hard it corrects."""
    try:
        mono = np.mean(audio, axis=1).astype(np.float32, copy=False)
        if mono.size < sample_rate:
            return audio, f"{mode} pitch polish skipped", "Vocal is too short for pitch estimation."
        mode_factor = {"Natural": 0.5, "Medium": 0.8, "Strong": 1.0}.get(mode, 0.0)
        if mode_factor <= 0:
            return audio, f"{mode} pitch polish skipped", None
        strength_ratio = max(0.0, min(1.0, strength / 100.0))
        humanize_ratio = max(0.0, min(1.0, humanize / 100.0))

        detected_key_note = ""
        if key == "Auto" and scale != "Chromatic":
            estimated_key, estimated_scale, key_confidence = _estimate_key_and_scale(mono, sample_rate)
            if estimated_key != "Auto" and key_confidence >= 35.0:
                key = estimated_key
                scale = estimated_scale
                detected_key_note = f", detected {estimated_key} {estimated_scale}"

        hop = 512
        frame_length = 2048
        f0, _voiced_flag, _voiced_prob = librosa.pyin(
            mono,
            fmin=librosa.note_to_hz("C2"),
            fmax=librosa.note_to_hz("C6"),
            sr=sample_rate,
            frame_length=frame_length,
            hop_length=hop,
        )
        midi = librosa.hz_to_midi(f0)
        voiced = np.isfinite(f0)
        if int(np.count_nonzero(voiced)) < 8:
            return audio, f"{mode} pitch polish skipped", "Could not find enough voiced vocal frames for pitch polish."

        segments = _note_segments(midi, voiced, hop, mono.shape[0], sample_rate)
        if not segments:
            return audio, f"{mode} pitch polish checked", None

        # Correction fraction toward the grid, softened by humanize.
        correction = strength_ratio * mode_factor * (1.0 - humanize_ratio * 0.4)
        max_note_shift = 2.0  # cap per-note pull so octave/tracking errors can't fling a note
        out = audio.astype(np.float32, copy=True)
        shifts: list[float] = []
        for start, end, median_midi in segments:
            if end - start < int(sample_rate * 0.05):
                continue
            target = _nearest_target_midi(median_midi, key, scale)
            semitones = (target - median_midi) * correction
            semitones = max(-max_note_shift, min(max_note_shift, semitones))
            if abs(semitones) < 0.03:
                continue
            note_f0_hz = float(librosa.midi_to_hz(median_midi))
            applied = False
            for channel in range(out.shape[1]):
                shifted = _shift_note_formant_preserving(audio[:, channel], start, end, sample_rate, float(semitones), f0_hz=note_f0_hz)
                if shifted is None:
                    continue
                shifted = _match_length(shifted, end - start).astype(np.float32, copy=False)
                _write_with_edge_fade(out[:, channel], shifted, start, end, sample_rate)
                applied = True
            if applied:
                shifts.append(abs(semitones))

        if not shifts:
            return audio, f"{mode} pitch polish checked", None
        avg_shift = float(np.mean(shifts))
        engine_label = "WORLD formant-preserving" if pw is not None else "formant-preserving"
        description = f"{mode} per-note pitch correction ({engine_label}, {len(shifts)} notes, avg {avg_shift:.2f} st, strength {int(round(strength))}%, humanize {int(round(humanize))}%{detected_key_note})"
        return _sanitize_audio(out), description, None
    except Exception as exc:
        return audio, f"{mode} pitch polish skipped", f"Pitch polish unavailable: {str(exc) or 'analysis failed'}."


def _note_segments(midi: np.ndarray, voiced: np.ndarray, hop: int, total_samples: int, sample_rate: int) -> list[tuple[int, int, float]]:
    """Split a per-frame pitch track into note-sized sample ranges: contiguous
    voiced runs, further split where the rounded semitone changes."""
    n = len(midi)
    min_frames = max(3, int(0.06 * sample_rate / hop))
    raw: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if not voiced[i]:
            i += 1
            continue
        j = i
        while j < n and voiced[j]:
            j += 1
        sub_start = i
        current = round(float(midi[i]))
        for k in range(i + 1, j):
            rounded = round(float(midi[k]))
            if abs(rounded - current) >= 1:
                if k - sub_start >= min_frames:
                    raw.append((sub_start, k))
                sub_start = k
                current = rounded
        if j - sub_start >= min_frames:
            raw.append((sub_start, j))
        i = j

    result: list[tuple[int, int, float]] = []
    for frame_start, frame_end in raw:
        start = min(total_samples, frame_start * hop)
        end = min(total_samples, frame_end * hop)
        if end - start < 1:
            continue
        median_midi = float(np.nanmedian(midi[frame_start:frame_end]))
        if not np.isfinite(median_midi):
            continue
        result.append((start, end, median_midi))
    return result


def _write_with_edge_fade(channel_out: np.ndarray, shifted: np.ndarray, start: int, end: int, sample_rate: int) -> None:
    """Replace channel_out[start:end] with `shifted`, crossfading the first and
    last few ms back to the existing signal to avoid clicks at note seams."""
    length = min(end - start, shifted.shape[0])
    if length <= 0:
        return
    end = start + length
    segment = shifted[:length].copy()
    original = channel_out[start:end]
    fade = min(int(sample_rate * 0.008), length // 2)
    if fade > 0:
        fade_in = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        fade_out = np.linspace(1.0, 0.0, fade, dtype=np.float32)
        segment[:fade] = original[:fade] * (1.0 - fade_in) + segment[:fade] * fade_in
        segment[-fade:] = original[-fade:] * (1.0 - fade_out) + segment[-fade:] * fade_out
    channel_out[start:end] = segment


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
    return ridden.astype(np.float32, copy=False)


def _modulated_voice(mono: np.ndarray, sample_rate: int, base_delay_ms: float, depth_ms: float, lfo_hz: float, lfo_phase: float) -> np.ndarray:
    """One chorus voice: a fractional delay line whose delay time drifts with a
    slow sine LFO. The drift is a real micro pitch/timing variation, which is
    what makes a double sound like another performance instead of a comb filter."""
    length = mono.shape[0]
    positions = np.arange(length, dtype=np.float64)
    delay = (base_delay_ms + depth_ms * np.sin(2.0 * math.pi * lfo_hz * positions / sample_rate + lfo_phase)) * sample_rate / 1000.0
    read = np.clip(positions - delay, 0.0, length - 1.0)
    return np.interp(read, positions, mono.astype(np.float64, copy=False)).astype(np.float32)


def _vocal_doubler(audio: np.ndarray, sample_rate: int, amount: float) -> np.ndarray:
    """Stereo doubler built from two LFO-modulated voices panned left/right.
    Both voices keep positive polarity, so the double stays present when the
    mix is folded to mono (the old polarity-flipped Haas trick cancelled)."""
    amount = max(0.0, min(0.35, amount))
    if amount <= 0 or audio.size == 0:
        return audio
    work = audio if audio.ndim == 2 else audio.reshape(-1, 1)
    mono = np.mean(work, axis=1).astype(np.float32, copy=False)
    voice_left = _modulated_voice(mono, sample_rate, base_delay_ms=14.0, depth_ms=1.6, lfo_hz=0.31, lfo_phase=0.0)
    voice_right = _modulated_voice(mono, sample_rate, base_delay_ms=21.0, depth_ms=2.1, lfo_hz=0.43, lfo_phase=1.9)
    doubled = work.astype(np.float32, copy=True) * (1.0 - amount * 0.12)
    level = amount * 0.55
    doubled[:, 0] += voice_left * level
    doubled[:, -1] += voice_right * level
    result = doubled if audio.ndim == 2 else doubled.reshape(-1)
    return _peak_limit(result, ceiling=0.98)


def _apply_vocal_fx(audio: np.ndarray, sample_rate: int, style: str, amount: float) -> np.ndarray:
    amount_ratio = max(0.0, min(1.0, amount / 100.0))
    if amount_ratio <= 0:
        return audio
    if style == "Natural Plate":
        wet = _simple_reverb(audio, sample_rate, amount=0.12 * amount_ratio, room_size=0.48)
        mixed = audio * (1.0 - 0.08 * amount_ratio) + wet
    elif style == "Small Hall":
        wet = _simple_reverb(audio, sample_rate, amount=0.16 * amount_ratio, room_size=0.74)
        mixed = audio * (1.0 - 0.10 * amount_ratio) + wet
    elif style == "Slap Delay":
        wet = _delay_effect(audio, sample_rate, delay_seconds=0.105, feedback=0.10, amount=0.14 * amount_ratio)
        mixed = audio * (1.0 - 0.06 * amount_ratio) + wet
    elif style == "Quarter Delay":
        wet = _delay_effect(audio, sample_rate, delay_seconds=0.32, feedback=0.22, amount=0.12 * amount_ratio)
        mixed = audio * (1.0 - 0.08 * amount_ratio) + wet
    elif style == "Worship Wide":
        reverb = _simple_reverb(audio, sample_rate, amount=0.16 * amount_ratio, room_size=0.88)
        delay = _delay_effect(audio, sample_rate, delay_seconds=0.28, feedback=0.22, amount=0.10 * amount_ratio)
        spread = _apply_width(delay + reverb, 0.26)
        mixed = audio * (1.0 - 0.12 * amount_ratio) + spread
    elif style == "Suno Space":
        # Lush produced vocal finish: bright plate + slap + quarter delay, widened.
        reverb = _simple_reverb(audio, sample_rate, amount=0.22 * amount_ratio, room_size=0.70)
        slap = _delay_effect(audio, sample_rate, delay_seconds=0.11, feedback=0.12, amount=0.10 * amount_ratio)
        quarter = _delay_effect(audio, sample_rate, delay_seconds=0.30, feedback=0.20, amount=0.09 * amount_ratio)
        spread = _apply_width(reverb + slap + quarter, 0.32)
        mixed = audio * (1.0 - 0.10 * amount_ratio) + spread
    else:
        mixed = audio
    return _peak_limit(mixed, ceiling=0.98)


def _final_vocal_level(audio: np.ndarray, target_peak_db: float) -> np.ndarray:
    trimmed, _ = _trim_peak_to_target(audio, target_peak_db)
    return trimmed


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


def _process_vocal_mix_bus(audio: np.ndarray, sample_rate: int, controls: dict, warnings: list[str], tempo_bpm: float | None = None) -> np.ndarray:
    if audio.size == 0:
        return audio
    vocal_bus = audio.astype(np.float32, copy=True)
    glue = _control_ratio(controls, "vocalGlueAmount")
    if glue > 0.01:
        vocal_bus = _compress_audio(vocal_bus, threshold_db=-21.5 + (0.5 - glue) * 4.0, ratio=1.5 + glue * 2.0, mix=0.12 + glue * 0.30, sample_rate=sample_rate)
    delay_amount = _control_ratio(controls, "vocalDelayAmount")
    if delay_amount > 0.01:
        vocal_bus = vocal_bus + _pingpong_delay(
            vocal_bus,
            sample_rate,
            delay_seconds=_synced_delay_seconds(tempo_bpm, 0.285),
            feedback=0.30 + delay_amount * 0.35,
            amount=0.10 + delay_amount * 0.42,
        )
    level = float(controls.get("vocalBusLevel", 0))
    if abs(level) > 0.01:
        vocal_bus = _apply_gain(vocal_bus, level)
    if glue > 0.82:
        warnings.append("High vocal bus glue can reduce vocal dynamics; compare the mix version against the previous one.")
    if delay_amount > 0.75:
        warnings.append("High vocal delay can blur lyrics; reduce Vocal Delay if the lead feels less direct.")
    return np.nan_to_num(vocal_bus, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32, copy=False)


def _stem_reverb_amount(stem_type: str, reverb_send: float, controls: dict) -> float:
    # Pre-fader send level into the shared reverb buses. Reverb intensity itself
    # is applied later via the reverb `amount`, so this must NOT also multiply by
    # the reverb control or the wet signal collapses to near silence.
    send = max(0.0, min(1.0, reverb_send / 100.0))
    vocal_amount = _control_ratio(controls, "vocalReverbAmount")
    type_factor = {
        "Lead Vocal": 0.70 + vocal_amount * 0.25,
        "Backing Vocal": 0.85 + vocal_amount * 0.15,
        "Drums": 0.45,
        "Kick": 0.05,
        "Snare": 0.50,
        "Bass": 0.05,
        "Electric Guitar": 0.55,
        "Acoustic Guitar": 0.60,
        "Keys/Piano": 0.60,
        "Pads/Strings": 0.85,
        "FX/Ambience": 0.95,
    }.get(stem_type, 0.45)
    return send * type_factor


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


@lru_cache(maxsize=16)
def _synth_reverb_ir(sample_rate: int, room_size_key: int, decay_key: int, damping_key: int, predelay_key: int) -> np.ndarray:
    """Synthesize a stereo reverb impulse response: sparse early reflections,
    then a dense decorrelated noise tail whose decay time falls with frequency
    (highs die faster, like real rooms). Convolving with this replaces the old
    parallel-comb tank, which rang metallically because combs concentrate
    energy at harmonically related delays. Deterministic RNG keeps renders
    reproducible; the cache key is the quantized parameter set."""
    room_size = room_size_key / 100.0
    decay = decay_key / 100.0
    damping_hz = float(damping_key)
    predelay_ms = predelay_key / 10.0
    rt60 = max(0.35, min(5.0, 0.5 + (decay - 0.70) * 8.0 + room_size * 0.6))
    tail_length = int(rt60 * 1.25 * sample_rate)
    predelay = max(0, int(sample_rate * predelay_ms / 1000.0))
    total = predelay + tail_length
    rng = np.random.default_rng(1701)
    ir = np.zeros((total, 2), dtype=np.float64)

    # Dense stochastic tail, decorrelated per channel, shaped per band so high
    # frequencies decay faster. Band split via complementary Butterworth filters
    # guarantees the bands sum back to the original noise.
    time_axis = np.arange(tail_length) / sample_rate
    band_edges = [220.0, 900.0, 2800.0, min(7500.0, sample_rate / 2 - 1500.0)]
    hf_damping = max(0.30, min(1.0, damping_hz / 9000.0))
    band_rt_factors = [1.18, 1.05, 0.9, 0.62 + hf_damping * 0.25, 0.32 + hf_damping * 0.38]
    for channel in range(2):
        noise = rng.standard_normal(tail_length)
        remaining = noise
        bands = []
        for edge in band_edges:
            sos = signal.butter(2, edge, btype="lowpass", fs=sample_rate, output="sos")
            low = signal.sosfilt(sos, remaining)
            bands.append(low)
            remaining = remaining - low
        bands.append(remaining)
        shaped = np.zeros(tail_length)
        for band, factor in zip(bands, band_rt_factors):
            band_rt = max(0.15, rt60 * factor)
            shaped += band * np.exp(-6.908 * time_axis / band_rt)
        # Slow fade-in over the first ~12 ms reads as diffusion building up.
        ramp = min(tail_length, max(8, int(sample_rate * 0.012)))
        shaped[:ramp] *= np.linspace(0.25, 1.0, ramp)
        ir[predelay:, channel] = shaped

    # Sparse early reflections before the tail: alternating pans, decaying level,
    # spacing stretched by room size.
    reflection_times_ms = np.array([7.1, 11.9, 17.3, 23.9, 31.7, 41.3, 53.9, 67.1]) * (0.6 + room_size * 0.8)
    for index, when_ms in enumerate(reflection_times_ms):
        position = predelay + int(sample_rate * when_ms / 1000.0)
        if position >= total:
            break
        level = 0.5 * (0.78 ** index)
        pan = 0.35 if index % 2 == 0 else -0.35
        ir[position, 0] += level * (1.0 - max(0.0, pan))
        ir[position, 1] += level * (1.0 + min(0.0, pan))

    energy = math.sqrt(float(np.sum(np.square(ir))) + 1e-12)
    return (ir / energy).astype(np.float32)


def _diffuse_reverb(audio: np.ndarray, sample_rate: int, room_size: float, decay: float, damping_hz: float, predelay_ms: float) -> np.ndarray:
    """Convolution reverb using a synthesized stereo IR. Returns a wet signal
    whose RMS is matched to the input so callers can treat the returned
    `amount` as a true wet gain."""
    if audio.size == 0:
        return np.zeros_like(audio)
    work = audio if audio.ndim == 2 else audio.reshape(-1, 1)
    length = work.shape[0]
    ir = _synth_reverb_ir(
        int(sample_rate),
        int(round(max(0.0, min(1.2, room_size)) * 100)),
        int(round(max(0.5, min(0.97, decay)) * 100)),
        int(round(max(1200.0, damping_hz) / 250.0) * 250),
        int(round(max(0.0, predelay_ms) * 10)),
    )
    reverbed = np.zeros((length, work.shape[1]), dtype=np.float32)
    for channel in range(work.shape[1]):
        ir_channel = ir[:, channel % ir.shape[1]]
        wet = signal.oaconvolve(work[:, channel].astype(np.float64, copy=False), ir_channel.astype(np.float64))
        reverbed[:, channel] = wet[:length].astype(np.float32)

    # Match the wet RMS to the input so `amount` behaves as a wet/dry gain
    # regardless of how quiet the send feeding it is.
    in_rms = float(np.sqrt(np.mean(np.square(work, dtype=np.float64)))) if work.size else 0.0
    wet_rms = float(np.sqrt(np.mean(np.square(reverbed, dtype=np.float64)))) if reverbed.size else 0.0
    if wet_rms > 1e-6 and in_rms > 1e-6:
        reverbed *= in_rms / wet_rms

    if audio.ndim == 1:
        return np.mean(reverbed, axis=1).astype(np.float32, copy=False)
    return reverbed.astype(np.float32, copy=False)


def _simple_reverb(audio: np.ndarray, sample_rate: int, amount: float, room_size: float) -> np.ndarray:
    amount = max(0.0, min(1.1, amount))
    if amount <= 0 or audio.size == 0:
        return np.zeros_like(audio)
    room_size = max(0.1, min(1.2, room_size))
    decay = 0.76 + min(1.0, room_size) * 0.16
    damping_hz = 8200.0 - min(3200.0, room_size * 2600.0)
    predelay_ms = 12.0 + room_size * 22.0
    wet = _diffuse_reverb(audio, sample_rate, room_size, decay, damping_hz, predelay_ms)
    return (wet * amount).astype(np.float32, copy=False)


def _estimate_tempo(audio: np.ndarray, sample_rate: int) -> float | None:
    """Estimate the song's tempo from onset strength. Result is normalized
    into the 70-180 BPM range (octave errors are the usual failure mode of
    tempo trackers, and delay note-values only care about the octave-folded
    value anyway). Returns None when the material is too short or ambiguous."""
    mono = np.mean(audio, axis=1) if audio.ndim == 2 else audio
    if mono.shape[0] < sample_rate * 5:
        return None
    max_samples = sample_rate * 90
    if mono.shape[0] > max_samples:
        start = (mono.shape[0] - max_samples) // 2
        mono = mono[start: start + max_samples]
    try:
        onset_env = librosa.onset.onset_strength(y=mono.astype(np.float32, copy=False), sr=sample_rate)
        try:
            from librosa.feature import rhythm as librosa_rhythm

            tempo_values = librosa_rhythm.tempo(onset_envelope=onset_env, sr=sample_rate)
        except (ImportError, AttributeError):
            tempo_values = librosa.beat.tempo(onset_envelope=onset_env, sr=sample_rate)
        bpm = float(np.atleast_1d(tempo_values)[0])
    except Exception:
        return None
    if not math.isfinite(bpm) or bpm <= 0:
        return None
    while bpm < 70.0:
        bpm *= 2.0
    while bpm > 180.0:
        bpm /= 2.0
    if not (40.0 <= bpm <= 220.0):
        return None
    return bpm


def _synced_delay_seconds(tempo_bpm: float | None, legacy_seconds: float) -> float:
    """Snap a delay time to the musical note value (1/16, 1/8, dotted 1/8 or
    1/4) closest to its legacy fixed default at the detected tempo, so echoes
    land in the groove instead of slightly fighting it. Without a tempo the
    legacy time is kept."""
    if not tempo_bpm:
        return legacy_seconds
    beat = 60.0 / tempo_bpm
    candidates = [beat / 4.0, beat / 2.0, beat * 0.75, beat]
    synced = min(candidates, key=lambda value: abs(value - legacy_seconds))
    return max(0.09, min(0.75, synced))


def _delay_effect(audio: np.ndarray, sample_rate: int, delay_seconds: float, feedback: float, amount: float) -> np.ndarray:
    """Feedback delay with progressive high-frequency damping: every repeat
    passes through a low-pass again, so echoes recede darker and darker like a
    tape delay instead of stacking bright verbatim copies over the vocal."""
    amount = max(0.0, min(0.5, amount))
    delay = max(1, int(sample_rate * delay_seconds))
    if amount <= 0 or delay >= audio.shape[0]:
        return np.zeros_like(audio)
    wet = np.zeros_like(audio)
    echo_source = audio
    level = 1.0
    gain = max(0.0, min(0.8, feedback))
    for tap in range(1, 7):
        offset = delay * tap
        if offset >= audio.shape[0]:
            break
        try:
            echo_source = _low_pass(echo_source, sample_rate, 5600.0)
        except Exception:
            pass
        if tap > 1:
            level *= gain
            if level < 0.02:
                break
        wet[offset:] += echo_source[:-offset] * level
    return (wet * amount).astype(np.float32, copy=False)


def _pingpong_delay(audio: np.ndarray, sample_rate: int, delay_seconds: float, feedback: float, amount: float, taps: int = 5, hp_hz: float = 320.0) -> np.ndarray:
    """Stereo ping-pong delay: successive echoes alternate hard left/right and
    decay by `feedback`. High-passed so it adds width and depth without
    muddying the low end. Returns a wet-only signal."""
    amount = max(0.0, min(0.6, amount))
    if amount <= 0 or audio.size == 0:
        return np.zeros_like(audio)
    work = audio if audio.ndim == 2 else audio.reshape(-1, 1)
    length = work.shape[0]
    mono = np.mean(work, axis=1)
    out = np.zeros((length, 2), dtype=np.float32)
    delay = max(1, int(sample_rate * delay_seconds))
    g = max(0.0, min(0.85, feedback))
    level = 1.0
    for tap in range(1, taps + 1):
        offset = delay * tap
        if offset >= length:
            break
        level *= g
        channel = (tap - 1) % 2
        out[offset:, channel] += mono[: length - offset] * level
    try:
        out = _high_pass(out, sample_rate, hp_hz)
    except Exception:
        pass
    result = np.clip(out * amount, -0.7, 0.7).astype(np.float32, copy=False)
    if audio.ndim == 2 and audio.shape[1] == 2:
        return result
    if audio.ndim == 2:  # single-channel 2D input
        return result[:, :1]
    return np.mean(result, axis=1).astype(np.float32, copy=False)


def _apply_vocal_ducking(audio: np.ndarray, vocal_bus: np.ndarray, sample_rate: int, amount_db: float) -> np.ndarray:
    if audio.size == 0 or vocal_bus.size == 0 or amount_db <= 0:
        return audio
    length = min(audio.shape[0], vocal_bus.shape[0])
    if length <= 0:
        return audio
    vocal_mono = np.mean(np.abs(vocal_bus[:length]), axis=1).astype(np.float32, copy=False)
    frame_size = max(256, int(sample_rate * 0.035))
    if vocal_mono.shape[0] < frame_size:
        return audio
    block = max(8, int(sample_rate * 0.001))
    blocks = _control_blocks(vocal_mono, block)
    control_rate = sample_rate / block
    # Fast attack so the duck lands before the vocal phrase, slow release so
    # the backing swells back instead of pumping.
    envelope = _asym_envelope(blocks, control_rate, attack_seconds=0.012, release_seconds=0.30)
    threshold = max(float(np.percentile(envelope, 65)), _db_to_linear(-38))
    if threshold <= 1e-8:
        return audio
    activity = np.clip((envelope - threshold) / (threshold * 3.0), 0.0, 1.0)
    gain_blocks = np.power(10.0, (-amount_db * activity) / 20.0).astype(np.float32)
    gain = _expand_control_gain(gain_blocks, block, length)
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
    """Inter-sample (true) peak via 4x oversampling. Long files are processed
    in overlapping chunks so full-length songs get a real measurement instead
    of silently falling back to the sample peak."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    try:
        work = audio if audio.ndim == 2 else audio.reshape(-1, 1)
        chunk = 2_000_000
        overlap = 256
        true_peak = peak
        for start in range(0, work.shape[0], chunk):
            stop = min(work.shape[0], start + chunk)
            block = work[max(0, start - overlap): min(work.shape[0], stop + overlap)]
            oversampled = signal.resample_poly(block, up=4, down=1, axis=0)
            true_peak = max(true_peak, float(np.max(np.abs(oversampled))))
        return true_peak
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
    """Equal-power pan law (unity at center). The old single-channel
    attenuation made panned stems drop up to 3 dB of acoustic power, so wide
    mixes collapsed toward whatever sat in the middle."""
    pan_norm = max(-1.0, min(1.0, pan / 100.0))
    if abs(pan_norm) < 1e-3:
        return audio.copy()
    theta = (pan_norm + 1.0) * (math.pi / 4.0)
    left_gain = math.cos(theta) * math.sqrt(2.0)
    right_gain = math.sin(theta) * math.sqrt(2.0)
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
