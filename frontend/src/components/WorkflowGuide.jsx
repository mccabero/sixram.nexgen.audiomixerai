import { BarChart3, CheckCircle2, Circle, Eraser, LockKeyhole, Mic2, SlidersHorizontal, Sparkles, UploadCloud } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { updateCleaningSettings, updateVocalEnhancementSettings } from "../api.js";
import Button from "./Button.jsx";

const stepDefinitions = [
  {
    key: "upload",
    number: 1,
    label: "Upload",
    title: "Upload Stems",
    icon: UploadCloud,
    href: (projectId) => `/projects/${projectId}/upload`,
  },
  {
    key: "analyze",
    number: 2,
    label: "Analyze",
    title: "Analyze + Detect",
    icon: BarChart3,
    href: (projectId) => `/projects/${projectId}/analyze`,
  },
  {
    key: "cleaning",
    number: 3,
    label: "Clean",
    title: "Clean Stems",
    icon: Eraser,
    href: (projectId) => `/projects/${projectId}/cleaning`,
    optional: true,
  },
  {
    key: "vocals",
    number: 4,
    label: "Vocals",
    title: "Enhance Vocals",
    icon: Mic2,
    href: (projectId) => `/projects/${projectId}/vocals`,
    optional: true,
  },
  {
    key: "mixer",
    number: 5,
    label: "Mix",
    title: "Auto Mix",
    icon: SlidersHorizontal,
    href: (projectId) => `/projects/${projectId}/mixer`,
  },
  {
    key: "export",
    number: 6,
    label: "Master",
    title: "Master + Export",
    icon: Sparkles,
    href: (projectId) => `/projects/${projectId}/mastering`,
  },
];

export default function WorkflowGuide({ project, currentStep = "", className = "", onProjectRefresh }) {
  const [sourceBusy, setSourceBusy] = useState("");
  const [sourceError, setSourceError] = useState("");

  if (!project) return null;

  const state = getWorkflowState(project);
  const nextStep = state.nextStep;
  const NextIcon = nextStep.icon;
  const activeKey = currentStep === "project" ? nextStep.key : currentStep || nextStep.key;
  const finalStepPage = currentStep === "export";

  const setCleanedSource = async (useCleaned) => {
    if (!state.cleanedSourceControl?.availableCount) return;
    setSourceBusy(useCleaned ? "cleaned-on" : "cleaned-off");
    setSourceError("");
    try {
      await Promise.all(
        state.cleanedReadyStems.map((stem) =>
          updateCleaningSettings(project.id, stem.id, {
            useCleanedInMix: useCleaned,
          }),
        ),
      );
      await onProjectRefresh?.();
    } catch (err) {
      setSourceError(err.message);
    } finally {
      setSourceBusy("");
    }
  };

  const setEnhancedSource = async (useEnhanced) => {
    if (!state.enhancedSourceControl?.availableCount) return;
    setSourceBusy(useEnhanced ? "enhanced-on" : "enhanced-off");
    setSourceError("");
    try {
      await Promise.all(
        state.enhancedReadyVocals.map((stem) =>
          updateVocalEnhancementSettings(project.id, stem.id, {
            useEnhancedInMix: useEnhanced,
          }),
        ),
      );
      await onProjectRefresh?.();
    } catch (err) {
      setSourceError(err.message);
    } finally {
      setSourceBusy("");
    }
  };

  return (
    <section className={`workflow-guide rounded-2xl border border-cyan-300/20 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.18),transparent_36%),linear-gradient(180deg,rgba(10,18,32,0.96),rgba(4,10,20,0.96))] p-4 shadow-[0_20px_60px_rgba(8,145,178,0.12)] ${className}`}>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-100/90">Step-by-step workflow</p>
          <h2 className="mt-2 text-lg font-semibold text-white">{finalStepPage ? "Final Step" : "Next"}: {nextStep.title}</h2>
          <p className="mt-1 text-sm text-slate-200/80">{state.summary}</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap xl:justify-end">
          {state.skipCleaningAvailable ? (
            <Button as={Link} to={state.skipCleaningHref(project.id)} variant="secondary" className="sm:w-auto">
              <SlidersHorizontal size={17} />
              Skip cleaning
            </Button>
          ) : null}
          {!finalStepPage ? (
            <Button as={Link} to={nextStep.href(project.id)} className="sm:w-auto">
              <NextIcon size={17} />
              Next step
            </Button>
          ) : null}
        </div>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        {state.steps.map((step) => (
          <WorkflowStepCard key={step.key} step={step} active={step.key === activeKey} projectId={project.id} />
        ))}
      </div>

      {state.cleanedSourceControl || state.enhancedSourceControl ? (
        <div className="workflow-guide-sources mt-4 rounded-xl border border-cyan-300/14 bg-slate-950/55 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
          <div className="flex flex-col gap-1 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-100/90">Next Step Input</p>
              <h3 className="mt-1 text-sm font-semibold text-white">Choose which prepared stems continue forward</h3>
              <p className="mt-1 text-sm text-slate-200/75">{state.sourceSummary}</p>
            </div>
            <p className="text-xs text-slate-300/55">Per-stem controls still remain on the Clean Stems and Enhance Vocals pages.</p>
          </div>

          <div className="mt-3 grid gap-3 xl:grid-cols-2">
            {state.cleanedSourceControl ? (
              <WorkflowSourceCard
                title={state.cleanedSourceControl.title}
                detail={state.cleanedSourceControl.detail}
                currentLabel={state.cleanedSourceControl.currentLabel}
                primaryLabel={state.cleanedSourceControl.primaryLabel}
                secondaryLabel={state.cleanedSourceControl.secondaryLabel}
                primaryActive={state.cleanedSourceControl.primaryActive}
                secondaryActive={state.cleanedSourceControl.secondaryActive}
                busy={sourceBusy === "cleaned-on" || sourceBusy === "cleaned-off"}
                onPrimary={() => setCleanedSource(true)}
                onSecondary={() => setCleanedSource(false)}
              />
            ) : null}
            {state.enhancedSourceControl ? (
              <WorkflowSourceCard
                title={state.enhancedSourceControl.title}
                detail={state.enhancedSourceControl.detail}
                currentLabel={state.enhancedSourceControl.currentLabel}
                primaryLabel={state.enhancedSourceControl.primaryLabel}
                secondaryLabel={state.enhancedSourceControl.secondaryLabel}
                primaryActive={state.enhancedSourceControl.primaryActive}
                secondaryActive={state.enhancedSourceControl.secondaryActive}
                busy={sourceBusy === "enhanced-on" || sourceBusy === "enhanced-off"}
                onPrimary={() => setEnhancedSource(true)}
                onSecondary={() => setEnhancedSource(false)}
              />
            ) : null}
          </div>

          {sourceError ? <p className="mt-3 rounded-lg border border-rose-300/30 bg-rose-400/14 px-3 py-2 text-sm text-rose-50">{sourceError}</p> : null}
        </div>
      ) : null}
    </section>
  );
}

