import { AudioLines, Mic, RefreshCw, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { getDirectRecordingStatus, listAudioInputDevices, startDirectRecording, stopDirectRecording } from "../api.js";
import Button from "./Button.jsx";

const SAMPLE_RATE_OPTIONS = [44100, 48000, 96000];

export default function DirectMultitrackRecorder({ projectId, onRecorded, className = "" }) {
  const [devices, setDevices] = useState([]);
  const [loadingDevices, setLoadingDevices] = useState(true);
  const [devicesError, setDevicesError] = useState("");
  const [session, setSession] = useState(null);
  const [sessionError, setSessionError] = useState("");
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [channelCount, setChannelCount] = useState("2");
  const [sampleRate, setSampleRate] = useState("48000");
  const [splitToMono, setSplitToMono] = useState(true);
  const [baseName, setBaseName] = useState("");
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);

  const activeSession = session?.active ? session : null;
  const selectedDevice = useMemo(() => devices.find((device) => String(device.id) === String(selectedDeviceId)) || null, [devices, selectedDeviceId]);

  const refreshDevices = async () => {
    setLoadingDevices(true);
    setDevicesError("");
    try {
      const response = await listAudioInputDevices();
      const nextDevices = response.devices || [];
      setDevices(nextDevices);
      setSelectedDeviceId((current) => {
        if (current && nextDevices.some((device) => String(device.id) === String(current))) {
          return current;
        }
        return nextDevices[0] ? String(nextDevices[0].id) : "";
      });
    } catch (error) {
      setDevicesError(error.message);
    } finally {
      setLoadingDevices(false);
    }
  };

  const refreshSession = async () => {
    try {
      const status = await getDirectRecordingStatus(projectId);
      setSession(status);
    } catch (error) {
      setSessionError(error.message);
    }
  };

  useEffect(() => {
    refreshDevices();
    refreshSession();
  }, [projectId]);

  useEffect(() => {
    if (!selectedDevice) {
      return;
    }
    setChannelCount(String(selectedDevice.maxInputChannels || 2));
    setSampleRate(String(selectedDevice.defaultSampleRate || 48000));
  }, [selectedDevice?.id]);

  useEffect(() => {
    if (!activeSession) {
      return undefined;
    }
    const intervalId = window.setInterval(() => {
      refreshSession();
    }, 1000);
    return () => window.clearInterval(intervalId);
  }, [activeSession, projectId]);

  const handleStart = async () => {
    if (!selectedDevice) return;
    setStarting(true);
    setSessionError("");
    try {
      const status = await startDirectRecording(projectId, {
        deviceId: Number(selectedDevice.id),
        channelCount: Number(channelCount),
        sampleRate: Number(sampleRate),
        splitToMono,
        baseName: baseName.trim() || undefined,
      });
      setSession(status);
    } catch (error) {
      setSessionError(error.message);
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    setStopping(true);
    setSessionError("");
    try {
      const response = await stopDirectRecording(projectId);
      setSession(response.recording);
      if (response.errors?.length) {
        setSessionError(response.errors.join(" | "));
      }
      await onRecorded?.(response);
      await refreshDevices();
    } catch (error) {
      setSessionError(error.message);
    } finally {
      setStopping(false);
    }
  };

  return (
    <section className={`rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.07] via-white/[0.04] to-black/30 p-5 shadow-[0_22px_70px_rgba(0,0,0,0.2)] ${className}`}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-2xl">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Direct Multitrack Recorder</p>
          <h2 className="mt-2 text-2xl font-semibold text-white">Capture the Zoom H8 directly into this project</h2>
          <p className="mt-2 text-sm leading-6 text-zinc-400">
            This uses the local backend and the machine&apos;s native audio drivers, not browser microphone capture.
            When the H8 appears as a multichannel input, the app records one multitrack take and then splits it into one WAV stem per channel.
          </p>
        </div>
        <Button type="button" variant="secondary" onClick={refreshDevices} disabled={loadingDevices || starting || stopping || Boolean(activeSession)}>
          <RefreshCw size={17} className={loadingDevices ? "animate-spin" : ""} />
          Refresh devices
        </Button>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_160px_160px]">
        <label className="block">
          <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Audio Device</span>
          <select
            value={selectedDeviceId}
            onChange={(event) => setSelectedDeviceId(event.target.value)}
            disabled={loadingDevices || !devices.length || Boolean(activeSession)}
            className="h-11 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50"
          >
            {devices.length ? (
              devices.map((device) => (
                <option key={device.id} value={device.id}>
                  {formatDeviceLabel(device)}
                </option>
              ))
            ) : (
              <option value="">No input devices found</option>
            )}
          </select>
        </label>

        <label className="block">
          <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Channels</span>
          <input
            type="number"
            min="1"
            max={selectedDevice?.maxInputChannels || 64}
            value={channelCount}
            onChange={(event) => setChannelCount(event.target.value)}
            disabled={!selectedDevice || Boolean(activeSession)}
            className="h-11 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50"
          />
        </label>

        <label className="block">
          <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Sample Rate</span>
          <select
            value={sampleRate}
            onChange={(event) => setSampleRate(event.target.value)}
            disabled={!selectedDevice || Boolean(activeSession)}
            className="h-11 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50"
          >
            {buildSampleRateOptions(selectedDevice?.defaultSampleRate).map((rate) => (
              <option key={rate} value={rate}>
                {Number(rate).toLocaleString()} Hz
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto_auto] lg:items-end">
        <label className="block">
          <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Take Name</span>
          <input
            type="text"
            value={baseName}
            onChange={(event) => setBaseName(event.target.value)}
            placeholder="leave blank for timestamped take"
            disabled={Boolean(activeSession)}
            className="h-11 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white placeholder:text-zinc-500 disabled:opacity-50"
          />
        </label>
        <label className="flex items-center gap-3 rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-200">
          <input type="checkbox" checked={splitToMono} onChange={(event) => setSplitToMono(event.target.checked)} disabled={Boolean(activeSession)} className="h-4 w-4 accent-teal-300" />
          Split channels into stems
        </label>
        <div className="flex gap-2">
          <Button type="button" onClick={handleStart} disabled={!selectedDevice || starting || stopping || Boolean(activeSession)}>
            <Mic size={17} />
            {starting ? "Starting..." : "Start"}
          </Button>
          <Button type="button" variant="secondary" onClick={handleStop} disabled={!activeSession || stopping}>
            <Square size={17} />
            {stopping ? "Stopping..." : "Stop"}
          </Button>
        </div>
      </div>

      {selectedDevice ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Badge tone={selectedDevice.isZoomDevice ? "teal" : "neutral"}>{selectedDevice.name}</Badge>
          <Badge tone="neutral">{selectedDevice.hostApi}</Badge>
          <Badge tone="neutral">{selectedDevice.maxInputChannels} input channels available</Badge>
          <Badge tone="neutral">Default {Number(selectedDevice.defaultSampleRate).toLocaleString()} Hz</Badge>
        </div>
      ) : null}

      {activeSession ? (
        <div className="mt-4 rounded-lg border border-rose-300/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
          <div className="flex items-center gap-2 font-semibold">
            <AudioLines size={16} />
            Recording from {activeSession.deviceName}
          </div>
          <p className="mt-2">
            {formatDuration(activeSession.durationSeconds)} captured at {Number(activeSession.sampleRate).toLocaleString()} Hz across {activeSession.channelCount} channels.
          </p>
        </div>
      ) : session?.status === "Completed" ? (
        <div className="mt-4 rounded-lg border border-teal-300/20 bg-teal-300/10 px-4 py-3 text-sm text-teal-100">
          Last direct recording finished and the take archive was saved at <span className="font-semibold">{session.multitrackFilePath}</span>.
        </div>
      ) : null}

      {devicesError ? <div className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm text-amber-100">{devicesError}</div> : null}
      {sessionError ? <div className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm text-amber-100">{sessionError}</div> : null}
      {!loadingDevices && !devices.length && !devicesError ? (
        <div className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm text-amber-100">
          No audio inputs were detected. Connect the Zoom H8 in Audio Interface mode, confirm the Windows driver is installed, and refresh the device list.
        </div>
      ) : null}
    </section>
  );
}

function formatDeviceLabel(device) {
  const flags = [];
  if (device.isZoomDevice) flags.push("Zoom");
  if (device.isDefault) flags.push("Default");
  const suffix = flags.length ? ` (${flags.join(", ")})` : "";
  return `${device.name} - ${device.hostApi} - ${device.maxInputChannels}ch${suffix}`;
}

function buildSampleRateOptions(defaultRate) {
  const values = new Set(SAMPLE_RATE_OPTIONS);
  if (defaultRate) {
    values.add(defaultRate);
  }
  return Array.from(values).sort((left, right) => left - right);
}

function formatDuration(seconds) {
  const totalSeconds = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const remainingSeconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainingSeconds}`;
}

function Badge({ children, tone }) {
  const tones = {
    neutral: "border-white/10 bg-black/20 text-zinc-300",
    teal: "border-teal-300/20 bg-teal-300/10 text-teal-100",
  };
  return <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${tones[tone]}`}>{children}</span>;
}
