import { Activity, ArrowLeft, BarChart3, Gauge, RefreshCw, Search, SlidersHorizontal, TriangleAlert, WandSparkles, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { acceptAllStemDetections, acceptStemDetection, clearDetectionMemory, detectStemTypes, generateAutoBalance, getProcessingJob, getProject, startAnalysis, updateStemType } from "../api.js";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import WorkflowGuide from "../components/WorkflowGuide.jsx";
import { STEM_TYPES } from "../constants.js";
import { formatDb, formatDuration, formatLufs, formatPercent } from "../utils/format.js";

const runningStatuses = new Set(["Pending", "Processing"]);
const analysisGridColumns =
  "xl:grid-cols-[minmax(220px,1fr)_160px_190px_90px_90px_90px_105px_90px_90px_90px_120px]";

export default function AnalyzePage() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [busyStemId, setBusyStemId] = useState("");
  const [error, setError] = useState("");
  const [balanceNotice, setBalanceNotice] = useState("");

  const stems = project?.stems || [];
  const analysisComplete = stems.length > 0 && stems.every((stem) => stem.analysisStatus === "Completed");
  const running = job && runningStatuses.has(job.status);

  const latestAnalysisJob = useMemo(() => {
    const jobs = project?.processingJobs?.filter((item) => item.type === "Analysis") || [];
    return jobs.length ? jobs[jobs.length - 1] : null;
  }, [project]);

  const loadProject = async () => {
    setError("");
    try {
      const next = await getProject(projectId);
      setProject(next);
      if (!job && latestAnalysisJob) setJob(latestAnalysisJob);
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
    if (!project || job || !latestAnalysisJob) return;
    setJob(latestAnalysisJob);
  }, [project, latestAnalysisJob, job]);

  useEffect(() => {
    if (!job?.id || !runningStatuses.has(job.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getProcessingJob(projectId, job.id);
        setJob(nextJob);
        const nextProject = await getProject(projectId);
        setProject(nextProject);
      } catch (err) {
        setError(err.message);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [projectId, job?.id, job?.status]);

  const runAnalysis = async () => {
    setActionLoading("analysis");
    setError("");
    try {
      const nextJob = await startAnalysis(projectId);
      setJob(nextJob);
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runDetection = async () => {
    setActionLoading("detect");
    setError("");
    try {
      setProject(await detectStemTypes(projectId));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const acceptAllDetections = async () => {
    setActionLoading("acceptAll");
    setError("");
    try {
      setProject(await acceptAllStemDetections(projectId));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const clearMemory = async () => {
    if (!window.confirm("Clear learned filename correction memory for all projects?")) return;
    setActionLoading("clearMemory");
    setError("");
    try {
      await clearDetectionMemory();
      setProject(await getProject(projectId));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const handleChangeType = async (stemId, stemType) => {
    setBusyStemId(stemId);
    setError("");
    try {
      const updated = await updateStemType(projectId, stemId, stemType);
      setProject((current) => ({
        ...current,
        stems: current.stems.map((stem) => (stem.id === stemId ? updated : stem)),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyStemId("");
    }
  };

  const handleAcceptDetection = async (stemId) => {
    setBusyStemId(stemId);
    setError("");
    try {
      const updated = await acceptStemDetection(projectId, stemId);
      setProject((current) => ({
        ...current,
        stems: current.stems.map((stem) => (stem.id === stemId ? updated : stem)),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyStemId("");
    }
  };

  const runAutoBalance = async () => {
    setActionLoading("balance");
    setError("");
    setBalanceNotice("");
    try {
      const nextProject = await generateAutoBalance(projectId);
      const suggestionCount = nextProject.stems.filter((stem) => stem.autoBalanceSuggestion).length;
      setProject(nextProject);
      setBalanceNotice(`${suggestionCount} suggested gain and pan move${suggestionCount === 1 ? "" : "s"} ready for review.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  if (loading) {
    return <ProcessingPanel title="Loading Analyze" message="Reading stem analysis, detection, and job metadata." />;
  }

  const actionPanel = running
    ? { title: "Analyzing Stems", message: job?.message || "Processing uploaded audio stems.", progress: job?.progress || 0 }
    : busyStemId
      ? { title: "Updating Stem", message: "Saving stem type or detection choice." }
      : actionLoading === "refresh"
        ? { title: "Refreshing Analyze", message: "Reading the latest local project metadata." }
        : actionLoading === "analysis"
          ? { title: "Starting Analysis", message: "Creating the local analysis job." }
          : actionLoading === "detect"
            ? { title: "Detecting Stem Types", message: "Checking filename hints and audio features for each stem." }
            : actionLoading === "acceptAll"
              ? { title: "Accepting Suggestions", message: "Saving confident detected stem types." }
              : actionLoading === "clearMemory"
                ? { title: "Clearing Detection Memory", message: "Removing learned filename correction patterns." }
                : actionLoading === "balance"
                  ? { title: "Generating Auto Balance", message: "Calculating suggested gain, pan, and role priority from analysis data." }
                  : null;

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>

      <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Analyze</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">{project?.songTitle || project?.name || "Stem analysis"}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
            Measure duration, loudness, peak, RMS, clipping, silence, and noise floor before creating an automatic balance.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button type="button" variant="secondary" onClick={refreshProject} disabled={actionLoading === "refresh"}>
            <RefreshCw size={17} />
            Refresh
          </Button>
          <Button type="button" onClick={runAnalysis} disabled={!stems.length || running || actionLoading === "analysis"}>
            <BarChart3 size={17} />
            {analysisComplete ? "Re-analyze" : "Analyze Stems"}
          </Button>
          <Button type="button" variant="secondary" onClick={runAutoBalance} disabled={!analysisComplete || running || actionLoading === "balance"}>
            <WandSparkles size={17} />
            Generate Auto Balance
          </Button>
          <Button as={Link} to={`/projects/${projectId}/mixer`} variant="secondary">
            <SlidersHorizontal size={17} />
            Mixer
          </Button>
        </div>
      </div>

      <WorkflowGuide project={project} currentStep="analyze" className="mt-6" />

      {error ? <p className="mt-5 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}

      {actionPanel ? (
        <div className="mt-5">
          <ProcessingPanel {...actionPanel} />
        </div>
      ) : null}

      {balanceNotice ? (
        <section className="mt-5 flex flex-col gap-3 rounded-lg border border-teal-200/20 bg-teal-300/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm font-medium text-teal-50">{balanceNotice}</p>
          <Button as={Link} to={`/projects/${projectId}/mixer`} variant="secondary" className="sm:w-auto">
            <SlidersHorizontal size={17} />
            Open Mixer
          </Button>
        </section>
      ) : null}

      <AnalysisOverview stems={stems} />

      <section className="mt-6 rounded-lg border border-white/10 bg-white/[0.035] p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-lg border border-white/10 bg-black/25 text-teal-200">
                <Search size={17} />
              </span>
              <div>
                <h2 className="font-semibold text-white">Stem Type Detection</h2>
                <p className="mt-1 text-sm text-zinc-400">
                  Pending suggestions: {project?.detectionSummary?.confidentPendingCount || 0} - Learned patterns: {project?.detectionSummary?.learnedPatternCount || 0}
                </p>
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap lg:justify-end">
            <Button type="button" variant="secondary" onClick={runDetection} disabled={!stems.length || running || actionLoading === "detect"}>
              <Search size={17} />
              {actionLoading === "detect" ? "Detecting..." : "Detect Stem Types"}
            </Button>
            <Button type="button" variant="secondary" onClick={acceptAllDetections} disabled={!project?.detectionSummary?.confidentPendingCount || actionLoading === "acceptAll"}>
              Accept all ({project?.detectionSummary?.confidentPendingCount || 0})
            </Button>
            <Button type="button" variant="ghost" onClick={clearMemory} disabled={!project?.detectionSummary?.learnedPatternCount || actionLoading === "clearMemory"}>
              Clear memory
            </Button>
          </div>
        </div>
      </section>

      {job ? (
        <section className="mt-6 rounded-lg border border-white/10 bg-white/[0.035] p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <h2 className="font-semibold text-white">Analysis Job</h2>
                <StatusBadge status={job.status} />
              </div>
              <p className="mt-1 text-sm text-zinc-400">{job.message}</p>
            </div>
            <span className="text-sm font-semibold text-zinc-200">{job.progress}%</span>
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10">
            <div className="h-full rounded-full bg-teal-300 transition-all" style={{ width: `${job.progress}%` }} />
          </div>
          {job.errors?.length ? (
            <div className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
              {job.errors.map((item) => (
                <p key={`${item.stemId}-${item.error}`}>
                  {item.filename || "Stem"}: {item.error}
                </p>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="mt-6">
        {stems.length ? (
          <AnalysisTable stems={stems} onChangeType={handleChangeType} onAcceptDetection={handleAcceptDetection} busyStemId={busyStemId} />
        ) : (
          <EmptyState
            icon={BarChart3}
            title="No stems to analyze"
            description="Upload stems first, then return here to run local audio analysis."
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

function AnalysisOverview({ stems }) {
  if (!stems.length) return null;
  const analyzed = stems.filter((stem) => stem.analysisStatus === "Completed");
  const warningCount = stems.reduce((count, stem) => count + (stem.analysisResult?.warnings?.length || 0), 0);
  const clippingCount = stems.filter((stem) => {
    const result = stem.analysisResult || {};
    return result.clippingDetected || (result.warnings || []).some((warning) => warning.toLowerCase().includes("clipping"));
  }).length;
  const lufsValues = analyzed.map((stem) => stem.analysisResult?.integratedLufs).filter(Number.isFinite);
  const averageLufs = lufsValues.length ? lufsValues.reduce((sum, value) => sum + value, 0) / lufsValues.length : null;
  const detectedCount = stems.filter((stem) => stem.detectionResult || stem.stemTypeSource === "Detected" || stem.stemTypeSource === "Manual" || stem.stemType !== "Unknown").length;

  return (
    <section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <OverviewCard icon={Activity} label="Analyzed" value={`${analyzed.length}/${stems.length}`} detail="Stem metrics ready" tone="teal" />
      <OverviewCard icon={Gauge} label="Average LUFS" value={formatLufs(averageLufs)} detail="Project loudness map" tone="cyan" />
      <OverviewCard icon={TriangleAlert} label="Warnings" value={warningCount} detail={`${clippingCount} clipping flag${clippingCount === 1 ? "" : "s"}`} tone={warningCount ? "amber" : "emerald"} />
      <OverviewCard icon={Zap} label="Typed Stems" value={`${detectedCount}/${stems.length}`} detail="Manual or detected" tone="emerald" />
    </section>
  );
}

function OverviewCard({ icon: Icon, label, value, detail, tone }) {
  const tones = {
    teal: "border-teal-300/20 bg-teal-300/10 text-teal-100",
    cyan: "border-cyan-300/20 bg-cyan-300/10 text-cyan-100",
    amber: "border-amber-300/20 bg-amber-300/10 text-amber-100",
    emerald: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
  };
  return (
    <div className="rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.055] to-black/25 p-4">
      <span className={`grid h-10 w-10 place-items-center rounded-lg border ${tones[tone] || tones.teal}`}>
        <Icon size={18} />
      </span>
      <p className="mt-4 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value || "--"}</p>
      <p className="mt-1 truncate text-sm text-zinc-500">{detail}</p>
    </div>
  );
}

function AnalysisTable({ stems, onChangeType, onAcceptDetection, busyStemId }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.035]">
      <div className="overflow-x-auto">
        <div className="xl:min-w-[1480px]">
          <div className={`hidden ${analysisGridColumns} gap-3 border-b border-white/10 px-4 py-3 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500 xl:grid`}>
            <span>Stem</span>
            <span>Type</span>
            <span>Detected</span>
            <span>Duration</span>
            <span>LUFS</span>
            <span>Peak</span>
            <span>True Peak</span>
            <span>RMS</span>
            <span>Noise</span>
            <span>Silence</span>
            <span>Status</span>
          </div>
          <div className="divide-y divide-white/10">
            {stems.map((stem) => {
              const result = stem.analysisResult || {};
              const detection = stem.detectionResult;
              const canAccept = detection && detection.suggestedStemType !== "Unknown" && detection.confidence >= 60 && !detection.accepted;
              return (
                <div key={stem.id} className={`grid gap-4 px-4 py-4 xl:items-center xl:gap-3 ${analysisGridColumns}`}>
                  <div className="min-w-0">
                    <p className="truncate font-medium text-white">{stem.originalFilename}</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {(result.warnings || []).slice(0, 3).map((warning) => (
                        <WarningBadge key={warning} label={shortWarning(warning)} title={warning} />
                      ))}
                      {result.error ? <WarningBadge label="Failed" /> : null}
                    </div>
                    {result.warnings?.length ? <p className="mt-1 line-clamp-2 text-xs leading-5 text-amber-100">{result.warnings[0]}</p> : null}
                  </div>
                  <div>
                    <span className="mb-1 block text-xs uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Type</span>
                    <select
                      value={stem.stemType}
                      onChange={(event) => onChangeType(stem.id, event.target.value)}
                      disabled={busyStemId === stem.id}
                      className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50"
                    >
                      {STEM_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-xs text-zinc-500">{stem.stemTypeSource === "Detected" ? "Accepted" : stem.stemTypeSource === "Manual" ? "Manual" : "Unset"}</p>
                  </div>
                  <div className="min-w-0">
                    <span className="mr-2 text-xs uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Detected</span>
                    {detection ? (
                      <>
                        <p className="truncate text-sm text-zinc-300">
                          {detection.suggestedStemType} - {detection.confidence}%
                        </p>
                        <p className="mt-1 line-clamp-2 text-xs leading-5 text-zinc-500">{detection.reason}</p>
                        {onAcceptDetection ? (
                          <Button
                            type="button"
                            variant="secondary"
                            className="mt-2 min-h-8 px-3 py-1 text-xs"
                            onClick={() => onAcceptDetection(stem.id)}
                            disabled={!canAccept || busyStemId === stem.id}
                          >
                            {detection.accepted ? "Accepted" : "Accept"}
                          </Button>
                        ) : null}
                      </>
                    ) : (
                      <span className="text-sm text-zinc-500">Not detected</span>
                    )}
                  </div>
                  <Metric label="Duration" value={formatDuration(result.durationSeconds)} />
                  <Metric label="LUFS" value={formatLufs(result.integratedLufs)} />
                  <Metric label="Peak" value={formatDb(result.peakDbfs)} />
                  <Metric label="True Peak" value={formatDb(result.truePeakDbfs)} />
                  <Metric label="RMS" value={formatDb(result.rmsDbfs)} />
                  <Metric label="Noise" value={formatDb(result.noiseFloorDbfs)} />
                  <Metric label="Silence" value={formatPercent(result.silencePercentage)} />
                  <StatusBadge status={stem.analysisStatus || "Pending"} />
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <span className="text-sm text-zinc-300">
      <span className="mr-2 text-xs uppercase tracking-[0.12em] text-zinc-500 xl:hidden">{label}</span>
      {value}
    </span>
  );
}

function WarningBadge({ label, title }) {
  return (
    <span title={title || label} className="rounded-full border border-amber-300/20 bg-amber-300/10 px-2 py-0.5 text-xs font-semibold text-amber-100">
      {label}
    </span>
  );
}

function shortWarning(warning) {
  if (warning.includes("Clipping")) return "Clipping";
  if (warning.includes("noisy")) return "Noisy";
  if (warning.includes("silent")) return "Silent";
  if (warning.includes("hot") || warning.includes("loud")) return "Too loud";
  if (warning.includes("quiet")) return "Too quiet";
  if (warning.includes("Duration")) return "Duration";
  return "Warning";
}
