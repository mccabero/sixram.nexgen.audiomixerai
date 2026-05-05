import { AlertTriangle, ArrowLeft, CheckCircle2, Eraser, Gauge, Power, RefreshCw, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { cancelProcessingJob, deleteCleanedStems, getProcessingJob, getProject, startCleaning, updateCleaningSettings } from "../api.js";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import WaveformPreview from "../components/WaveformPreview.jsx";
import WorkflowGuide from "../components/WorkflowGuide.jsx";
import { CLEANING_MODES, HUM_FREQUENCIES } from "../constants.js";
import { formatDb, formatLufs, formatPercent } from "../utils/format.js";

const runningStatuses = new Set(["Pending", "Processing", "Cancelling"]);
const STALE_JOB_MS = 30 * 60 * 1000;
const cleaningGridColumns = "xl:grid-cols-[minmax(220px,1fr)_120px_130px_130px_90px_120px_minmax(330px,1.15fr)_minmax(320px,1fr)]";

export default function CleaningPage() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [stoppingJobId, setStoppingJobId] = useState("");
  const [busyStemId, setBusyStemId] = useState("");
  const [error, setError] = useState("");

  const stems = project?.stems || [];
  const suggestionEntries = useMemo(
    () =>
      stems
        .map((stem) => {
          const suggestion = getCleaningSuggestion(stem);
          if (!suggestion) return null;
          return { stem, suggestion, state: getCleaningSuggestionState(stem, suggestion) };
        })
        .filter(Boolean)
        .sort(compareSuggestionEntries),
    [stems],
  );
  const actionableSuggestionEntries = useMemo(() => suggestionEntries.filter((entry) => entry.state !== "done"), [suggestionEntries]);
  const suggestionLookup = useMemo(() => new Map(suggestionEntries.map((entry) => [entry.stem.id, entry])), [suggestionEntries]);
  const displayedStems = useMemo(() => {
    if (!actionableSuggestionEntries.length) return stems;
    const priority = new Map(actionableSuggestionEntries.map((entry, index) => [entry.stem.id, index]));
    return [...stems].sort((left, right) => {
      const leftPriority = priority.has(left.id) ? priority.get(left.id) : Number.POSITIVE_INFINITY;
      const rightPriority = priority.has(right.id) ? priority.get(right.id) : Number.POSITIVE_INFINITY;
      return leftPriority - rightPriority;
    });
  }, [stems, actionableSuggestionEntries]);
  const enabledCount = stems.filter((stem) => cleaningSettings(stem).enabled && cleaningSettings(stem).mode !== "Off").length;
  const strongCount = stems.filter((stem) => cleaningSettings(stem).enabled && cleaningSettings(stem).mode === "Strong").length;
  const cleanedCount = stems.filter((stem) => stem.cleaningResult?.status === "Completed" || stem.cleaningStatus === "Cleaned").length;
  const useCleanedCount = stems.filter((stem) => stem.cleaningSettings?.useCleanedInMix && stem.cleaningResult?.status === "Completed").length;
  const needsCleaningCount = actionableSuggestionEntries.length;
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

  const stopCleaning = async () => {
    if (!job?.id || job.status === "Cancelling") return;
    setStoppingJobId(job.id);
    setError("");
    try {
      setJob(await cancelProcessingJob(projectId, job.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setStoppingJobId("");
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
    ? {
        title: job?.status === "Cancelling" ? "Stopping Cleaning" : "Cleaning Stems",
        message: job?.message || "Processing enabled stems.",
        progress: job?.progress || 0,
        actionLabel: "Stop Cleaning",
        actionBusy: stoppingJobId === job?.id || job?.status === "Cancelling",
        actionDisabled: stoppingJobId === job?.id || job?.status === "Cancelling",
        onAction: stopCleaning,
      }
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

      <WorkflowGuide project={project} currentStep="cleaning" className="mt-6" onProjectRefresh={loadProject} />

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
        <section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <CleaningStat icon={Power} label="Enabled" value={`${enabledCount}/${stems.length}`} detail="Will run in cleaning job" tone="teal" />
          <CleaningStat
            icon={AlertTriangle}
            label="Needs Cleaning"
            value={needsCleaningCount}
            detail={needsCleaningCount ? "Suggested from stem analysis" : "No remaining flagged stems"}
            tone={needsCleaningCount ? "amber" : "emerald"}
          />
          <CleaningStat icon={CheckCircle2} label="Cleaned" value={`${cleanedCount}/${stems.length}`} detail="Processed versions saved" tone="emerald" />
          <CleaningStat icon={Gauge} label="Strong Mode" value={strongCount} detail="Compare before mixing" tone={strongCount ? "amber" : "zinc"} />
          <CleaningStat icon={Sparkles} label="Mix Source" value={useCleanedCount} detail="Using cleaned files" tone="cyan" />
        </section>
      ) : null}

      {actionableSuggestionEntries.length ? (
        <section className="mt-6 overflow-hidden rounded-lg border border-amber-300/20 bg-gradient-to-br from-amber-300/10 via-white/[0.04] to-transparent">
          <div className="flex flex-col gap-2 border-b border-white/10 px-4 py-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-amber-100/80">Suggested Cleaning</p>
              <h2 className="mt-1 text-lg font-semibold text-white">Stems That Need Cleaning</h2>
              <p className="mt-1 max-w-3xl text-sm text-zinc-300">
                These stems were flagged from the existing analysis warnings and measured noise floor. Apply the suggestion to stage them for the next cleaning pass.
              </p>
            </div>
            <p className="text-sm text-amber-100">
              {needsCleaningCount} stem{needsCleaningCount === 1 ? "" : "s"} still need attention.
            </p>
          </div>
          <div className="divide-y divide-white/10">
            {actionableSuggestionEntries.map(({ stem, suggestion, state }) => (
              <SuggestedCleaningItem
                key={stem.id}
                stem={stem}
                suggestion={suggestion}
                state={state}
                busy={busyStemId === stem.id}
                onApply={updateStemCleaning}
              />
            ))}
          </div>
        </section>
      ) : suggestionEntries.length ? (
        <p className="mt-6 rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-3 py-2 text-sm text-emerald-100">
          Current analysis does not show any remaining stems that still need cleaning.
        </p>
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
                  {displayedStems.map((stem) => {
                    const suggestionEntry = suggestionLookup.get(stem.id);
                    return (
                      <CleaningRow
                        key={stem.id}
                        stem={stem}
                        busy={busyStemId === stem.id}
                        onChange={updateStemCleaning}
                        suggestion={suggestionEntry?.suggestion || null}
                        suggestionState={suggestionEntry?.state || ""}
                      />
                    );
                  })}
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

function SuggestedCleaningItem({ stem, suggestion, state, busy, onApply }) {
  const settings = cleaningSettings(stem);
  const applyDisabled = busy || state !== "needs-apply";
  const stateMessage =
    state === "needs-apply"
      ? `Current mode: ${settings.enabled ? settings.mode : "Off"}`
      : "Settings are already in place. Run Cleaning to render the cleaned file.";

  return (
    <div className="flex flex-col gap-3 px-4 py-4 xl:flex-row xl:items-center xl:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate font-medium text-white">{stem.originalFilename}</p>
          <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-0.5 text-xs font-semibold text-zinc-300">{stem.stemType}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {suggestion.badges.map((badge) => (
            <SuggestionBadge key={`${stem.id}-${badge.label}`} {...badge} />
          ))}
          <SuggestionStateBadge state={state} />
        </div>
        <p className="mt-2 text-sm text-zinc-300">{suggestion.summary}</p>
      </div>
      <div className="flex shrink-0 flex-col items-start gap-2 xl:items-end">
        <p className="text-xs text-zinc-400">{stateMessage}</p>
        <Button
          type="button"
          className="min-h-8 px-3 py-1 text-xs"
          onClick={() => onApply(stem, suggestion.updates)}
          disabled={applyDisabled}
        >
          {state === "needs-apply" ? "Apply Suggestion" : "Applied"}
        </Button>
      </div>
    </div>
  );
}

function CleaningRow({ stem, busy, onChange, suggestion, suggestionState }) {
  const settings = cleaningSettings(stem);
  const result = stem.cleaningResult || {};
  const originalUrl = mediaUrl(stem.filePath);
  const cleanedUrl = result.cleanedFileUrl || mediaUrl(result.cleanedFilePath);
  const cleanedReady = result.status === "Completed" && cleanedUrl;
  const showSuggestion = Boolean(suggestion);
  const suggestionActionable = suggestionState === "needs-apply";
  const suggestionPendingRun = suggestionState === "ready-to-run";

  return (
    <div className={`grid gap-4 px-4 py-4 xl:items-start xl:gap-3 ${cleaningGridColumns} ${showSuggestion && suggestionState !== "done" ? "bg-amber-300/[0.03]" : ""}`}>
      <div className="min-w-0">
        <p className="truncate font-medium text-white">{stem.originalFilename}</p>
        {showSuggestion ? (
          <div className="mt-2 flex flex-wrap gap-2">
            {suggestion.badges.map((badge) => (
              <SuggestionBadge key={`${stem.id}-row-${badge.label}`} {...badge} />
            ))}
            <SuggestionStateBadge state={suggestionState} />
          </div>
        ) : null}
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
        {showSuggestion ? (
          <div className="rounded-lg border border-teal-300/15 bg-teal-300/5 p-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-teal-100">Suggested {suggestion.mode}</p>
            <p className="mt-1 text-xs leading-5 text-zinc-400">{suggestion.summary}</p>
            <Button
              type="button"
              variant={suggestionActionable ? "primary" : "secondary"}
              className="mt-2 min-h-8 w-full px-3 py-1 text-xs"
              onClick={() => onChange(stem, suggestion.updates)}
              disabled={busy || !suggestionActionable}
            >
              {suggestionActionable ? "Apply suggestion" : suggestionPendingRun ? "Applied" : "Done"}
            </Button>
          </div>
        ) : null}
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

function SuggestionBadge({ label, tone = "zinc", title }) {
  const tones = {
    amber: "border-amber-300/20 bg-amber-300/10 text-amber-100",
    emerald: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
    rose: "border-rose-300/20 bg-rose-300/10 text-rose-100",
    teal: "border-teal-300/20 bg-teal-300/10 text-teal-100",
    zinc: "border-white/10 bg-white/[0.06] text-zinc-300",
  };
  return (
    <span title={title || label} className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${tones[tone] || tones.zinc}`}>
      {label}
    </span>
  );
}

function SuggestionStateBadge({ state }) {
  if (!state) return null;
  const badges = {
    "needs-apply": { label: "Apply Needed", tone: "amber" },
    "ready-to-run": { label: "Ready To Run", tone: "teal" },
    done: { label: "Already Covered", tone: "emerald" },
  };
  const badge = badges[state];
  return badge ? <SuggestionBadge {...badge} /> : null;
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

function getCleaningSuggestion(stem) {
  const analysis = stem.analysisResult || {};
  const warnings = Array.isArray(analysis.warnings) ? analysis.warnings : [];
  const warningText = warnings.join(" ").toLowerCase();
  const noiseFloor = analysis.noiseFloorDbfs;
  const sensitiveStem = isNoiseSensitiveStem(stem.stemType);
  const noisyWarning = warningText.includes("consider cleaning") || warningText.includes("noisy");
  const humWarning = warningText.includes("hum") || warningText.includes("buzz") || warningText.includes("mains");

  let mode = "Off";
  let headline = "";
  let summary = "";

  if (Number.isFinite(noiseFloor) && noiseFloor > -32) {
    mode = "Strong";
    headline = "Heavy noise";
    summary = `Noise floor is ${formatDb(noiseFloor)}. Strong cleaning is recommended before mixing.`;
  } else if (noisyWarning || (Number.isFinite(noiseFloor) && noiseFloor > -38)) {
    mode = sensitiveStem && Number.isFinite(noiseFloor) && noiseFloor > -34 ? "Strong" : "Medium";
    headline = "Noise flagged";
    summary = Number.isFinite(noiseFloor)
      ? `Analysis flagged this stem at ${formatDb(noiseFloor)}. ${mode} cleaning should keep that noise from carrying into the mix.`
      : `${mode} cleaning is recommended from the current analysis warnings.`;
  } else if (sensitiveStem && Number.isFinite(noiseFloor) && noiseFloor > -45) {
    mode = "Light";
    headline = "Light cleanup";
    summary = `Noise floor is ${formatDb(noiseFloor)} on a detail-sensitive stem. Light cleaning should tidy it without over-processing.`;
  } else if (humWarning) {
    mode = "Light";
    headline = "Hum control";
    summary = "Analysis hints at electrical hum or buzz. Start with Light cleaning and hum reduction.";
  } else {
    return null;
  }

  const badges = [
    { label: headline, tone: mode === "Strong" ? "rose" : "amber" },
    { label: `Suggest ${mode}`, tone: "teal" },
  ];
  if (Number.isFinite(noiseFloor)) {
    badges.push({ label: `Noise ${formatDb(noiseFloor)}`, tone: "zinc", title: `Measured noise floor: ${formatDb(noiseFloor)}` });
  }
  if (humWarning) {
    badges.push({ label: "Hum 60 Hz", tone: "amber", title: "Hum reduction suggested from analysis warnings." });
  }

  return {
    mode,
    summary,
    badges,
    priority: cleaningModeRank(mode),
    updates: {
      enabled: true,
      mode,
      ...(humWarning ? { humRemoval: true, humFrequency: 60 } : {}),
    },
  };
}

function getCleaningSuggestionState(stem, suggestion) {
  if (!satisfiesCleaningSuggestion(cleaningSettings(stem), suggestion)) return "needs-apply";
  return stem.cleaningResult?.status === "Completed" ? "done" : "ready-to-run";
}

function satisfiesCleaningSuggestion(settings, suggestion) {
  if (!settings.enabled) return false;
  if (cleaningModeRank(settings.mode) < cleaningModeRank(suggestion.mode)) return false;
  if (suggestion.updates.humRemoval && !settings.humRemoval) return false;
  if (suggestion.updates.humRemoval && Number(settings.humFrequency) !== Number(suggestion.updates.humFrequency || 60)) return false;
  return true;
}

function compareSuggestionEntries(left, right) {
  const stateDelta = suggestionStateRank(left.state) - suggestionStateRank(right.state);
  if (stateDelta !== 0) return stateDelta;
  const priorityDelta = (right.suggestion.priority || 0) - (left.suggestion.priority || 0);
  if (priorityDelta !== 0) return priorityDelta;
  return `${left.stem.originalFilename || ""}`.localeCompare(`${right.stem.originalFilename || ""}`);
}

function suggestionStateRank(state) {
  if (state === "needs-apply") return 0;
  if (state === "ready-to-run") return 1;
  return 2;
}

function cleaningModeRank(mode) {
  const ranks = { Off: 0, Light: 1, Medium: 2, Strong: 3 };
  return ranks[mode] || 0;
}

function isNoiseSensitiveStem(stemType) {
  const value = `${stemType || ""}`.toLowerCase();
  return value.includes("vocal") || value.includes("acoustic") || value.includes("piano") || value.includes("strings");
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