function WorkflowSourceCard({
  title,
  detail,
  currentLabel,
  primaryLabel,
  secondaryLabel,
  primaryActive,
  secondaryActive,
  busy,
  onPrimary,
  onSecondary,
}) {
  return (
    <div className="workflow-source-card rounded-xl border border-white/12 bg-slate-950/70 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">{title}</p>
          <p className="mt-1 text-xs leading-5 text-slate-200/72">{detail}</p>
        </div>
        <span className="rounded-full border border-cyan-300/18 bg-cyan-400/10 px-2 py-0.5 text-[11px] font-semibold text-cyan-50">{currentLabel}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={busy}
          aria-pressed={primaryActive}
          onClick={primaryActive ? undefined : onPrimary}
          className={`min-h-10 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
            primaryActive
              ? "border-cyan-100/75 bg-gradient-to-br from-cyan-300 via-sky-300 to-sky-400 text-slate-950 shadow-[0_0_0_1px_rgba(224,242,254,0.35),0_12px_28px_rgba(14,165,233,0.28)]"
              : "border-white/12 bg-slate-900/80 text-slate-100 hover:border-cyan-300/24 hover:bg-slate-900"
          }`}
        >
          {busy && !primaryActive ? "Saving..." : primaryLabel}
        </button>
        <button
          type="button"
          disabled={busy}
          aria-pressed={secondaryActive}
          onClick={secondaryActive ? undefined : onSecondary}
          className={`min-h-10 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
            secondaryActive
              ? "border-cyan-100/75 bg-gradient-to-br from-cyan-300 via-sky-300 to-sky-400 text-slate-950 shadow-[0_0_0_1px_rgba(224,242,254,0.35),0_12px_28px_rgba(14,165,233,0.28)]"
              : "border-white/12 bg-slate-900/80 text-slate-100 hover:border-cyan-300/24 hover:bg-slate-900"
          }`}
        >
          {busy && !secondaryActive ? "Saving..." : secondaryLabel}
        </button>
      </div>
    </div>
  );
}

