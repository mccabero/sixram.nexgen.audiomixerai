import { ArrowRight, BarChart3, CheckCircle2, Circle, Eraser, LockKeyhole, Mic2, SlidersHorizontal, Sparkles, UploadCloud } from "lucide-react";
import { Link } from "react-router-dom";
import Button from "./Button.jsx";

const stepDefinitions = [
  {
    key: "upload",
    number: 1,
    label: "Upload",
    title: "Upload Stems",
    icon: UploadCloud,
    href: (projectId) => `/projects/${projectId}/upload`,
    cta: "Upload stems",
  },
  {
    key: "analyze",
    number: 2,
    label: "Analyze",
    title: "Analyze + Detect",
    icon: BarChart3,
    href: (projectId) => `/projects/${projectId}/analyze`,
    cta: "Analyze stems",
  },
  {
    key: "cleaning",
    number: 3,
    label: "Clean",
    title: "Clean Stems",
    icon: Eraser,
    href: (projectId) => `/projects/${projectId}/cleaning`,
    cta: "Clean stems",
    optional: true,
  },
  {
    key: "vocals",
    number: 4,
    label: "Vocals",
    title: "Enhance Vocals",
    icon: Mic2,
    href: (projectId) => `/projects/${projectId}/vocals`,
    cta: "Polish vocals",
    optional: true,
  },
  {
    key: "mixer",
    number: 5,
    label: "Mix",
    title: "Auto Mix",
    icon: SlidersHorizontal,
    href: (projectId) => `/projects/${projectId}/mixer`,
    cta: "Open mixer",
  },
  {
    key: "export",
    number: 6,
    label: "Master",
    title: "Master + Export",
    icon: Sparkles,
    href: (projectId) => `/projects/${projectId}/mastering`,
    cta: "Master/export",
  },
];

export default function WorkflowGuide({ project, currentStep = "", className = "" }) {
  if (!project) return null;

  const state = getWorkflowState(project);
  const nextStep = state.nextStep;
  const NextIcon = nextStep.icon;
  const activeKey = currentStep === "project" ? nextStep.key : currentStep || nextStep.key;

  return (
    <section className={`rounded-lg border border-white/10 bg-white/[0.04] p-4 shadow-glow ${className}`}>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-100/70">Step-by-step workflow</p>
          <h2 className="mt-2 text-lg font-semibold text-white">Next: {nextStep.title}</h2>
          <p className="mt-1 text-sm text-zinc-400">{state.summary}</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap xl:justify-end">
          {state.skipCleaningAvailable ? (
            <Button as={Link} to={`/projects/${project.id}/mixer`} variant="secondary" className="sm:w-auto">
              <SlidersHorizontal size={17} />
              Skip cleaning
            </Button>
          ) : null}
          <Button as={Link} to={nextStep.href(project.id)} className="sm:w-auto">
            <NextIcon size={17} />
            {nextStep.cta}
            <ArrowRight size={16} />
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        {state.steps.map((step) => (
          <WorkflowStepCard key={step.key} step={step} active={step.key === activeKey} projectId={project.id} />
        ))}
      </div>
    </section>
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
  return {
    steps,
    nextStep,
    summary: workflowSummary({ uploadedCount, analyzedCount, detectedCount, cleanedCount, vocalCount, enhancedCount, mixCount: mixVersions.length, masterCount: masterVersions.length }),
    skipCleaningAvailable: analysisComplete && !hasCleanedStems && !hasMix,
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
