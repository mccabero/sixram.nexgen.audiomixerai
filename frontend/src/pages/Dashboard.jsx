import { AudioLines, Clock3, FolderKanban, FolderPlus, HardDrive, Music2, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createProject, getHealth, listProjects } from "../api.js";
import Button from "../components/Button.jsx";
import CreateProjectModal from "../components/CreateProjectModal.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import ProjectCard from "../components/ProjectCard.jsx";

export default function Dashboard() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [health, setHealth] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const navigate = useNavigate();

  const loadProjects = async () => {
    setLoading(true);
    setError("");
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

  const totalStems = projects.reduce((total, project) => total + (project.stemCount || 0), 0);
  const recentProjects = [...projects]
    .sort((a, b) => new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0))
    .slice(0, 3);
  const healthReady = health?.status === "ok";

  return (
    <div>
      <div className="rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.075] via-white/[0.04] to-teal-300/[0.04] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.28)]">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Dashboard</p>
            <h1 className="mt-2 text-3xl font-semibold text-white">Projects</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
              Manage local song workspaces, upload stems, and move each project through analysis, cleaning, mixing, mastering, and export.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
            <Button type="button" variant="secondary" onClick={loadProjects} disabled={loading} title="Refresh projects">
              <RefreshCw size={17} />
              Refresh
            </Button>
            <Button type="button" onClick={() => setModalOpen(true)}>
              <FolderPlus size={17} />
              Create project
            </Button>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <DashboardStat icon={FolderKanban} label="Projects" value={projects.length} detail="Local sessions" />
          <DashboardStat icon={AudioLines} label="Uploaded Stems" value={totalStems} detail="Original files preserved" />
          <DashboardStat icon={Clock3} label="Recent" value={recentProjects.length} detail="Ready for quick open" />
          <DashboardStat
            icon={healthReady ? ShieldCheck : TriangleAlert}
            label="Audio Engine"
            value={health ? (healthReady ? "Ready" : "Check") : "Loading"}
            detail={healthReady ? "ffmpeg and Python OK" : "Dependency status"}
            tone={healthReady ? "emerald" : "amber"}
          />
        </div>
      </div>

      <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Recent Projects</h2>
          <p className="mt-1 text-sm text-zinc-400">Open a session or start a new one.</p>
        </div>
        <Button type="button" variant="secondary" onClick={() => setModalOpen(true)} className="sm:w-auto">
          <FolderPlus size={17} />
          New session
        </Button>
      </div>

      {!loading && recentProjects.length ? (
        <section className="mt-4 grid gap-3 lg:grid-cols-3">
          {recentProjects.map((project) => (
            <ProjectCard key={`recent-${project.id}`} project={project} compact />
          ))}
        </section>
      ) : null}

      <section className="mt-7">
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-white">All Projects</h2>
            <p className="mt-1 text-sm text-zinc-400">Every project stored in this local workspace.</p>
          </div>
          {projects.length ? (
            <Button type="button" onClick={() => setModalOpen(true)} className="sm:w-auto">
              <FolderPlus size={17} />
              Create project
            </Button>
          ) : null}
        </div>

        {error ? <p className="rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}
      </section>

      {health && health.status !== "ok" ? (
        <section className="mt-6 flex flex-col gap-3 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <span className="inline-flex items-center gap-2 text-sm font-medium text-amber-100">
            <TriangleAlert size={17} />
            Audio engine needs attention: {health.error || health.audioEnvironment?.ffmpeg?.error || "dependency check failed"}
          </span>
        </section>
      ) : health ? (
        <section className="mt-6 inline-flex items-center gap-2 rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-3 py-2 text-sm font-medium text-emerald-100">
          <ShieldCheck size={17} />
          Audio engine ready
        </section>
      ) : null}

      {loading ? (
        <div className="mt-6">
          <ProcessingPanel title="Loading Projects" message="Reading local project metadata." />
        </div>
      ) : null}

      <section className="mt-4">
        {loading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((item) => (
              <div key={item} className="h-52 animate-pulse rounded-lg border border-white/10 bg-white/[0.04]" />
            ))}
          </div>
        ) : projects.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
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

function DashboardStat({ icon: Icon, label, value, detail, tone = "teal" }) {
  const toneClass =
    tone === "emerald"
      ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100"
      : tone === "amber"
        ? "border-amber-300/20 bg-amber-300/10 text-amber-100"
        : "border-teal-300/20 bg-teal-300/10 text-teal-100";

  return (
    <div className="rounded-lg border border-white/10 bg-black/25 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
      <div className="flex items-center justify-between gap-3">
        <span className={`grid h-10 w-10 place-items-center rounded-lg border ${toneClass}`}>
          <Icon size={18} />
        </span>
        <HardDrive size={16} className="text-zinc-600" />
      </div>
      <p className="mt-4 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
      <p className="mt-1 truncate text-sm text-zinc-500">{detail}</p>
    </div>
  );
}
