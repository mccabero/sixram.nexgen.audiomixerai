import { ArrowRight, CalendarDays, FolderOpen, Music2 } from "lucide-react";
import { Link } from "react-router-dom";
import StatusBadge from "./StatusBadge.jsx";
import { formatDate } from "../utils/format.js";

export default function ProjectCard({ project, compact = false }) {
  const title = project.songTitle || project.name;
  const subtitle = [project.artistName, project.songTitle && project.name].filter(Boolean).join(" - ");

  return (
    <Link
      to={`/projects/${project.id}`}
      className="group relative block overflow-hidden rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.07] via-white/[0.04] to-black/30 p-5 shadow-[0_18px_55px_rgba(0,0,0,0.24)] transition duration-200 hover:-translate-y-0.5 hover:border-teal-200/30 hover:bg-white/[0.07]"
    >
      <span className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-teal-200/50 to-transparent opacity-0 transition group-hover:opacity-100" />
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold text-white">{title}</h2>
          <p className="mt-1 min-h-5 truncate text-sm text-zinc-400">{subtitle}</p>
        </div>
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/25 text-teal-200 transition group-hover:border-teal-200/30 group-hover:bg-teal-300/10">
          <FolderOpen size={19} />
        </span>
      </div>
      <div className={`mt-5 grid gap-3 ${compact ? "grid-cols-2" : "sm:grid-cols-2"}`}>
        <CardMetric icon={Music2} label="Stems" value={project.stemCount || 0} />
        <CardMetric icon={CalendarDays} label="Created" value={formatDate(project.createdAt)} />
      </div>
      <div className="mt-5 flex items-center justify-between gap-3">
        <StatusBadge status={project.status} />
        <span className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500 transition group-hover:text-teal-100">
          Open
          <ArrowRight size={13} />
        </span>
      </div>
    </Link>
  );
}

function CardMetric({ icon: Icon, label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
      <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
        <Icon size={14} />
        {label}
      </p>
      <p className="mt-1 truncate text-sm font-semibold text-zinc-100">{value}</p>
    </div>
  );
}
