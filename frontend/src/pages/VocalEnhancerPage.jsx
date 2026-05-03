import { ArrowLeft, Mic2, RefreshCw, SlidersHorizontal, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getProcessingJob, getProject, listVocalEnhancerPresets, startVocalEnhancement, updateVocalEnhancementSettings } from "../api.js";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import WaveformPreview from "../components/WaveformPreview.jsx";
import WorkflowGuide from "../components/WorkflowGuide.jsx";
import { formatDb, formatLufs } from "../utils/format.js";

const runningStatuses = new Set(["Pending", "Processing"]);
const vocalTypes = new Set(["Lead Vocal", "Backing Vocal"]);
const defaultOptions = {
  presets: ["Natural Clean", "Pop Vocal", "Worship Lead", "Live Vocal Fix", "Bright AI Polish", "Warm Ballad", "Backing Vocal Wide"],
  pitchCorrectionModes: ["Off", "Natural", "Medium", "Strong"],
  keys: ["Auto", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"],
  scales: ["Major", "Minor", "Chromatic"],
};

export default function VocalEnhancerPage() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [options, setOptions] = useState(defaultOptions);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [busyStemId, setBusyStemId] = useState("");
  const [error, setError] = useState("");

  const stems = project?.stems || [];
  const vocalStems = stems.filter((stem) => vocalTypes.has(stem.stemType) || vocalTypes.has(stem.detectionResult?.suggestedStemType));
  const enabledCount = vocalStems.filter((stem) => vocalSettings(stem).enabled).length;
  const enhancedCount = vocalStems.filter((stem) => stem.vocalEnhancementResult?.status === "Completed").length;
  const useEnhancedCount = vocalStems.filter((stem) => vocalSettings(stem).useEnhancedInMix && stem.vocalEnhancementResult?.status === "Completed").length;
  const running = job && runningStatuses.has(job.status);

  const latestJob = useMemo(() => {
    const jobs = project?.processingJobs?.filter((item) => item.type === "Vocal Enhancement") || [];
    return jobs.length ? jobs[jobs.length - 1] : null;
  }, [project]);

  const loadProject = async () => {
    setError("");
    try {
      const [nextProject, presetPayload] = await Promise.all([getProject(projectId), listVocalEnhancerPresets().catch(() => null)]);
      setProject(nextProject);
      if (presetPayload) setOptions({ ...defaultOptions, ...presetPayload });
      if (!job && latestJob) setJob(latestJob);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProject();
  }, [projectId]);

  useEffect(() => {
    if (!project || job || !latestJob) return;
    setJob(latestJob);
  }, [project, latestJob, job]);

  useEffect(() => {
    if (!job?.id || !runningStatuses.has(job.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getProcessingJob(projectId, job.id);
        setJob(nextJob);
        setProject(await getProject(projectId));
      } catch (err) {
        setError(err.message);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [projectId, job?.id, job?.status]);

  const refreshProject = async () => {
    setActionLoading("refresh");
    try {
      await loadProject();
    } finally {
      setActionLoading("");
    }
  };

  const runEnhancement = async () => {
    setActionLoading("enhance");
    setError("");
    try {
      const nextJob = await startVocalEnhancement(projectId);
      setJob(nextJob);
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const updateStem = async (stem, updates) => {
    setBusyStemId(stem.id);
    setError("");
    try {
      const updated = await updateVocalEnhancementSettings(projectId, stem.id, updates);
      setProject((current) => ({
        ...current,
        stems: current.stems.map((item) => (item.id === stem.id ? updated : item)),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyStemId("");
    }
  };

  if (loading) {
    return <ProcessingPanel title="Loading Vocal Enhancer" message="Reading vocal settings and enhanced stem references." />;
  }

  const actionPanel = running
    ? { title: "Enhancing Vocals", message: job?.message || "Processing enabled vocal stems.", progress: job?.progress || 0 }
    : actionLoading === "refresh"
      ? { title: "Refreshing Vocal Enhancer", message: "Reading latest vocal enhancement metadata." }
      : actionLoading === "enhance"
        ? { title: "Starting Vocal Enhancement", message: "Creating the local vocal enhancer job." }
        : busyStemId
          ? { title: "Saving Vocal Settings", message: "Updating the selected vocal enhancement settings." }
          : null;

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>

      <div className="mt-5 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Vocal Enhancer</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">{project?.songTitle || project?.name || "Vocal polish"}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">Create non-destructive enhanced vocal stems with leveling, de-essing, pitch polish, presence, air, and subtle doubling.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button type="button" variant="secondary" onClick={refreshProject} disabled={actionLoading === "refresh"}>
            <RefreshCw size={17} />
            Refresh
          </Button>
          <Button type="button" onClick={runEnhancement} disabled={!enabledCount || running || actionLoading === "enhance"}>
            <Sparkles size={17} />
            Enhance Vocals
          </Button>
          <Button as={Link} to={`/projects/${projectId}/mixer`} variant="secondary">
            <SlidersHorizontal size={17} />
            Mixer
          </Button>
        </div>
      </div>

      <WorkflowGuide project={project} currentStep="vocals" className="mt-6" />

      {error ? <p className="mt-5 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}

      {actionPanel ? (
        <div className="mt-5">
          <ProcessingPanel {...actionPanel} />
        </div>
      ) : null}

      {vocalStems.length ? (
        <section className="mt-6 grid gap-3 sm:grid-cols-3">
          <VocalStat label="Vocal Stems" value={vocalStems.length} detail="Lead/backing candidates" />
          <VocalStat label="Enabled" value={`${enabledCount}/${vocalStems.length}`} detail="Queued for enhancement" />
          <VocalStat label="Mix Source" value={useEnhancedCount} detail="Using enhanced vocals" />
        </section>
      ) : null}

      <section className="mt-6">
        {vocalStems.length ? (
          <div className="grid gap-4">
            {vocalStems.map((stem) => (
              <VocalStemCard key={stem.id} stem={stem} options={options} busy={busyStemId === stem.id} onChange={updateStem} />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Mic2}
            title="No vocal stems found"
            description="Set at least one stem type to Lead Vocal or Backing Vocal before using the vocal enhancer."
            action={
              <Button as={Link} to={`/projects/${projectId}/analyze`}>
                Open Analyze
              </Button>
            }
          />
        )}
      </section>
    </div>
  );
}

function VocalStemCard({ stem, options, busy, onChange }) {
  const settings = vocalSettings(stem);
  const result = stem.vocalEnhancementResult || {};
  const sourceUrl = sourcePreviewUrl(stem);
  const enhancedReady = result.status === "Completed" && result.enhancedFileUrl;

  return (
    <article className="rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.06] to-black/30 p-4 shadow-[0_18px_55px_rgba(0,0,0,0.2)]">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate font-semibold text-white">{stem.originalFilename}</h2>
            <span className="rounded-full border border-teal-300/20 bg-teal-300/10 px-2.5 py-1 text-xs font-semibold text-teal-100">{stem.stemType}</span>
          </div>
          <p className="mt-1 text-sm text-zinc-500">{result.enhancedFilePath || "No enhanced vocal file yet."}</p>
        </div>
        <StatusBadge status={stem.vocalEnhancementStatus || "Not Enhanced"} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="grid gap-3 sm:grid-cols-2">
          <Toggle
            label="Enable"
            checked={settings.enabled}
            disabled={busy}
            onChange={(checked) => onChange(stem, { enabled: checked })}
          />
          <Toggle
            label="Use In Mix"
            checked={settings.useEnhancedInMix && enhancedReady}
            disabled={busy || !enhancedReady}
            onChange={(checked) => onChange(stem, { useEnhancedInMix: checked })}
          />
          <SelectControl label="Preset" value={settings.preset} options={options.presets} disabled={busy} onChange={(value) => onChange(stem, { preset: value })} />
          <SelectControl label="Pitch" value={settings.pitchCorrection} options={options.pitchCorrectionModes} disabled={busy} onChange={(value) => onChange(stem, { pitchCorrection: value })} />
          <SelectControl label="Key" value={settings.key} options={options.keys} disabled={busy || settings.pitchCorrection === "Off"} onChange={(value) => onChange(stem, { key: value })} />
          <SelectControl label="Scale" value={settings.scale} options={options.scales} disabled={busy || settings.pitchCorrection === "Off"} onChange={(value) => onChange(stem, { scale: value })} />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <PreviewPlayer label={result.sourceKind ? `${result.sourceKind} Source` : "Source"} src={sourceUrl} variant="amber" />
          <PreviewPlayer label="Enhanced" src={result.enhancedFileUrl} disabled={!enhancedReady} variant="teal" />
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Readout label="LUFS" value={formatLufs(result.integratedLufs)} />
        <Readout label="Peak" value={formatDb(result.peakDbfs)} />
        <Readout label="RMS" value={formatDb(result.rmsDbfs)} />
      </div>

      {result.operations?.length ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {result.operations.slice(0, 8).map((operation) => (
            <span key={operation} className="rounded-full border border-white/10 bg-black/25 px-2 py-1 text-xs font-medium text-zinc-300">
              {operation}
            </span>
          ))}
        </div>
      ) : null}

      {result.error ? <p className="mt-4 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{result.error}</p> : null}
      {result.warnings?.length ? <p className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">{result.warnings[0]}</p> : null}
    </article>
  );
}

function VocalStat({ label, value, detail }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-sm text-zinc-500">{detail}</p>
    </div>
  );
}

function Toggle({ label, checked, disabled, onChange }) {
  return (
    <button
      type="button"
      aria-pressed={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`min-h-10 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
        checked ? "border-teal-200/30 bg-teal-300/20 text-teal-50" : "border-white/10 bg-black/20 text-zinc-300 hover:bg-white/[0.06]"
      }`}
    >
      {label}
    </button>
  );
}

function SelectControl({ label, value, options, disabled, onChange }) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</span>
      <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50">
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function PreviewPlayer({ label, src, disabled, variant }) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</p>
      <div className="space-y-2 rounded-lg border border-white/10 bg-black/20 p-3">
        <WaveformPreview src={src} disabled={disabled || !src} variant={variant} />
        {src && !disabled ? <audio src={src} controls className="h-9 w-full" /> : <p className="py-2 text-sm text-zinc-500">No preview yet.</p>}
      </div>
    </div>
  );
}

function Readout({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-zinc-100">{value || "--"}</p>
    </div>
  );
}

function vocalSettings(stem) {
  return {
    enabled: false,
    preset: "Natural Clean",
    pitchCorrection: "Off",
    key: "Auto",
    scale: "Major",
    useEnhancedInMix: true,
    ...(stem.vocalEnhancementSettings || {}),
  };
}

function sourcePreviewUrl(stem) {
  const result = stem.vocalEnhancementResult || {};
  if (result.sourceFilePath) return mediaUrl(result.sourceFilePath);
  const cleaningSettings = stem.cleaningSettings || {};
  const cleaningResult = stem.cleaningResult || {};
  if (cleaningSettings.enabled && cleaningSettings.useCleanedInMix !== false && cleaningResult.status === "Completed" && cleaningResult.cleanedFileUrl) {
    return cleaningResult.cleanedFileUrl;
  }
  return mediaUrl(stem.filePath);
}

function mediaUrl(path) {
  if (!path) return "";
  const normalized = path.replace(/\\/g, "/").replace(/^storage\//, "");
  return `/media/${normalized}`;
}
