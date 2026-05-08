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

export default function ProjectCard({ project, compact = false, onDelete, deleting = false }) {
  const title = getProjectTitle(project);
  const subtitle = getProjectSubtitle(project);
  const stage = getProjectStage(project);
  const progress = getProjectProgress(project);
  const action = getNextProjectAction(project);
  const ActionIcon = actionIcons[action.icon] || FolderOpen;

  return (
    <article className={`group relative overflow-hidden rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.065] via-white/[0.035] to-black/30 shadow-[0_18px_55px_rgba(0,0,0,0.22)] transition duration-200 hover:-translate-y-0.5 hover:border-teal-200/30 hover:bg-white/[0.07] ${compact ? "p-4" : "p-5"}`}>
      <span className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-teal-200/50 to-transparent opacity-0 transition group-hover:opacity-100" />

      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Link to={`/projects/${project.id}`} className="block truncate text-lg font-semibold text-white hover:text-teal-100">
            {title}
          </Link>
          <p className="mt-1 min-h-5 truncate text-sm text-zinc-400">{subtitle || stage.summary}</p>
        </div>
        <StatusBadge status={project.status} />
      </div>

      <div className="mt-5">
        <div className="flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">
          <span>{stage.label}</span>
          <span>Step {progress.current}/6</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-black/30">
          <span className="block h-full rounded-full bg-gradient-to-r from-teal-200 via-cyan-200 to-emerald-200" style={{ width: `${progress.percent}%` }} />
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-zinc-400">
        <span className="inline-flex items-center gap-1.5">
          <Music2 size={15} className="text-teal-200" />
          {project.stemCount || 0} {(project.stemCount || 0) === 1 ? "stem" : "stems"}
        </span>
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <CalendarDays size={15} className="text-teal-200" />
          <span className="truncate">Updated {formatDateTime(project.updatedAt || project.createdAt)}</span>
        </span>
      </div>

      <div className="mt-5 flex items-center justify-between gap-3 border-t border-white/10 pt-4">
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
        ) : (
          <span />
        )}
        <Link
          to={action.href}
          className="inline-flex min-h-9 min-w-0 items-center justify-center gap-2 rounded-lg border border-teal-200/35 bg-teal-300/10 px-3 py-2 text-sm font-semibold text-teal-50 transition hover:border-teal-100/60 hover:bg-teal-300/20"
        >
          <ActionIcon size={16} className="shrink-0" />
          <span className="truncate">{action.label}</span>
          <ArrowRight size={15} className="shrink-0" />
        </Link>
      </div>
    </article>
  );
}
