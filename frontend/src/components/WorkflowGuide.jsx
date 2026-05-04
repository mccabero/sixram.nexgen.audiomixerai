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
    <section className={`rounded-lg border border-white/10 bg-white/[0.04] p-4 shadow-glow ${className}`}>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-100/70">Step-by-step workflow</p>
          <h2 className="mt-2 text-lg font-semibold text-white">{finalStepPage ? "Final Step" : "Next"}: {nextStep.title}</h2>
          <p className="mt-1 text-sm text-zinc-400">{state.summary}</p>
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

      {state.cleanedSourceControl || state.enhancedSourceControl ? (
        <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-4">
          <div className="flex flex-col gap-1 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-100/75">Next Step Input</p>
              <h3 className="mt-1 text-sm font-semibold text-white">Choose which prepared stems continue forward</h3>
              <p className="mt-1 text-sm text-zinc-400">{state.sourceSummary}</p>
            </div>
            <p className="text-xs text-zinc-500">Per-stem controls still remain on the Clean Stems and Enhance Vocals pages.</p>
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

          {sourceError ? <p className="mt-3 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{sourceError}</p> : null}
        </div>
      ) : null}

      <div className="mt-4 grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        {state.steps.map((step) => (
          <WorkflowStepCard key={step.key} step={step} active={step.key === activeKey} projectId={project.id} />
        ))}
      </div>
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
    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">{title}</p>
          <p className="mt-1 text-xs leading-5 text-zinc-400">{detail}</p>
        </div>
        <span className="rounded-full border border-white/10 bg-black/25 px-2 py-0.5 text-[11px] font-semibold text-zinc-300">{currentLabel}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={busy || primaryActive}
          onClick={onPrimary}
          className={`min-h-10 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
            primaryActive ? "border-teal-200/30 bg-teal-300/20 text-teal-50 shadow-[0_0_18px_rgba(45,212,191,0.12)]" : "border-white/10 bg-black/20 text-zinc-300 hover:bg-white/[0.06]"
          }`}
        >
          {busy && !primaryActive ? "Saving..." : primaryLabel}
        </button>
        <button
          type="button"
          disabled={busy || secondaryActive}
          onClick={onSecondary}
          className={`min-h-10 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
            secondaryActive ? "border-teal-200/30 bg-teal-300/20 text-teal-50 shadow-[0_0_18px_rgba(45,212,191,0.12)]" : "border-white/10 bg-black/20 text-zinc-300 hover:bg-white/[0.06]"
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
    ? "border-teal-200/30 bg-teal-300/10"
    : step.available
      ? "border-white/10 bg-black/20 hover:border-teal-200/25 hover:bg-white/[0.06]"
      : "border-white/10 bg-black/10 opacity-70";

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
      <p className="mt-3 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Step {step.number}</p>
      <p className="mt-1 truncate text-sm font-semibold text-white">{step.title}</p>
      <p className="mt-1 min-h-5 truncate text-xs text-zinc-500">{step.detail}</p>
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
    icon: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
    badge: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
  },
  current: {
    icon: "border-teal-300/25 bg-teal-300/10 text-teal-100",
    badge: "border-teal-300/25 bg-teal-300/10 text-teal-100",
  },
  ready: {
    icon: "border-cyan-300/20 bg-cyan-300/10 text-cyan-100",
    badge: "border-cyan-300/20 bg-cyan-300/10 text-cyan-100",
  },
  skipped: {
    icon: "border-amber-300/20 bg-amber-300/10 text-amber-100",
    badge: "border-amber-300/20 bg-amber-300/10 text-amber-100",
  },
  locked: {
    icon: "border-zinc-500/20 bg-zinc-500/10 text-zinc-400",
    badge: "border-zinc-500/20 bg-zinc-500/10 text-zinc-400",
  },
};
