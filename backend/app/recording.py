from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import sounddevice as sd
import soundfile as sf
from fastapi import HTTPException

from .logging_utils import append_project_log, utc_now_iso
from .models import AudioInputDevice, DirectRecordingStatus, StartDirectRecordingRequest, StopDirectRecordingResponse
from .storage import ensure_project_dirs, get_project, project_subdirs, register_recorded_stems


@dataclass
class RecordingSession:
    id: str
    project_id: str
    device_id: int
    device_name: str
    host_api: str
    sample_rate: int
    channel_count: int
    split_to_mono: bool
    base_name: str
    started_at: str
    multitrack_path: Path
    multitrack_url: str
    queue_items: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=256))
    frames_captured: int = 0
    status: str = "Recording"
    error: str | None = None
    stream: sd.InputStream | None = None
    writer_thread: threading.Thread | None = None
    writer_closed: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> DirectRecordingStatus:
        with self.lock:
            frames_captured = self.frames_captured
            error = self.error
            status = "Failed" if error else self.status
        duration_seconds = frames_captured / float(self.sample_rate) if self.sample_rate else 0
        return DirectRecordingStatus(
            projectId=self.project_id,
            active=status == "Recording",
            status=status,
            sessionId=self.id,
            deviceId=self.device_id,
            deviceName=self.device_name,
            hostApi=self.host_api,
            channelCount=self.channel_count,
            sampleRate=self.sample_rate,
            splitToMono=self.split_to_mono,
            startedAt=self.started_at,
            durationSeconds=round(duration_seconds, 2),
            framesCaptured=frames_captured,
            multitrackFilePath=_display_path(self.multitrack_path),
            multitrackFileUrl=_media_url(_display_path(self.multitrack_path)),
            error=error,
        )


class DirectRecordingManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_session: RecordingSession | None = None

    def list_devices(self) -> list[AudioInputDevice]:
        try:
            devices = sd.query_devices()
            host_apis = sd.query_hostapis()
            default_input = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not query local audio devices: {exc}") from exc

        mapped: list[AudioInputDevice] = []
        for index, device in enumerate(devices):
            max_input_channels = int(device.get("max_input_channels", 0))
            if max_input_channels <= 0:
                continue
            name = str(device.get("name", f"Input {index}")).strip()
            host_api_index = int(device.get("hostapi", -1))
            host_api_name = host_apis[host_api_index]["name"] if 0 <= host_api_index < len(host_apis) else "Unknown"
            mapped.append(
                AudioInputDevice(
                    id=index,
                    name=name,
                    hostApi=host_api_name,
                    maxInputChannels=max_input_channels,
                    defaultSampleRate=int(round(float(device.get("default_samplerate", 44100)))),
                    isDefault=index == default_input,
                    isZoomDevice="zoom" in name.lower() or "h8" in name.lower(),
                )
            )

        mapped.sort(key=lambda item: (not item.isZoomDevice, not item.isDefault, -item.maxInputChannels, item.name.lower()))
        return mapped

    def get_status(self, project_id: str) -> DirectRecordingStatus:
        get_project(project_id)
        with self._lock:
            session = self._active_session
            if session and session.project_id == project_id:
                return session.snapshot()
        return DirectRecordingStatus(projectId=project_id)

    def start(self, project_id: str, payload: StartDirectRecordingRequest) -> DirectRecordingStatus:
        get_project(project_id)
        device = next((item for item in self.list_devices() if item.id == payload.deviceId), None)
        if device is None:
            raise HTTPException(status_code=404, detail="Audio input device not found.")

        requested_channels = payload.channelCount or device.maxInputChannels
        if requested_channels > device.maxInputChannels:
            raise HTTPException(status_code=400, detail=f"Selected device only exposes {device.maxInputChannels} input channels.")

        sample_rate = int(payload.sampleRate or device.defaultSampleRate or 48000)
        base_name = _safe_base_name(payload.baseName)
        dirs = ensure_project_dirs(project_id)
        multitrack_path = _unique_recording_path(dirs["original"], f"{base_name}_multitrack", ".wav")
        session = RecordingSession(
            id=uuid.uuid4().hex,
            project_id=project_id,
            device_id=device.id,
            device_name=device.name,
            host_api=device.hostApi,
            sample_rate=sample_rate,
            channel_count=requested_channels,
            split_to_mono=payload.splitToMono,
            base_name=base_name,
            started_at=utc_now_iso(),
            multitrack_path=multitrack_path,
            multitrack_url=_media_url(_display_path(multitrack_path)),
        )

        with self._lock:
            if self._active_session and self._active_session.status == "Recording":
                raise HTTPException(status_code=409, detail="Another direct recording session is already active.")
            self._active_session = session

        try:
            writer = sf.SoundFile(str(multitrack_path), mode="w", samplerate=sample_rate, channels=requested_channels, subtype="PCM_24", format="WAV")
        except Exception as exc:
            with self._lock:
                self._active_session = None
            raise HTTPException(status_code=500, detail=f"Could not create the multitrack recording file: {exc}") from exc

        def writer_loop() -> None:
            try:
                while True:
                    chunk = session.queue_items.get()
                    if chunk is None:
                        break
                    writer.write(chunk)
            except Exception as exc:
                with session.lock:
                    session.error = str(exc) or "Could not write audio data to disk."
                    session.status = "Failed"
            finally:
                writer.close()
                session.writer_closed.set()

        def audio_callback(indata, frames, callback_time, status) -> None:  # noqa: ANN001
            del callback_time
            if status:
                with session.lock:
                    session.error = str(status)
                    session.status = "Failed"
                raise sd.CallbackAbort
            try:
                session.queue_items.put_nowait(indata.copy())
            except queue.Full:
                with session.lock:
                    session.error = "Recording buffer overflow. Lower the channel count or close other audio apps and try again."
                    session.status = "Failed"
                raise sd.CallbackAbort
            with session.lock:
                session.frames_captured += frames

        try:
            session.writer_thread = threading.Thread(target=writer_loop, name=f"direct-recording-writer-{session.id}", daemon=True)
            session.writer_thread.start()
            session.stream = sd.InputStream(
                device=device.id,
                samplerate=sample_rate,
                channels=requested_channels,
                dtype="float32",
                callback=audio_callback,
                blocksize=0,
                latency="high",
            )
            session.stream.start()
        except Exception as exc:
            self._finalize_failed_start(session, writer, exc)
            raise HTTPException(status_code=500, detail=f"Could not start recording from '{device.name}': {exc}") from exc

        append_project_log(project_subdirs(project_id)["logs"], f"Started direct multitrack recording from {device.name} at {sample_rate} Hz with {requested_channels} channels.")
        return session.snapshot()

    def stop(self, project_id: str) -> StopDirectRecordingResponse:
        get_project(project_id)
        with self._lock:
            session = self._active_session
            if session is None or session.project_id != project_id:
                raise HTTPException(status_code=404, detail="No active direct recording session was found for this project.")
            self._active_session = None

        errors: list[str] = []
        try:
            if session.stream is not None:
                try:
                    session.stream.stop()
                finally:
                    session.stream.close()
        except Exception as exc:
            errors.append(str(exc))

        session.queue_items.put(None)
        if session.writer_thread is not None:
            session.writer_thread.join(timeout=15)
        session.writer_closed.wait(timeout=15)

        with session.lock:
            session.status = "Completed" if not session.error else "Failed"

        if session.error:
            errors.append(session.error)

        if not session.multitrack_path.exists():
            errors.append("The multitrack recording file was not created.")

        uploaded = []
        if not errors:
            try:
                split_paths = self._split_recording(session)
                uploaded = register_recorded_stems(project_id, split_paths)
                append_project_log(
                    project_subdirs(project_id)["logs"],
                    f"Completed direct multitrack recording from {session.device_name}. Added {len(uploaded)} stem files from {session.channel_count} recorded channels.",
                )
            except Exception as exc:
                errors.append(str(exc))

        if errors:
            append_project_log(project_subdirs(project_id)["logs"], f"Direct multitrack recording ended with errors: {' | '.join(errors)}")

        status = session.snapshot()
        status.active = False
        status.status = "Completed" if not errors else "Failed"
        status.error = " | ".join(errors) if errors else None
        return StopDirectRecordingResponse(recording=status, uploaded=uploaded, errors=errors)

    def _split_recording(self, session: RecordingSession) -> list[Path]:
        if not session.split_to_mono:
            return [session.multitrack_path]

        output_paths = [_unique_recording_path(session.multitrack_path.parent, f"{session.base_name}_ch{index + 1:02d}", ".wav") for index in range(session.channel_count)]
        outputs = [sf.SoundFile(str(path), mode="w", samplerate=session.sample_rate, channels=1, subtype="PCM_24", format="WAV") for path in output_paths]
        try:
            with sf.SoundFile(str(session.multitrack_path), mode="r") as source:
                while True:
                    block = source.read(frames=65536, dtype="float32", always_2d=True)
                    if not len(block):
                        break
                    for channel_index, output in enumerate(outputs):
                        output.write(block[:, channel_index : channel_index + 1])
        finally:
            for output in outputs:
                output.close()
        return output_paths

    def _finalize_failed_start(self, session: RecordingSession, writer: sf.SoundFile, error: Exception) -> None:
        try:
            writer.close()
        except Exception:
            pass
        try:
            if session.multitrack_path.exists():
                session.multitrack_path.unlink()
        except OSError:
            pass
        with self._lock:
            self._active_session = None
        if session.writer_thread and session.writer_thread.is_alive():
            session.queue_items.put(None)
            session.writer_thread.join(timeout=5)
        append_project_log(project_subdirs(session.project_id)["logs"], f"Direct multitrack recording failed to start: {error}")


def _display_path(path: Path) -> str:
    parts = list(path.parts)
    try:
        storage_index = parts.index("storage")
        return "/".join(parts[storage_index:])
    except ValueError:
        return str(path).replace("\\", "/")


def _media_url(path_value: str) -> str:
    normalized = path_value.replace("\\", "/")
    if normalized.startswith("storage/"):
        normalized = normalized[len("storage/") :]
    return f"/media/{normalized}"


def _safe_base_name(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    sanitized = "".join(character if character.isalnum() else "-" for character in candidate)
    sanitized = "-".join(part for part in sanitized.split("-") if part)
    if sanitized:
        return sanitized[:48]
    return datetime.now(timezone.utc).strftime("take-%Y%m%d-%H%M%S")


def _unique_recording_path(directory: Path, base_name: str, extension: str) -> Path:
    candidate = directory / f"{base_name}{extension}"
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        numbered = directory / f"{base_name}_{index:02d}{extension}"
        if not numbered.exists():
            return numbered
    return directory / f"{base_name}_{uuid.uuid4().hex[:8]}{extension}"


recording_manager = DirectRecordingManager()