function WorkflowStepCard({ step, active, projectId }) {
  const Icon = step.icon;
  const CardTag = step.available ? Link : "div";
  const cardProps = step.available ? { to: step.href(projectId) } : {};
  const statusClass = statusStyles[step.status] || statusStyles.locked;
  const toneClass = active
    ? "border-cyan-100/75 bg-[linear-gradient(180deg,rgba(103,232,249,0.34),rgba(14,165,233,0.22))] shadow-[0_0_0_1px_rgba(224,242,254,0.3),0_18px_40px_rgba(14,165,233,0.24)]"
    : step.available
      ? "border-white/12 bg-slate-950/72 hover:border-cyan-300/28 hover:bg-slate-900/92"
      : "border-slate-700/45 bg-slate-950/42 opacity-80";
  const stepNumberClass = active ? "text-slate-950/80" : "text-slate-300/62";
  const titleClass = active ? "text-slate-950" : "text-white";
  const detailClass = active ? "text-slate-900/72" : "text-slate-200/68";

  return (
    <CardTag {...cardProps} className={`rounded-lg border p-3 transition ${toneClass}`}>
      <div className="flex items-start justify-between gap-3">
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border ${statusClass.icon}`}>
          <Icon size={17} />
        </span>
        <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass.badge}`}>
          {step.status === "complete" ? <CheckCircle2 size={12} /> : step.status === "locked" ? <LockKeyhole size={12} /> : <Circle size={12} />}
          {step.statusLabel}
        </span>
      </div>
      <p className={`mt-3 text-xs font-semibold uppercase tracking-[0.12em] ${stepNumberClass}`}>Step {step.number}</p>
      <p className={`mt-1 truncate text-sm font-semibold ${titleClass}`}>{step.title}</p>
      <p className={`mt-1 min-h-5 truncate text-xs ${detailClass}`}>{step.detail}</p>
    </CardTag>
  );
}

