import {
  Activity,
  AudioLines,
  BarChart3,
  CheckCircle2,
  Clock3,
  Eraser,
  FolderKanban,
  FolderOpen,
  FolderPlus,
  Music2,
  RefreshCw,
  Search,
  Server,
  ServerOff,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TriangleAlert,
  UploadCloud,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createProject, deleteProject, getHealth, listProjects } from "../api.js";
import Button from "../components/Button.jsx";
import CreateProjectModal from "../components/CreateProjectModal.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import ProjectCard from "../components/ProjectCard.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { formatDateTime } from "../utils/format.js";
import {
  getNextProjectAction,
  getProjectBucket,
  getProjectProgress,
  getProjectStage,
  getProjectSubtitle,
  getProjectTitle,
  projectMatchesQuery,
} from "../utils/projectWorkflow.js";

const actionIcons = {
  upload: UploadCloud,
  analyze: BarChart3,
  cleaning: Eraser,
  mixer: SlidersHorizontal,
  export: Sparkles,
  project: FolderOpen,
};

const filters = [
  { value: "all", label: "All projects" },
  { value: "active", label: "In progress" },
  { value: "needs-stems", label: "Needs stems" },
  { value: "ready", label: "Masters ready" },
];

const sortOptions = [
  { value: "recent", label: "Recently updated" },
  { value: "name", label: "Project name" },
  { value: "stage", label: "Workflow stage" },
  { value: "oldest", label: "Oldest first" },
];

