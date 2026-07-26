import { ArrowLeft, BarChart3, Film, Pencil, Sparkles, Trash2, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { cancelProcessingJob, deleteProject, deleteStem, getProcessingJob, getProject, startAutoPolish, updateProject, updateStemType } from "../api.js";
import Button from "../components/Button.jsx";
import CreateProjectModal from "../components/CreateProjectModal.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import ProjectLogPanel from "../components/ProjectLogPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import StemList from "../components/StemList.jsx";
import WorkflowGuide from "../components/WorkflowGuide.jsx";
import { formatDate, formatDateTime } from "../utils/format.js";

export default function ProjectDetail() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyStemId, setBusyStemId] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [polishJob, setPolishJob] = useState(null);
  const [polishNotice, setPolishNotice] = useState("");
  const [stoppingPolish, setStoppingPolish] = useState(false);
  const navigate = useNavigate();
  const runningStatuses = new Set(["Pending", "Processing", "Cancelling"]);
  const polishRunning = Boolean(polishJob && runningStatuses.has(polishJob.status));

  const loadProject = async () => {
    setLoading(true);
    setError("");
    try {
      setProject(await getProject(projectId));
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
    if (!polishJob?.id || !runningStatuses.has(polishJob.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getProcessingJob(projectId, polishJob.id);
        setPolishJob(nextJob);
        if (!runningStatuses.has(nextJob.status)) {
          setStoppingPolish(false);
          setPolishNotice(nextJob.message || (nextJob.status === "Completed" ? "Auto Polish complete." : "Auto Polish stopped."));
          await loadProject();
        }
      } catch {
        // keep polling; transient fetch errors are fine
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [projectId, polishJob?.id, polishJob?.status]);

  const handleAutoPolish = async () => {
    setError("");
    setPolishNotice("");
    try {
      const job = await startAutoPolish(projectId);
      setPolishJob(job);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleStopPolish = async () => {
    if (!polishJob?.id || stoppingPolish) return;
    setStoppingPolish(true);
    try {
      setPolishJob(await cancelProcessingJob(projectId, polishJob.id));
    } catch (err) {
      setError(err.message);
      setStoppingPolish(false);
    }
  };

  const handleChangeType = async (stemId, stemType) => {
    setBusyStemId(stemId);
    setActionMessage("Saving stem type change.");
    setError("");
    try {
      const updated = await updateStemType(projectId, stemId, stemType);
      setProject((current) => ({
        ...current,
        stems: current.stems.map((stem) => (stem.id === stemId ? updated : stem)),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyStemId("");
      setActionMessage("");
    }
  };

  const handleDelete = async (stemId) => {
    const stem = project.stems.find((item) => item.id === stemId);
    if (!window.confirm(`Delete "${stem?.originalFilename || "this stem"}" from this project?`)) return;
    setBusyStemId(stemId);
    setActionMessage("Deleting stem from local project metadata and storage.");
    setError("");
    try {
      await deleteStem(projectId, stemId);
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyStemId("");
      setActionMessage("");
    }
  };

  const handleUpdateProject = async (details) => {
    const updated = await updateProject(projectId, details);
    setProject(updated);
    setEditOpen(false);
  };

  const handleDeleteProject = async () => {
    const title = project.songTitle || project.name;
    if (!window.confirm(`Delete "${title}" and all local project files? This cannot be undone.`)) return;
    setActionMessage("Deleting project metadata and its full local storage folder.");
    setError("");
    try {
      await deleteProject(projectId);
      navigate("/");
    } catch (err) {
      setError(err.message);
      setActionMessage("");
    }
  };

  if (loading) {
    return <ProcessingPanel title="Loading Project" message="Reading project details and uploaded stem metadata." />;
  }

  if (error && !project) {
    return (
      <div>
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
          <ArrowLeft size={16} />
          Back to dashboard
        </Link>
        <p className="mt-6 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p>
      </div>
    );
  }

  const hasMaster = Boolean(project.masteringSettings?.masterVersions?.length);

  return (
    <div>
      <Link to="/" className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to dashboard
      </Link>

      <div className="mt-5">
        <section className="rounded-lg border border-white/10 bg-gradient-to-br from-white/[0.07] via-white/[0.04] to-black/30 p-5 shadow-[0_24px_80px_rgba(0,0,0,0.26)]">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Project</p>
              <h1 className="mt-2 truncate text-3xl font-semibold text-white">{project.songTitle || project.name}</h1>
              <p className="mt-2 text-sm text-zinc-400">
                {[project.artistName, project.songTitle && project.name].filter(Boolean).join(" - ") || "Local project"}
              </p>
            </div>
            <div className="flex shrink-0 flex-col gap-2 sm:items-end">
              <StatusBadge status={project.status} />
              <Button type="button" variant="secondary" onClick={() => setEditOpen(true)} className="min-h-9 px-3 py-1.5 text-xs">
                <Pencil size={15} />
                Edit details
              </Button>
              <Button type="button" variant="danger" onClick={handleDeleteProject} className="min-h-9 px-3 py-1.5 text-xs">
                <Trash2 size={15} />
                Delete project
              </Button>
            </div>
          </div>
          {project.notes ? <p className="mt-5 rounded-lg border border-white/10 bg-black/20 p-4 text-sm leading-6 text-zinc-300">{project.notes}</p> : null}
          <dl className="mt-5 grid gap-3 sm:grid-cols-3">
            <SummaryItem label="Created" value={formatDate(project.createdAt)} />
            <SummaryItem label="Updated" value={formatDateTime(project.updatedAt)} />
            <SummaryItem label="Stems" value={project.stems.length} />
          </dl>
        </section>

        <WorkflowGuide project={project} currentStep="project" className="mt-5" onProjectRefresh={loadProject} />
      </div>

      {project.stems.length ? (
        <section className="mt-5 rounded-lg border border-teal-200/20 bg-gradient-to-br from-teal-300/10 via-white/[0.04] to-black/25 p-4 shadow-[0_18px_55px_rgba(0,0,0,0.2)]">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-teal-200/25 bg-black/25 text-teal-100">
                <Sparkles size={19} />
              </span>
              <div>
                <h2 className="text-lg font-semibold text-white">Auto Polish</h2>
                <p className="mt-1 text-sm leading-6 text-zinc-400">
                  One click runs the whole workflow with recommended settings: analyze, clean each stem, enhance vocals, mix, and master.
                  Uses your current mastering preset{project.masteringSettings?.reference ? " and reference track" : ""}. Expect several minutes for a full song.
                </p>
              </div>
            </div>
            <Button type="button" onClick={handleAutoPolish} disabled={polishRunning} className="shrink-0">
              <Sparkles size={17} />
              {polishRunning ? "Polishing..." : "Auto Polish"}
            </Button>
          </div>
          {polishRunning ? (
            <div className="mt-4">
              <ProcessingPanel
                title={polishJob.status === "Cancelling" ? "Stopping Auto Polish" : "Auto Polish Running"}
                message={polishJob.message || "Working through cleaning, vocals, mix, and master."}
                progress={polishJob.progress || 0}
                actionLabel="Stop"
                actionBusy={stoppingPolish || polishJob.status === "Cancelling"}
                actionDisabled={stoppingPolish || polishJob.status === "Cancelling"}
                onAction={handleStopPolish}
              />
            </div>
          ) : null}
          {!polishRunning && polishNotice ? (
            <p className={`mt-3 rounded-lg border px-3 py-2 text-sm ${polishJob?.status === "Completed" ? "border-teal-200/25 bg-teal-300/10 text-teal-100" : "border-amber-300/25 bg-amber-400/10 text-amber-100"}`}>
              {polishNotice}
              {polishJob?.status === "Completed" ? (
                <Link to={`/projects/${project.id}/mastering`} className="ml-2 font-semibold underline decoration-teal-200/50 hover:text-white">
                  Review the master
                </Link>
              ) : null}
            </p>
          ) : null}
        </section>
      ) : null}

      {error ? <p className="mt-5 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}
      {actionMessage ? (
        <div className="mt-5">
          <ProcessingPanel title="Updating Project" message={actionMessage} />
        </div>
      ) : null}

      <ProjectLogPanel projectId={project.id} className="mt-6" />

      {hasMaster ? (
        <section className="mt-6 rounded-lg border border-white/10 bg-white/[0.04] p-4 shadow-[0_18px_55px_rgba(0,0,0,0.18)]">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-xl font-semibold text-white">Video Editor</h2>
              <p className="mt-1 text-sm text-zinc-400">Finish a simple performance MP4 using this project&apos;s mastered audio.</p>
            </div>
            <Button as={Link} to={`/projects/${project.id}/video-editor`} variant="secondary">
              <Film size={17} />
              Open Video Editor
            </Button>
          </div>
        </section>
      ) : null}

      <section className="mt-6">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-white">Uploaded Stems</h2>
            <p className="mt-1 text-sm text-zinc-400">Original files copied into local project storage.</p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
            <Button as={Link} to={`/projects/${project.id}/upload`}>
              <UploadCloud size={17} />
              Upload stems
            </Button>
            {project.stems.length ? (
              <Button as={Link} to={`/projects/${project.id}/analyze`} variant="secondary">
                <BarChart3 size={17} />
                Open Analyze
              </Button>
            ) : null}
          </div>
        </div>
        {project.stems.length ? (
          <StemList stems={project.stems} onChangeType={handleChangeType} onDelete={handleDelete} busyStemId={busyStemId} />
        ) : (
          <EmptyState
            icon={UploadCloud}
            title="No stems uploaded"
            description="Upload vocal, drum, bass, guitar, keys, pads, and FX stems to prepare this project for analysis in the next phase."
            action={
              <Button as={Link} to={`/projects/${project.id}/upload`}>
                <UploadCloud size={17} />
                Upload stems
              </Button>
            }
          />
        )}
      </section>

      <CreateProjectModal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        onCreate={handleUpdateProject}
        initialValues={project}
        title="Edit Project"
        description="Update this local project's basic information."
        submitLabel="Save changes"
        submittingLabel="Saving..."
        processingTitle="Saving Project"
        processingMessage="Updating local project metadata."
      />
    </div>
  );
}

function SummaryItem({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/25 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
      <dt className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500">{label}</dt>
      <dd className="mt-2 truncate text-sm font-semibold text-zinc-100">{value}</dd>
    </div>
  );
}
