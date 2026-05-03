import { ArrowLeft, CheckCircle2, Eraser, Gauge, Power, RefreshCw, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { deleteCleanedStems, getProcessingJob, getProject, startCleaning, updateCleaningSettings } from "../api.js";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import WaveformPreview from "../components/WaveformPreview.jsx";
import WorkflowGuide from "../components/WorkflowGuide.jsx";
import { CLEANING_MODES, HUM_FREQUENCIES } from "../constants.js";
import { formatDb, formatLufs, formatPercent } from "../utils/format.js";

const runningStatuses = new Set(["Pending", "Processing"]);
const STALE_JOB_MS = 30 * 60 * 1000;
const cleaningGridColumns = "xl:grid-cols-[minmax(220px,1fr)_120px_130px_130px_90px_120px_minmax(330px,1.15fr)_minmax(320px,1fr)]";

export default function CleaningPage() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [busyStemId, setBusyStemId] = useState("");
  const [error, setError] = useState("");

  const stems = project?.stems || [];
  const enabledCount = stems.filter((stem) => cleaningSettings(stem).enabled && cleaningSettings(stem).mode !== "Off").length;
  const strongCount = stems.filter((stem) => cleaningSettings(stem).enabled && cleaningSettings(stem).mode === "Strong").length;
  const cleanedCount = stems.filter((stem) => stem.cleaningResult?.status === "Completed" || stem.cleaningStatus === "Cleaned").length;
  const useCleanedCount = stems.filter((stem) => stem.cleaningSettings?.useCleanedInMix && stem.cleaningResult?.status === "Completed").length;
  const staleJob = job && runningStatuses.has(job.status) && isStaleJob(job);
  const running = job && runningStatuses.has(job.status) && !staleJob;

  const latestCleaningJob = useMemo(() => {
    const jobs = project?.processingJobs?.filter((item) => item.type === "Cleaning") || [];
    return jobs.length ? jobs[jobs.length - 1] : null;
  }, [project]);

  const loadProject = async () => {
    setError("");
    try {
      const next = await getProject(projectId);
      setProject(next);
      if (!job && latestCleaningJob) setJob(latestCleaningJob);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const refreshProject = async () => {
    setActionLoading("refresh");
    try {
      await loadProject();
    } finally {
      setActionLoading("");
    }
  };

  useEffect(() => {
    loadProject();
  }, [projectId]);

  useEffect(() => {
    if (!project || job || !latestCleaningJob) return;
    setJob(latestCleaningJob);
  }, [project, latestCleaningJob, job]);

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

  const runCleaning = async () => {
    setActionLoading("clean");
    setError("");
    try {
      const nextJob = await startCleaning(projectId);
      setJob(nextJob);
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const removeCleanedStems = async () => {
    if (!window.confirm("Delete cleaned stem files and downstream vocal/mix/master outputs? Original stems and cleaning settings are kept.")) return;
    setActionLoading("deleteCleaned");
    setError("");
    try {
      setProject(await deleteCleanedStems(projectId));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const updateStemCleaning = async (stem, updates) => {
    const current = cleaningSettings(stem);
    const nextUpdates = { ...updates };
    if (updates.mode) {
      nextUpdates.enabled = updates.mode !== "Off";
    }
    if (updates.enabled === true && current.mode === "Off" && !updates.mode) {
      nextUpdates.mode = "Light";
    }
    setBusyStemId(stem.id);
    setError("");
    try {
      const updated = await updateCleaningSettings(projectId, stem.id, nextUpdates);
      setProject((currentProject) => ({
        ...currentProject,
        stems: currentProject.stems.map((item) => (item.id === stem.id ? updated : item)),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyStemId("");
    }
  };

  if (loading) {
    return <ProcessingPanel title="Loading Cleaning" message="Reading cleaning settings and processed stem references." />;
  }

  const actionPanel = running
    ? { title: "Cleaning Stems", message: job?.message || "Processing enabled stems.", progress: job?.progress || 0 }
    : actionLoading === "refresh"
      ? { title: "Refreshing Cleaning", message: "Reading the latest cleaning metadata." }
      : actionLoading === "clean"
        ? { title: "Starting Cleaning", message: "Creating the local cleaning job." }
        : actionLoading === "deleteCleaned"
          ? { title: "Deleting Cleaned Stems", message: "Removing cleaned files and stale downstream generated outputs." }
          : busyStemId
            ? { title: "Saving Cleaning Settings", message: "Updating the selected stem cleaning options." }
            : null;

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>

      <div className="mt-5 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Cleaning</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">{project?.songTitle || project?.name || "Stem cleaning"}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">Prepare noisy stems before auto-balance and rough mix rendering.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button type="button" variant="secondary" onClick={refreshProject} disabled={actionLoading === "refresh"}>
            <RefreshCw size={17} />
            Refresh
          </Button>
          <Button type="button" onClick={runCleaning} disabled={!enabledCount || running || actionLoading === "clean"}>
            <Eraser size={17} />
            Run Cleaning
          </Button>
          <Button type="button" variant="danger" onClick={removeCleanedStems} disabled={!cleanedCount || running || actionLoading === "deleteCleaned"}>
            <Trash2 size={17} />
            Delete Cleaned
          </Button>
          <Button as={Link} to={`/projects/${projectId}/mixer`} variant="secondary">
            <SlidersHorizontal size={17} />
            Mixer
          </Button>
        </div>
      </div>

      <WorkflowGuide project={project} currentStep="cleaning" className="mt-6" />

      {error ? <p className="mt-5 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}

      {actionPanel ? (
        <div className="mt-5">
          <ProcessingPanel {...actionPanel} />
        </div>
      ) : null}

      {strongCount ? (
        <p className="mt-5 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
          Strong cleaning is enabled on {strongCount} stem{strongCount === 1 ? "" : "s"}; compare the cleaned preview before mixing.
        </p>
      ) : null}

      {staleJob ? (
        <p className="mt-5 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
          The previous cleaning job looks interrupted. Click Run Cleaning to mark it stale and retry the enabled stems.
        </p>
      ) : null}

      {stems.length ? (
        <section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <CleaningStat icon={Power} label="Enabled" value={`${enabledCount}/${stems.length}`} detail="Will run in cleaning job" tone="teal" />
          <CleaningStat icon={CheckCircle2} label="Cleaned" value={`${cleanedCount}/${stems.length}`} detail="Processed versions saved" tone="emerald" />
          <CleaningStat icon={Gauge} label="Strong Mode" value={strongCount} detail="Compare before mixing" tone={strongCount ? "amber" : "zinc"} />
          <CleaningStat icon={Sparkles} label="Mix Source" value={useCleanedCount} detail="Using cleaned files" tone="cyan" />
        </section>
      ) : null}

      <section className="mt-6">
        {stems.length ? (
          <div className="rounded-lg border border-white/10 bg-white/[0.035]">
            <div className="overflow-x-auto">
              <div className="xl:min-w-[1600px]">
                <div className={`hidden ${cleaningGridColumns} gap-3 border-b border-white/10 px-4 py-3 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500 xl:grid`}>
                  <span>Stem</span>
                  <span>Type</span>
                  <span>Mode</span>
                  <span>Hum</span>
                  <span>Use</span>
                  <span>Status</span>
                  <span>Preview</span>
                  <span>Results</span>
                </div>
                <div className="divide-y divide-white/10">
                  {stems.map((stem) => (
                    <CleaningRow key={stem.id} stem={stem} busy={busyStemId === stem.id} onChange={updateStemCleaning} />
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <EmptyState
            icon={Eraser}
            title="No stems to clean"
            description="Upload stems before preparing cleaned versions."
            action={
              <Button as={Link} to={`/projects/${projectId}/upload`}>
                Upload stems
              </Button>
            }
          />
        )}
      </section>
    </div>
  );
}

function CleaningStat({ icon: Icon, label, value, detail, tone }) {
  const tones = {
    teal: "border-teal-300/20 bg-teal-300/10 text-teal-100",
    emerald: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
    cyan: "border-cyan-300/20 bg-cyan-300/10 text-cyan-100",
    amber: "border-amber-300/20 bg-amber-300/10 text-amber-100",
    zinc: "border-zinc-500/20 bg-zinc-500/10 text-zinc-300",
  };
  return (
    <div className="rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.055] to-black/25 p-4">
      <span className={`grid h-10 w-10 place-items-center rounded-lg border ${tones[tone] || tones.teal}`}>
        <Icon size={18} />
      </span>
      <p className="mt-4 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
      <p className="mt-1 truncate text-sm text-zinc-500">{detail}</p>
    </div>
  );
}

function CleaningRow({ stem, busy, onChange }) {
  const settings = cleaningSettings(stem);
  const result = stem.cleaningResult || {};
  const originalUrl = mediaUrl(stem.filePath);
  const cleanedUrl = result.cleanedFileUrl || mediaUrl(result.cleanedFilePath);
  const cleanedReady = result.status === "Completed" && cleanedUrl;

  return (
    <div className={`grid gap-4 px-4 py-4 xl:items-start xl:gap-3 ${cleaningGridColumns}`}>
      <div className="min-w-0">
        <p className="truncate font-medium text-white">{stem.originalFilename}</p>
        {result.error ? <p className="mt-1 line-clamp-2 text-xs text-rose-200">{result.error}</p> : null}
        {result.warnings?.length ? <p className="mt-1 line-clamp-2 text-xs text-amber-100">{result.warnings[0]}</p> : null}
      </div>
      <span className="text-sm text-zinc-300">
        <span className="mr-2 text-xs uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Type</span>
        {stem.stemType}
      </span>
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Mode</p>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={settings.enabled}
            disabled={busy}
            onChange={(event) => onChange(stem, { enabled: event.target.checked })}
            className="h-4 w-4 rounded border-white/20 bg-black/30 accent-teal-300"
          />
          Enabled
        </label>
        <select
          value={settings.mode}
          disabled={busy}
          onChange={(event) => onChange(stem, { mode: event.target.value })}
          className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50"
        >
          {CLEANING_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Hum</p>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={settings.humRemoval}
            disabled={busy || !settings.enabled}
            onChange={(event) => onChange(stem, { humRemoval: event.target.checked })}
            className="h-4 w-4 rounded border-white/20 bg-black/30 accent-teal-300 disabled:opacity-50"
          />
          Hum
        </label>
        <select
          value={settings.humFrequency}
          disabled={busy || !settings.humRemoval || !settings.enabled}
          onChange={(event) => onChange(stem, { humFrequency: Number(event.target.value) })}
          className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50"
        >
          {HUM_FREQUENCIES.map((frequency) => (
            <option key={frequency} value={frequency}>
              {frequency} Hz
            </option>
          ))}
        </select>
      </div>
      <label className="flex items-center gap-2 text-sm text-zinc-300">
        <input
          type="checkbox"
          checked={settings.useCleanedInMix}
          disabled={busy || !cleanedReady}
          onChange={(event) => onChange(stem, { useCleanedInMix: event.target.checked })}
          className="h-4 w-4 rounded border-white/20 bg-black/30 accent-teal-300 disabled:opacity-50"
        />
        Mix
      </label>
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Status</p>
        <StatusBadge status={stem.cleaningStatus || "Not Cleaned"} />
        {Number.isFinite(result.peakDbfs) ? <p className="mt-2 text-xs text-zinc-500">Peak {formatDb(result.peakDbfs)}</p> : null}
      </div>
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Preview</p>
        <PreviewPlayer label="Original" src={originalUrl} variant="amber" />
        <PreviewPlayer label="Cleaned" src={cleanedUrl} disabled={!cleanedReady} variant="teal" />
      </div>
      <div className="min-w-0 space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Results</p>
        <MetricComparison result={result} />
        <p className="truncate text-sm text-zinc-300">{result.cleanedFilePath || "--"}</p>
        {result.operations?.length ? <OperationList title="Operations" items={result.operations} /> : null}
        {result.warnings?.length ? <OperationList title="Warnings" items={result.warnings} tone="warning" /> : null}
      </div>
    </div>
  );
}

function PreviewPlayer({ label, src, disabled, variant }) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</p>
      <div className="space-y-2">
        <WaveformPreview src={src} disabled={disabled || !src} variant={variant} />
        {src && !disabled ? <audio src={src} controls className="h-9 w-full" /> : null}
      </div>
    </div>
  );
}

function MetricComparison({ result }) {
  const original = result.originalMetrics;
  const cleaned = result.cleanedMetrics || fallbackCleanedMetrics(result);
  const deltas = result.metricDeltas || {};

  if (!original && !cleaned?.peakDbfs && !cleaned?.rmsDbfs && !cleaned?.noiseFloorDbfs) {
    return <p className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-zinc-500">Run cleaning to see before/after metrics.</p>;
  }

  const rows = [
    ["Peak", original?.peakDbfs, cleaned?.peakDbfs, deltas.peakDbfs, formatDb],
    ["RMS", original?.rmsDbfs, cleaned?.rmsDbfs, deltas.rmsDbfs, formatDb],
    ["LUFS", original?.integratedLufs, cleaned?.integratedLufs, deltas.integratedLufs, formatLufs],
    ["Noise", original?.noiseFloorDbfs, cleaned?.noiseFloorDbfs, deltas.noiseFloorDbfs, formatDb],
    ["Silence", original?.silencePercentage, cleaned?.silencePercentage, deltas.silencePercentage, formatPercent],
  ];

  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="grid grid-cols-[70px_1fr_1fr_58px] gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
        <span>Metric</span>
        <span>Before</span>
        <span>After</span>
        <span>Delta</span>
      </div>
      <div className="mt-2 space-y-1">
        {rows.map(([label, before, after, delta, formatter]) => (
          <div key={label} className="grid grid-cols-[70px_1fr_1fr_58px] gap-2 text-xs text-zinc-300">
            <span className="text-zinc-500">{label}</span>
            <span>{formatter(before)}</span>
            <span>{formatter(after)}</span>
            <span className={deltaTone(delta)}>{formatDelta(delta)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function OperationList({ title, items, tone = "default" }) {
  const textClass = tone === "warning" ? "text-amber-100" : "text-zinc-400";
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">{title}</p>
      <ul className={`mt-1 space-y-1 text-xs ${textClass}`}>
        {items.map((item, index) => (
          <li key={`${item}-${index}`} className="line-clamp-2">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function fallbackCleanedMetrics(result) {
  if (!result) return null;
  return {
    peakDbfs: result.peakDbfs,
    rmsDbfs: result.rmsDbfs,
    noiseFloorDbfs: result.noiseFloorDbfs,
  };
}

function formatDelta(value) {
  if (!Number.isFinite(value)) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}

function deltaTone(value) {
  if (!Number.isFinite(value) || Math.abs(value) < 0.05) return "text-zinc-500";
  return value < 0 ? "text-teal-200" : "text-amber-200";
}

function cleaningSettings(stem) {
  return {
    enabled: false,
    mode: "Off",
    humRemoval: false,
    humFrequency: 60,
    useCleanedInMix: true,
    ...(stem.cleaningSettings || {}),
  };
}

function mediaUrl(path) {
  if (!path) return "";
  const normalized = path.replace(/\\/g, "/").replace(/^storage\//, "");
  return `/media/${normalized}`;
}

function isStaleJob(job) {
  const timestamp = job?.updatedAt || job?.createdAt;
  if (!timestamp) return true;
  const parsed = new Date(timestamp).getTime();
  if (!Number.isFinite(parsed)) return true;
  return Date.now() - parsed > STALE_JOB_MS;
}
