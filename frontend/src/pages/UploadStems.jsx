import { ArrowLeft, BarChart3, CheckCircle2, FileAudio, Mic, RefreshCw, Square, UploadCloud, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getProject, updateStemType, uploadStems } from "../api.js";
import Button from "../components/Button.jsx";
import DirectMultitrackRecorder from "../components/DirectMultitrackRecorder.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StemList from "../components/StemList.jsx";
import { MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, SUPPORTED_EXTENSIONS } from "../constants.js";
import { formatBytes } from "../utils/format.js";

export default function UploadStems() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const recorderRef = useRef(null);
  const recordingChunksRef = useRef([]);
  const recordingStreamRef = useRef(null);
  const recordingTimerRef = useRef(null);
  const recordingStartedAtRef = useRef(0);
  const [project, setProject] = useState(null);
  const [loadingProject, setLoadingProject] = useState(true);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [inputMode, setInputMode] = useState("upload");
  const [errors, setErrors] = useState([]);
  const [uploadErrors, setUploadErrors] = useState([]);
  const [progress, setProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [busyStemId, setBusyStemId] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [recordingSupported, setRecordingSupported] = useState(() => supportsInterfaceRecording());
  const [recordingError, setRecordingError] = useState("");
  const [loadingInputs, setLoadingInputs] = useState(false);
  const [audioInputs, setAudioInputs] = useState([]);
  const [selectedInputId, setSelectedInputId] = useState("");
  const [recording, setRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [showBrowserFallback, setShowBrowserFallback] = useState(false);

  const loadProject = useCallback(() => {
    setLoadingProject(true);
    return getProject(projectId)
      .then(setProject)
      .catch((err) => setErrors([err.message]))
      .finally(() => setLoadingProject(false));
  }, [projectId]);

  useEffect(() => {
    loadProject();
  }, [loadProject]);

  const addFiles = useCallback((files) => {
    const nextFiles = [];
    const nextErrors = [];

    Array.from(files).forEach((file) => {
      const extension = getExtension(file.name);
      if (!SUPPORTED_EXTENSIONS.includes(extension)) {
        nextErrors.push(`${file.name}: unsupported format.`);
        return;
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        nextErrors.push(`${file.name}: exceeds ${MAX_UPLOAD_MB} MB.`);
        return;
      }
      if (file.size === 0) {
        nextErrors.push(`${file.name}: file is empty.`);
        return;
      }
      nextFiles.push(file);
    });

    setErrors(nextErrors);
    setUploadErrors([]);
    setSelectedFiles((current) => mergeFiles(current, nextFiles));
  }, []);

  const releaseRecordingResources = useCallback(() => {
    if (recordingTimerRef.current) {
      window.clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
    recordingStartedAtRef.current = 0;
    if (recordingStreamRef.current) {
      recordingStreamRef.current.getTracks().forEach((track) => track.stop());
      recordingStreamRef.current = null;
    }
    recorderRef.current = null;
    recordingChunksRef.current = [];
  }, []);

  const loadAudioInputs = useCallback(async (requestPermission = true) => {
    if (!supportsInterfaceRecording()) {
      setRecordingSupported(false);
      setRecordingError("Browser audio capture is not available here. You can still upload files recorded on the Zoom H8 SD card.");
      return { inputs: [], selectedInputId: "" };
    }

    setLoadingInputs(true);
    setRecordingError("");

    let permissionStream = null;
    try {
      if (requestPermission) {
        permissionStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
          },
        });
      }

      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices.filter((device) => device.kind === "audioinput");
      setAudioInputs(inputs);
      const nextSelectedInputId = selectedInputId && inputs.some((device) => device.deviceId === selectedInputId) ? selectedInputId : choosePreferredInputId(inputs);
      setSelectedInputId(nextSelectedInputId);

      if (!inputs.length) {
        setRecordingError("No audio inputs were found. Put the Zoom H8 into Audio Interface mode, reconnect it, and try again.");
      }
      return { inputs, selectedInputId: nextSelectedInputId };
    } catch (error) {
      setRecordingError(error?.message || "Could not access audio input devices.");
      return { inputs: [], selectedInputId: "" };
    } finally {
      permissionStream?.getTracks().forEach((track) => track.stop());
      setLoadingInputs(false);
    }
  }, [selectedInputId]);

  useEffect(() => {
    if (!recordingSupported || !navigator.mediaDevices?.addEventListener) {
      return undefined;
    }

    const handleDeviceChange = () => {
      if (audioInputs.length || selectedInputId) {
        loadAudioInputs(false);
      }
    };

    navigator.mediaDevices.addEventListener("devicechange", handleDeviceChange);
    return () => navigator.mediaDevices.removeEventListener("devicechange", handleDeviceChange);
  }, [audioInputs.length, loadAudioInputs, recordingSupported, selectedInputId]);

  useEffect(() => {
    return () => {
      releaseRecordingResources();
    };
  }, [releaseRecordingResources]);

  const handleDrop = (event) => {
    event.preventDefault();
    setDragActive(false);
    addFiles(event.dataTransfer.files);
  };

  const handlePickerChange = (event) => {
    addFiles(event.target.files);
    event.target.value = "";
  };

  const handleStartRecording = async () => {
    if (recording || loadingInputs) return;

    let availableInputs = audioInputs;
    let activeInputId = selectedInputId;
    if (!audioInputs.length) {
      const refreshed = await loadAudioInputs(true);
      availableInputs = refreshed?.inputs || [];
      activeInputId = refreshed?.selectedInputId || "";
    }

    if (!availableInputs.length) {
      setRecordingError("No audio inputs are ready yet. Enable audio inputs and confirm the Zoom H8 is connected.");
      return;
    }

    const mimeType = getSupportedRecordingMimeType();
    if (!mimeType) {
      setRecordingError("This browser can list audio devices but cannot record them as WebM audio yet.");
      return;
    }

    try {
      setRecordingError("");
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId: activeInputId ? { exact: activeInputId } : undefined,
          channelCount: 2,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });

      const recorder = new MediaRecorder(stream, { mimeType });
      recorderRef.current = recorder;
      recordingStreamRef.current = stream;
      recordingChunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          recordingChunksRef.current.push(event.data);
        }
      };

      recorder.onerror = (event) => {
        setRecordingError(event.error?.message || "Recording failed.");
        setRecording(false);
        setRecordingSeconds(0);
        releaseRecordingResources();
      };

      recorder.onstop = () => {
        const blob = new Blob(recordingChunksRef.current, { type: recorder.mimeType || mimeType || "audio/webm" });
        const filename = buildRecordingFilename(availableInputs.find((device) => device.deviceId === activeInputId)?.label);
        setRecording(false);
        setRecordingSeconds(0);
        if (blob.size > 0) {
          addFiles([new File([blob], filename, { type: blob.type || "audio/webm", lastModified: Date.now() })]);
        } else {
          setRecordingError("Recorded audio was empty.");
        }
        releaseRecordingResources();
      };

      recordingStartedAtRef.current = Date.now();
      setRecordingSeconds(0);
      recordingTimerRef.current = window.setInterval(() => {
        setRecordingSeconds(Math.max(0, Math.floor((Date.now() - recordingStartedAtRef.current) / 1000)));
      }, 250);
      recorder.start(250);
      setRecording(true);
    } catch (error) {
      setRecordingError(error?.message || "Could not start recording from the selected audio input.");
      setRecording(false);
      setRecordingSeconds(0);
      releaseRecordingResources();
    }
  };

  const handleStopRecording = () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    recorder.stop();
  };

  const handleUpload = async () => {
    if (!selectedFiles.length) return;
    setUploading(true);
    setProgress(0);
    setUploadErrors([]);
    setErrors([]);

    try {
      const result = await uploadStems(projectId, selectedFiles, setProgress);
      if (result.errors?.length) {
        setUploadErrors(result.errors);
      }
      if (result.uploaded?.length) {
        navigate(`/projects/${projectId}`);
      }
    } catch (err) {
      setErrors([err.message]);
    } finally {
      setUploading(false);
    }
  };

  const handleChangeType = async (stemId, stemType) => {
    setBusyStemId(stemId);
    setActionMessage("Saving stem type change.");
    setErrors([]);
    try {
      const updated = await updateStemType(projectId, stemId, stemType);
      setProject((current) => ({
        ...current,
        stems: current.stems.map((stem) => (stem.id === stemId ? updated : stem)),
      }));
    } catch (err) {
      setErrors([err.message]);
    } finally {
      setBusyStemId("");
      setActionMessage("");
    }
  };

  const handleDirectRecordingComplete = async () => {
    await loadProject();
  };

  const uploadedCount = project?.stems?.length || 0;
  const queuedTotalBytes = selectedFiles.reduce((total, file) => total + file.size, 0);

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>

      <section className="mt-5 rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.075] via-white/[0.04] to-teal-300/[0.04] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.24)]">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Step 1</p>
            <h1 className="mt-2 text-3xl font-semibold text-white">Add audio stems</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
              Upload the separate tracks for {project?.songTitle || project?.name || "this project"}. Keep this step simple: add files first, then analyze them in Step 2.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3 xl:min-w-[420px]">
            <StepSummary label="Uploaded" value={uploadedCount} />
            <StepSummary label="Queued" value={selectedFiles.length} />
            <StepSummary label="Size" value={selectedFiles.length ? formatBytes(queuedTotalBytes) : "--"} />
          </div>
        </div>

        <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button
            type="button"
            onClick={() => {
              setInputMode("upload");
              inputRef.current?.click();
            }}
          >
            <FileAudio size={17} />
            Browse audio files
          </Button>
          <Button as={Link} to={`/projects/${projectId}`} variant="secondary">
            <ArrowLeft size={17} />
            Back to project
          </Button>
          <Button type="button" variant="secondary" onClick={() => setInputMode(inputMode === "record" ? "upload" : "record")}>
            {inputMode === "record" ? <UploadCloud size={17} /> : <Mic size={17} />}
            {inputMode === "record" ? "Back to upload" : "Record instead"}
          </Button>
        </div>
      </section>

      <input
        ref={inputRef}
        type="file"
        accept=".wav,.mp3,.flac,.aiff,.aif,.webm,audio/*"
        multiple
        className="hidden"
        onChange={handlePickerChange}
      />

      {inputMode === "upload" ? (
        <section
          className={`mt-6 overflow-hidden rounded-lg border border-dashed p-6 text-center shadow-[0_24px_70px_rgba(0,0,0,0.22)] transition sm:p-9 ${
            dragActive ? "border-teal-200/70 bg-teal-300/10" : "border-white/16 bg-gradient-to-br from-white/[0.065] via-white/[0.035] to-black/30"
          }`}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragActive(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            event.preventDefault();
            setDragActive(false);
          }}
          onDrop={handleDrop}
        >
          <div className="mx-auto max-w-2xl">
            <span className="mx-auto grid h-16 w-16 place-items-center rounded-lg border border-teal-200/25 bg-teal-300/10 text-teal-100 shadow-[0_0_34px_rgba(45,212,191,0.12)]">
              <UploadCloud size={27} />
            </span>
            <h2 className="mt-5 text-2xl font-semibold text-white">Drop stems here</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-400">
              Add all tracks for the song. The originals are copied into local project storage and never overwritten.
            </p>
            <div className="mt-5 flex flex-col items-center justify-center gap-2 sm:flex-row">
              <Button type="button" onClick={() => inputRef.current?.click()}>
                <FileAudio size={17} />
                Browse files
              </Button>
              {selectedFiles.length ? (
                <Button type="button" onClick={handleUpload} disabled={uploading} variant="secondary">
                  <UploadCloud size={17} />
                  {uploading ? "Uploading..." : `Upload ${selectedFiles.length}`}
                </Button>
              ) : null}
            </div>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {SUPPORTED_EXTENSIONS.map((extension) => (
                <span key={extension} className="rounded-full border border-white/10 bg-black/25 px-3 py-1 text-xs font-semibold uppercase tracking-[0.08em] text-zinc-300">
                  {extension.replace(".", "")}
                </span>
              ))}
              <span className="rounded-full border border-amber-300/20 bg-amber-300/10 px-3 py-1 text-xs font-semibold text-amber-100">
                {MAX_UPLOAD_MB} MB max each
              </span>
            </div>
          </div>
        </section>
      ) : null}

      {inputMode === "record" ? (
        <>
          <section className="mt-6 rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="text-xl font-semibold text-white">Record audio into this project</h2>
                <p className="mt-1 text-sm leading-6 text-zinc-400">Use this only when the Zoom H8 is connected and ready. Uploaded files remain the simplest path.</p>
              </div>
              <Button type="button" variant="secondary" onClick={() => setInputMode("upload")}>
                <UploadCloud size={17} />
                Upload files instead
              </Button>
            </div>
          </section>
          <DirectMultitrackRecorder projectId={projectId} onRecorded={handleDirectRecordingComplete} className="mt-4" />
          <section className="mt-4 rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="font-semibold text-white">Browser stereo fallback</h3>
                <p className="mt-1 text-sm leading-6 text-zinc-400">Only use this if direct multitrack recording is unavailable.</p>
              </div>
              <Button type="button" variant="secondary" onClick={() => setShowBrowserFallback((current) => !current)}>
                {showBrowserFallback ? "Hide fallback" : "Show fallback"}
              </Button>
            </div>
          </section>
        </>
      ) : null}

      {inputMode === "record" && showBrowserFallback ? (
        <BrowserFallbackRecorder
          audioInputs={audioInputs}
          handleStartRecording={handleStartRecording}
          handleStopRecording={handleStopRecording}
          loadAudioInputs={loadAudioInputs}
          loadingInputs={loadingInputs}
          recording={recording}
          recordingError={recordingError}
          recordingSeconds={recordingSeconds}
          recordingSupported={recordingSupported}
          selectedInputId={selectedInputId}
          setSelectedInputId={setSelectedInputId}
          uploading={uploading}
        />
      ) : null}

      {errors.length ? (
        <div className="mt-5 rounded-lg border border-rose-300/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
          {errors.map((error) => (
            <p key={error}>{error}</p>
          ))}
        </div>
      ) : null}

      {loadingProject ? (
        <div className="mt-5">
          <ProcessingPanel title="Loading Project" message="Reading uploaded stem metadata." />
        </div>
      ) : null}

      {actionMessage ? (
        <div className="mt-5">
          <ProcessingPanel title="Updating Stem" message={actionMessage} />
        </div>
      ) : null}

      {uploadErrors.length ? (
        <div className="mt-5 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm text-amber-100">
          {uploadErrors.map((error) => (
            <p key={`${error.filename}-${error.error}`}>
              {error.filename}: {error.error}
            </p>
          ))}
        </div>
      ) : null}

      {selectedFiles.length ? (
      <section className="mt-6 rounded-lg border border-white/10 bg-white/[0.04] shadow-[0_18px_55px_rgba(0,0,0,0.18)]">
        <div className="flex flex-col gap-2 border-b border-white/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-semibold text-white">Ready to upload</h2>
            <p className="mt-1 text-sm text-zinc-500">{selectedFiles.length} file{selectedFiles.length === 1 ? "" : "s"} queued, {formatBytes(queuedTotalBytes)} total</p>
          </div>
          <span className="inline-flex items-center gap-2 rounded-full border border-teal-300/20 bg-teal-300/10 px-3 py-1 text-xs font-semibold text-teal-100">
            <CheckCircle2 size={14} />
            Ready
          </span>
        </div>
          <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
            {selectedFiles.map((file) => (
              <div key={`${file.name}-${file.lastModified}-${file.size}`} className="flex min-w-0 items-start justify-between gap-4 rounded-lg border border-white/10 bg-black/20 p-3">
                <div className="min-w-0">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <p className="max-w-full truncate text-sm font-semibold text-white">{file.name}</p>
                    <span className="rounded-full border border-white/10 bg-white/[0.055] px-2 py-0.5 text-[11px] font-semibold uppercase text-zinc-300">
                      {getExtension(file.name).replace(".", "") || "audio"}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-zinc-500">{formatBytes(file.size)}</p>
                  <span className="mt-3 inline-flex rounded-full border border-teal-300/20 bg-teal-300/10 px-2.5 py-1 text-xs font-semibold text-teal-100">
                    {guessStemChip(file.name)}
                  </span>
                </div>
                <button
                  type="button"
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 text-zinc-300 hover:bg-white/[0.06]"
                  onClick={() => setSelectedFiles((current) => current.filter((item) => item !== file))}
                  aria-label={`Remove ${file.name}`}
                  title="Remove file"
                >
                  <X size={16} />
                </button>
              </div>
            ))}
          </div>
      </section>
      ) : null}

      <section className="mt-6 grid gap-3 md:grid-cols-2">
        <StepCue number="1" title="Add stems" detail="Upload separate tracks like vocals, drums, bass, guitars, keys, and FX." />
        <StepCue number="2" title="Analyze stems" detail="After upload, open Analyze so Studio Pilot AI can detect types and audio levels." highlighted={uploadedCount > 0} />
      </section>

      {project?.stems?.length ? (
        <section className="mt-6">
          <div className="mb-4 rounded-lg border border-teal-300/30 bg-gradient-to-r from-teal-300/15 via-teal-300/10 to-white/[0.04] p-4 shadow-[0_0_42px_rgba(45,212,191,0.12)]">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold uppercase tracking-[0.16em] text-teal-100/80">Step 2 is ready</p>
                <h2 className="mt-1 text-xl font-semibold text-white">Analyze uploaded stems</h2>
                <p className="mt-1 text-sm leading-6 text-zinc-300">Run detection and audio checks before mixing.</p>
              </div>
              <Button as={Link} to={`/projects/${projectId}/analyze`} className="w-full justify-center sm:w-auto">
                <BarChart3 size={17} />
                Go to Step 2
              </Button>
            </div>
          </div>
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-xl font-semibold text-white">Uploaded Stems</h2>
              <p className="mt-1 text-sm text-zinc-400">Stored files and manual type assignments.</p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
              <Button as={Link} to={`/projects/${projectId}/analyze`}>
                <BarChart3 size={17} />
                Step 2: Analyze
              </Button>
            </div>
          </div>
          <StemList stems={project.stems} onChangeType={handleChangeType} busyStemId={busyStemId} />
        </section>
      ) : null}

      {uploading ? (
        <div className="mt-5">
          <ProcessingPanel title="Uploading Stems" message="Copying selected audio files into local project storage." progress={progress} />
        </div>
      ) : null}

      {selectedFiles.length ? (
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button as={Link} to={`/projects/${projectId}`} variant="secondary" className="w-full sm:w-auto">
            Cancel
          </Button>
          <Button type="button" onClick={handleUpload} disabled={uploading} className="w-full sm:w-auto">
            <UploadCloud size={17} />
            {uploading ? "Uploading..." : `Upload ${selectedFiles.length}`.trim()}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function getExtension(filename) {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
}

function mergeFiles(current, nextFiles) {
  const keys = new Set(current.map((file) => `${file.name}-${file.size}-${file.lastModified}`));
  const merged = [...current];
  nextFiles.forEach((file) => {
    const key = `${file.name}-${file.size}-${file.lastModified}`;
    if (!keys.has(key)) {
      keys.add(key);
      merged.push(file);
    }
  });
  return merged;
}

function StepSummary({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-3">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function StepCue({ number, title, detail, highlighted = false }) {
  return (
    <div className={`rounded-lg border p-4 ${highlighted ? "border-teal-300/30 bg-teal-300/10 shadow-[0_0_34px_rgba(45,212,191,0.1)]" : "border-white/10 bg-white/[0.04]"}`}>
      <div className="flex items-start gap-3">
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border text-sm font-semibold ${highlighted ? "border-teal-200/50 bg-teal-200/20 text-white" : "border-teal-300/20 bg-teal-300/10 text-teal-100"}`}>
          {number}
        </span>
        <div>
          <h3 className="font-semibold text-white">{title}</h3>
          <p className="mt-1 text-sm leading-6 text-zinc-400">{detail}</p>
        </div>
      </div>
    </div>
  );
}

function BrowserFallbackRecorder({
  audioInputs,
  handleStartRecording,
  handleStopRecording,
  loadAudioInputs,
  loadingInputs,
  recording,
  recordingError,
  recordingSeconds,
  recordingSupported,
  selectedInputId,
  setSelectedInputId,
  uploading,
}) {
  return (
    <section className="mt-4 overflow-hidden rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.07] via-white/[0.04] to-black/30 p-5 shadow-[0_22px_70px_rgba(0,0,0,0.2)]">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-2xl">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Fallback Recorder</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Quick stereo capture</h2>
          <p className="mt-2 text-sm leading-6 text-zinc-400">This records one browser stereo take as a WebM stem. Use direct multitrack recording above when possible.</p>
        </div>
        <Button type="button" variant="secondary" onClick={() => loadAudioInputs(true)} disabled={loadingInputs || recording}>
          <RefreshCw size={17} className={loadingInputs ? "animate-spin" : ""} />
          {audioInputs.length ? "Refresh inputs" : "Enable inputs"}
        </Button>
      </div>

      {recordingSupported ? (
        <div className="mt-5">
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_auto]">
            <label className="block">
              <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">Input Device</span>
              <select
                value={selectedInputId}
                onChange={(event) => setSelectedInputId(event.target.value)}
                disabled={!audioInputs.length || loadingInputs || recording}
                className="h-11 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50"
              >
                {audioInputs.length ? (
                  audioInputs.map((device) => (
                    <option key={device.deviceId} value={device.deviceId}>
                      {formatInputLabel(device)}
                    </option>
                  ))
                ) : (
                  <option value="">No audio inputs detected yet</option>
                )}
              </select>
            </label>
            <Button type="button" onClick={handleStartRecording} disabled={loadingInputs || uploading || recording || !audioInputs.length}>
              <Mic size={17} />
              {recording ? "Recording..." : "Start"}
            </Button>
            <Button type="button" variant="secondary" onClick={handleStopRecording} disabled={!recording}>
              <Square size={17} />
              Stop
            </Button>
          </div>

          {recording ? (
            <div className="mt-4 rounded-lg border border-rose-300/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
              Recording from {formatSelectedDevice(audioInputs, selectedInputId)}. Current take: {formatRecordingDuration(recordingSeconds)}.
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-5 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm text-amber-100">
          Browser audio capture is not available here. You can still upload files recorded on the Zoom H8 SD card.
        </div>
      )}

      {recordingError ? (
        <div className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm text-amber-100">
          {recordingError}
        </div>
      ) : null}
    </section>
  );
}
function guessStemChip(filename) {
  const normalized = filename.toLowerCase();
  if (/(lead.?vox|lead.?vocal|vocal|vox)/.test(normalized)) return "Likely Vocal";
  if (/(bgv|backing|harmony)/.test(normalized)) return "Likely Backing Vocal";
  if (/(kick)/.test(normalized)) return "Likely Kick";
  if (/(snare)/.test(normalized)) return "Likely Snare";
  if (/(drum|kit)/.test(normalized)) return "Likely Drums";
  if (/(bass)/.test(normalized)) return "Likely Bass";
  if (/(egtr|gtr|guitar)/.test(normalized)) return "Likely Guitar";
  if (/(keys|piano|synth)/.test(normalized)) return "Likely Keys";
  if (/(pad|strings)/.test(normalized)) return "Likely Pads";
  if (/(fx|ambience|ambient)/.test(normalized)) return "Likely FX";
  return "Type unknown";
}

function supportsInterfaceRecording() {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof window.MediaRecorder !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    Boolean(navigator.mediaDevices?.enumerateDevices)
  );
}

function getSupportedRecordingMimeType() {
  if (typeof window === "undefined" || typeof window.MediaRecorder?.isTypeSupported !== "function") {
    return "";
  }
  return ["audio/webm;codecs=opus", "audio/webm"].find((mimeType) => window.MediaRecorder.isTypeSupported(mimeType)) || "";
}

function choosePreferredInputId(inputs) {
  const preferred = inputs.find((device) => /zoom|h8/i.test(device.label || ""));
  return preferred?.deviceId || inputs[0]?.deviceId || "";
}

function formatInputLabel(device) {
  if (!device?.label) {
    return "Unnamed audio input";
  }
  return device.label;
}

function formatSelectedDevice(inputs, selectedInputId) {
  return formatInputLabel(inputs.find((device) => device.deviceId === selectedInputId)) || "Selected input";
}

function buildRecordingFilename(label) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const source = (label || "live-input")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 36);
  return `${source || "live-input"}_${timestamp}.webm`;
}

function formatRecordingDuration(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = Math.floor(totalSeconds % 60)
    .toString()
    .padStart(2, "0");
  return `${minutes}:${seconds}`;
}
