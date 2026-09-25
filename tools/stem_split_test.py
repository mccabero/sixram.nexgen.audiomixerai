"""
stem_split_test.py - one-off quality/speed benchmark for the Stem Splitter module.

This is NOT part of the app. It is a throwaway script to answer one question:
how good, and how slow, is htdemucs_6s on THIS machine?

Note: downloading audio from YouTube is against YouTube's Terms of Service.
Run this on material you have the right to use.

Setup (Windows PowerShell, from the repo root):

    backend\\.venv\\Scripts\\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    backend\\.venv\\Scripts\\python.exe -m pip install demucs
    backend\\.venv\\Scripts\\python.exe tools\\stem_split_test.py --url "https://www.youtube.com/watch?v=qmOLtTGvsbM"

Optional: benchmark a 45-second excerpt first so you get an answer in ~3 minutes
instead of ~20:

    ... stem_split_test.py --url "<url>" --start 60 --duration 45
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "_stem_test"
MODEL = "htdemucs_6s"


def log(msg: str) -> None:
    print(f"[stem-test] {msg}", flush=True)


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg not found. Install it or `pip install imageio-ffmpeg`.")


def download(url: str, dest_dir: Path) -> Path:
    try:
        import yt_dlp
    except ImportError:
        sys.exit("yt-dlp missing. Run: pip install yt-dlp")

    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "restrictfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # Same client list phase6.py already uses, so behaviour matches the app.
        "extractor_args": {
            "youtube": {"player_client": ["tv", "ios", "web_safari", "android", "web"]},
        },
    }

    log("downloading audio...")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    title = (info or {}).get("title", "unknown")
    log(f"got: {title}")

    files = [p for p in dest_dir.iterdir() if p.is_file() and p.stem == "source"]
    if not files:
        sys.exit("nothing downloaded")
    return files[0]


def to_wav(src: Path, dest: Path, start: float | None, duration: float | None) -> Path:
    cmd = [ffmpeg_exe(), "-y"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(src)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(dest)]

    log("converting to 44.1 kHz WAV...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not dest.exists():
        tail = "\n".join((result.stderr or "").strip().splitlines()[-5:])
        sys.exit(f"ffmpeg failed:\n{tail}")
    return dest


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def separate(wav: Path, out_dir: Path, jobs: int, segment: int | None) -> float:
    cmd = [
        sys.executable, "-m", "demucs",
        "-n", MODEL,
        "-d", "cpu",
        "-j", str(jobs),
        "-o", str(out_dir),
    ]
    if segment:
        cmd += ["--segment", str(segment)]
    cmd += [str(wav)]

    log(f"separating with {MODEL} on CPU ({jobs} workers) - this is the slow part")
    started = time.time()
    result = subprocess.run(cmd)
    elapsed = time.time() - started
    if result.returncode != 0:
        sys.exit("demucs failed - see output above")
    return elapsed


def report(stem_dir: Path, audio_seconds: float, elapsed: float) -> None:
    import math

    log("")
    log("=" * 58)
    log(f"audio length     : {audio_seconds:6.1f} s")
    log(f"separation time  : {elapsed:6.1f} s")
    log(f"realtime factor  : {elapsed / max(audio_seconds, 0.001):6.2f}x")
    projected = (elapsed / max(audio_seconds, 0.001)) * 270
    log(f"projected 4:30 song: {projected / 60:.1f} min")
    log("=" * 58)

    stems = sorted(stem_dir.glob("*.wav"))
    if not stems:
        log("no stems found?")
        return

    log("")
    log(f"{'stem':<10} {'size':>9}  {'RMS dBFS':>9}  {'peak dBFS':>9}")
    for stem in stems:
        with wave.open(str(stem), "rb") as handle:
            frames = handle.readframes(handle.getnframes())
        import array

        samples = array.array("h")
        samples.frombytes(frames)
        if not samples:
            continue
        total = 0.0
        peak = 0
        for value in samples:
            total += float(value) * value
            magnitude = abs(value)
            if magnitude > peak:
                peak = magnitude
        rms = math.sqrt(total / len(samples))
        rms_db = 20 * math.log10(rms / 32768.0) if rms > 0 else -999
        peak_db = 20 * math.log10(peak / 32768.0) if peak > 0 else -999
        size_mb = stem.stat().st_size / 1_048_576
        log(f"{stem.stem:<10} {size_mb:8.1f}M  {rms_db:9.1f}  {peak_db:9.1f}")

    log("")
    log(f"stems are in: {stem_dir}")
    log("listen to piano.wav and guitar.wav first - that is where the bleed lives.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark htdemucs_6s on this machine.")
    parser.add_argument("--url", required=True, help="source URL")
    parser.add_argument("--start", type=float, default=None, help="excerpt start, seconds")
    parser.add_argument("--duration", type=float, default=None, help="excerpt length, seconds")
    parser.add_argument("--jobs", type=int, default=2, help="demucs worker processes")
    parser.add_argument("--segment", type=int, default=None, help="segment length, lower = less RAM")
    args = parser.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)
    source = download(args.url, WORK)
    wav = to_wav(source, WORK / "input.wav", args.start, args.duration)
    seconds = wav_seconds(wav)

    out_dir = WORK / "separated"
    elapsed = separate(wav, out_dir, args.jobs, args.segment)
    report(out_dir / MODEL / wav.stem, seconds, elapsed)


if __name__ == "__main__":
    main()
