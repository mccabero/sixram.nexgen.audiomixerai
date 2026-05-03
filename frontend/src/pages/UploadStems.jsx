import { ArrowLeft, BarChart3, CheckCircle2, FileAudio, Music2, ShieldCheck, TriangleAlert, UploadCloud, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getProject, updateStemType, uploadStems } from "../api.js";
import Button from "../components/Button.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StemList from "../components/StemList.jsx";
import WorkflowGuide from "../components/WorkflowGuide.jsx";
import { MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, SUPPORTED_EXTENSIONS } from "../constants.js";
import { formatBytes } from "../utils/format.js";

export default function UploadStems() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [project, setProject] = useState(null);
  const [loadingProject, setLoadingProject] = useState(true);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [errors, setErrors] = useState([]);
  const [uploadErrors, setUploadErrors] = useState([]);
  const [progress, setProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [busyStemId, setBusyStemId] = useState("");
  const [actionMessage, setActionMessage] = useState("");

  useEffect(() => {
    setLoadingProject(true);
    getProject(projectId)
      .then(setProject)
      .catch((err) => setErrors([err.message]))
      .finally(() => setLoadingProject(false));
  }, [projectId]);

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

  const handleDrop = (event) => {
    event.preventDefault();
    setDragActive(false);
    addFiles(event.dataTransfer.files);
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

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>

      <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Upload Stems</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">{project?.songTitle || project?.name || "Project stems"}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
            Add WAV, MP3, FLAC, AIFF, or AIF files. The app copies them into project storage and preserves metadata for later processing.
          </p>
        </div>
        <Button type="button" onClick={() => inputRef.current?.click()} variant="secondary">
          <FileAudio size={17} />
          Browse files
        </Button>
      </div>

      <WorkflowGuide project={project} currentStep="upload" className="mt-6" />

      <input
        ref={inputRef}
        type="file"
        accept=".wav,.mp3,.flac,.aiff,.aif,audio/*"
        multiple
        className="hidden"
        onChange={(event) => addFiles(event.target.files)}
      />

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
          <h2 className="mt-5 text-2xl font-semibold text-white">Drop audio stems here</h2>
          <p className="mt-2 text-sm leading-6 text-zinc-400">Multiple files supported. Originals are copied into project storage and never overwritten.</p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            {SUPPORTED_EXTENSIONS.map((extension) => (
              <span key={extension} className="rounded-full border border-white/10 bg-black/25 px-3 py-1 text-xs font-semibold uppercase tracking-[0.08em] text-zinc-300">
                {extension.replace(".", "")}
              </span>
            ))}
            <span className="rounded-full border border-amber-300/20 bg-amber-300/10 px-3 py-1 text-xs font-semibold text-amber-100">
              {MAX_UPLOAD_MB} MB max
            </span>
          </div>
          <div className="mt-5 grid gap-2 text-left sm:grid-cols-3">
            <UploadAssurance icon={ShieldCheck} label="Local only" />
            <UploadAssurance icon={CheckCircle2} label="Duplicate-safe names" />
            <UploadAssurance icon={Music2} label="Stem metadata saved" />
          </div>
        </div>
      </section>

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

      <section className="mt-6 rounded-lg border border-white/10 bg-white/[0.04] shadow-[0_18px_55px_rgba(0,0,0,0.18)]">
        <div className="flex flex-col gap-2 border-b border-white/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-semibold text-white">Selected Files</h2>
            <p className="mt-1 text-sm text-zinc-500">{selectedFiles.length ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} queued for upload` : "Choose stems to stage them here."}</p>
          </div>
          {selectedFiles.length ? (
            <span className="inline-flex items-center gap-2 rounded-full border border-teal-300/20 bg-teal-300/10 px-3 py-1 text-xs font-semibold text-teal-100">
              <CheckCircle2 size={14} />
              Ready
            </span>
          ) : null}
        </div>
        {selectedFiles.length ? (
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
        ) : (
          <div className="px-4 py-8 text-center">
            <TriangleAlert size={18} className="mx-auto text-zinc-600" />
            <p className="mt-2 text-sm text-zinc-500">No files selected.</p>
          </div>
        )}
      </section>

      {project?.stems?.length ? (
        <section className="mt-6">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-xl font-semibold text-white">Uploaded Stems</h2>
              <p className="mt-1 text-sm text-zinc-400">Stored files and manual type assignments.</p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
              <Button as={Link} to={`/projects/${projectId}/analyze`} variant="secondary">
                <BarChart3 size={17} />
                Open Analyze
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

      <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <Button as={Link} to={`/projects/${projectId}`} variant="secondary" className="w-full sm:w-auto">
          Cancel
        </Button>
        <Button type="button" onClick={handleUpload} disabled={!selectedFiles.length || uploading} className="w-full sm:w-auto">
          <UploadCloud size={17} />
          {uploading ? "Uploading..." : `Upload ${selectedFiles.length || ""}`.trim()}
        </Button>
      </div>
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

function UploadAssurance({ icon: Icon, label }) {
  return (
    <span className="inline-flex items-center justify-center gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs font-semibold text-zinc-300">
      <Icon size={15} className="text-teal-200" />
      {label}
    </span>
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