function getWorkflowState(project) {
  const stems = project.stems || [];
  const mixVersions = project.mixSettings?.mixVersions || [];
  const masterVersions = project.masteringSettings?.masterVersions || [];
  const uploadedCount = stems.length;
  const analyzedCount = stems.filter((stem) => stem.analysisStatus === "Completed").length;
  const detectedCount = stems.filter((stem) => stem.detectionResult || stem.stemTypeSource === "Detected" || stem.stemTypeSource === "Manual" || stem.stemType !== "Unknown").length;
  const cleanedCount = stems.filter((stem) => stem.cleaningStatus === "Cleaned" || stem.cleaningResult?.status === "Completed").length;
  const vocalCount = stems.filter((stem) => ["Lead Vocal", "Backing Vocal"].includes(stem.stemType) || ["Lead Vocal", "Backing Vocal"].includes(stem.detectionResult?.suggestedStemType)).length;
  const enhancedCount = stems.filter((stem) => stem.vocalEnhancementResult?.status === "Completed").length;
  const cleanedReadyStems = stems.filter((stem) => stem.cleaningResult?.status === "Completed" && (stem.cleaningResult?.cleanedFileUrl || stem.cleaningResult?.cleanedFilePath));
  const enhancedReadyVocals = stems.filter(
    (stem) =>
      (["Lead Vocal", "Backing Vocal"].includes(stem.stemType) || ["Lead Vocal", "Backing Vocal"].includes(stem.detectionResult?.suggestedStemType)) &&
      stem.vocalEnhancementResult?.status === "Completed" &&
      (stem.vocalEnhancementResult?.enhancedFileUrl || stem.vocalEnhancementResult?.enhancedFilePath),
  );
  const cleanedSelectedCount = cleanedReadyStems.filter((stem) => stem.cleaningSettings?.useCleanedInMix !== false).length;
  const enhancedSelectedCount = enhancedReadyVocals.filter((stem) => stem.vocalEnhancementSettings?.useEnhancedInMix !== false).length;
  const hasStems = uploadedCount > 0;
  const analysisComplete = hasStems && analyzedCount === uploadedCount;
  const hasCleanedStems = cleanedCount > 0;
  const hasEnhancedVocals = enhancedCount > 0;
  const hasMix = mixVersions.length > 0;
  const hasMaster = masterVersions.length > 0;
  const cleaningSkipped = hasMix && !hasCleanedStems;
  const vocalEnhancementSkipped = hasMix && vocalCount > 0 && !hasEnhancedVocals;

  const availability = {
    upload: true,
    analyze: hasStems,
    cleaning: analysisComplete,
    vocals: analysisComplete && vocalCount > 0,
    mixer: analysisComplete || hasMix,
    export: hasMix,
  };

  const completion = {
    upload: hasStems,
    analyze: analysisComplete,
    cleaning: hasCleanedStems || cleaningSkipped,
    vocals: hasEnhancedVocals || vocalEnhancementSkipped || vocalCount === 0,
    mixer: hasMix,
    export: hasMaster,
  };

  let nextKey = "upload";
  if (hasStems && !analysisComplete) nextKey = "analyze";
  else if (analysisComplete && !hasCleanedStems && !hasMix) nextKey = "cleaning";
  else if (analysisComplete && vocalCount > 0 && !hasEnhancedVocals && !hasMix) nextKey = "vocals";
  else if (analysisComplete && !hasMix) nextKey = "mixer";
  else if (hasMix && !hasMaster) nextKey = "export";
  else if (hasMaster) nextKey = "export";

  const steps = stepDefinitions.map((definition) => {
    const status = getStepStatus(definition.key, completion, availability, nextKey, cleaningSkipped, vocalEnhancementSkipped);
    return {
      ...definition,
      available: availability[definition.key],
      status,
      statusLabel: statusLabels[status],
      detail: stepDetail(definition.key, {
        uploadedCount,
        analyzedCount,
        detectedCount,
        cleanedCount,
        vocalCount,
        enhancedCount,
        mixCount: mixVersions.length,
        masterCount: masterVersions.length,
        cleaningSkipped,
        vocalEnhancementSkipped,
      }),
    };
  });

  const nextStep = steps.find((step) => step.key === nextKey) || steps[0];
  const cleanedSourceControl = cleanedReadyStems.length
    ? {
        availableCount: cleanedReadyStems.length,
        title: nextKey === "vocals" ? "Vocal Input Source" : "Cleaned Stem Source",
        detail:
          nextKey === "vocals"
            ? `${cleanedSelectedCount}/${cleanedReadyStems.length} cleaned stem${cleanedReadyStems.length === 1 ? "" : "s"} feed the Vocal Enhancer right now.`
            : `${cleanedSelectedCount}/${cleanedReadyStems.length} prepared stem${cleanedReadyStems.length === 1 ? "" : "s"} are set to continue as cleaned audio.`,
        currentLabel: cleanedSelectedCount === cleanedReadyStems.length ? "Using cleaned" : cleanedSelectedCount === 0 ? "Using originals" : `${cleanedSelectedCount}/${cleanedReadyStems.length} cleaned`,
        primaryLabel: `Use cleaned${cleanedReadyStems.length > 1 ? ` (${cleanedReadyStems.length})` : ""}`,
        secondaryLabel: "Use originals",
        primaryActive: cleanedSelectedCount === cleanedReadyStems.length,
        secondaryActive: cleanedSelectedCount === 0,
      }
    : null;
  const enhancedSourceControl = enhancedReadyVocals.length
    ? {
        availableCount: enhancedReadyVocals.length,
        title: "Vocal Mix Source",
        detail: `${enhancedSelectedCount}/${enhancedReadyVocals.length} enhanced vocal${enhancedReadyVocals.length === 1 ? "" : "s"} are currently feeding the mixer.`,
        currentLabel: enhancedSelectedCount === enhancedReadyVocals.length ? "Using enhanced" : enhancedSelectedCount === 0 ? "Using source vocals" : `${enhancedSelectedCount}/${enhancedReadyVocals.length} enhanced`,
        primaryLabel: `Use enhanced${enhancedReadyVocals.length > 1 ? ` (${enhancedReadyVocals.length})` : ""}`,
        secondaryLabel: "Use source vocals",
        primaryActive: enhancedSelectedCount === enhancedReadyVocals.length,
        secondaryActive: enhancedSelectedCount === 0,
      }
    : null;
  return {
    steps,
    nextStep,
    summary: workflowSummary({ uploadedCount, analyzedCount, detectedCount, cleanedCount, vocalCount, enhancedCount, mixCount: mixVersions.length, masterCount: masterVersions.length }),
    sourceSummary: workflowSourceSummary(nextKey, cleanedReadyStems.length, cleanedSelectedCount, enhancedReadyVocals.length, enhancedSelectedCount),
    cleanedReadyStems,
    enhancedReadyVocals,
    cleanedSourceControl,
    enhancedSourceControl,
    skipCleaningAvailable: analysisComplete && !hasCleanedStems && !hasMix,
    skipCleaningHref: (projectId) => (vocalCount > 0 && !hasEnhancedVocals ? `/projects/${projectId}/vocals` : `/projects/${projectId}/mixer`),
  };
}

