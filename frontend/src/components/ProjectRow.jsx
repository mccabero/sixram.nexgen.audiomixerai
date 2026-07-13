import { ArrowRight, BarChart3, CalendarDays, Eraser, FolderOpen, Music2, SlidersHorizontal, Sparkles, Trash2, UploadCloud } from "lucide-react";
import { Link } from "react-router-dom";
import StatusBadge from "./StatusBadge.jsx";
import { formatDateTime } from "../utils/format.js";
import { getNextProjectAction, getProjectProgress, getProjectStage, getProjectSubtitle, getProjectTitle } from "../utils/projectWorkflow.js";

const actionIcons = {
  upload: UploadCloud,
  analyze: BarChart3,
  cleaning: Eraser,
  mixer: SlidersHorizontal,
  export: Sparkles,
  project: FolderOpen,
};

export default function ProjectRow({ project, onDelete, deleting = false }) {
  const title = getProjectTitle(project);
  const subtitle = getProjectSubtitle(project);
  const stage = getProjectStage(project);
  const progress = getProjectProgress(project);
  const action = getNextProjectAction(project);
  const ActionIcon = actionIcons[action.icon] || FolderOpen;
  const stemCount = project.stemCount || 0;

  return (
    <article className="group relative grid gap-3 rounded-lg border border-white/10 bg-white/[0.035] p-4 transition hover:border-teal-200/30 hover:bg-white/[0.06] lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1.35fr)_auto] lg:items-center lg:gap-6">
      <span className="pointer-events-none absolute inset-y-0 left-0 w-0.5 rounded-l-lg bg-gradient-to-b from-teal-200/60 to-emerald-200/40 opacity-0 transition group-hover:opacity-100" />

      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <Link to={`/projects/${project.id}`} className="truncate font-semibold text-white hover:text-teal-100">
            {title}
          </Link>
          <StatusBadge status={project.status} />
        </div>
        <p className="mt-1 truncate text-sm text-zinc-400">{subtitle || stage.summary}</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500 lg:hidden">
          <span className="inline-flex items-center gap-1.5">
            <Music2 size={13} className="text-teal-200" />
            {stemCount} {stemCount === 1 ? "stem" : "stems"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <CalendarDays size={13} className="text-teal-200" />
            {formatDateTime(project.updatedAt || project.createdAt)}
          </span>
        </div>
      </div>

      <div className="min-w-0">
        <div className="flex items-center justify-between gap-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
          <span className="truncate">{stage.label}</span>
          <span className="shrink-0">Step {progress.current}/{progress.total}</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/30">
          <span className="block h-full rounded-full bg-gradient-to-r from-teal-200 via-cyan-200 to-emerald-200" style={{ width: `${progress.percent}%` }} />
        </div>
        <div className="mt-2 hidden items-center gap-4 text-xs text-zinc-500 lg:flex">
          <span className="inline-flex items-center gap-1.5">
            <Music2 size={13} className="text-teal-200" />
            {stemCount} {stemCount === 1 ? "stem" : "stems"}
          </span>
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <CalendarDays size={13} className="shrink-0 text-teal-200" />
            <span className="truncate">Updated {formatDateTime(project.updatedAt || project.createdAt)}</span>
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 lg:justify-end">
        <Link
          to={action.href}
          className="inline-flex min-h-9 min-w-0 flex-1 items-center justify-center gap-2 rounded-lg border border-teal-200/35 bg-teal-300/10 px-3 py-2 text-sm font-semibold text-teal-50 transition hover:border-teal-100/60 hover:bg-teal-300/20 lg:flex-none"
        >
          <ActionIcon size={16} className="shrink-0" />
          <span className="truncate">{action.label}</span>
          <ArrowRight size={15} className="shrink-0" />
        </Link>
        {onDelete ? (
          <button
            type="button"
            onClick={() => onDelete(project)}
            disabled={deleting}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-rose-300/15 bg-rose-400/10 text-rose-100 transition hover:border-rose-300/30 hover:bg-rose-400/20 disabled:cursor-not-allowed disabled:opacity-50"
            title="Delete project"
            aria-label={`Delete ${title}`}
          >
            <Trash2 size={15} />
          </button>
        ) : null}
      </div>
    </article>
  );
}