export default function Dashboard() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [health, setHealth] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [deletingProjectId, setDeletingProjectId] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [sortMode, setSortMode] = useState("recent");
  const navigate = useNavigate();

  const loadProjects = async () => {
    setLoading(true);
    setError("");
    setHealth(null);
    try {
      const [nextProjects, nextHealth] = await Promise.all([listProjects(), getHealth().catch((err) => ({ status: "degraded", error: err.message }))]);
      setProjects(nextProjects);
      setHealth(nextHealth);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProjects();
  }, []);

  const handleCreate = async (project) => {
    const created = await createProject(project);
    setModalOpen(false);
    navigate(`/projects/${created.id}`);
  };

  const handleDeleteProject = async (project) => {
    const title = getProjectTitle(project);
    if (!window.confirm(`Delete "${title}" and all files in its local project folder? This cannot be undone.`)) return;
    setDeletingProjectId(project.id);
    setError("");
    try {
      await deleteProject(project.id);
      setProjects((current) => current.filter((item) => item.id !== project.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setDeletingProjectId("");
    }
  };

  const sortedProjects = useMemo(() => sortProjects(projects, sortMode), [projects, sortMode]);
  const filteredProjects = useMemo(
    () =>
      sortedProjects.filter((project) => {
        const matchesFilter = filter === "all" || getProjectBucket(project) === filter;
        return matchesFilter && projectMatchesQuery(project, query);
      }),
    [sortedProjects, filter, query],
  );

  const resumeProject = sortedProjects.find((project) => getProjectBucket(project) !== "ready") || sortedProjects[0];
  const totalStems = projects.reduce((total, project) => total + (project.stemCount || 0), 0);
  const activeProjects = projects.filter((project) => getProjectBucket(project) === "active").length;
  const readyProjects = projects.filter((project) => getProjectBucket(project) === "ready").length;
  const backendReady = Boolean(health);
  const healthReady = health?.status === "ok";

  return (
    <div className="space-y-7">
      <section className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Dashboard</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Project workspace</h1>
          <p className="mt-3 text-sm leading-6 text-zinc-400">
            Resume active mixes, check local audio readiness, and find the right song session quickly.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.055] px-3 py-2 text-sm text-zinc-300">
              <FolderKanban size={16} className="text-teal-200" />
              {projects.length} local {projects.length === 1 ? "project" : "projects"}
            </span>
            <span
              className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                health ? (healthReady ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100" : "border-amber-300/20 bg-amber-300/10 text-amber-100") : "border-white/10 bg-white/[0.055] text-zinc-300"
              }`}
            >
              {health ? healthReady ? <ShieldCheck size={16} /> : <TriangleAlert size={16} /> : <Clock3 size={16} />}
              {health ? (healthReady ? "Audio ready" : "Audio check needed") : "Checking audio"}
            </span>
            <span
              className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                loading && !backendReady
                  ? "border-white/10 bg-white/[0.055] text-zinc-300"
                  : backendReady
                    ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100"
                    : "border-rose-300/20 bg-rose-400/10 text-rose-100"
              }`}
            >
              {loading && !backendReady ? <Clock3 size={16} /> : backendReady ? <Server size={16} /> : <ServerOff size={16} />}
              {loading && !backendReady ? "Checking backend" : backendReady ? "Backend ready" : "Backend offline"}
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap lg:justify-end">
          <Button type="button" variant="secondary" onClick={loadProjects} disabled={loading} title="Refresh projects">
            <RefreshCw size={17} />
            Refresh
          </Button>
          <Button type="button" onClick={() => setModalOpen(true)}>
            <FolderPlus size={17} />
            Create project
          </Button>
        </div>
      </section>

      {error ? <p className="rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}

      <section className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
        {resumeProject ? <ResumeProjectPanel project={resumeProject} /> : <StartProjectPanel onCreate={() => setModalOpen(true)} />}
        <EngineStatusPanel health={health} loading={loading} />
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <DashboardStat icon={FolderKanban} label="Projects" value={projects.length} detail="Local song sessions" />
        <DashboardStat icon={AudioLines} label="Uploaded stems" value={totalStems} detail="Original files preserved" />
        <DashboardStat icon={Activity} label="In progress" value={activeProjects} detail="Still moving through workflow" tone="cyan" />
        <DashboardStat icon={CheckCircle2} label="Masters ready" value={readyProjects} detail="Ready for review or export" tone="emerald" />
      </section>

      {loading ? <ProcessingPanel title="Loading Projects" message="Reading local project metadata." /> : null}
      {deletingProjectId ? <ProcessingPanel title="Deleting Project" message="Removing metadata and all local files for the selected project." /> : null}

      <section>
        <div className="mb-4 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-white">Projects</h2>
            <p className="mt-1 text-sm text-zinc-400">
              {filteredProjects.length === projects.length ? "Every project stored in this local workspace." : `${filteredProjects.length} of ${projects.length} projects shown.`}
            </p>
          </div>

          <div className="grid gap-2 sm:grid-cols-[minmax(220px,1fr)_auto_auto]">
            <label className="relative block">
              <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="min-h-10 w-full rounded-lg border border-white/10 bg-black/25 py-2 pl-9 pr-3 text-sm text-white placeholder:text-zinc-600"
                placeholder="Search projects"
                aria-label="Search projects"
              />
            </label>

            <label className="block">
              <span className="sr-only">Filter projects</span>
              <select
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                className="min-h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-white"
              >
                {filters.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="sr-only">Sort projects</span>
              <select
                value={sortMode}
                onChange={(event) => setSortMode(event.target.value)}
                className="min-h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2 text-sm text-white"
              >
                {sortOptions.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {loading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((item) => (
              <div key={item} className="h-56 animate-pulse rounded-lg border border-white/10 bg-white/[0.04]" />
            ))}
          </div>
        ) : filteredProjects.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filteredProjects.map((project) => (
              <ProjectCard key={project.id} project={project} onDelete={handleDeleteProject} deleting={deletingProjectId === project.id} />
            ))}
          </div>
        ) : projects.length ? (
          <EmptyState
            icon={Search}
            title="No matching projects"
            description="Try a different search term or show all workflow stages."
            action={
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setQuery("");
                  setFilter("all");
                }}
              >
                Show all projects
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={Music2}
            title="No projects yet"
            description="Create a project to start a local folder structure for original stems, processed files, exports, and logs."
            action={
              <Button type="button" onClick={() => setModalOpen(true)}>
                <FolderPlus size={17} />
                Create project
              </Button>
            }
          />
        )}
      </section>

      <CreateProjectModal open={modalOpen} onClose={() => setModalOpen(false)} onCreate={handleCreate} />
    </div>
  );
}