function getStepStatus(key, completion, availability, nextKey, cleaningSkipped, vocalEnhancementSkipped) {
  if (completion[key]) {
    if (key === "cleaning" && cleaningSkipped) return "skipped";
    if (key === "vocals" && vocalEnhancementSkipped) return "skipped";
    return "complete";
  }
  if (!availability[key]) return "locked";
  if (key === nextKey) return "current";
  return "ready";
}

function stepDetail(key, counts) {
  if (key === "upload") return counts.uploadedCount ? `${counts.uploadedCount} stem${counts.uploadedCount === 1 ? "" : "s"}` : "No stems yet";
  if (key === "analyze") return counts.uploadedCount ? `${counts.analyzedCount}/${counts.uploadedCount} analyzed, ${counts.detectedCount}/${counts.uploadedCount} typed` : "Waiting for stems";
  if (key === "cleaning") {
    if (counts.cleaningSkipped) return "Skipped";
    return counts.cleanedCount ? `${counts.cleanedCount} cleaned` : "Optional cleanup";
  }
  if (key === "vocals") {
    if (!counts.vocalCount) return "No vocals";
    if (counts.vocalEnhancementSkipped) return "Skipped";
    return counts.enhancedCount ? `${counts.enhancedCount} enhanced` : `${counts.vocalCount} vocal${counts.vocalCount === 1 ? "" : "s"}`;
  }
  if (key === "mixer") return counts.mixCount ? `${counts.mixCount} mix version${counts.mixCount === 1 ? "" : "s"}` : "No mix yet";
  if (key === "export") return counts.masterCount ? `${counts.masterCount} master${counts.masterCount === 1 ? "" : "s"}` : "No master yet";
  return "";
}

function workflowSummary(counts) {
  if (!counts.uploadedCount) return "Start by adding the stems for this song.";
  if (counts.analyzedCount < counts.uploadedCount) return "Uploaded stems are ready for analysis and type detection.";
  if (!counts.cleanedCount && !counts.mixCount) return "Analysis is ready. Clean stems next, or skip cleaning and move to the mixer.";
  if (counts.vocalCount && !counts.enhancedCount && !counts.mixCount) return "Vocal stems can be polished before the final auto mix.";
  if (!counts.mixCount) return "Cleaned stems are ready for auto mixing.";
  if (!counts.masterCount) return "Mix versions are ready for mastering.";
  return "The project has a completed local master and can be reviewed or exported again.";
}

function workflowSourceSummary(nextKey, cleanedReadyCount, cleanedSelectedCount, enhancedReadyCount, enhancedSelectedCount) {
  if (nextKey === "vocals" && cleanedReadyCount) {
    return `${cleanedSelectedCount}/${cleanedReadyCount} cleaned stems are currently feeding the Vocal Enhancer.`;
  }
  if ((nextKey === "mixer" || nextKey === "export") && enhancedReadyCount) {
    if (cleanedReadyCount) {
      return `${enhancedSelectedCount}/${enhancedReadyCount} enhanced vocals are currently feeding the mixer, and ${cleanedSelectedCount}/${cleanedReadyCount} cleaned stems are enabled where available.`;
    }
    return `${enhancedSelectedCount}/${enhancedReadyCount} enhanced vocals are currently feeding the mixer.`;
  }
  if (cleanedReadyCount) {
    return `${cleanedSelectedCount}/${cleanedReadyCount} cleaned stems are enabled for the next render path.`;
  }
  if (enhancedReadyCount) {
    return `${enhancedSelectedCount}/${enhancedReadyCount} enhanced vocals are enabled for the next mix.`;
  }
  return "";
}

const statusLabels = {
  complete: "Done",
  current: "Next",
  ready: "Ready",
  skipped: "Skipped",
  locked: "Locked",
};

const statusStyles = {
  complete: {
    icon: "border-emerald-200/35 bg-emerald-400/18 text-emerald-50",
    badge: "border-emerald-200/35 bg-emerald-400/18 text-emerald-50",
  },
  current: {
    icon: "border-cyan-200/45 bg-cyan-400/20 text-cyan-50",
    badge: "border-cyan-200/45 bg-cyan-400/20 text-cyan-50",
  },
  ready: {
    icon: "border-sky-200/35 bg-sky-400/18 text-sky-50",
    badge: "border-sky-200/35 bg-sky-400/18 text-sky-50",
  },
  skipped: {
    icon: "border-amber-200/35 bg-amber-400/18 text-amber-50",
    badge: "border-amber-200/35 bg-amber-400/18 text-amber-50",
  },
  locked: {
    icon: "border-slate-500/35 bg-slate-700/28 text-slate-200/80",
    badge: "border-slate-500/35 bg-slate-700/28 text-slate-200/80",
  },
};
