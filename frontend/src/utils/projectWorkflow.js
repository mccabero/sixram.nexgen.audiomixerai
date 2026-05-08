const stageDefinitions = [
  {
    key: "setup",
    label: "Setup",
    statuses: ["Created"],
    progress: 1,
    tone: "amber",
    actionLabel: "Upload stems",
    actionIcon: "upload",
    href: (id) => `/projects/${id}/upload`,
    summary: "Ready for stem upload.",
  },
  {
    key: "analysis",
    label: "Analysis",
    statuses: ["Stems Uploaded", "Stem Detection Ready"],
    progress: 2,
    tone: "cyan",
    actionLabel: "Analyze stems",
    actionIcon: "analyze",
    href: (id) => `/projects/${id}/analyze`,
    summary: "Stems are ready for analysis.",
  },
  {
    key: "cleaning",
    label: "Cleaning",
    statuses: ["Analyzed"],
    progress: 3,
    tone: "sky",
    actionLabel: "Clean stems",
    actionIcon: "cleaning",
    href: (id) => `/projects/${id}/cleaning`,
    summary: "Analysis is complete.",
  },
  {
    key: "mix",
    label: "Mix",
    statuses: ["Cleaned", "Vocals Enhanced"],
    progress: 4,
    tone: "teal",
    actionLabel: "Open mixer",
    actionIcon: "mixer",
    href: (id) => `/projects/${id}/mixer`,
    summary: "Prepared stems are ready to mix.",
  },
  {
    key: "mastering",
    label: "Mastering",
    statuses: ["Auto Balance Ready", "Auto Balanced", "Rough Mix Ready", "Advanced Mix Ready"],
    progress: 5,
    tone: "violet",
    actionLabel: "Master mix",
    actionIcon: "export",
    href: (id) => `/projects/${id}/mastering`,
    summary: "Mix versions are ready for mastering.",
  },
  {
    key: "ready",
    label: "Ready",
    statuses: ["Master Ready"],
    progress: 6,
    tone: "emerald",
    actionLabel: "Review master",
    actionIcon: "export",
    href: (id) => `/projects/${id}/mastering`,
    summary: "Master is ready for review.",
  },
  {
    key: "exported",
    label: "Exported",
    statuses: ["Exported"],
    progress: 6,
    tone: "emerald",
    actionLabel: "Open exports",
    actionIcon: "export",
    href: (id) => `/projects/${id}/export`,
    summary: "Exports are available.",
  },
];

const fallbackStage = {
  key: "project",
  label: "Project",
  progress: 2,
  tone: "zinc",
  actionLabel: "Open project",
  actionIcon: "project",
  href: (id) => `/projects/${id}`,
  summary: "Open the project overview.",
};

export function getProjectTitle(project) {
  return project?.songTitle || project?.name || "Untitled project";
}

export function getProjectSubtitle(project) {
  return [project?.artistName, project?.songTitle && project?.name].filter(Boolean).join(" - ");
}

export function getProjectStage(project) {
  if (!project) return fallbackStage;
  if ((project.stemCount || 0) === 0) return stageDefinitions[0];
  return stageDefinitions.find((stage) => stage.statuses.includes(project.status)) || fallbackStage;
}

export function getProjectProgress(project) {
  const stage = getProjectStage(project);
  return {
    current: stage.progress,
    total: 6,
    percent: Math.min(100, Math.max(0, Math.round((stage.progress / 6) * 100))),
  };
}

export function getNextProjectAction(project) {
  const stage = getProjectStage(project);
  return {
    label: stage.actionLabel,
    icon: stage.actionIcon,
    href: stage.href(project.id),
    summary: stage.summary,
  };
}

export function getProjectBucket(project) {
  const stage = getProjectStage(project);
  if (stage.key === "setup") return "needs-stems";
  if (stage.progress >= 6) return "ready";
  return "active";
}

export function projectMatchesQuery(project, query) {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;

  return [project.name, project.songTitle, project.artistName, project.status]
    .filter(Boolean)
    .some((value) => value.toLowerCase().includes(normalizedQuery));
}