function ResumeProjectPanel({ project }) {
  const title = getProjectTitle(project);
  const subtitle = getProjectSubtitle(project);
  const stage = getProjectStage(project);
  const progress = getProjectProgress(project);
  const action = getNextProjectAction(project);
  const ActionIcon = actionIcons[action.icon] || FolderOpen;

  return (
    <section className="rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.07] via-white/[0.04] to-teal-300/[0.045] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.24)]">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-teal-100/70">Resume work</p>
          <h2 className="mt-2 truncate text-2xl font-semibold text-white">{title}</h2>
          <p className="mt-2 max-w-2xl truncate text-sm text-zinc-400">{subtitle || action.summary}</p>
        </div>
        <StatusBadge status={project.status} />
      </div>

      <div className="mt-5">
        <div className="flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">
          <span>{stage.label}</span>
          <span>Step {progress.current} of {progress.total}</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-black/30">
          <span className="block h-full rounded-full bg-gradient-to-r from-teal-200 via-cyan-200 to-emerald-200" style={{ width: `${progress.percent}%` }} />
        </div>
      </div>

      <dl className="mt-5 grid gap-x-6 gap-y-3 sm:grid-cols-3">
        <SummaryItem label="Stems" value={project.stemCount || 0} />
        <SummaryItem label="Updated" value={formatDateTime(project.updatedAt || project.createdAt)} />
        <SummaryItem label="Next" value={action.label} />
      </dl>

      <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <Button as={Link} to={action.href} className="sm:w-auto">
          <ActionIcon size={17} />
          {action.label}
        </Button>
        <Button as={Link} to={`/projects/${project.id}`} variant="secondary" className="sm:w-auto">
          <FolderOpen size={17} />
          Overview
        </Button>
      </div>
    </section>
  );
}

function StartProjectPanel({ onCreate }) {
  return (
    <section className="rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.07] via-white/[0.04] to-teal-300/[0.045] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.24)]">
      <p className="text-sm font-semibold uppercase tracking-[0.16em] text-teal-100/70">Start work</p>
      <h2 className="mt-2 text-2xl font-semibold text-white">Create your first project</h2>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">Set up a local song session before adding stems.</p>
      <Button type="button" onClick={onCreate} className="mt-5 sm:w-auto">
        <FolderPlus size={17} />
        Create project
      </Button>
    </section>
  );
}

function EngineStatusPanel({ health, loading }) {
  const ready = health?.status === "ok";
  const Icon = !health ? Clock3 : ready ? ShieldCheck : TriangleAlert;
  const title = !health ? (loading ? "Checking audio engine" : "Audio engine not checked") : ready ? "Audio engine ready" : "Audio engine needs attention";
  const detail = !health
    ? "Waiting for the local API."
    : ready
      ? "ffmpeg and Python checks passed."
      : health.error || health.audioEnvironment?.ffmpeg?.error || "Dependency check failed.";

  return (
    <section className={`rounded-lg border p-5 shadow-[0_18px_55px_rgba(0,0,0,0.18)] ${ready ? "border-emerald-300/20 bg-emerald-300/10" : health ? "border-amber-300/20 bg-amber-300/10" : "border-white/10 bg-white/[0.04]"}`}>
      <div className="flex items-start gap-3">
        <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-lg border ${ready ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-100" : health ? "border-amber-300/25 bg-amber-300/10 text-amber-100" : "border-white/10 bg-black/25 text-zinc-300"}`}>
          <Icon size={20} />
        </span>
        <div className="min-w-0">
          <p className={`text-sm font-semibold ${ready ? "text-emerald-100" : health ? "text-amber-100" : "text-white"}`}>{title}</p>
          <p className="mt-1 text-sm leading-6 text-zinc-400">{detail}</p>
        </div>
      </div>
    </section>
  );
}

function DashboardStat({ icon: Icon, label, value, detail, tone = "teal" }) {
  const toneClass =
    tone === "emerald"
      ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100"
      : tone === "cyan"
        ? "border-cyan-300/20 bg-cyan-300/10 text-cyan-100"
        : "border-teal-300/20 bg-teal-300/10 text-teal-100";

  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.045] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
      <span className={`grid h-10 w-10 place-items-center rounded-lg border ${toneClass}`}>
        <Icon size={18} />
      </span>
      <p className="mt-4 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-sm text-zinc-500">{detail}</p>
    </div>
  );
}

function SummaryItem({ label, value }) {
  return (
    <div className="border-l border-white/10 pl-3">
      <dt className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</dt>
      <dd className="mt-1 truncate text-sm font-semibold text-zinc-100">{value}</dd>
    </div>
  );
}

function sortProjects(projects, sortMode) {
  return [...projects].sort((a, b) => {
    if (sortMode === "name") return getProjectTitle(a).localeCompare(getProjectTitle(b));
    if (sortMode === "stage") return getProjectProgress(a).current - getProjectProgress(b).current || getProjectTitle(a).localeCompare(getProjectTitle(b));
    if (sortMode === "oldest") return getTime(a.updatedAt || a.createdAt) - getTime(b.updatedAt || b.createdAt);
    return getTime(b.updatedAt || b.createdAt) - getTime(a.updatedAt || a.createdAt);
  });
}

function getTime(value) {
  const time = new Date(value || 0).getTime();
  return Number.isFinite(time) ? time : 0;
}
