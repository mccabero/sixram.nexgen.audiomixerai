import { ArrowLeft, Brain, CheckCircle2, ChevronDown, Library, Mic2, RefreshCw, Save, Settings2, SlidersHorizontal, Sparkles, Stethoscope, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  analyzeVocalRecommendations,
  applyAllVocalRecommendations,
  applyVocalDoctorFix,
  applyVocalRecommendation,
  cancelProcessingJob,
  createCustomVocalPreset,
  deleteCustomVocalPreset,
  deleteVocalEnhancements,
  getProcessingJob,
  getProject,
  listCustomVocalPresets,
  listVocalEnhancerPresets,
  revertVocalEnhancement,
  runVocalQualityDoctor,
  startVocalEnhancement,
  startStemVocalEnhancement,
  updateVocalEnhancementSettings,
} from "../api.js";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import WaveformPreview from "../components/WaveformPreview.jsx";
import { formatDb, formatLufs } from "../utils/format.js";

const runningStatuses = new Set(["Pending", "Processing", "Cancelling"]);
const vocalTypes = new Set(["Lead Vocal", "Backing Vocal"]);
const defaultOptions = {
  presets: ["AI Pop Clean", "AI Studio Clear", "Suno-Style Lead", "Suno Clean Dry", "Natural Clean", "Pop Vocal", "Worship Lead", "Live Vocal Fix", "Bright AI Polish", "Warm Ballad", "Backing Vocal Wide"],
  pitchCorrectionModes: ["Off", "Natural", "Medium", "Strong"],
  fxStyles: ["Dry", "Natural Plate", "Small Hall", "Slap Delay", "Quarter Delay", "Worship Wide"],
  keys: ["Auto", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"],
  scales: ["Major", "Minor", "Chromatic"],
};
const recommendationSettingLabels = [
  ["preset", "Preset"],
  ["pitchCorrection", "Pitch"],
  ["bodyAmount", "Body"],
  ["presenceAmount", "Presence"],
  ["airAmount", "Air"],
  ["deEssAmount", "De-ess"],
  ["compressionAmount", "Comp"],
  ["riderAmount", "Rider"],
  ["breathReductionAmount", "Breath"],
  ["mouthClickReductionAmount", "Clicks"],
  ["key", "Key"],
  ["scale", "Scale"],
];

export default function VocalEnhancerPage() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [options, setOptions] = useState(defaultOptions);
  const [customPresets, setCustomPresets] = useState([]);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [stoppingJobId, setStoppingJobId] = useState("");
  const [busyStemId, setBusyStemId] = useState("");
  const [error, setError] = useState("");
  const [showMoreTools, setShowMoreTools] = useState(true);
  const [recommendationProgress, setRecommendationProgress] = useState(null);
  const [doctorProgress, setDoctorProgress] = useState(null);
  const localProgressTimerRef = useRef(null);

  const stems = project?.stems || [];
  const vocalStems = stems.filter((stem) => vocalTypes.has(stem.stemType) || vocalTypes.has(stem.detectionResult?.suggestedStemType));
  const enabledCount = vocalStems.filter((stem) => vocalSettings(stem).enabled).length;
  const enhancedCount = vocalStems.filter((stem) => stem.vocalEnhancementResult?.status === "Completed").length;
  const useEnhancedCount = vocalStems.filter((stem) => vocalSettings(stem).useEnhancedInMix && stem.vocalEnhancementResult?.status === "Completed").length;
  const recommendationCount = vocalStems.filter((stem) => stem.vocalAnalysisResult?.status === "Completed").length;
  const doctorCount = vocalStems.filter((stem) => stem.vocalQualityDoctorResult?.status === "Completed").length;
  const latestMix = latestMixVersion(project);
  const running = job && runningStatuses.has(job.status);
  const enhancementComplete = enhancedCount > 0;

  const latestJob = useMemo(() => {
    const jobs = project?.processingJobs?.filter((item) => item.type === "Vocal Enhancement") || [];
    return jobs.length ? jobs[jobs.length - 1] : null;
  }, [project]);

  const loadProject = async () => {
    setError("");
    try {
      const [nextProject, presetPayload, customPresetPayload] = await Promise.all([
        getProject(projectId),
        listVocalEnhancerPresets().catch(() => null),
        listCustomVocalPresets().catch(() => null),
      ]);
      setProject(nextProject);
      if (presetPayload) setOptions({ ...defaultOptions, ...presetPayload });
      if (customPresetPayload?.presets) setCustomPresets(customPresetPayload.presets);
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

  useEffect(() => {
    return () => {
      if (localProgressTimerRef.current) window.clearInterval(localProgressTimerRef.current);
    };
  }, []);

  const startEstimatedProgress = (setProgress) => {
    if (localProgressTimerRef.current) window.clearInterval(localProgressTimerRef.current);
    setProgress(4);
    localProgressTimerRef.current = window.setInterval(() => {
      setProgress((current) => {
        const value = typeof current === "number" ? current : 4;
        return Math.min(92, value + Math.max(1, Math.round((94 - value) * 0.12)));
      });
    }, 450);
  };

  const finishEstimatedProgress = (setProgress) => {
    if (localProgressTimerRef.current) {
      window.clearInterval(localProgressTimerRef.current);
      localProgressTimerRef.current = null;
    }
    setProgress(100);
    window.setTimeout(() => setProgress(null), 500);
  };

  const cancelEstimatedProgress = (setProgress) => {
    if (localProgressTimerRef.current) {
      window.clearInterval(localProgressTimerRef.current);
      localProgressTimerRef.current = null;
    }
    setProgress(null);
  };

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

  const runStemEnhancement = async (stem) => {
    setActionLoading("stem-enhance");
    setBusyStemId(stem.id);
    setError("");
    try {
      const nextJob = await startStemVocalEnhancement(projectId, stem.id);
      setJob(nextJob);
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
      setBusyStemId("");
    }
  };

  const stopEnhancement = async () => {
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

  const removeVocalEnhancements = async () => {
    if (!window.confirm("Delete enhanced vocal files and downstream mix/master outputs? Original and cleaned stems are kept.")) return;
    setActionLoading("delete-vocals");
    setError("");
    try {
      setProject(await deleteVocalEnhancements(projectId));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const revertStemEnhancement = async (stem) => {
    if (!window.confirm(`Revert ${stem.originalFilename} to the source vocal and delete downstream generated files?`)) return;
    setActionLoading("revert-vocal");
    setBusyStemId(stem.id);
    setError("");
    try {
      setProject(await revertVocalEnhancement(projectId, stem.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
      setBusyStemId("");
    }
  };

  const analyzeVocals = async () => {
    setActionLoading("analyze-vocals");
    setError("");
    startEstimatedProgress(setRecommendationProgress);
    try {
      setProject(await analyzeVocalRecommendations(projectId));
      finishEstimatedProgress(setRecommendationProgress);
    } catch (err) {
      cancelEstimatedProgress(setRecommendationProgress);
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const applyRecommendation = async (stem) => {
    setBusyStemId(stem.id);
    setError("");
    try {
      const updated = await applyVocalRecommendation(projectId, stem.id);
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

  const applyAllRecommendations = async () => {
    setActionLoading("apply-all-recommendations");
    setError("");
    try {
      setProject(await applyAllVocalRecommendations(projectId));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runDoctor = async () => {
    setActionLoading("doctor");
    setError("");
    startEstimatedProgress(setDoctorProgress);
    try {
      setProject(await runVocalQualityDoctor(projectId));
      finishEstimatedProgress(setDoctorProgress);
    } catch (err) {
      cancelEstimatedProgress(setDoctorProgress);
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const applyDoctorFix = async (stem) => {
    setBusyStemId(stem.id);
    setError("");
    try {
      setProject(await applyVocalDoctorFix(projectId, stem.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyStemId("");
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

  const saveCustomPreset = async (stem) => {
    const fallbackName = `${stem.stemType || "Vocal"} ${new Date().toLocaleDateString()}`;
    const name = window.prompt("Preset name", fallbackName);
    if (!name?.trim()) return;
    setBusyStemId(stem.id);
    setError("");
    try {
      const preset = await createCustomVocalPreset({ name: name.trim(), settings: presetSettingsFromStem(stem) });
      setCustomPresets((current) => [preset, ...current]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyStemId("");
    }
  };

  const applyCustomPreset = async (stem, presetId) => {
    if (!presetId) return;
    const preset = customPresets.find((item) => item.id === presetId);
    if (!preset) return;
    await updateStem(stem, preset.settings || {});
  };

  const removeCustomPreset = async (presetId) => {
    setActionLoading("preset-delete");
    setError("");
    try {
      await deleteCustomVocalPreset(presetId);
      setCustomPresets((current) => current.filter((preset) => preset.id !== presetId));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  if (loading) {
    return <ProcessingPanel title="Loading Vocal Enhancer" message="Reading vocal settings and enhanced stem references." />;
  }

  const actionPanel = running
    ? {
        title: job?.status === "Cancelling" ? "Stopping Vocal Enhancement" : "Enhancing Vocals",
        message: job?.message || "Processing enabled vocal stems.",
        progress: job?.progress || 0,
        actionLabel: "Stop Enhancement",
        actionBusy: stoppingJobId === job?.id || job?.status === "Cancelling",
        actionDisabled: stoppingJobId === job?.id || job?.status === "Cancelling",
        onAction: stopEnhancement,
      }
    : actionLoading === "refresh"
      ? { title: "Refreshing Vocal Enhancer", message: "Reading latest vocal enhancement metadata." }
      : actionLoading === "analyze-vocals"
        ? { title: "Analyzing Vocals", message: "Listening for tone, sibilance, noise, dynamics, and level issues.", progress: recommendationProgress ?? 4 }
        : actionLoading === "doctor"
          ? { title: "Running Vocal Doctor", message: "Checking vocal quality, FX balance, pitch risk, mix placement, and one-click fixes.", progress: doctorProgress ?? 4 }
          : actionLoading === "apply-all-recommendations"
            ? { title: "Applying Vocal Recommendations", message: "Writing recommended settings to all analyzed vocal stems." }
            : actionLoading === "enhance"
              ? { title: "Starting Vocal Enhancement", message: "Creating the local vocal enhancer job." }
              : actionLoading === "stem-enhance"
                ? { title: "Starting Stem Enhancement", message: "Creating a local vocal enhancer job for the selected stem." }
                : actionLoading === "delete-vocals"
                  ? { title: "Deleting Enhanced Vocals", message: "Removing enhanced vocal files and stale downstream mix/master outputs." }
                  : actionLoading === "revert-vocal"
                    ? { title: "Reverting Enhanced Vocal", message: "Switching the selected vocal back to its source audio." }
                    : actionLoading === "preset-delete"
                      ? { title: "Deleting Vocal Preset", message: "Removing the saved local preset." }
                      : busyStemId
                        ? { title: "Saving Vocal Settings", message: "Updating the selected vocal enhancement settings." }
                        : null;

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>

      <section className="mt-5 rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.075] via-white/[0.04] to-teal-300/[0.04] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.24)]">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Step 4</p>
            <h1 className="mt-2 text-3xl font-semibold text-white">Enhance vocals</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
              Polish lead and backing vocals with one local enhancement pass. Enable the vocals you want, then enhance them before mixing.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3 xl:min-w-[420px]">
            <StepSummary label="Vocals" value={vocalStems.length} />
            <StepSummary label="Enabled" value={`${enabledCount}/${vocalStems.length || 0}`} />
            <StepSummary label="Enhanced" value={`${enhancedCount}/${vocalStems.length || 0}`} />
          </div>
        </div>

        <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button type="button" onClick={runEnhancement} disabled={!enabledCount || running || actionLoading === "enhance"}>
            <Sparkles size={17} />
            {enabledCount ? "Enhance vocals" : "Enable vocals first"}
          </Button>
          <Button as={Link} to={`/projects/${projectId}/cleaning`} variant="secondary">
            <ArrowLeft size={17} />
            Back to Step 3
          </Button>
          <Button type="button" variant="secondary" onClick={refreshProject} disabled={actionLoading === "refresh"}>
            <RefreshCw size={17} />
            Refresh
          </Button>
          <Button type="button" variant="ghost" onClick={() => setShowMoreTools((current) => !current)} aria-expanded={showMoreTools}>
            <Settings2 size={17} />
            More tools
            <ChevronDown size={16} className={`transition ${showMoreTools ? "rotate-180" : ""}`} />
          </Button>
        </div>
      </section>

      {showMoreTools ? (
        <section className="mt-4 grid gap-3 lg:grid-cols-3">
          <ToolGroup
            icon={Brain}
            title="Vocal recommendations"
            description={`${recommendationCount}/${vocalStems.length || 0} vocal recommendation${recommendationCount === 1 ? "" : "s"} ready.`}
            badge={recommendationCount ? `${recommendationCount}/${vocalStems.length || 0} done` : ""}
          >
            <Button type="button" variant="secondary" onClick={analyzeVocals} disabled={!vocalStems.length || running || actionLoading === "analyze-vocals"}>
              <Brain size={17} />
              Analyze vocals
            </Button>
            <Button type="button" variant="secondary" onClick={applyAllRecommendations} disabled={!recommendationCount || running || actionLoading === "apply-all-recommendations"}>
              <CheckCircle2 size={17} />
              Apply all
            </Button>
          </ToolGroup>
          <ToolGroup
            icon={Stethoscope}
            title="Vocal doctor"
            description={`${doctorCount}/${vocalStems.length || 0} vocal quality check${doctorCount === 1 ? "" : "s"} complete.`}
            badge={doctorCount ? `${doctorCount}/${vocalStems.length || 0} done` : ""}
          >
            <Button type="button" variant="secondary" onClick={runDoctor} disabled={!vocalStems.length || running || actionLoading === "doctor"}>
              <Stethoscope size={17} />
              Run doctor
            </Button>
          </ToolGroup>
          <ToolGroup icon={Trash2} title="Enhanced output" description={`${enhancedCount}/${vocalStems.length || 0} vocal stem${enhancedCount === 1 ? "" : "s"} enhanced. ${useEnhancedCount} will feed the mixer.`}>
            <Button type="button" variant="danger" onClick={removeVocalEnhancements} disabled={!enhancedCount || running || actionLoading === "delete-vocals"}>
              <Trash2 size={17} />
              Delete enhanced
            </Button>
          </ToolGroup>
        </section>
      ) : null}

      {error ? <p className="mt-5 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}

      {actionPanel ? (
        <div className="mt-5">
          <ProcessingPanel {...actionPanel} />
        </div>
      ) : null}

      {enhancementComplete ? (
        <section className="mt-5 rounded-lg border border-teal-300/30 bg-gradient-to-r from-teal-300/15 via-emerald-300/10 to-white/[0.04] p-4 shadow-[0_0_42px_rgba(45,212,191,0.13)]">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.16em] text-teal-100/80">Step 5 is ready</p>
              <h2 className="mt-1 text-xl font-semibold text-white">Continue to mixer</h2>
              <p className="mt-1 text-sm leading-6 text-zinc-300">Enhanced vocals are ready. Open the mixer to balance the full song.</p>
            </div>
            <Button as={Link} to={`/projects/${projectId}/mixer`} className="w-full justify-center sm:w-auto">
              <SlidersHorizontal size={17} />
              Go to Step 5
            </Button>
          </div>
        </section>
      ) : null}

      <section className="mt-6">
        {vocalStems.length ? (
          <div className="grid gap-4">
            {vocalStems.map((stem) => (
              <VocalStemCard
                key={stem.id}
                stem={stem}
                options={options}
                customPresets={customPresets}
                latestMix={latestMix}
                busy={busyStemId === stem.id}
                pageBusy={running || Boolean(actionLoading)}
                onApplyCustomPreset={applyCustomPreset}
                onApplyDoctorFix={applyDoctorFix}
                onApplyRecommendation={applyRecommendation}
                onDeleteCustomPreset={removeCustomPreset}
                onEnhance={runStemEnhancement}
                onRevert={revertStemEnhancement}
                onSaveCustomPreset={saveCustomPreset}
                onChange={updateStem}
              />
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

function VocalStemCard({ stem, options, customPresets, latestMix, busy, pageBusy, onApplyCustomPreset, onApplyDoctorFix, onApplyRecommendation, onDeleteCustomPreset, onEnhance, onRevert, onSaveCustomPreset, onChange }) {
  const settings = vocalSettings(stem);
  const result = stem.vocalEnhancementResult || {};
  const recommendation = stem.vocalAnalysisResult || {};
  const doctor = stem.vocalQualityDoctorResult || {};
  const sourceUrl = sourcePreviewUrl(stem);
  const enhancedReady = result.status === "Completed" && result.enhancedFileUrl;
  const matchedVolumes = loudnessMatchedVolumes(result);
  const canEnhance = settings.enabled;
  const renderOutdated = enhancedReady && vocalRenderNeedsUpdate(settings, result);

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
        <div className="flex shrink-0 flex-col items-start gap-2 sm:flex-row sm:items-center xl:flex-col xl:items-end">
          <StatusBadge status={stem.vocalEnhancementStatus || "Not Enhanced"} />
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant={!enhancedReady || result.status === "Failed" || renderOutdated ? "primary" : "secondary"}
              className="min-h-8 px-3 py-1 text-xs"
              onClick={() => onEnhance(stem)}
              disabled={busy || pageBusy || !canEnhance}
              title={renderOutdated ? "Settings changed. Re-render this vocal to hear the update." : canEnhance ? "Enhance only this vocal stem" : "Enable this vocal first"}
            >
              <Sparkles size={14} />
              {renderOutdated ? "Re-render changes" : enhancedReady ? "Re-render" : result.status === "Failed" ? "Retry" : "Enhance"}
            </Button>
            {enhancedReady ? (
              <Button
                type="button"
                variant="secondary"
                className="min-h-8 px-3 py-1 text-xs"
                onClick={() => onRevert(stem)}
                disabled={busy || pageBusy}
                title="Revert this vocal back to source audio"
              >
                Revert
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <VocalPresetPanel
        stem={stem}
        customPresets={customPresets}
        busy={busy}
        onApplyPreset={(presetId) => onApplyCustomPreset(stem, presetId)}
        onDeletePreset={onDeleteCustomPreset}
        onSavePreset={() => onSaveCustomPreset(stem)}
      />

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
          <SelectControl label="FX Style" value={settings.fxStyle} options={options.fxStyles} disabled={busy} onChange={(value) => onChange(stem, { fxStyle: value })} />
          <RangeControl label="FX Amount" value={settings.fxAmount} disabled={busy || settings.fxStyle === "Dry"} onChange={(value) => onChange(stem, { fxAmount: value })} />
          <RangeControl label="Pitch Strength" value={settings.pitchStrength} disabled={busy || settings.pitchCorrection === "Off"} onChange={(value) => onChange(stem, { pitchStrength: value })} />
          <RangeControl label="Pitch Humanize" value={settings.pitchHumanize} disabled={busy || settings.pitchCorrection === "Off"} onChange={(value) => onChange(stem, { pitchHumanize: value })} />
        </div>

        <div>
          <div className="mb-3 rounded-lg border border-teal-300/20 bg-teal-300/10 px-3 py-2 text-xs text-teal-100">
            Loudness-matched A/B is applied to preview players when both source and enhanced LUFS are available.
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <PreviewPlayer label={result.sourceKind ? `${result.sourceKind} Source` : "Source"} src={sourceUrl} variant="amber" volume={matchedVolumes.source} volumeLabel={matchedVolumes.sourceLabel} />
            <PreviewPlayer label="Enhanced" src={result.enhancedFileUrl} disabled={!enhancedReady} variant="teal" volume={matchedVolumes.enhanced} volumeLabel={matchedVolumes.enhancedLabel} />
          </div>
        </div>
      </div>

      <ContextPreviewPanel sourceUrl={sourceUrl} enhancedUrl={result.enhancedFileUrl} latestMix={latestMix} enhancedReady={enhancedReady} matchedVolumes={matchedVolumes} />
      <VocalDoctorPanel doctor={doctor} busy={busy} onApply={() => onApplyDoctorFix(stem)} />

      <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-4">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h3 className="font-semibold text-white">Fine Tune</h3>
            <p className="mt-1 text-sm text-zinc-500">Small offsets on top of the selected vocal preset.</p>
          </div>
          <span className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Preset-safe controls</span>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <RangeControl label="Body" value={settings.bodyAmount} min={-50} max={50} disabled={busy} onChange={(value) => onChange(stem, { bodyAmount: value })} />
          <RangeControl label="Presence" value={settings.presenceAmount} min={-50} max={50} disabled={busy} onChange={(value) => onChange(stem, { presenceAmount: value })} />
          <RangeControl label="Air" value={settings.airAmount} min={-50} max={50} disabled={busy} onChange={(value) => onChange(stem, { airAmount: value })} />
          <RangeControl label="De-ess" value={settings.deEssAmount} disabled={busy} onChange={(value) => onChange(stem, { deEssAmount: value })} />
          <RangeControl label="Compression" value={settings.compressionAmount} disabled={busy} onChange={(value) => onChange(stem, { compressionAmount: value })} />
          <RangeControl label="Vocal Rider" value={settings.riderAmount} disabled={busy} onChange={(value) => onChange(stem, { riderAmount: value })} />
          <RangeControl label="Saturation" value={settings.saturationAmount} disabled={busy} onChange={(value) => onChange(stem, { saturationAmount: value })} />
          <RangeControl label="Doubler" value={settings.doublerAmount} disabled={busy} onChange={(value) => onChange(stem, { doublerAmount: value })} />
          <RangeControl label="Breath Softener" value={settings.breathReductionAmount} disabled={busy} onChange={(value) => onChange(stem, { breathReductionAmount: value })} />
          <RangeControl label="Mouth Clicks" value={settings.mouthClickReductionAmount} disabled={busy} onChange={(value) => onChange(stem, { mouthClickReductionAmount: value })} />
        </div>
      </div>

      <VocalRecommendationPanel recommendation={recommendation} busy={busy} onApply={() => onApplyRecommendation(stem)} />
      <VocalReportPanel result={result} />

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

function VocalPresetPanel({ stem, customPresets, busy, onApplyPreset, onDeletePreset, onSavePreset }) {
  return (
    <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Library size={17} className="text-teal-100" />
            <h3 className="font-semibold text-white">Custom Vocal Presets</h3>
          </div>
          <p className="mt-1 text-sm text-zinc-500">Save this stem's controls, then reuse them on other vocals.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <select
            defaultValue=""
            disabled={busy || !customPresets.length}
            onChange={(event) => {
              onApplyPreset(event.target.value);
              event.target.value = "";
            }}
            className="h-10 min-w-48 rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50"
            aria-label={`Apply custom vocal preset to ${stem.originalFilename}`}
          >
            <option value="">Apply preset...</option>
            {customPresets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.name}
              </option>
            ))}
          </select>
          <Button type="button" variant="secondary" onClick={onSavePreset} disabled={busy}>
            <Save size={17} />
            Save Preset
          </Button>
        </div>
      </div>
      {customPresets.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {customPresets.slice(0, 8).map((preset) => (
            <span key={preset.id} className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.05] py-1 pl-3 pr-1 text-xs font-medium text-zinc-200">
              {preset.name}
              <button type="button" onClick={() => onDeletePreset(preset.id)} className="grid h-6 w-6 place-items-center rounded-full text-zinc-400 transition hover:bg-rose-400/15 hover:text-rose-100" aria-label={`Delete ${preset.name}`}>
                <Trash2 size={13} />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-sm text-zinc-500">No custom presets saved yet.</p>
      )}
    </div>
  );
}

function ContextPreviewPanel({ sourceUrl, enhancedUrl, latestMix, enhancedReady, matchedVolumes }) {
  const bedRef = useRef(null);
  const sourceRef = useRef(null);
  const enhancedRef = useRef(null);
  const [bedVolume, setBedVolume] = useState(24);
  const [mode, setMode] = useState("");

  const stopAll = () => {
    [bedRef, sourceRef, enhancedRef].forEach((ref) => {
      if (ref.current) {
        ref.current.pause();
        ref.current.currentTime = 0;
      }
    });
    setMode("");
  };

  const playContext = async (nextMode) => {
    const vocalRef = nextMode === "enhanced" ? enhancedRef : sourceRef;
    if (!latestMix?.url || !vocalRef.current || (nextMode === "enhanced" && !enhancedReady)) return;
    stopAll();
    setMode(nextMode);
    if (bedRef.current) {
      bedRef.current.volume = Math.max(0, Math.min(1, bedVolume / 100));
      bedRef.current.currentTime = 0;
    }
    vocalRef.current.volume = nextMode === "enhanced" ? matchedVolumes.enhanced : matchedVolumes.source;
    vocalRef.current.currentTime = 0;
    try {
      await Promise.all([bedRef.current?.play(), vocalRef.current.play()]);
    } catch {
      setMode("");
    }
  };

  useEffect(() => {
    if (bedRef.current) bedRef.current.volume = Math.max(0, Math.min(1, bedVolume / 100));
  }, [bedVolume]);

  const disabledReason = !latestMix?.url
    ? "Available after Step 5 creates a mix version."
    : !sourceUrl
      ? "Source audio is not available for this vocal."
      : !enhancedReady
        ? "Enhance this vocal first to compare the enhanced version in the mix."
        : "";

  return (
    <div className="mt-4 rounded-lg border border-fuchsia-300/15 bg-fuchsia-300/[0.055] p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h3 className="font-semibold text-white">A/B In Mix Context</h3>
          <p className="mt-1 text-sm text-zinc-400">{latestMix?.url ? `Using ${latestMix.label} quietly underneath the selected vocal.` : "Generate a mix version first to preview vocals in context."}</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button type="button" variant={mode === "source" ? "primary" : "secondary"} onClick={() => playContext("source")} disabled={!latestMix?.url || !sourceUrl} title={!latestMix?.url ? "Create a mix version first." : !sourceUrl ? "Source audio is not available." : "Preview source vocal with the latest mix."}>
            Source In Mix
          </Button>
          <Button type="button" variant={mode === "enhanced" ? "primary" : "secondary"} onClick={() => playContext("enhanced")} disabled={!latestMix?.url || !enhancedReady} title={!latestMix?.url ? "Create a mix version first." : !enhancedReady ? "Enhance this vocal first." : "Preview enhanced vocal with the latest mix."}>
            Enhanced In Mix
          </Button>
          <Button type="button" variant="secondary" onClick={stopAll} disabled={!mode} title={!mode ? "Nothing is playing yet." : "Stop preview playback."}>
            Stop
          </Button>
        </div>
      </div>
      {disabledReason ? (
        <p className="mt-3 rounded-lg border border-fuchsia-200/15 bg-black/20 px-3 py-2 text-sm text-fuchsia-50">
          {disabledReason}
        </p>
      ) : null}
      <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_220px] lg:items-center">
        <audio ref={bedRef} src={latestMix?.url || ""} onEnded={() => setMode("")} />
        <audio ref={sourceRef} src={sourceUrl || ""} onEnded={() => setMode("")} />
        <audio ref={enhancedRef} src={enhancedUrl || ""} onEnded={() => setMode("")} />
        <p className="truncate text-xs text-zinc-500">{latestMix?.path || "No mix bed available."}</p>
        <label>
          <span className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">
            <span>Mix Bed</span>
            <span className="normal-case tracking-normal text-zinc-300">{bedVolume}%</span>
          </span>
          <input type="range" min={0} max={60} value={bedVolume} onChange={(event) => setBedVolume(Number(event.target.value))} className="w-full accent-fuchsia-300" />
        </label>
      </div>
    </div>
  );
}

function VocalDoctorPanel({ doctor, busy, onApply }) {
  const ready = doctor.status === "Completed";
  const failed = doctor.status === "Failed";
  const problems = doctor.problems || [];
  const settings = doctor.recommendedSettings || {};
  const mixControls = doctor.mixControlSuggestions || {};
  const hasFix = Object.keys(settings).length > 0 || Object.keys(mixControls).length > 0;

  return (
    <div className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/[0.065] p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Stethoscope size={17} className="text-amber-100" />
            <h3 className="font-semibold text-white">Vocal Quality Doctor</h3>
            {ready ? <span className={`rounded-full border px-2 py-1 text-xs font-semibold ${doctorScoreClass(doctor.score)}`}>{doctor.score}/100</span> : null}
          </div>
          <p className="mt-1 text-sm text-zinc-400">
            {ready ? doctor.summary : failed ? doctor.error || "Vocal Doctor could not diagnose this stem." : "Run Vocal Doctor to explain why this vocal may sound rough and get a one-click fix."}
          </p>
        </div>
        {ready && hasFix ? (
          <Button type="button" variant="secondary" onClick={onApply} disabled={busy}>
            <CheckCircle2 size={17} />
            Apply Doctor Fix
          </Button>
        ) : null}
      </div>

      {ready ? (
        <div className="mt-4 grid gap-3 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-lg border border-white/10 bg-black/20 p-3">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Diagnosis</p>
            {problems.length ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {problems.map((problem) => (
                  <span key={`${problem.type}-${problem.message}`} className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${severityClass(problem.severity)}`} title={problem.message}>
                    {problem.type}
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm text-zinc-500">No major vocal quality blockers found.</p>
            )}
            {doctor.nextSteps?.length ? (
              <div className="mt-3 space-y-1">
                {doctor.nextSteps.slice(0, 4).map((step) => (
                  <p key={step} className="text-xs text-zinc-400">{step}</p>
                ))}
              </div>
            ) : null}
          </div>

          <div className="rounded-lg border border-white/10 bg-black/20 p-3">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Doctor Fixes</p>
            {hasFix ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {Object.entries(settings).map(([key, value]) => (
                  <span key={`vocal-${key}`} className="rounded-full border border-amber-200/20 bg-amber-300/10 px-2.5 py-1 text-xs font-medium text-amber-50">
                    {doctorPatchLabel(key)}: <span className="text-white">{formatRecommendedValue(key, value)}</span>
                  </span>
                ))}
                {Object.entries(mixControls).map(([key, value]) => (
                  <span key={`mix-${key}`} className="rounded-full border border-fuchsia-200/20 bg-fuchsia-300/10 px-2.5 py-1 text-xs font-medium text-fuchsia-50">
                    Mix {doctorPatchLabel(key)}: <span className="text-white">{formatRecommendedValue(key, value)}</span>
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm text-zinc-500">No setting changes needed right now.</p>
            )}
            {doctor.warnings?.length ? (
              <p className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">{doctor.warnings[0]}</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function VocalRecommendationPanel({ recommendation, busy, onApply }) {
  const ready = recommendation.status === "Completed";
  const failed = recommendation.status === "Failed";
  const issues = recommendation.issues || [];
  const settings = recommendation.recommendedSettings || {};

  return (
    <div className="mt-4 rounded-lg border border-cyan-300/15 bg-cyan-300/[0.06] p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Brain size={17} className="text-cyan-100" />
            <h3 className="font-semibold text-white">Vocal Recommendation</h3>
            {ready ? <span className="rounded-full border border-cyan-200/20 bg-cyan-200/10 px-2 py-1 text-xs font-semibold text-cyan-100">{recommendation.confidence}% confidence</span> : null}
          </div>
          <p className="mt-1 text-sm text-zinc-400">
            {ready ? recommendation.summary : failed ? recommendation.error || "Recommendation analysis failed." : "Run Analyze Vocals to get automatic settings for this stem."}
          </p>
        </div>
        {ready ? (
          <Button type="button" variant="secondary" onClick={onApply} disabled={busy}>
            <CheckCircle2 size={17} />
            Apply Recommendation
          </Button>
        ) : null}
      </div>

      {ready ? (
        <>
          <div className="mt-4 grid gap-3 lg:grid-cols-[0.9fr_1.1fr]">
            <div className="rounded-lg border border-white/10 bg-black/20 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Findings</p>
              {issues.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {issues.map((issue) => (
                    <span key={`${issue.type}-${issue.message}`} className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${severityClass(issue.severity)}`} title={issue.message}>
                      {issue.type}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm text-zinc-500">No major vocal issues found.</p>
              )}
            </div>
            <div className="rounded-lg border border-white/10 bg-black/20 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Suggested Settings</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {recommendationSettingLabels.map(([key, label]) => (
                  <span key={key} className="rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-xs font-medium text-zinc-200">
                    {label}: <span className="text-white">{formatRecommendedValue(key, settings[key])}</span>
                  </span>
                ))}
              </div>
            </div>
          </div>
          {recommendation.warnings?.length ? (
            <p className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">{recommendation.warnings[0]}</p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function VocalReportPanel({ result }) {
  const report = result.report || {};
  if (result.status !== "Completed" || !report.summary) return null;
  return (
    <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-4">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="font-semibold text-white">Vocal Report</h3>
          <p className="mt-1 text-sm text-zinc-400">{report.summary}</p>
        </div>
        <span className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Before / After</span>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Readout label="LUFS Delta" value={formatDelta(report.deltas?.integratedLufs, " dB")} />
        <Readout label="Peak Delta" value={formatDelta(report.deltas?.peakDbfs, " dB")} />
        <Readout label="Noise Delta" value={formatDelta(report.deltas?.noiseFloorDbfs, " dB")} />
      </div>
      {report.improvements?.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {report.improvements.slice(0, 6).map((item) => (
            <span key={item} className="rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-xs font-medium text-zinc-200">
              {item}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function StepSummary({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-3">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function ToolGroup({ icon: Icon, title, description, badge = "", children }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/25 text-teal-200">
          <Icon size={17} />
        </span>
        <div>
          <h2 className="font-semibold text-white">{title}</h2>
          <p className="mt-1 text-sm leading-6 text-zinc-400">{description}</p>
        </div>
        </div>
        {badge ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-emerald-300/25 bg-emerald-300/10 px-2.5 py-1 text-xs font-semibold text-emerald-100">
            <CheckCircle2 size={13} />
            {badge}
          </span>
        ) : null}
      </div>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">{children}</div>
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

function RangeControl({ label, value, min = 0, max = 100, disabled, onChange }) {
  const numericValue = Number.isFinite(value) ? value : 0;
  const [draft, setDraft] = useState(numericValue);

  useEffect(() => {
    setDraft(numericValue);
  }, [numericValue]);

  const commit = (nextValue) => {
    if (Number(nextValue) !== numericValue) onChange(Number(nextValue));
  };

  return (
    <label className="block">
      <span className="mb-2 flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">
        <span>{label}</span>
        <span className="normal-case tracking-normal text-zinc-300">{formatRangeValue(draft, min)}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={1}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(Number(event.target.value))}
        onPointerUp={(event) => commit(event.currentTarget.value)}
        onBlur={(event) => commit(event.currentTarget.value)}
        className="w-full accent-teal-300 disabled:opacity-50"
      />
    </label>
  );
}

function PreviewPlayer({ label, src, disabled, variant, volume = 1, volumeLabel = "" }) {
  const audioRef = useRef(null);
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.volume = Math.max(0, Math.min(1, volume));
    }
  }, [volume, src]);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</p>
        {volumeLabel ? <span className="text-xs text-zinc-500">{volumeLabel}</span> : null}
      </div>
      <div className="space-y-2 rounded-lg border border-white/10 bg-black/20 p-3">
        <WaveformPreview src={src} disabled={disabled || !src} variant={variant} />
        {src && !disabled ? <audio ref={audioRef} src={src} controls className="h-9 w-full" /> : <p className="py-2 text-sm text-zinc-500">No preview yet.</p>}
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
    preset: "AI Pop Clean",
    pitchCorrection: "Off",
    key: "Auto",
    scale: "Major",
    fxStyle: "Dry",
    fxAmount: 0,
    bodyAmount: 0,
    presenceAmount: 0,
    airAmount: 0,
    deEssAmount: 50,
    compressionAmount: 40,
    riderAmount: 36,
    saturationAmount: 18,
    doublerAmount: 16,
    breathReductionAmount: 35,
    mouthClickReductionAmount: 30,
    pitchStrength: 42,
    pitchHumanize: 72,
    useEnhancedInMix: true,
    ...(stem.vocalEnhancementSettings || {}),
  };
}

function vocalRenderNeedsUpdate(settings, result) {
  if (result?.status !== "Completed") return false;
  const fields = [
    "preset",
    "pitchCorrection",
    "key",
    "scale",
    "fxStyle",
    "fxAmount",
    "bodyAmount",
    "presenceAmount",
    "airAmount",
    "deEssAmount",
    "compressionAmount",
    "riderAmount",
    "saturationAmount",
    "doublerAmount",
    "breathReductionAmount",
    "mouthClickReductionAmount",
    "pitchStrength",
    "pitchHumanize",
  ];

  return fields.some((field) => {
    const currentValue = settings[field];
    const renderedValue = result[field];
    if (typeof currentValue === "number" || typeof renderedValue === "number") {
      return Math.abs(Number(currentValue || 0) - Number(renderedValue || 0)) > 0.01;
    }
    return `${currentValue ?? ""}` !== `${renderedValue ?? ""}`;
  });
}

function presetSettingsFromStem(stem) {
  const settings = vocalSettings(stem);
  const keys = [
    "preset",
    "pitchCorrection",
    "key",
    "scale",
    "fxStyle",
    "fxAmount",
    "bodyAmount",
    "presenceAmount",
    "airAmount",
    "deEssAmount",
    "compressionAmount",
    "riderAmount",
    "saturationAmount",
    "doublerAmount",
    "breathReductionAmount",
    "mouthClickReductionAmount",
    "pitchStrength",
    "pitchHumanize",
  ];
  return Object.fromEntries(keys.map((key) => [key, settings[key]]));
}

function latestMixVersion(project) {
  const versions = project?.mixSettings?.mixVersions || [];
  if (!versions.length) return null;
  const latestId = project?.mixSettings?.latestMixVersionId;
  const version = versions.find((item) => item.id === latestId) || versions[versions.length - 1];
  return {
    id: version.id,
    label: version.label || `Mix v${String(version.versionNumber).padStart(3, "0")}`,
    url: version.mp3Url || version.wavUrl,
    path: version.mp3Path || version.wavPath,
  };
}

function formatRangeValue(value, min) {
  if (min < 0) return signedPercent(value);
  return `${Math.round(value)}%`;
}

function signedPercent(value) {
  if (!Number.isFinite(value)) return "--";
  return `${value > 0 ? "+" : ""}${Math.round(value)}%`;
}

function formatRecommendedValue(key, value) {
  if (value === undefined || value === null || value === "") return "--";
  if (["bodyAmount", "presenceAmount", "airAmount"].includes(key)) return signedPercent(Number(value));
  if (["vocalBoost", "vocalBusLevel"].includes(key)) return formatDb(Number(value));
  if (typeof value === "number") return `${Math.round(value)}%`;
  if (typeof value === "boolean") return value ? "On" : "Off";
  return value;
}

function doctorPatchLabel(key) {
  const labels = {
    enabled: "Enable",
    preset: "Preset",
    pitchCorrection: "Pitch",
    key: "Key",
    scale: "Scale",
    fxStyle: "FX",
    fxAmount: "FX Amount",
    bodyAmount: "Body",
    presenceAmount: "Presence",
    airAmount: "Air",
    deEssAmount: "De-ess",
    compressionAmount: "Comp",
    riderAmount: "Rider",
    saturationAmount: "Saturation",
    doublerAmount: "Doubler",
    breathReductionAmount: "Breath",
    mouthClickReductionAmount: "Clicks",
    pitchStrength: "Pitch Strength",
    pitchHumanize: "Humanize",
    useEnhancedInMix: "Use In Mix",
    vocalBoost: "Vocal Boost",
    vocalBusLevel: "Bus Level",
    vocalGlueAmount: "Glue",
    vocalDelayAmount: "Delay",
    vocalReverbAmount: "Reverb",
    reverbAmount: "Global Reverb",
  };
  return labels[key] || key;
}

function doctorScoreClass(score) {
  if (score < 55) return "border-rose-300/25 bg-rose-400/10 text-rose-100";
  if (score < 75) return "border-amber-300/25 bg-amber-300/10 text-amber-100";
  return "border-emerald-300/25 bg-emerald-300/10 text-emerald-100";
}

function severityClass(severity) {
  if (severity === "High") return "border-rose-300/25 bg-rose-400/10 text-rose-100";
  if (severity === "Medium") return "border-amber-300/25 bg-amber-300/10 text-amber-100";
  return "border-cyan-300/20 bg-cyan-300/10 text-cyan-100";
}

function formatDelta(value, suffix = "") {
  if (!Number.isFinite(value)) return "--";
  return `${value > 0 ? "+" : ""}${Number(value).toFixed(1)}${suffix}`;
}

function loudnessMatchedVolumes(result) {
  const sourceLufs = result.originalMetrics?.integratedLufs;
  const enhancedLufs = result.enhancedMetrics?.integratedLufs;
  if (!Number.isFinite(sourceLufs) || !Number.isFinite(enhancedLufs)) {
    return { source: 1, enhanced: 1, sourceLabel: "", enhancedLabel: "" };
  }
  const delta = enhancedLufs - sourceLufs;
  if (Math.abs(delta) < 0.2) {
    return { source: 1, enhanced: 1, sourceLabel: "matched", enhancedLabel: "matched" };
  }
  if (delta > 0) {
    const enhanced = dbToVolume(-delta);
    return { source: 1, enhanced, sourceLabel: "0.0 dB", enhancedLabel: `${(-delta).toFixed(1)} dB` };
  }
  const source = dbToVolume(delta);
  return { source, enhanced: 1, sourceLabel: `${delta.toFixed(1)} dB`, enhancedLabel: "0.0 dB" };
}

function dbToVolume(db) {
  return Math.max(0.05, Math.min(1, Math.pow(10, db / 20)));
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
