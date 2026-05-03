import { AlertTriangle, CheckCircle2, LoaderCircle, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  abandonProcessingJob,
  getProject,
  startAdvancedMix,
  startAnalysis,
  startCleaning,
  startVocalEnhancement,
  startInstrumentalMix,
  startMasteringJob,
} from "../api.js";
import { formatDateTime } from "../utils/format.js";
import Button from "./Button.jsx";

const runningStatuses = new Set(["Pending", "Processing"]);
const retryableTypes = new Set(["Analysis", "Cleaning", "Vocal Enhancement", "Advanced Mix", "Instrumental Mix", "Mastering"]);
const staleJobMs = 30 * 60 * 1000;
const recentFailureMs = 24 * 60 * 60 * 1000;

export default function GlobalJobStatus() {
  const location = useLocation();
  const projectId = getProjectId(location.pathname);
  const [project, setProject] = useState(null);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [dismissed, setDismissed] = useState(() => new Set(readDismissedJobs()));

  const loadProject = async () => {
    if (!projectId) return;
    try {
      setProject(await getProject(projectId));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    setProject(null);
    setError("");
    if (!projectId) return undefined;
    let cancelled = false;
    const load = async () => {
      try {
        const nextProject = await getProject(projectId);
        if (!cancelled) {
          setProject(nextProject);
          setError("");
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    };
    load();
    const timer = window.setInterval(load, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [projectId]);

  const visibleJob = useMemo(() => selectVisibleJob(project, dismissed), [project, dismissed]);
  if (!projectId || (!visibleJob && !error)) return null;

  const stale = visibleJob && runningStatuses.has(visibleJob.status) && isStaleJob(visibleJob);
  const failed = visibleJob?.status === "Failed";
  const retryable = visibleJob && retryableTypes.has(visibleJob.type) && (failed || stale);
  const destination = visibleJob ? jobDestination(projectId, visibleJob.type) : `/projects/${projectId}`;

  const retryJob = async () => {
    if (!visibleJob || !project) return;
    setRetrying(true);
    setError("");
    try {
      if (runningStatuses.has(visibleJob.status)) {
        await abandonProcessingJob(projectId, visibleJob.id);
      }
      await startRetry(projectId, project, visibleJob.type);
      setDismissed((current) => {
        const next = new Set(current);
        next.delete(visibleJob.id);
        writeDismissedJobs(next);
        return next;
      });
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setRetrying(false);
    }
  };

  const dismissJob = () => {
    if (!visibleJob) return;
    setDismissed((current) => {
      const next = new Set(current);
      next.add(visibleJob.id);
      writeDismissedJobs(next);
      return next;
    });
  };

  return (
    <div className="border-b border-white/10 bg-zinc-950/62 backdrop-blur-xl">
      <div className="mx-auto max-w-7xl px-4 py-3 sm:px-6 lg:px-8">
        {error && !visibleJob ? (
          <div className="rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">{error}</div>
        ) : null}

        {visibleJob ? (
          <section className={`rounded-lg border px-4 py-3 shadow-[0_18px_55px_rgba(0,0,0,0.2)] ${failed || stale ? "border-amber-300/20 bg-amber-300/10" : "border-teal-300/20 bg-teal-300/10"}`}>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-3">
                  <span className={`mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-lg border ${failed || stale ? "border-amber-300/20 bg-black/25 text-amber-100" : "border-teal-300/20 bg-black/25 text-teal-100"}`}>
                    {failed || stale ? <AlertTriangle size={18} /> : visibleJob.status === "Completed" ? <CheckCircle2 size={18} /> : <LoaderCircle size={18} className="animate-spin" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                      <h2 className={`font-semibold ${failed || stale ? "text-amber-100" : "text-teal-50"}`}>
                        {jobTitle(visibleJob, stale)}
                      </h2>
                      <span className="text-sm font-semibold text-zinc-200">{Math.round(visibleJob.progress || 0)}%</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm leading-6 text-zinc-300">{jobMessage(visibleJob, stale)}</p>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-black/40">
                      <div className={`h-full rounded-full transition-all ${failed || stale ? "bg-gradient-to-r from-amber-200 to-rose-200" : "bg-gradient-to-r from-teal-200 to-emerald-200"}`} style={{ width: `${Math.max(0, Math.min(100, visibleJob.progress || 0))}%` }} />
                    </div>
                    <p className="mt-2 text-xs text-zinc-500">Updated {formatDateTime(visibleJob.updatedAt)}</p>
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap lg:justify-end">
                <Button as={Link} to={destination} variant="secondary" className="sm:w-auto">
                  Open
                </Button>
                {retryable ? (
                  <Button type="button" onClick={retryJob} disabled={retrying} className="sm:w-auto">
                    <RotateCcw size={17} />
                    {retrying ? "Retrying..." : "Retry"}
                  </Button>
                ) : null}
                {failed || stale ? (
                  <Button type="button" variant="ghost" onClick={dismissJob} className="sm:w-auto">
                    <X size={17} />
                    Dismiss
                  </Button>
                ) : null}
              </div>
            </div>
            {error ? <p className="mt-3 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}
          </section>
        ) : null}
      </div>
    </div>
  );
}

function selectVisibleJob(project, dismissed) {
  const jobs = project?.processingJobs || [];
  const active = jobs.slice().reverse().find((job) => runningStatuses.has(job.status) && !(isStaleJob(job) && dismissed.has(job.id)));
  if (active) return active;
  return jobs
    .slice()
    .reverse()
    .find((job) => job.status === "Failed" && retryableTypes.has(job.type) && !dismissed.has(job.id) && isRecentFailure(job));
}

function startRetry(projectId, project, type) {
  if (type === "Analysis") return startAnalysis(projectId);
  if (type === "Cleaning") return startCleaning(projectId);
  if (type === "Vocal Enhancement") return startVocalEnhancement(projectId);
  if (type === "Advanced Mix") return startAdvancedMix(projectId);
  if (type === "Instrumental Mix") return startInstrumentalMix(projectId);
  if (type === "Mastering") return startMasteringJob(projectId, masteringRetryPayload(project));
  throw new Error(`${type} jobs cannot be retried from the global status bar yet.`);
}

function masteringRetryPayload(project) {
  const controls = project.masteringSettings?.controls || {};
  const mixVersions = project.mixSettings?.mixVersions || [];
  const selectedMixVersionId = controls.selectedMixVersionId || project.mixSettings?.latestMixVersionId || mixVersions[mixVersions.length - 1]?.id;
  if (!selectedMixVersionId) {
    throw new Error("Generate or select a mix version before retrying mastering.");
  }
  return {
    selectedMixVersionId,
    preset: controls.preset || "Streaming",
    outputFormat: controls.outputFormat || "WAV 16-bit",
    brightness: controls.brightness ?? 0,
    warmth: controls.warmth ?? 0,
    compressionAmount: controls.compressionAmount ?? 45,
    limiterStrength: controls.limiterStrength ?? 55,
    stereoWidth: controls.stereoWidth ?? 55,
  };
}

function jobTitle(job, stale) {
  if (stale) return `${job.type} looks interrupted`;
  if (job.status === "Failed") return `${job.type} failed`;
  return `${job.type} ${job.status.toLowerCase()}`;
}

function jobMessage(job, stale) {
  if (stale) return "This job has not updated in a while. Retry will mark it failed and start a fresh job.";
  return job.errors?.[0]?.error || job.message || "Processing locally.";
}

function jobDestination(projectId, type) {
  if (type === "Analysis") return `/projects/${projectId}/analyze`;
  if (type === "Cleaning") return `/projects/${projectId}/cleaning`;
  if (type === "Vocal Enhancement") return `/projects/${projectId}/vocals`;
  if (type === "Advanced Mix" || type === "Instrumental Mix") return `/projects/${projectId}/mixer`;
  if (type === "Mastering") return `/projects/${projectId}/mastering`;
  return `/projects/${projectId}`;
}

function getProjectId(pathname) {
  const match = pathname.match(/\/projects\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function isStaleJob(job) {
  const timestamp = job?.updatedAt || job?.createdAt;
  if (!timestamp) return true;
  const parsed = new Date(timestamp).getTime();
  if (!Number.isFinite(parsed)) return true;
  return Date.now() - parsed > staleJobMs;
}

function isRecentFailure(job) {
  const timestamp = job?.completedAt || job?.updatedAt || job?.createdAt;
  if (!timestamp) return true;
  const parsed = new Date(timestamp).getTime();
  if (!Number.isFinite(parsed)) return true;
  return Date.now() - parsed < recentFailureMs;
}

function readDismissedJobs() {
  try {
    return JSON.parse(window.sessionStorage.getItem("dismissedProcessingJobs") || "[]");
  } catch {
    return [];
  }
}

function writeDismissedJobs(values) {
  window.sessionStorage.setItem("dismissedProcessingJobs", JSON.stringify([...values].slice(-50)));
}
