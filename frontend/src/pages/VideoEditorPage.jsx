import { ArrowLeft, ArrowRight, CheckCircle2, Circle, Clock, Download, Film, Image, LockKeyhole, Music2, Palette, RefreshCw, Scissors, SlidersHorizontal, Sparkles, TriangleAlert, Type, UploadCloud, Video } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  applyVideoBrandingTemplate,
  createVideoBrandingTemplate,
  deleteVideoBrandingTemplate,
  deleteVideoRawClip,
  deleteVideoExport,
  getProject,
  getVideoEditorState,
  getVideoExportJob,
  getVideoWaveforms,
  runVideoAutoSync,
  startVideoExportJob,
  startVideoPreviewJob,
  updateVideoEditorSettings,
  uploadRawVideo,
  uploadVideoWatermarkLogo,
} from "../api.js";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { MAX_VIDEO_LOGO_UPLOAD_BYTES, MAX_VIDEO_LOGO_UPLOAD_MB, MAX_VIDEO_UPLOAD_BYTES, MAX_VIDEO_UPLOAD_MB, SUPPORTED_VIDEO_EXTENSIONS, SUPPORTED_VIDEO_LOGO_EXTENSIONS } from "../constants.js";
import { formatBytes, formatDateTime, formatDuration } from "../utils/format.js";

const runningStatuses = new Set(["Pending", "Processing"]);
const exportPresets = [
  { name: "YouTube 1080p", description: "Full HD MP4 for final session uploads." },
  { name: "YouTube 1440p (2K)", description: "2560 x 1440 export for sharper YouTube uploads." },
  { name: "YouTube 4K", description: "3840 x 2160 export for UHD delivery when your source can support it." },
  { name: "Lightweight Preview", description: "Smaller 720p render for quick review." },
  { name: "Source Quality", description: "Keep the source frame size where possible." },
];
const overlayPositions = ["Lower Left", "Lower Right", "Top Left", "Top Right"];
const overlayStyles = ["Boxed", "Clean", "Shadow"];
const overlaySizes = ["Small", "Medium", "Large"];
const watermarkPositions = ["Top Right", "Top Left", "Bottom Right", "Bottom Left"];
const transitionStyles = [
  { name: "Crossfade", description: "Blend clips together with a soft dissolve." },
  { name: "Dip to Black", description: "Fade through black between clips." },
  { name: "Cut", description: "Switch clips instantly with no overlap." },
];
const videoWorkflowDefinitions = [
  {
    key: "sources",
    number: 1,
    title: "Upload Videos",
    label: "Sources",
    icon: UploadCloud,
  },
  {
    key: "branding",
    number: 2,
    title: "Branding Info",
    label: "Brand",
    icon: Palette,
  },
  {
    key: "editor",
    number: 3,
    title: "Story Timeline",
    label: "Editor",
    icon: Scissors,
  },
  {
    key: "render",
    number: 4,
    title: "Render MP4",
    label: "Render",
    icon: Film,
  },
];
const videoWorkflowStatusLabels = {
  complete: "Done",
  current: "Now",
  ready: "Ready",
  locked: "Locked",
};
const videoWorkflowStatusStyles = {
  complete: {
    icon: "border-emerald-300/25 bg-emerald-300/10 text-emerald-50",
    badge: "border-emerald-300/25 bg-emerald-300/10 text-emerald-50",
  },
  current: {
    icon: "border-cyan-100/60 bg-cyan-200/30 text-cyan-50",
    badge: "border-cyan-100/40 bg-cyan-200/20 text-cyan-50",
  },
  ready: {
    icon: "border-white/16 bg-white/[0.04] text-zinc-200",
    badge: "border-white/16 bg-white/[0.04] text-zinc-300",
  },
  locked: {
    icon: "border-slate-600/45 bg-slate-950/30 text-slate-400",
    badge: "border-slate-600/45 bg-slate-950/30 text-slate-400",
  },
};
const defaultSettings = {
  rawVideo: null,
  rawVideos: [],
  selectedAudioAssetId: "",
  useSelectedMasterAudio: true,
  useOriginalVideoAudio: false,
  audioOffsetMs: 0,
  trimStartSeconds: 0,
  trimEndSeconds: 0,
  fadeInSeconds: 0,
  fadeOutSeconds: 0,
  exportPreset: "YouTube 1080p",
  assembly: {
    transitionStyle: "Crossfade",
    transitionDurationSeconds: 0.45,
    focusPlacements: [],
  },
  overlay: {
    songTitle: "",
    artistName: "",
    sessionLabel: "",
    position: "Lower Left",
    style: "Boxed",
    size: "Medium",
  },
  watermark: {
    enabled: false,
    logo: null,
    position: "Top Right",
    opacity: 0.82,
    scale: 0.14,
  },
  introCard: {
    enabled: false,
    durationSeconds: 2.5,
    title: "",
    subtitle: "",
  },
  outroCard: {
    enabled: false,
    durationSeconds: 2.5,
    title: "",
    subtitle: "",
  },
  autoSyncResult: {
    status: "Not Run",
    offsetMs: null,
    confidence: null,
    analyzedAt: null,
    message: "",
  },
  brandingTemplates: [],
  previewRender: null,
  finalExport: null,
  finalExports: [],
};

export default function VideoEditorPage() {
  const { projectId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const primaryVideoInputRef = useRef(null);
  const secondaryVideoInputRef = useRef(null);
  const logoInputRef = useRef(null);
  const [project, setProject] = useState(null);
  const [settings, setSettings] = useState(defaultSettings);
  const [audioAssets, setAudioAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [logoProgress, setLogoProgress] = useState(0);
  const [renderJob, setRenderJob] = useState(null);
  const [previewJob, setPreviewJob] = useState(null);
  const [waveformState, setWaveformState] = useState(null);
  const [waveformLoading, setWaveformLoading] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeStepKey, setActiveStepKey] = useState("sources");
  const requestedAudioId = searchParams.get("audio") || "";

  const selectedAudioAsset = useMemo(
    () => audioAssets.find((asset) => asset.id === settings.selectedAudioAssetId) || audioAssets[0] || null,
    [audioAssets, settings.selectedAudioAssetId],
  );
  const renderRunning = Boolean(renderJob && runningStatuses.has(renderJob.status));
  const previewRunning = Boolean(previewJob && runningStatuses.has(previewJob.status));
  const videoJobRunning = renderRunning || previewRunning;
  const rawVideos = settings.rawVideos || (settings.rawVideo ? [settings.rawVideo] : []);
  const primaryVideo = rawVideos.find((clip) => clip?.role === "Primary") || settings.rawVideo || null;
  const secondaryVideos = rawVideos.filter((clip) => clip?.role !== "Primary");
  const rawVideo = primaryVideo;
  const previewRender = settings.previewRender;
  const finalExport = settings.finalExport;
  const brandingTemplates = settings.brandingTemplates || [];
  const exportHistory = settings.finalExports || [];
  const rawDuration = estimateAssemblyDuration(primaryVideo);
  const trimStart = Math.max(0, Number(settings.trimStartSeconds) || 0);
  const trimEnd = Math.max(0, Number(settings.trimEndSeconds) || 0);
  const trimDuration = trimEnd > trimStart ? trimEnd - trimStart : Number.isFinite(rawDuration) ? Math.max(0, rawDuration - trimStart) : Number.NaN;
  const trimInvalid = trimEnd > 0 && trimEnd <= trimStart;
  const originalAudioChoiceValid = !settings.useOriginalVideoAudio || Boolean(primaryVideo?.hasAudioTrack);
  const validationMessages = getValidationMessages({ primaryVideo, secondaryVideos, selectedAudioAsset, settings, trimInvalid, originalAudioChoiceValid });
  const canExport = validationMessages.length === 0;
  const videoWorkflowState = getVideoWorkflowState({
    activeStepKey,
    primaryVideo,
    secondaryVideos,
    selectedAudioAsset,
    settings,
    previewRender,
    finalExport,
    canExport,
  });
  const nextWorkflowStep = getNextWorkflowStep(videoWorkflowState.steps, activeStepKey);

  useEffect(() => {
    if (!primaryVideo && activeStepKey !== "sources") {
      setActiveStepKey("sources");
    }
  }, [activeStepKey, primaryVideo]);

  const loadPage = async () => {
    setError("");
    try {
      const [nextProject, state] = await Promise.all([getProject(projectId), getVideoEditorState(projectId)]);
      setProject(nextProject);
      setVideoState(state);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPage();
  }, [projectId]);

  useEffect(() => {
    if (!renderJob?.id || !runningStatuses.has(renderJob.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getVideoExportJob(projectId, renderJob.id);
        setRenderJob(nextJob);
        if (!runningStatuses.has(nextJob.status)) {
          const state = await getVideoEditorState(projectId);
          setVideoState(state);
          setActionLoading("");
          if (nextJob.status === "Completed") {
            setNotice("Final MP4 is ready.");
          } else {
            setError(nextJob.errors?.[0]?.error || nextJob.message || "Video export failed.");
          }
        }
      } catch (err) {
        setError(err.message);
        setActionLoading("");
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [projectId, renderJob?.id, renderJob?.status]);

  useEffect(() => {
    if (!previewJob?.id || !runningStatuses.has(previewJob.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getVideoExportJob(projectId, previewJob.id);
        setPreviewJob(nextJob);
        if (!runningStatuses.has(nextJob.status)) {
          const state = await getVideoEditorState(projectId);
          setVideoState(state);
          setActionLoading("");
          if (nextJob.status === "Completed") {
            setNotice("Edited preview is ready.");
          } else {
            setError(nextJob.errors?.[0]?.error || nextJob.message || "Edited preview failed.");
          }
        }
      } catch (err) {
        setError(err.message);
        setActionLoading("");
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [projectId, previewJob?.id, previewJob?.status]);

  useEffect(() => {
    if (!requestedAudioId || !audioAssets.length) return undefined;
    const requestedAsset = audioAssets.find((asset) => asset.id === requestedAudioId);
    if (!requestedAsset) return undefined;
    if (settings.selectedAudioAssetId === requestedAsset.id && settings.useSelectedMasterAudio) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.delete("audio");
        return next;
      }, { replace: true });
      return undefined;
    }

    let cancelled = false;
    const applyRequestedAudio = async () => {
      setActionLoading("settings");
      setError("");
      try {
        const state = await updateVideoEditorSettings(projectId, {
          selectedAudioAssetId: requestedAsset.id,
          useSelectedMasterAudio: true,
        });
        if (cancelled) return;
        setVideoState(state);
        setNotice(`Video Editor loaded with ${requestedAsset.label}. You can still switch audio assets below.`);
      } catch (err) {
        if (cancelled) return;
        setError(err.message);
      } finally {
        if (cancelled) return;
        setActionLoading("");
        setSearchParams((current) => {
          const next = new URLSearchParams(current);
          next.delete("audio");
          return next;
        }, { replace: true });
      }
    };

    applyRequestedAudio();
    return () => {
      cancelled = true;
    };
  }, [audioAssets, projectId, requestedAudioId, setSearchParams, settings.selectedAudioAssetId, settings.useSelectedMasterAudio]);

  useEffect(() => {
    const canLoadWaveforms = Boolean(primaryVideo?.hasAudioTrack && selectedAudioAsset);
    if (!canLoadWaveforms) {
      setWaveformState(null);
      setWaveformLoading(false);
      return undefined;
    }

    let cancelled = false;
    const loadWaveforms = async () => {
      setWaveformLoading(true);
      try {
        const nextWaveforms = await getVideoWaveforms(projectId);
        if (!cancelled) setWaveformState(nextWaveforms);
      } catch {
        if (!cancelled) setWaveformState(null);
      } finally {
        if (!cancelled) setWaveformLoading(false);
      }
    };

    loadWaveforms();
    return () => {
      cancelled = true;
    };
  }, [projectId, primaryVideo?.id, primaryVideo?.hasAudioTrack, selectedAudioAsset?.id]);

  const setVideoState = (state) => {
    const nextSettings = normalizeSettings(state?.settings);
    setSettings(nextSettings);
    setAudioAssets(state?.availableAudioAssets || []);
  };

  const refreshState = async () => {
    setActionLoading("refresh");
    setError("");
    try {
      const state = await getVideoEditorState(projectId);
      setVideoState(state);
      setProject(await getProject(projectId));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const handlePrimaryVideoSelect = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const extension = getExtension(file.name);
    if (!SUPPORTED_VIDEO_EXTENSIONS.includes(extension)) {
      setError(`${file.name}: unsupported video format.`);
      return;
    }
    if (file.size > MAX_VIDEO_UPLOAD_BYTES) {
      setError(`${file.name}: exceeds ${MAX_VIDEO_UPLOAD_MB} MB.`);
      return;
    }

    setActionLoading("upload");
    setUploadProgress(0);
    setError("");
    setNotice("");
    try {
      const state = await uploadRawVideo(projectId, file, "primary", setUploadProgress);
      setVideoState(state);
      setNotice("Primary whole-band video uploaded and scanned.");
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const handleSecondaryVideoSelect = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;

    for (const file of files) {
      const extension = getExtension(file.name);
      if (!SUPPORTED_VIDEO_EXTENSIONS.includes(extension)) {
        setError(`${file.name}: unsupported video format.`);
        return;
      }
      if (file.size > MAX_VIDEO_UPLOAD_BYTES) {
        setError(`${file.name}: exceeds ${MAX_VIDEO_UPLOAD_MB} MB.`);
        return;
      }
    }

    setActionLoading("upload");
    setUploadProgress(0);
    setError("");
    setNotice("");
    try {
      let latestState = null;
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        latestState = await uploadRawVideo(projectId, file, "secondary", (progress) => {
          const overall = ((index + progress / 100) / files.length) * 100;
          setUploadProgress(Math.round(overall));
        });
      }
      if (latestState) {
        setVideoState(latestState);
        setNotice(`${files.length} focused clip${files.length === 1 ? "" : "s"} uploaded and scanned.`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const handleLogoSelect = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const extension = getExtension(file.name);
    if (!SUPPORTED_VIDEO_LOGO_EXTENSIONS.includes(extension)) {
      setError(`${file.name}: unsupported logo format.`);
      return;
    }
    if (file.size > MAX_VIDEO_LOGO_UPLOAD_BYTES) {
      setError(`${file.name}: exceeds ${MAX_VIDEO_LOGO_UPLOAD_MB} MB.`);
      return;
    }
    setActionLoading("logo");
    setLogoProgress(0);
    setError("");
    setNotice("");
    try {
      const state = await uploadVideoWatermarkLogo(projectId, file, setLogoProgress);
      setVideoState(state);
      setNotice("Watermark logo uploaded.");
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const updateLocalSettings = (updates) => {
    setSettings((current) => normalizeSettings({ ...current, ...updates }));
  };

  const updateLocalOverlay = (updates) => {
    setSettings((current) => normalizeSettings({ ...current, overlay: { ...(current.overlay || {}), ...updates } }));
  };

  const updateLocalFades = (updates) => {
    setSettings((current) => normalizeSettings({ ...current, ...updates }));
  };

  const commitSettings = async (updates) => {
    setActionLoading("settings");
    setError("");
    try {
      const state = await updateVideoEditorSettings(projectId, updates);
      setVideoState(state);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runAutoSync = async () => {
    setActionLoading("autoSync");
    setError("");
    setNotice("");
    try {
      const state = await runVideoAutoSync(projectId);
      setVideoState(state);
      const result = state?.settings?.autoSyncResult;
      setNotice(result?.message || "Auto-sync updated the audio offset.");
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runExport = async () => {
    setActionLoading("render");
    setError("");
    setNotice("");
    let queued = false;
    try {
      await updateVideoEditorSettings(projectId, settingsToPayload(settings));
      const job = await startVideoExportJob(projectId);
      setRenderJob(job);
      setNotice("Video export queued. Progress will update here.");
      queued = true;
    } catch (err) {
      setError(err.message);
    } finally {
      if (!queued) setActionLoading("");
    }
  };

  const runPreview = async () => {
    setActionLoading("preview");
    setError("");
    setNotice("");
    let queued = false;
    try {
      await updateVideoEditorSettings(projectId, settingsToPayload(settings));
      const job = await startVideoPreviewJob(projectId);
      setPreviewJob(job);
      setNotice("Edited preview queued. A lightweight draft MP4 will appear here when ready.");
      queued = true;
    } catch (err) {
      setError(err.message);
    } finally {
      if (!queued) setActionLoading("");
    }
  };

  const saveBrandingTemplate = async () => {
    const name = templateName.trim();
    if (!name) {
      setError("Enter a template name before saving.");
      return;
    }
    setActionLoading("templateSave");
    setError("");
    setNotice("");
    try {
      const state = await createVideoBrandingTemplate(projectId, { name });
      setVideoState(state);
      setTemplateName("");
      setNotice(`Saved branding template: ${name}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const applyTemplate = async (template) => {
    setActionLoading("templateApply");
    setError("");
    setNotice("");
    try {
      const state = await applyVideoBrandingTemplate(projectId, template.id);
      setVideoState(state);
      setNotice(`Applied branding template: ${template.name}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const removeTemplate = async (template) => {
    if (!window.confirm(`Delete branding template "${template.name}"?`)) return;
    setActionLoading("templateDelete");
    setError("");
    setNotice("");
    try {
      const state = await deleteVideoBrandingTemplate(projectId, template.id);
      setVideoState(state);
      setNotice(`Deleted branding template: ${template.name}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const removeExport = async (item) => {
    if (!window.confirm(`Delete video export "${item.label}"?`)) return;
    setActionLoading("exportDelete");
    setError("");
    setNotice("");
    try {
      const state = await deleteVideoExport(projectId, item.id);
      setVideoState(state);
      setNotice(`Deleted video export: ${item.label}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const moveClip = async (clipId, direction) => {
    const currentIndex = secondaryVideos.findIndex((clip) => clip.id === clipId);
    const nextIndex = currentIndex + direction;
    if (currentIndex < 0 || nextIndex < 0 || nextIndex >= secondaryVideos.length) return;
    const nextClips = [...secondaryVideos];
    const [clip] = nextClips.splice(currentIndex, 1);
    nextClips.splice(nextIndex, 0, clip);
    const ordered = primaryVideo ? [primaryVideo, ...nextClips] : nextClips;
    updateLocalSettings({ rawVideos: ordered, rawVideo: primaryVideo || null });
    setActionLoading("clipOrder");
    setError("");
    try {
      const state = await updateVideoEditorSettings(projectId, { clipOrderIds: ordered.map((item) => item.id) });
      setVideoState(state);
    } catch (err) {
      setError(err.message);
      await refreshState();
    } finally {
      setActionLoading("");
    }
  };

  const removeClip = async (clip) => {
    if (!window.confirm(`Remove raw video clip "${clip.originalFilename}"?`)) return;
    setActionLoading("clipDelete");
    setError("");
    setNotice("");
    try {
      const state = await deleteVideoRawClip(projectId, clip.id);
      setVideoState(state);
      setNotice(`Removed clip: ${clip.originalFilename}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const removePrimaryVideo = async () => {
    if (!primaryVideo) return;
    if (!window.confirm(`Remove primary video "${primaryVideo.originalFilename}"?`)) return;
    setActionLoading("clipDelete");
    setError("");
    setNotice("");
    try {
      const state = await deleteVideoRawClip(projectId, primaryVideo.id);
      setVideoState(state);
      setNotice(`Removed primary video: ${primaryVideo.originalFilename}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  if (loading) {
    return <ProcessingPanel title="Loading Video Editor" message="Reading video assets, master files, and editor settings." />;
  }

  const actionPanel = actionPanelFor(actionLoading, renderJob, previewJob, uploadProgress, logoProgress);

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>

      <div className="mt-5 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Video Editor</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">{project?.songTitle || project?.name || "Performance video"}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">Attach a generated master to one primary whole-band video, add optional secondary focused clips, let the editor assemble the cut automatically, then fine-tune sync, trim, branding, and export a final MP4.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button type="button" variant="secondary" onClick={refreshState} disabled={actionLoading === "refresh" || videoJobRunning}>
            <RefreshCw size={17} />
            Refresh
          </Button>
          <Button type="button" variant="secondary" onClick={runPreview} disabled={!canExport || actionLoading === "preview" || videoJobRunning}>
            <Video size={17} />
            Preview Edit
          </Button>
          <Button type="button" onClick={runExport} disabled={!canExport || actionLoading === "render" || videoJobRunning}>
            <Film size={17} />
            Export MP4
          </Button>
        </div>
      </div>

      {error ? <p className="mt-5 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}
      {notice ? <p className="mt-5 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">{notice}</p> : null}
      {validationMessages.length ? (
        <div className="mt-5 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-3">
          <p className="inline-flex items-center gap-2 text-sm font-semibold text-amber-100">
            <TriangleAlert size={16} />
            Video export needs attention
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {validationMessages.map((message) => (
              <span key={message} className="rounded-full border border-amber-300/20 bg-black/20 px-2.5 py-1 text-xs font-semibold text-amber-100">
                {message}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {actionPanel ? (
        <div className="mt-5">
          <ProcessingPanel {...actionPanel} />
        </div>
      ) : null}

      <VideoWorkflowGuide
        className="mt-5"
        state={videoWorkflowState}
        activeStepKey={activeStepKey}
        onStepChange={setActiveStepKey}
        nextStep={nextWorkflowStep}
        onNext={() => {
          if (nextWorkflowStep) setActiveStepKey(nextWorkflowStep.key);
        }}
      />

      <input ref={primaryVideoInputRef} type="file" accept=".mp4,.mov,.m4v,.webm,.mkv,video/*" className="hidden" onChange={handlePrimaryVideoSelect} />
      <input ref={secondaryVideoInputRef} type="file" accept=".mp4,.mov,.m4v,.webm,.mkv,video/*" multiple className="hidden" onChange={handleSecondaryVideoSelect} />
      <input ref={logoInputRef} type="file" accept=".png,.jpg,.jpeg,.webp,image/*" className="hidden" onChange={handleLogoSelect} />

      <section className={`mt-6 grid gap-5 ${["sources", "editor"].includes(activeStepKey) ? "xl:grid-cols-1" : "xl:grid-cols-[0.95fr_1.05fr]"}`}>
        <div className="space-y-5">
          {activeStepKey === "sources" ? (
            <>
          <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">Video Sources</h2>
                <p className="mt-1 text-sm text-zinc-400">Use one primary whole-band performance video as the base timeline, then add secondary focused clips for automatic cutaways.</p>
              </div>
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/20 text-teal-100">
                <Video size={18} />
              </div>
            </div>

            <div className="mt-4 space-y-5">
              <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-white">Primary Video</p>
                    <p className="mt-1 text-xs leading-5 text-zinc-500">This should be the full whole-band performance video. The final edit follows this timeline and uses it for sync and trim.</p>
                  </div>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Button type="button" onClick={() => primaryVideoInputRef.current?.click()} disabled={actionLoading === "upload" || videoJobRunning}>
                      <UploadCloud size={17} />
                      {primaryVideo ? "Replace Primary" : "Upload Primary"}
                    </Button>
                    {primaryVideo ? (
                      <Button type="button" variant="danger" onClick={removePrimaryVideo} disabled={actionLoading === "clipDelete" || videoJobRunning}>
                        Remove
                      </Button>
                    ) : null}
                  </div>
                </div>

                {primaryVideo ? (
                  <div className="mt-4 space-y-4">
                    <video className="aspect-video w-full rounded-lg border border-white/10 bg-black object-contain" src={primaryVideo.fileUrl} controls preload="metadata" />
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Readout label="Primary Video" value={primaryVideo.originalFilename} />
                      <Readout label="Timeline Length" value={formatDuration(primaryVideo.durationSeconds)} />
                      <Readout label="Resolution" value={primaryVideo.width && primaryVideo.height ? `${primaryVideo.width} x ${primaryVideo.height}` : "--"} />
                      <Readout label="Original Audio" value={primaryVideo.hasAudioTrack ? "Detected" : "None"} />
                    </div>
                  </div>
                ) : (
                  <div className="mt-4">
                    <EmptyState
                      icon={Video}
                      title="No primary video yet"
                      description="Upload the whole-band performance video first. Secondary focused clips stay optional."
                      action={
                        <Button type="button" onClick={() => primaryVideoInputRef.current?.click()}>
                          <UploadCloud size={17} />
                          Upload Primary
                        </Button>
                      }
                    />
                  </div>
                )}
              </div>

              <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-white">Secondary Focused Clips</p>
                    <p className="mt-1 text-xs leading-5 text-zinc-500">These clips are automatically inserted as focused cutaways over the primary performance video.</p>
                  </div>
                  <Button type="button" onClick={() => secondaryVideoInputRef.current?.click()} disabled={actionLoading === "upload" || videoJobRunning}>
                    <UploadCloud size={17} />
                    {secondaryVideos.length ? "Add Focus Clips" : "Upload Focus Clips"}
                  </Button>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Readout label="Focused Clips" value={secondaryVideos.length} />
                  <Readout label="Timeline Length" value={formatDuration(rawDuration)} />
                  <Readout label="Transition Style" value={settings.assembly?.transitionStyle || "Crossfade"} />
                  <Readout label="Transition" value={formatSecondsLabel(settings.assembly?.transitionDurationSeconds)} />
                </div>

                {secondaryVideos.length ? (
                  <div className="mt-4 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-white">Focus Clip Order</p>
                        <p className="mt-1 text-xs leading-5 text-zinc-500">Move these up or down to change the order of automatic focused cutaways.</p>
                      </div>
                      <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-300">
                        {secondaryVideos.length} clip{secondaryVideos.length === 1 ? "" : "s"}
                      </span>
                    </div>
                    {secondaryVideos.map((clip, index) => (
                      <RawVideoClipCard
                        key={clip.id}
                        clip={clip}
                        index={index}
                        clipCount={secondaryVideos.length}
                        onMove={moveClip}
                        onRemove={removeClip}
                        busy={videoJobRunning || actionLoading === "clipDelete" || actionLoading === "clipOrder"}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">No focused cutaway clips yet. The editor will use the primary whole-band video on its own until you add secondary clips.</p>
                )}
              </div>
            </div>
          </section>

            </>
          ) : activeStepKey === "branding" ? (
            <BrandingStepPreviewPanel rawVideos={rawVideos} settings={settings} previewRender={previewRender} canExport={canExport} videoJobRunning={videoJobRunning} actionLoading={actionLoading} onPreview={runPreview} />
          ) : activeStepKey === "editor" ? (
            <>
            <GeneratedAudioPanel
              projectId={projectId}
              audioAssets={audioAssets}
              selectedAudioAsset={selectedAudioAsset}
              selectedId={settings.selectedAudioAssetId || selectedAudioAsset?.id || ""}
              onSelect={(value) => {
                updateLocalSettings({ selectedAudioAssetId: value, useSelectedMasterAudio: true });
                commitSettings({ selectedAudioAssetId: value, useSelectedMasterAudio: true });
              }}
            />
            <VideoStoryEditorPanel
              primaryVideo={primaryVideo}
              secondaryVideos={secondaryVideos}
              selectedAudioAsset={selectedAudioAsset}
              settings={settings}
              trimStart={trimStart}
              trimEnd={trimEnd}
              trimDuration={trimDuration}
              onFocusPlacementsPreview={(focusPlacements) => updateLocalSettings({ assembly: { ...(settings.assembly || {}), focusPlacements } })}
              onFocusPlacementsCommit={(focusPlacements) => commitSettings({ focusPlacements })}
            />
            <SyncTrimPanel
              settings={settings}
              audioAssets={audioAssets}
              videoJobRunning={videoJobRunning}
              primaryVideo={primaryVideo}
              selectedAudioAsset={selectedAudioAsset}
              actionLoading={actionLoading}
              waveformState={waveformState}
              waveformLoading={waveformLoading}
              trimInvalid={trimInvalid}
              trimDuration={trimDuration}
              runAutoSync={runAutoSync}
              updateLocalSettings={updateLocalSettings}
              updateLocalFades={updateLocalFades}
              commitSettings={commitSettings}
            />
            <EditedPreviewPanel
              previewRender={previewRender}
              settings={settings}
              rawVideo={rawVideo}
              canExport={canExport}
              actionLoading={actionLoading}
              videoJobRunning={videoJobRunning}
              runPreview={runPreview}
            />
            </>
          ) : (
            <RenderQualityPanel
              presets={exportPresets}
              selectedPreset={settings.exportPreset}
              primaryVideo={primaryVideo}
              secondaryVideos={secondaryVideos}
              selectedAudioAsset={selectedAudioAsset}
              settings={settings}
              trimDuration={trimDuration}
              validationMessages={validationMessages}
              canExport={canExport}
              actionLoading={actionLoading}
              videoJobRunning={videoJobRunning}
              onPresetSelect={(exportPreset) => {
                updateLocalSettings({ exportPreset });
                commitSettings({ exportPreset });
              }}
              onRender={runExport}
            />
          )}
        </div>

        {["branding", "render"].includes(activeStepKey) ? (
        <div className="space-y-5">
          {activeStepKey === "branding" ? (
            <>
          <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="font-semibold text-white">Branding Templates</h2>
                <p className="mt-1 text-sm text-zinc-400">Save and reapply overlay, watermark, and card combinations for repeated session finishing.</p>
              </div>
              <StatusBadge status={brandingTemplates.length ? "Completed" : "Pending"} />
            </div>

            <div className="mt-4 flex flex-col gap-3 lg:flex-row">
              <input
                type="text"
                value={templateName}
                placeholder="Sunday live session"
                onChange={(event) => setTemplateName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") saveBrandingTemplate();
                }}
                className="h-10 flex-1 rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white placeholder:text-zinc-600"
              />
              <Button type="button" variant="secondary" onClick={saveBrandingTemplate} disabled={actionLoading === "templateSave"}>
                <Palette size={17} />
                Save Current Branding
              </Button>
            </div>

            {brandingTemplates.length ? (
              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                {brandingTemplates.map((template) => (
                  <BrandingTemplateCard
                    key={template.id}
                    template={template}
                    applyTemplate={applyTemplate}
                    removeTemplate={removeTemplate}
                    busy={actionLoading === "templateApply" || actionLoading === "templateDelete"}
                  />
                ))}
              </div>
            ) : (
              <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">No branding templates saved yet.</p>
            )}
          </section>

          <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">Branding Overlay</h2>
                <p className="mt-1 text-sm text-zinc-400">Burn a title block into the export with configurable placement, style, and size.</p>
              </div>
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/20 text-teal-100">
                <Type size={18} />
              </span>
            </div>

            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              <TextControl
                label="Song Title"
                value={settings.overlay.songTitle}
                placeholder={project?.songTitle || "Song title"}
                onChange={(value) => updateLocalOverlay({ songTitle: value })}
                onCommit={(value) => commitSettings({ songTitle: value })}
              />
              <TextControl
                label="Artist / Band"
                value={settings.overlay.artistName}
                placeholder={project?.artistName || "Artist name"}
                onChange={(value) => updateLocalOverlay({ artistName: value })}
                onCommit={(value) => commitSettings({ artistName: value })}
              />
              <TextControl
                label="Session Label"
                value={settings.overlay.sessionLabel}
                placeholder="Live Session"
                onChange={(value) => updateLocalOverlay({ sessionLabel: value })}
                onCommit={(value) => commitSettings({ sessionLabel: value })}
              />
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              <SelectControl
                label="Placement"
                value={settings.overlay.position}
                onChange={(overlayPosition) => {
                  updateLocalOverlay({ position: overlayPosition });
                  commitSettings({ overlayPosition });
                }}
                options={overlayPositions.map((value) => ({ value, label: value }))}
              />
              <SelectControl
                label="Style"
                value={settings.overlay.style}
                onChange={(overlayStyle) => {
                  updateLocalOverlay({ style: overlayStyle });
                  commitSettings({ overlayStyle });
                }}
                options={overlayStyles.map((value) => ({ value, label: value }))}
              />
              <SelectControl
                label="Size"
                value={settings.overlay.size}
                onChange={(overlaySize) => {
                  updateLocalOverlay({ size: overlaySize });
                  commitSettings({ overlaySize });
                }}
                options={overlaySizes.map((value) => ({ value, label: value }))}
              />
            </div>
            <VideoFramePreview rawVideos={rawVideos} settings={settings} />
          </section>

          <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">Watermark Logo</h2>
                <p className="mt-1 text-sm text-zinc-400">Optional static logo burned into the final MP4.</p>
              </div>
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/20 text-teal-100">
                <Image size={18} />
              </span>
            </div>

            <div className="mt-4 space-y-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <label className="flex items-center gap-2 text-sm font-semibold text-zinc-300">
                  <input
                    type="checkbox"
                    checked={Boolean(settings.watermark.enabled)}
                    disabled={!settings.watermark.logo || videoJobRunning}
                    onChange={(event) => {
                      updateLocalSettings({ watermark: { ...settings.watermark, enabled: event.target.checked } });
                      commitSettings({ watermarkEnabled: event.target.checked });
                    }}
                    className="h-4 w-4 rounded border-white/20 bg-black/30 accent-teal-300"
                  />
                  Enable watermark
                </label>
                <Button type="button" variant="secondary" onClick={() => logoInputRef.current?.click()} disabled={actionLoading === "logo" || videoJobRunning}>
                  <UploadCloud size={17} />
                  {settings.watermark.logo ? "Replace Logo" : "Upload Logo"}
                </Button>
              </div>
              {settings.watermark.logo ? (
                <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-black/20 p-3">
                  <img src={settings.watermark.logo.fileUrl} alt="" className="h-12 w-12 rounded border border-white/10 object-contain" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">{settings.watermark.logo.originalFilename}</p>
                    <p className="mt-1 text-xs text-zinc-500">{formatBytes(settings.watermark.logo.fileSize)}</p>
                  </div>
                </div>
              ) : null}
              <div className="grid gap-4 sm:grid-cols-3">
                <SelectControl
                  label="Position"
                  value={settings.watermark.position}
                  onChange={(watermarkPosition) => {
                    updateLocalSettings({ watermark: { ...settings.watermark, position: watermarkPosition } });
                    commitSettings({ watermarkPosition });
                  }}
                  options={watermarkPositions.map((value) => ({ value, label: value }))}
                />
                <NumberControl
                  label="Opacity"
                  suffix=""
                  min={0.05}
                  max={1}
                  step={0.05}
                  value={settings.watermark.opacity}
                  helper="1 is fully opaque."
                  onChange={(value) => updateLocalSettings({ watermark: { ...settings.watermark, opacity: value } })}
                  onCommit={(value) => commitSettings({ watermarkOpacity: value })}
                />
                <NumberControl
                  label="Logo Scale"
                  suffix=""
                  min={0.05}
                  max={0.5}
                  step={0.01}
                  value={settings.watermark.scale}
                  helper="Relative to video height."
                  onChange={(value) => updateLocalSettings({ watermark: { ...settings.watermark, scale: value } })}
                  onCommit={(value) => commitSettings({ watermarkScale: value })}
                />
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">Intro & Outro Cards</h2>
                <p className="mt-1 text-sm text-zinc-400">Add simple still title cards before or after the performance.</p>
              </div>
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/20 text-teal-100">
                <Palette size={18} />
              </span>
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <TitleCardControls
                label="Intro Card"
                card={settings.introCard}
                onLocalChange={(updates) => updateLocalSettings({ introCard: { ...settings.introCard, ...updates } })}
                onCommit={(updates) => commitSettings(prefixTitleCardPayload("intro", updates))}
              />
              <TitleCardControls
                label="Outro Card"
                card={settings.outroCard}
                onLocalChange={(updates) => updateLocalSettings({ outroCard: { ...settings.outroCard, ...updates } })}
                onCommit={(updates) => commitSettings(prefixTitleCardPayload("outro", updates))}
              />
            </div>
          </section>
            </>
          ) : null}

          {activeStepKey === "branding" ? (
          <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="font-semibold text-white">Edited Preview</h2>
                <p className="mt-1 text-sm text-zinc-400">Render a lightweight draft MP4 using the current trim, sync, overlays, cards, watermark, and fades before exporting the final version.</p>
              </div>
              <Button type="button" variant="secondary" onClick={runPreview} disabled={!canExport || actionLoading === "preview" || videoJobRunning}>
                <Video size={17} />
                Render Preview
              </Button>
            </div>

            {previewRender ? (
              <div className="mt-4 space-y-4">
                <video className="aspect-video w-full rounded-lg border border-white/10 bg-black object-contain" src={previewRender.fileUrl} controls preload="metadata" />
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <Readout label="Preview" value={previewRender.label} />
                  <Readout label="Created" value={formatDateTime(previewRender.createdAt)} />
                  <Readout label="Duration" value={formatDuration(previewRender.durationSeconds)} />
                  <Readout label="Soundtrack" value={describeFinalExportAudioSource(previewRender)} />
                  <Readout label="Assembly" value={describeFinalExportAssembly(previewRender)} />
                  <Readout label="Sync Offset" value={formatSignedMilliseconds(previewRender.settings?.audioOffsetMs)} />
                  <Readout label="Trim" value={describeFinalExportTrim(previewRender)} />
                  <Readout label="Fades" value={describeFinalExportFades(previewRender)} />
                  <Readout label="Overlay" value={describeFinalExportOverlay(previewRender)} />
                  <Readout label="Cards" value={describeFinalExportCards(previewRender)} />
                </div>
                <p className="truncate text-xs text-zinc-500">{previewRender.filePath}</p>
                <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                  <Button as="a" href={previewRender.fileUrl} target="_blank" rel="noreferrer" variant="secondary">
                    <Download size={17} />
                    Open Preview
                  </Button>
                  <Button type="button" variant="secondary" onClick={runPreview} disabled={!canExport || actionLoading === "preview" || videoJobRunning}>
                    <RefreshCw size={17} />
                    Refresh Preview
                  </Button>
                </div>
                {isPreviewOutdated(previewRender, settings, rawVideo) ? (
                  <p className="rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">Preview may be outdated. Render it again after changing edit settings.</p>
                ) : null}
              </div>
            ) : (
              <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">No edited preview yet. Render one to watch the current cut before final export.</p>
            )}
          </section>
          ) : null}

          {activeStepKey === "render" ? (
          <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="font-semibold text-white">Final MP4</h2>
                <p className="mt-1 text-sm text-zinc-400">The latest rendered video and its finishing snapshot are saved in this project&apos;s local video exports.</p>
              </div>
              <Button type="button" onClick={runExport} disabled={!canExport || actionLoading === "render" || videoJobRunning}>
                <Scissors size={17} />
                Render MP4
              </Button>
            </div>

            {finalExport ? (
              <div className="mt-4 space-y-4">
                <video className="aspect-video w-full rounded-lg border border-white/10 bg-black object-contain" src={finalExport.fileUrl} controls preload="metadata" />
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <Readout label="Export" value={finalExport.label} />
                  <Readout label="Preset" value={finalExport.exportPreset || finalExport.settings?.exportPreset} />
                  <Readout label="Created" value={formatDateTime(finalExport.createdAt)} />
                  <Readout label="Duration" value={formatDuration(finalExport.durationSeconds)} />
                  <Readout label="Size" value={formatBytes(finalExport.sizeBytes)} />
                  <Readout label="Soundtrack" value={describeFinalExportAudioSource(finalExport)} />
                  <Readout label="Assembly" value={describeFinalExportAssembly(finalExport)} />
                  <Readout label="Audio Mix" value={describeFinalExportAudioBlend(finalExport)} />
                  <Readout label="Sync Offset" value={formatSignedMilliseconds(finalExport.settings?.audioOffsetMs)} />
                  <Readout label="Trim" value={describeFinalExportTrim(finalExport)} />
                  <Readout label="Fades" value={describeFinalExportFades(finalExport)} />
                  <Readout label="Overlay" value={describeFinalExportOverlay(finalExport)} />
                  <Readout label="Cards" value={describeFinalExportCards(finalExport)} />
                  <Readout label="Watermark" value={describeFinalExportWatermark(finalExport)} />
                </div>
                <p className="truncate text-xs text-zinc-500">{finalExport.filePath}</p>
                <Button as="a" href={finalExport.fileUrl} target="_blank" rel="noreferrer" variant="secondary">
                  <Download size={17} />
                  Open MP4
                </Button>

                <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-white">Render History</p>
                      <p className="mt-1 text-xs leading-5 text-zinc-500">Older final videos stay available here until you remove them.</p>
                    </div>
                    <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-300">
                      {exportHistory.length} version{exportHistory.length === 1 ? "" : "s"}
                    </span>
                  </div>

                  <div className="mt-3 space-y-3">
                    {exportHistory.map((item) => (
                      <ExportHistoryCard
                        key={item.id}
                        item={item}
                        active={item.id === finalExport.id}
                        onDelete={removeExport}
                        busy={actionLoading === "exportDelete"}
                      />
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">No final video has been exported yet.</p>
            )}
          </section>
          ) : null}
        </div>
        ) : null}
      </section>
    </div>
  );
}

function normalizeSettings(settings) {
  const normalizedVideosSource = Array.isArray(settings?.rawVideos) && settings.rawVideos.length
    ? settings.rawVideos
    : settings?.rawVideo
      ? [settings.rawVideo]
      : [];
  const normalizedVideos = normalizedVideosSource.map((clip, index) => ({
    ...clip,
    role: clip?.role || (index === 0 ? "Primary" : "Secondary"),
  }));
  const normalizedPrimaryVideo = normalizedVideos.find((clip) => clip?.role === "Primary") || settings?.rawVideo || null;
  return {
    ...defaultSettings,
    ...(settings || {}),
    rawVideos: normalizedVideos,
    rawVideo: normalizedPrimaryVideo,
    selectedAudioAssetId: settings?.selectedAudioAssetId || "",
    fadeInSeconds: Number(settings?.fadeInSeconds) || 0,
    fadeOutSeconds: Number(settings?.fadeOutSeconds) || 0,
    exportPreset: settings?.exportPreset || "YouTube 1080p",
    assembly: {
      ...defaultSettings.assembly,
      ...(settings?.assembly || {}),
      transitionStyle: settings?.assembly?.transitionStyle || "Crossfade",
      transitionDurationSeconds: Number(settings?.assembly?.transitionDurationSeconds) || 0.45,
      focusPlacements: Array.isArray(settings?.assembly?.focusPlacements) ? settings.assembly.focusPlacements : [],
    },
    overlay: {
      ...defaultSettings.overlay,
      ...(settings?.overlay || {}),
      songTitle: settings?.overlay?.songTitle || "",
      artistName: settings?.overlay?.artistName || "",
      sessionLabel: settings?.overlay?.sessionLabel || "",
      position: settings?.overlay?.position || "Lower Left",
      style: settings?.overlay?.style || "Boxed",
      size: settings?.overlay?.size || "Medium",
    },
    watermark: {
      ...defaultSettings.watermark,
      ...(settings?.watermark || {}),
    },
    introCard: {
      ...defaultSettings.introCard,
      ...(settings?.introCard || {}),
      title: settings?.introCard?.title || "",
      subtitle: settings?.introCard?.subtitle || "",
    },
    outroCard: {
      ...defaultSettings.outroCard,
      ...(settings?.outroCard || {}),
      title: settings?.outroCard?.title || "",
      subtitle: settings?.outroCard?.subtitle || "",
    },
    autoSyncResult: {
      ...defaultSettings.autoSyncResult,
      ...(settings?.autoSyncResult || {}),
      message: settings?.autoSyncResult?.message || "",
    },
    brandingTemplates: Array.isArray(settings?.brandingTemplates) ? settings.brandingTemplates : [],
    previewRender: settings?.previewRender || null,
    finalExports: Array.isArray(settings?.finalExports) ? settings.finalExports : settings?.finalExport ? [settings.finalExport] : [],
  };
}

function settingsToPayload(settings) {
  return {
    selectedAudioAssetId: settings.selectedAudioAssetId || null,
    useSelectedMasterAudio: Boolean(settings.useSelectedMasterAudio),
    useOriginalVideoAudio: Boolean(settings.useOriginalVideoAudio),
    clipOrderIds: Array.isArray(settings.rawVideos) ? settings.rawVideos.map((clip) => clip.id) : [],
    audioOffsetMs: Number(settings.audioOffsetMs) || 0,
    trimStartSeconds: Math.max(0, Number(settings.trimStartSeconds) || 0),
    trimEndSeconds: Math.max(0, Number(settings.trimEndSeconds) || 0),
    fadeInSeconds: Math.max(0, Number(settings.fadeInSeconds) || 0),
    fadeOutSeconds: Math.max(0, Number(settings.fadeOutSeconds) || 0),
    exportPreset: settings.exportPreset || "YouTube 1080p",
    transitionStyle: settings.assembly?.transitionStyle || "Crossfade",
    transitionDurationSeconds: Math.max(0, Number(settings.assembly?.transitionDurationSeconds) || 0),
    focusPlacements: Array.isArray(settings.assembly?.focusPlacements)
      ? settings.assembly.focusPlacements.map((placement) => ({
          id: placement.id || newFocusCutId(),
          clipId: placement.clipId,
          startSeconds: Math.max(0, Number(placement.startSeconds) || 0),
          durationSeconds: Math.max(0.25, Number(placement.durationSeconds) || 0.25),
          sourceStartSeconds: Math.max(0, Number(placement.sourceStartSeconds) || 0),
        }))
      : [],
    songTitle: settings.overlay?.songTitle || null,
    artistName: settings.overlay?.artistName || null,
    sessionLabel: settings.overlay?.sessionLabel || null,
    overlayPosition: settings.overlay?.position || "Lower Left",
    overlayStyle: settings.overlay?.style || "Boxed",
    overlaySize: settings.overlay?.size || "Medium",
    watermarkEnabled: Boolean(settings.watermark?.enabled),
    watermarkPosition: settings.watermark?.position || "Top Right",
    watermarkOpacity: Number(settings.watermark?.opacity) || 0.82,
    watermarkScale: Number(settings.watermark?.scale) || 0.14,
    introEnabled: Boolean(settings.introCard?.enabled),
    introDurationSeconds: Number(settings.introCard?.durationSeconds) || 2.5,
    introTitle: settings.introCard?.title || null,
    introSubtitle: settings.introCard?.subtitle || null,
    outroEnabled: Boolean(settings.outroCard?.enabled),
    outroDurationSeconds: Number(settings.outroCard?.durationSeconds) || 2.5,
    outroTitle: settings.outroCard?.title || null,
    outroSubtitle: settings.outroCard?.subtitle || null,
  };
}

function VideoWorkflowGuide({ state, activeStepKey, onStepChange, nextStep, onNext, className = "" }) {
  const activeStep = state.steps.find((step) => step.key === activeStepKey) || state.steps[0];
  const NextIcon = nextStep?.icon || activeStep.icon;

  return (
    <section className={`workflow-guide rounded-2xl border border-cyan-300/20 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.18),transparent_36%),linear-gradient(180deg,rgba(10,18,32,0.96),rgba(4,10,20,0.96))] p-4 shadow-[0_20px_60px_rgba(8,145,178,0.12)] ${className}`}>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-100/90">Step-by-step video workflow</p>
          <h2 className="mt-2 text-lg font-semibold text-white">
            Step {activeStep.number}: {activeStep.title}
          </h2>
          <p className="mt-1 text-sm text-slate-200/80">{state.summary}</p>
        </div>
        {nextStep ? (
          <Button type="button" onClick={onNext} className="sm:w-auto">
            <NextIcon size={17} />
            Next: {nextStep.label}
            <ArrowRight size={16} />
          </Button>
        ) : null}
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {state.steps.map((step) => (
          <VideoWorkflowStepCard key={step.key} step={step} active={step.key === activeStepKey} onSelect={() => onStepChange(step.key)} />
        ))}
      </div>
    </section>
  );
}

function VideoWorkflowStepCard({ step, active, onSelect }) {
  const Icon = step.icon;
  const statusClass = videoWorkflowStatusStyles[step.status] || videoWorkflowStatusStyles.locked;
  const disabled = !step.available;
  const toneClass = active
    ? "border-cyan-100/75 bg-[linear-gradient(180deg,rgba(103,232,249,0.34),rgba(14,165,233,0.22))] shadow-[0_0_0_1px_rgba(224,242,254,0.3),0_18px_40px_rgba(14,165,233,0.24)]"
    : step.available
      ? "border-white/12 bg-slate-950/72 hover:border-cyan-300/28 hover:bg-slate-900/92"
      : "border-slate-700/45 bg-slate-950/42 opacity-80";
  const stepNumberClass = active ? "text-slate-950/80" : "text-slate-300/62";
  const titleClass = active ? "text-slate-950" : "text-white";
  const detailClass = active ? "text-slate-900/72" : "text-slate-200/68";

  return (
    <button
      type="button"
      data-status={step.status}
      disabled={disabled}
      onClick={disabled ? undefined : onSelect}
      className={`workflow-step-card rounded-lg border p-3 text-left transition disabled:cursor-not-allowed ${toneClass}`}
    >
      <div className="flex items-start justify-between gap-3">
        <span className={`workflow-step-icon grid h-9 w-9 shrink-0 place-items-center rounded-lg border ${statusClass.icon}`}>
          <Icon size={17} />
        </span>
        <span className={`workflow-status-badge inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass.badge}`}>
          {step.status === "complete" ? <CheckCircle2 size={12} /> : step.status === "locked" ? <LockKeyhole size={12} /> : <Circle size={12} />}
          {step.statusLabel}
        </span>
      </div>
      <p className={`mt-3 text-xs font-semibold uppercase tracking-[0.12em] ${stepNumberClass}`}>Step {step.number}</p>
      <p className={`mt-1 truncate text-sm font-semibold ${titleClass}`}>{step.title}</p>
      <p className={`mt-1 min-h-5 truncate text-xs ${detailClass}`}>{step.detail}</p>
    </button>
  );
}

function GeneratedAudioPanel({ projectId, audioAssets, selectedAudioAsset, selectedId, onSelect }) {
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-semibold text-white">Generated Audio</h2>
          <p className="mt-1 text-sm text-zinc-400">Choose a master or audio export already created in this project for the edited video soundtrack.</p>
        </div>
        {selectedAudioAsset ? <StatusBadge status={selectedAudioAsset.kind} /> : null}
      </div>

      {audioAssets.length ? (
        <div className="mt-4 space-y-4">
          <SelectControl
            label="Audio Asset"
            value={selectedId}
            onChange={onSelect}
            options={audioAssets.map((asset) => ({ value: asset.id, label: `${asset.label} - ${asset.kind}${asset.outputFormat ? ` - ${asset.outputFormat}` : ""}` }))}
          />
          <AudioAssetCards assets={audioAssets} selectedId={selectedId} onSelect={onSelect} />
          {selectedAudioAsset ? (
            <div className="rounded-lg border border-white/10 bg-black/20 p-3">
              <p className="truncate text-sm font-semibold text-white">{selectedAudioAsset.label}</p>
              <p className="mt-1 truncate text-xs text-zinc-500">{selectedAudioAsset.filePath}</p>
              <audio className="mt-3 w-full" src={selectedAudioAsset.fileUrl} controls preload="metadata" />
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-4">
          <EmptyState
            icon={Music2}
            title="No generated audio yet"
            description="Generate a master first, then return here to attach it to the performance video."
            action={
              <Button as={Link} to={`/projects/${projectId}/mastering`}>
                Open Mastering
              </Button>
            }
          />
        </div>
      )}
    </section>
  );
}

function SyncTrimPanel({
  settings,
  audioAssets,
  videoJobRunning,
  primaryVideo,
  selectedAudioAsset,
  actionLoading,
  waveformState,
  waveformLoading,
  trimInvalid,
  trimDuration,
  runAutoSync,
  updateLocalSettings,
  updateLocalFades,
  commitSettings,
}) {
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-white">Sync & Trim</h2>
          <p className="mt-1 text-sm text-zinc-400">Shape focused-cut transitions, align the generated audio, and keep the primary timeline to a clean start/end range.</p>
        </div>
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/20 text-teal-100">
          <SlidersHorizontal size={18} />
        </span>
      </div>

      <div className="mt-4 space-y-4">
        <TransitionStyleCards
          styles={transitionStyles}
          selectedStyle={settings.assembly?.transitionStyle || "Crossfade"}
          onSelect={(transitionStyle) => {
            updateLocalSettings({ assembly: { ...(settings.assembly || {}), transitionStyle } });
            commitSettings({ transitionStyle });
          }}
        />
        <label className="flex items-start gap-3 rounded-lg border border-white/10 bg-black/20 p-3 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={Boolean(settings.useSelectedMasterAudio)}
            disabled={!audioAssets.length || videoJobRunning}
            onChange={(event) => {
              updateLocalSettings({ useSelectedMasterAudio: event.target.checked });
              commitSettings({ useSelectedMasterAudio: event.target.checked });
            }}
            className="mt-1 h-4 w-4 rounded border-white/20 bg-black/30 accent-teal-300"
          />
          <span>
            <span className="block font-semibold text-white">Use selected generated audio</span>
            <span className="mt-1 block text-xs leading-5 text-zinc-500">When enabled, the selected master or export becomes the main soundtrack.</span>
          </span>
        </label>
        <label className="flex items-start gap-3 rounded-lg border border-white/10 bg-black/20 p-3 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={Boolean(settings.useOriginalVideoAudio)}
            disabled={!primaryVideo?.hasAudioTrack || videoJobRunning}
            onChange={(event) => {
              updateLocalSettings({ useOriginalVideoAudio: event.target.checked });
              commitSettings({ useOriginalVideoAudio: event.target.checked });
            }}
            className="mt-1 h-4 w-4 rounded border-white/20 bg-black/30 accent-teal-300"
          />
          <span>
            <span className="block font-semibold text-white">Keep original video audio</span>
            <span className="mt-1 block text-xs leading-5 text-zinc-500">{primaryVideo?.hasAudioTrack ? "Mix in the primary video audio underneath the generated master when you want some room feel." : "The current primary video has no detected original audio."}</span>
          </span>
        </label>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
          <NumberControl
            label="Transition"
            suffix="sec"
            min={0}
            max={2}
            step={0.05}
            value={settings.assembly?.transitionDurationSeconds}
            helper={(settings.assembly?.transitionStyle || "Crossfade") === "Cut" ? "Cut ignores overlap duration." : "Shared overlap duration between clip transitions."}
            onChange={(value) => updateLocalSettings({ assembly: { ...(settings.assembly || {}), transitionDurationSeconds: value } })}
            onCommit={(value) => commitSettings({ transitionDurationSeconds: value })}
          />
          <NumberControl
            label="Audio Offset"
            suffix="ms"
            min={-600000}
            max={600000}
            step={10}
            value={settings.audioOffsetMs}
            helper="Positive delays the master. Negative starts it earlier."
            onChange={(value) => updateLocalSettings({ audioOffsetMs: value })}
            onCommit={(value) => commitSettings({ audioOffsetMs: value })}
          />
          <NumberControl
            label="Trim Start"
            suffix="sec"
            min={0}
            step={0.1}
            value={settings.trimStartSeconds}
            helper="Seconds into the primary video timeline where the output begins."
            onChange={(value) => updateLocalSettings({ trimStartSeconds: value })}
            onCommit={(value) => commitSettings({ trimStartSeconds: value })}
          />
          <NumberControl
            label="Trim End"
            suffix="sec"
            min={0}
            step={0.1}
            value={settings.trimEndSeconds}
            helper="Use 0 to render until the primary video timeline ends."
            onChange={(value) => updateLocalSettings({ trimEndSeconds: value })}
            onCommit={(value) => commitSettings({ trimEndSeconds: value })}
          />
          <NumberControl
            label="Fade In"
            suffix="sec"
            min={0}
            max={8}
            step={0.1}
            value={settings.fadeInSeconds}
            helper="Applies to video and audio at the start."
            onChange={(value) => updateLocalFades({ fadeInSeconds: value })}
            onCommit={(value) => commitSettings({ fadeInSeconds: value })}
          />
          <NumberControl
            label="Fade Out"
            suffix="sec"
            min={0}
            max={8}
            step={0.1}
            value={settings.fadeOutSeconds}
            helper="Applies to video and audio at the end."
            onChange={(value) => updateLocalFades({ fadeOutSeconds: value })}
            onCommit={(value) => commitSettings({ fadeOutSeconds: value })}
          />
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-white">Automatic Sync</p>
              <p className="mt-1 text-xs leading-5 text-zinc-500">
                Uses the primary video audio as the sync reference against the selected generated audio. You can still fine-tune manually after the estimate.
              </p>
              {settings.autoSyncResult?.message ? (
                <p className="mt-2 text-xs text-teal-100">
                  {settings.autoSyncResult.message}
                  {Number.isFinite(settings.autoSyncResult.confidence) ? ` Confidence ${Math.round(settings.autoSyncResult.confidence * 100)}%.` : ""}
                </p>
              ) : null}
            </div>
            <Button type="button" variant="secondary" onClick={runAutoSync} disabled={!primaryVideo?.hasAudioTrack || !selectedAudioAsset || actionLoading === "autoSync" || videoJobRunning}>
              <Sparkles size={17} />
              Try Auto-Sync
            </Button>
          </div>
        </div>

        <WaveformSyncPanel
          waveformState={waveformState}
          loading={waveformLoading}
          offsetMs={settings.audioOffsetMs}
          hasOriginalAudio={Boolean(primaryVideo?.hasAudioTrack)}
          hasSelectedAudio={Boolean(selectedAudioAsset)}
        />

        <div className={`rounded-lg border px-3 py-2 ${trimInvalid ? "border-rose-300/20 bg-rose-400/10 text-rose-100" : "border-teal-300/20 bg-teal-300/10 text-teal-100"}`}>
          <p className="inline-flex items-center gap-2 text-sm font-semibold">
            {trimInvalid ? <TriangleAlert size={16} /> : <Clock size={16} />}
            {trimInvalid ? "Trim range needs attention" : `Estimated output length: ${formatDuration(trimDuration)}`}
          </p>
        </div>
      </div>
    </section>
  );
}

function EditedPreviewPanel({ previewRender, settings, rawVideo, canExport, actionLoading, videoJobRunning, runPreview }) {
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-semibold text-white">Edited Preview</h2>
          <p className="mt-1 text-sm text-zinc-400">Render a lightweight draft MP4 using the current trim, sync, overlays, cards, watermark, and fades before exporting the final version.</p>
        </div>
        <Button type="button" variant="secondary" onClick={runPreview} disabled={!canExport || actionLoading === "preview" || videoJobRunning}>
          <Video size={17} />
          Render Preview
        </Button>
      </div>

      {previewRender ? (
        <div className="mt-4 space-y-4">
          <video className="aspect-video w-full rounded-lg border border-white/10 bg-black object-contain" src={previewRender.fileUrl} controls preload="metadata" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Readout label="Preview" value={previewRender.label} />
            <Readout label="Created" value={formatDateTime(previewRender.createdAt)} />
            <Readout label="Duration" value={formatDuration(previewRender.durationSeconds)} />
            <Readout label="Soundtrack" value={describeFinalExportAudioSource(previewRender)} />
            <Readout label="Assembly" value={describeFinalExportAssembly(previewRender)} />
            <Readout label="Sync Offset" value={formatSignedMilliseconds(previewRender.settings?.audioOffsetMs)} />
            <Readout label="Trim" value={describeFinalExportTrim(previewRender)} />
            <Readout label="Fades" value={describeFinalExportFades(previewRender)} />
            <Readout label="Overlay" value={describeFinalExportOverlay(previewRender)} />
            <Readout label="Cards" value={describeFinalExportCards(previewRender)} />
          </div>
          <p className="truncate text-xs text-zinc-500">{previewRender.filePath}</p>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <Button as="a" href={previewRender.fileUrl} target="_blank" rel="noreferrer" variant="secondary">
              <Download size={17} />
              Open Preview
            </Button>
            <Button type="button" variant="secondary" onClick={runPreview} disabled={!canExport || actionLoading === "preview" || videoJobRunning}>
              <RefreshCw size={17} />
              Refresh Preview
            </Button>
          </div>
          {isPreviewOutdated(previewRender, settings, rawVideo) ? (
            <p className="rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">Preview may be outdated. Render it again after changing edit settings.</p>
          ) : null}
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">No edited preview yet. Render one to watch the current cut before final export.</p>
      )}
    </section>
  );
}

function BrandingStepPreviewPanel({ rawVideos, settings, previewRender, canExport, videoJobRunning, actionLoading, onPreview }) {
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-semibold text-white">Branding Preview</h2>
          <p className="mt-1 text-sm text-zinc-400">Preview the title card, performance overlay, watermark, and outro sequence before moving into timeline edits.</p>
        </div>
        <Button type="button" variant="secondary" onClick={onPreview} disabled={!canExport || actionLoading === "preview" || videoJobRunning}>
          <Video size={17} />
          Render Draft
        </Button>
      </div>
      <VideoFramePreview rawVideos={rawVideos} settings={settings} />
      {previewRender ? (
        <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-3">
          <p className="text-sm font-semibold text-white">Latest edited preview</p>
          <p className="mt-1 text-xs text-zinc-500">{previewRender.label} - {formatDateTime(previewRender.createdAt)}</p>
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">Use Render Draft when you want a playable MP4 preview of these branding settings.</p>
      )}
    </section>
  );
}

function VideoStoryEditorPanel({ primaryVideo, secondaryVideos, selectedAudioAsset, settings, trimStart, trimEnd, trimDuration, onFocusPlacementsPreview, onFocusPlacementsCommit }) {
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-white">Video Editor Timeline</h2>
          <p className="mt-1 text-sm text-zinc-400">Review the primary performance video, focused clip placements, selected master audio, and trim window in one story timeline.</p>
        </div>
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/20 text-teal-100">
          <Scissors size={18} />
        </span>
      </div>

      {primaryVideo ? (
        <div className="mt-4 space-y-4">
          <video className="aspect-video w-full rounded-lg border border-white/10 bg-black object-contain" src={primaryVideo.fileUrl} controls preload="metadata" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Readout label="Primary" value={primaryVideo.originalFilename} />
            <Readout label="Focused Clips" value={secondaryVideos.length} />
            <Readout label="Selected Audio" value={selectedAudioAsset?.label || "None"} />
            <Readout label="Output Length" value={formatDuration(trimDuration)} />
          </div>
          <StoryTimelineLanes
            primaryVideo={primaryVideo}
            secondaryVideos={secondaryVideos}
            selectedAudioAsset={selectedAudioAsset}
            settings={settings}
            trimStart={trimStart}
            trimEnd={trimEnd}
            onFocusPlacementsPreview={onFocusPlacementsPreview}
            onFocusPlacementsCommit={onFocusPlacementsCommit}
          />
        </div>
      ) : (
        <div className="mt-4">
          <EmptyState icon={Video} title="Upload a primary video first" description="The story timeline unlocks after the whole-band performance video is available." />
        </div>
      )}
    </section>
  );
}

function StoryTimelineLanes({ primaryVideo, secondaryVideos, selectedAudioAsset, settings, trimStart, trimEnd, onFocusPlacementsPreview, onFocusPlacementsCommit }) {
  const focusLaneRef = useRef(null);
  const [dragState, setDragState] = useState(null);
  const [focusCursorSeconds, setFocusCursorSeconds] = useState(0);
  const [selectedFocusCutId, setSelectedFocusCutId] = useState("");
  const totalDuration = Math.max(0, Number(primaryVideo?.durationSeconds) || 0);
  const timelineDuration = totalDuration || 1;
  const focusPlan = calculateFocusInsertPlan(primaryVideo, secondaryVideos, settings);
  const trimVisualEnd = trimEnd > trimStart ? Math.min(trimEnd, totalDuration || trimEnd) : totalDuration;
  const trimLeft = totalDuration > 0 ? Math.max(0, trimStart) / timelineDuration : 0;
  const trimWidth = totalDuration > 0 ? Math.max(0, trimVisualEnd - trimStart) / timelineDuration : 0;
  const audioOffsetSeconds = (Number(settings.audioOffsetMs) || 0) / 1000;
  const audioLeft = Math.max(0, Math.min(0.9, audioOffsetSeconds / timelineDuration));
  const audioWidth = Math.max(8, Math.min(100 - audioLeft * 100, ((trimVisualEnd || timelineDuration) / timelineDuration) * 100));
  const dragPlacementId = dragState?.placementId || "";
  const selectedFocusCut = focusPlan.find((insert) => insert.id === selectedFocusCutId) || null;
  const manualPlacements = Array.isArray(settings.assembly?.focusPlacements) ? settings.assembly.focusPlacements : [];
  const hasManualCuts = manualPlacements.length > 0;
  const clampedFocusCursorSeconds = Math.max(0, Math.min(timelineDuration, focusCursorSeconds));

  const placementFromPointer = (clientX, nextDragState = dragState) => {
    const lane = focusLaneRef.current;
    if (!lane || !nextDragState) return null;
    const rect = lane.getBoundingClientRect();
    const pointerSeconds = ((clientX - rect.left) / Math.max(1, rect.width)) * timelineDuration;
    const maxStart = Math.max(0, timelineDuration - nextDragState.durationSeconds);
    return Math.max(0, Math.min(maxStart, pointerSeconds - nextDragState.pointerOffsetSeconds));
  };

  const secondsFromLanePointer = (clientX) => {
    const lane = focusLaneRef.current;
    if (!lane) return clampedFocusCursorSeconds;
    const rect = lane.getBoundingClientRect();
    const pointerSeconds = ((clientX - rect.left) / Math.max(1, rect.width)) * timelineDuration;
    return Math.max(0, Math.min(timelineDuration, pointerSeconds));
  };

  const placeFocusCursor = (event) => {
    if (!secondaryVideos.length) return;
    setFocusCursorSeconds(secondsFromLanePointer(event.clientX));
  };

  const emitFocusPlacement = (placementId, updates = {}, commit = false) => {
    const placements = buildFocusPlacementPayload(focusPlan).map((placement) =>
      placement.id === placementId
        ? {
            ...placement,
            ...updates,
            startSeconds: Number((updates.startSeconds ?? placement.startSeconds).toFixed(3)),
            sourceStartSeconds: Number((updates.sourceStartSeconds ?? placement.sourceStartSeconds).toFixed(3)),
            durationSeconds: Number((updates.durationSeconds ?? placement.durationSeconds).toFixed(3)),
          }
        : placement,
    );
    onFocusPlacementsPreview?.(placements);
    if (commit) onFocusPlacementsCommit?.(placements);
  };

  const startFocusDrag = (event, insert) => {
    if (!focusLaneRef.current || !onFocusPlacementsPreview) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedFocusCutId(insert.id);
    const rect = focusLaneRef.current.getBoundingClientRect();
    const insertLeft = rect.left + (insert.startSeconds / timelineDuration) * rect.width;
    const pointerOffsetSeconds = ((event.clientX - insertLeft) / Math.max(1, rect.width)) * timelineDuration;
    setDragState({
      placementId: insert.id,
      sourceTracksTimeline: Math.abs((Number(insert.sourceStartSeconds) || 0) - insert.startSeconds) < 0.05,
      durationSeconds: insert.durationSeconds,
      pointerOffsetSeconds: Math.max(0, Math.min(insert.durationSeconds, pointerOffsetSeconds)),
    });
  };

  const nudgeFocusPlacement = (insert, deltaSeconds) => {
    const maxStart = Math.max(0, timelineDuration - insert.durationSeconds);
    const nextStart = Math.max(0, Math.min(maxStart, insert.startSeconds + deltaSeconds));
    const updates = { startSeconds: nextStart };
    if (Math.abs((Number(insert.sourceStartSeconds) || 0) - insert.startSeconds) < 0.05) updates.sourceStartSeconds = nextStart;
    emitFocusPlacement(insert.id, updates, true);
  };

  const addFocusCutAt = (requestedStartSeconds = null) => {
    if (!secondaryVideos.length) return;
    const placements = buildFocusPlacementPayload(focusPlan);
    const clip = secondaryVideos[placements.length % secondaryVideos.length];
    const durationSeconds = defaultFocusCutDuration(primaryVideo, clip);
    const lastEnd = placements.reduce((end, placement) => Math.max(end, Number(placement.startSeconds || 0) + Number(placement.durationSeconds || 0)), 0);
    const fallbackStartSeconds = placements.length ? lastEnd + 4 : timelineDuration * 0.2;
    const startSeconds = Math.max(0, Math.min(timelineDuration - durationSeconds, Number.isFinite(Number(requestedStartSeconds)) ? Number(requestedStartSeconds) : fallbackStartSeconds));
    const sourceStartSeconds = Math.max(0, Math.min(Math.max(0, Number(clip.durationSeconds || 0) - durationSeconds), startSeconds));
    const nextPlacements = [
      ...placements,
      {
        id: newFocusCutId(),
        clipId: clip.id,
        startSeconds: Number(startSeconds.toFixed(3)),
        durationSeconds: Number(durationSeconds.toFixed(3)),
        sourceStartSeconds: Number(sourceStartSeconds.toFixed(3)),
      },
    ];
    onFocusPlacementsPreview?.(nextPlacements);
    onFocusPlacementsCommit?.(nextPlacements);
    setSelectedFocusCutId(nextPlacements[nextPlacements.length - 1]?.id || "");
  };

  const addFocusCut = () => addFocusCutAt(null);

  const cutAtCursor = () => addFocusCutAt(clampedFocusCursorSeconds);

  const applyAutoCuts = () => {
    const placements = buildFocusPlacementPayload(calculateAutomaticFocusInsertPlan(primaryVideo, secondaryVideos, settings));
    onFocusPlacementsPreview?.(placements);
    onFocusPlacementsCommit?.(placements);
  };

  const resetAutoCuts = () => {
    setSelectedFocusCutId("");
    onFocusPlacementsPreview?.([]);
    onFocusPlacementsCommit?.([]);
  };

  const deleteSelectedFocusCut = () => {
    if (!selectedFocusCut) return;
    const placements = buildFocusPlacementPayload(focusPlan).filter((placement) => placement.id !== selectedFocusCut.id);
    setSelectedFocusCutId("");
    onFocusPlacementsPreview?.(placements);
    onFocusPlacementsCommit?.(placements);
  };

  useEffect(() => {
    if (selectedFocusCutId && !focusPlan.some((insert) => insert.id === selectedFocusCutId)) {
      setSelectedFocusCutId("");
    }
  }, [focusPlan, selectedFocusCutId]);

  useEffect(() => {
    if (!dragState) return undefined;
    const handlePointerMove = (event) => {
      const startSeconds = placementFromPointer(event.clientX, dragState);
      if (startSeconds !== null) {
        const updates = { startSeconds };
        if (dragState.sourceTracksTimeline) updates.sourceStartSeconds = startSeconds;
        emitFocusPlacement(dragState.placementId, updates, false);
      }
    };
    const handlePointerUp = (event) => {
      const startSeconds = placementFromPointer(event.clientX, dragState);
      if (startSeconds !== null) {
        const updates = { startSeconds };
        if (dragState.sourceTracksTimeline) updates.sourceStartSeconds = startSeconds;
        emitFocusPlacement(dragState.placementId, updates, true);
      }
      setDragState(null);
    };
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp, { once: true });
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, [dragState, focusPlan, timelineDuration, onFocusPlacementsPreview, onFocusPlacementsCommit]);

  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-white">Story Timeline</p>
          <p className="mt-1 text-xs leading-5 text-zinc-500">Primary video stays continuous. Add auto/manual focus cuts from full-song camera angles, then drag them on the song timeline.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={applyAutoCuts} disabled={!secondaryVideos.length}>
            Auto Cut Focus
          </Button>
          <Button type="button" variant="secondary" onClick={cutAtCursor} disabled={!secondaryVideos.length}>
            Cut at Cursor
          </Button>
          <Button type="button" variant="danger" onClick={deleteSelectedFocusCut} disabled={!selectedFocusCut}>
            Delete Selected Cut
          </Button>
          <Button type="button" variant="secondary" onClick={addFocusCut} disabled={!secondaryVideos.length}>
            Add Manual Cut
          </Button>
          {hasManualCuts ? (
            <Button type="button" variant="secondary" onClick={resetAutoCuts}>
              Reset Auto
            </Button>
          ) : null}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <div className="grid grid-cols-[88px_1fr] items-center gap-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">Primary</p>
          <div className="relative h-12 overflow-hidden rounded-lg border border-white/10 bg-zinc-950">
            <div className="absolute inset-y-0 left-0 w-full bg-[linear-gradient(90deg,rgba(45,212,191,0.22),rgba(45,212,191,0.08))]" />
            {trimWidth > 0 ? (
              <div
                className="absolute inset-y-1 rounded-md border border-amber-300/30 bg-amber-300/15"
                style={{ left: `${trimLeft * 100}%`, width: `${trimWidth * 100}%` }}
                title={`Trim window: ${formatSecondsLabel(trimStart)} to ${trimEnd > trimStart ? formatSecondsLabel(trimVisualEnd) : "end"}`}
              />
            ) : null}
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs font-semibold text-teal-50">{primaryVideo.originalFilename}</span>
          </div>
        </div>

        <div className="grid grid-cols-[88px_1fr] items-center gap-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">Focus</p>
          <div ref={focusLaneRef} onPointerDown={placeFocusCursor} className="relative min-h-14 cursor-crosshair overflow-hidden rounded-lg border border-white/10 bg-zinc-950">
            {secondaryVideos.length ? (
              <div className="pointer-events-none absolute inset-y-0 z-20" style={{ left: `${(clampedFocusCursorSeconds / timelineDuration) * 100}%` }}>
                <div className="h-full w-px bg-amber-200 shadow-[0_0_14px_rgba(251,191,36,0.55)]" />
              </div>
            ) : null}
            {focusPlan.length ? (
              focusPlan.map((insert, index) => {
                const left = (insert.startSeconds / timelineDuration) * 100;
                const width = Math.max(4, (insert.durationSeconds / timelineDuration) * 100);
                return (
                  <div
                    key={insert.id || `${insert.clip.id}-${index}`}
                    role="button"
                    tabIndex={0}
                    onFocus={() => setSelectedFocusCutId(insert.id)}
                    onPointerDown={(event) => startFocusDrag(event, insert)}
                    onKeyDown={(event) => {
                      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                        event.preventDefault();
                        nudgeFocusPlacement(insert, event.key === "ArrowLeft" ? -0.5 : 0.5);
                      }
                    }}
                    className={`absolute top-2 h-9 cursor-grab touch-none overflow-hidden rounded-md border px-2 text-[11px] font-semibold shadow-[0_0_18px_rgba(56,189,248,0.18)] transition ${
                      dragPlacementId === insert.id || selectedFocusCutId === insert.id
                        ? "z-10 border-cyan-100/70 bg-cyan-300/35 text-cyan-50 ring-2 ring-cyan-200/35"
                        : "border-sky-200/35 bg-sky-300/20 text-sky-50 hover:border-cyan-100/60 hover:bg-sky-300/28"
                    }`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    title={`${insert.displayLabel}: timeline ${formatSecondsLabel(insert.startSeconds)} to ${formatSecondsLabel(insert.endSeconds)}, source ${formatSecondsLabel(insert.sourceStartSeconds)}`}
                  >
                    <span className="block truncate leading-9">{insert.displayLabel} · {formatSecondsLabel(insert.startSeconds)}</span>
                  </div>
                );
              })
            ) : (
              <p className="px-3 py-4 text-xs text-zinc-500">No focused clips placed yet.</p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-[88px_1fr] items-center gap-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">Audio</p>
          <div className="relative h-10 overflow-hidden rounded-lg border border-white/10 bg-zinc-950">
            {selectedAudioAsset ? (
              <div
                className="absolute inset-y-1 overflow-hidden rounded-md border border-emerald-200/35 bg-emerald-300/18 px-2 text-[11px] font-semibold text-emerald-50"
                style={{ left: `${audioLeft * 100}%`, width: `${audioWidth}%` }}
                title={`Audio offset: ${formatSignedMilliseconds(settings.audioOffsetMs)}`}
              >
                <span className="block truncate leading-8">{selectedAudioAsset.label} ({formatSignedMilliseconds(settings.audioOffsetMs)})</span>
              </div>
            ) : (
              <p className="px-3 py-3 text-xs text-zinc-500">Select generated audio before rendering.</p>
            )}
          </div>
        </div>
      </div>

      <div className="mt-2 flex items-center justify-between text-[11px] text-zinc-500">
        <span>0:00</span>
        <span>Cursor {formatSecondsLabel(clampedFocusCursorSeconds)}. Click the focus lane, then Cut at Cursor.</span>
        <span>{formatDuration(totalDuration)}</span>
      </div>
    </div>
  );
}

function RenderQualityPanel({ presets, selectedPreset, primaryVideo, secondaryVideos, selectedAudioAsset, settings, trimDuration, validationMessages, canExport, actionLoading, videoJobRunning, onPresetSelect, onRender }) {
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-semibold text-white">Render Quality</h2>
          <p className="mt-1 text-sm text-zinc-400">Choose the final MP4 quality, confirm the finishing snapshot, then render the video.</p>
        </div>
        <Button type="button" onClick={onRender} disabled={!canExport || actionLoading === "render" || videoJobRunning}>
          <Film size={17} />
          Render MP4
        </Button>
      </div>

      <div className="mt-4 space-y-4">
        <ExportPresetCards presets={presets} selectedPreset={selectedPreset} onSelect={onPresetSelect} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Readout label="Preset" value={selectedPreset} />
          <Readout label="Primary Video" value={primaryVideo?.originalFilename || "Missing"} />
          <Readout label="Focused Clips" value={secondaryVideos.length} />
          <Readout label="Audio Asset" value={selectedAudioAsset?.label || "Missing"} />
          <Readout label="Output Length" value={formatDuration(trimDuration)} />
          <Readout label="Sync Offset" value={formatSignedMilliseconds(settings.audioOffsetMs)} />
        </div>
        {validationMessages.length ? (
          <div className="rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-3">
            <p className="inline-flex items-center gap-2 text-sm font-semibold text-amber-100">
              <TriangleAlert size={16} />
              Complete these before rendering
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {validationMessages.map((message) => (
                <span key={message} className="rounded-full border border-amber-300/20 bg-black/20 px-2.5 py-1 text-xs font-semibold text-amber-100">
                  {message}
                </span>
              ))}
            </div>
          </div>
        ) : (
          <p className="rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-3 py-3 text-sm text-emerald-100">Ready to render with the selected quality preset.</p>
        )}
      </div>
    </section>
  );
}

function getVideoWorkflowState({ activeStepKey, primaryVideo, secondaryVideos, selectedAudioAsset, settings, previewRender, finalExport, canExport }) {
  const hasPrimary = Boolean(primaryVideo);
  const hasBranding = Boolean(
    settings.overlay?.songTitle ||
      settings.overlay?.artistName ||
      settings.overlay?.sessionLabel ||
      settings.watermark?.enabled ||
      settings.introCard?.enabled ||
      settings.outroCard?.enabled ||
      (Array.isArray(settings.brandingTemplates) && settings.brandingTemplates.length),
  );
  const completion = {
    sources: hasPrimary,
    branding: hasPrimary && hasBranding,
    editor: hasPrimary && Boolean(previewRender),
    render: Boolean(finalExport),
  };
  const availability = {
    sources: true,
    branding: hasPrimary,
    editor: hasPrimary,
    render: hasPrimary,
  };

  const steps = videoWorkflowDefinitions.map((definition) => {
    const status = definition.key === activeStepKey ? "current" : completion[definition.key] ? "complete" : availability[definition.key] ? "ready" : "locked";
    return {
      ...definition,
      available: availability[definition.key],
      status,
      statusLabel: videoWorkflowStatusLabels[status],
      detail: videoWorkflowDetail(definition.key, {
        primaryVideo,
        secondaryVideos,
        selectedAudioAsset,
        settings,
        previewRender,
        finalExport,
        canExport,
      }),
    };
  });

  return {
    steps,
    summary: videoWorkflowSummary(activeStepKey, {
      primaryVideo,
      secondaryVideos,
      selectedAudioAsset,
      settings,
      previewRender,
      finalExport,
      canExport,
    }),
  };
}

function getNextWorkflowStep(steps, activeStepKey) {
  const currentIndex = Math.max(0, steps.findIndex((step) => step.key === activeStepKey));
  return steps.slice(currentIndex + 1).find((step) => step.available) || null;
}

function videoWorkflowDetail(key, { primaryVideo, secondaryVideos, selectedAudioAsset, settings, previewRender, finalExport }) {
  if (key === "sources") {
    return primaryVideo ? `1 primary, ${secondaryVideos.length} focus` : "Primary video needed";
  }
  if (key === "branding") {
    const labels = [
      settings.overlay?.songTitle || settings.overlay?.artistName || settings.overlay?.sessionLabel ? "Overlay" : null,
      settings.watermark?.enabled ? "Watermark" : null,
      settings.introCard?.enabled || settings.outroCard?.enabled ? "Cards" : null,
    ].filter(Boolean);
    return labels.length ? labels.join(", ") : "Info + preview";
  }
  if (key === "editor") {
    return previewRender ? "Preview rendered" : selectedAudioAsset ? "Sync + timeline" : "Select audio";
  }
  return finalExport ? "MP4 ready" : settings.exportPreset || "Choose quality";
}

function videoWorkflowSummary(key, { primaryVideo, secondaryVideos, selectedAudioAsset, settings, previewRender, finalExport, canExport }) {
  if (key === "sources") {
    return primaryVideo
      ? `Primary video is ready with ${secondaryVideos.length} focused clip${secondaryVideos.length === 1 ? "" : "s"}. You can add more focused clips or move to branding.`
      : "Upload the whole-band primary video first, then add optional focused clips for automatic cutaways.";
  }
  if (key === "branding") {
    return "Add reusable branding, title overlay, watermark, intro card, and outro card. The preview sequence updates here before timeline editing.";
  }
  if (key === "editor") {
    return selectedAudioAsset
      ? `Place and review the automatic focused clips, sync ${selectedAudioAsset.label}, adjust trim, and render a draft preview.`
      : "Select generated audio first, then use this timeline to review focused clip placement and sync.";
  }
  if (finalExport) {
    return `Latest final MP4 is ready. Current preset is ${settings.exportPreset || "YouTube 1080p"}.`;
  }
  return canExport
    ? "Choose the final quality preset and render the MP4."
    : "Finish the required source, audio, and trim settings before rendering.";
}

function AudioAssetCards({ assets, selectedId, onSelect }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {assets.map((asset) => {
        const selected = asset.id === selectedId;
        return (
          <button
            key={asset.id}
            type="button"
            onClick={() => onSelect(asset.id)}
            className={`rounded-lg border p-3 text-left transition ${
              selected ? "border-teal-200/35 bg-teal-300/10 shadow-[0_0_24px_rgba(45,212,191,0.12)]" : "border-white/10 bg-black/20 hover:border-teal-200/25 hover:bg-white/[0.06]"
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-white">{asset.label}</p>
                <p className="mt-1 text-xs text-zinc-500">{asset.kind}{asset.outputFormat ? ` - ${asset.outputFormat}` : ""}</p>
              </div>
              <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg border ${selected ? "border-teal-200/30 bg-teal-300/10 text-teal-100" : "border-white/10 bg-white/[0.04] text-zinc-300"}`}>
                {selected ? <CheckCircle2 size={16} /> : <Music2 size={16} />}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function ExportPresetCards({ presets, selectedPreset, onSelect }) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {presets.map((preset) => {
        const selected = preset.name === selectedPreset;
        return (
          <button
            key={preset.name}
            type="button"
            onClick={() => onSelect(preset.name)}
            className={`rounded-lg border p-3 text-left transition ${
              selected ? "border-teal-200/35 bg-teal-300/10 shadow-[0_0_24px_rgba(45,212,191,0.12)]" : "border-white/10 bg-black/20 hover:border-teal-200/25 hover:bg-white/[0.06]"
            }`}
          >
            <p className="text-sm font-semibold text-white">{preset.name}</p>
            <p className="mt-1 text-xs leading-5 text-zinc-500">{preset.description}</p>
          </button>
        );
      })}
    </div>
  );
}

function TransitionStyleCards({ styles, selectedStyle, onSelect }) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {styles.map((style) => {
        const selected = style.name === selectedStyle;
        return (
          <button
            key={style.name}
            type="button"
            onClick={() => onSelect(style.name)}
            className={`rounded-lg border p-3 text-left transition ${
              selected ? "border-teal-200/35 bg-teal-300/10 shadow-[0_0_24px_rgba(45,212,191,0.12)]" : "border-white/10 bg-black/20 hover:border-teal-200/25 hover:bg-white/[0.06]"
            }`}
          >
            <p className="text-sm font-semibold text-white">{style.name}</p>
            <p className="mt-1 text-xs leading-5 text-zinc-500">{style.description}</p>
          </button>
        );
      })}
    </div>
  );
}

function FocusClipTimeline({ primaryVideo, secondaryVideos, settings, trimStart, trimEnd }) {
  const totalDuration = Math.max(0, Number(primaryVideo?.durationSeconds) || 0);
  const focusPlan = calculateFocusInsertPlan(primaryVideo, secondaryVideos, settings);
  const timelineDuration = totalDuration || 1;
  const trimVisualEnd = trimEnd > trimStart ? Math.min(trimEnd, totalDuration || trimEnd) : totalDuration;
  const trimWidth = totalDuration > 0 ? Math.max(0, trimVisualEnd - trimStart) / timelineDuration : 0;
  const trimLeft = totalDuration > 0 ? Math.max(0, trimStart) / timelineDuration : 0;

  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-white">Focus Placement Timeline</p>
          <p className="mt-1 text-xs leading-5 text-zinc-500">This shows where the focused overlay clips are currently placed on the primary performance timeline before preview/export.</p>
        </div>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-300">
          {focusPlan.length} insert{focusPlan.length === 1 ? "" : "s"}
        </span>
      </div>

      {primaryVideo ? (
        <div className="mt-4 space-y-4">
          <div className="rounded-lg border border-white/10 bg-black/25 p-3">
            <div className="flex items-center justify-between gap-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
              <span>Primary Timeline</span>
              <span>{formatDuration(totalDuration)}</span>
            </div>
            <div className="relative mt-3 h-12 overflow-hidden rounded-lg border border-white/10 bg-zinc-950">
              <div className="absolute inset-y-0 left-0 w-full bg-[linear-gradient(90deg,rgba(45,212,191,0.18),rgba(45,212,191,0.08))]" />
              {trimWidth > 0 ? (
                <div
                  className="absolute inset-y-0 rounded-md border border-amber-300/30 bg-amber-300/15"
                  style={{ left: `${trimLeft * 100}%`, width: `${trimWidth * 100}%` }}
                  title={`Trimmed output region: ${formatSecondsLabel(trimStart)} to ${trimEnd > trimStart ? formatSecondsLabel(trimVisualEnd) : "timeline end"}`}
                />
              ) : null}
              {focusPlan.map((insert, index) => {
                const left = (insert.startSeconds / timelineDuration) * 100;
                const width = Math.max(2, (insert.durationSeconds / timelineDuration) * 100);
                return (
                  <div
                    key={`${insert.clip.id}-${index}`}
                    className="absolute top-1/2 h-6 -translate-y-1/2 overflow-hidden rounded-md border border-teal-200/35 bg-teal-300/20 px-2 text-[11px] font-semibold text-teal-50 shadow-[0_0_18px_rgba(45,212,191,0.2)]"
                    style={{ left: `${left}%`, width: `${width}%` }}
                    title={`${insert.clip.originalFilename}: ${formatSecondsLabel(insert.startSeconds)} to ${formatSecondsLabel(insert.endSeconds)}`}
                  >
                    <span className="block truncate leading-6">{insert.displayLabel}</span>
                  </div>
                );
              })}
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] text-zinc-500">
              <span>0:00</span>
              <span>{formatDuration(totalDuration)}</span>
            </div>
          </div>

          {focusPlan.length ? (
            <div className="space-y-2">
              {focusPlan.map((insert) => (
                <div key={insert.clip.id} className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-white">{insert.displayLabel}</p>
                      <p className="mt-1 text-xs text-zinc-500">{insert.clip.originalFilename}</p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-300">
                      <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">Start {formatSecondsLabel(insert.startSeconds)}</span>
                      <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">End {formatSecondsLabel(insert.endSeconds)}</span>
                      <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1">Dur {formatSecondsLabel(insert.durationSeconds)}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : secondaryVideos.length ? (
            <p className="rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-3 text-sm text-amber-100">Focused clips are uploaded, but they are too short or the primary timeline is too tight for visible automatic inserts with the current settings.</p>
          ) : (
            <p className="rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">Add focused clips to see their overlay placement on the primary timeline.</p>
          )}
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">Upload the primary video first to unlock the focus placement timeline.</p>
      )}
    </div>
  );
}

function RawVideoClipCard({ clip, index, clipCount, onMove, onRemove, busy }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/15 p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-zinc-300">
              Focus {index + 1}
            </span>
          </div>
          <p className="mt-2 truncate text-sm font-semibold text-white">{clip.originalFilename}</p>
          <p className="mt-1 text-xs text-zinc-500">
            {formatDuration(clip.durationSeconds)} - {clip.width && clip.height ? `${clip.width} x ${clip.height}` : "--"} - {Number.isFinite(clip.fps) ? `${clip.fps.toFixed(2)} fps` : "--"} - {clip.hasAudioTrack ? "Audio detected" : "Silent"}
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button type="button" variant="secondary" onClick={() => onMove(clip.id, -1)} disabled={busy || index === 0}>
            Move Up
          </Button>
          <Button type="button" variant="secondary" onClick={() => onMove(clip.id, 1)} disabled={busy || index === clipCount - 1}>
            Move Down
          </Button>
          <Button type="button" variant="danger" onClick={() => onRemove(clip)} disabled={busy}>
            Remove
          </Button>
        </div>
      </div>
    </div>
  );
}

function BrandingTemplateCard({ template, applyTemplate, removeTemplate, busy }) {
  const summary = [
    template?.watermark?.enabled ? "Watermark" : null,
    template?.introCard?.enabled ? "Intro" : null,
    template?.outroCard?.enabled ? "Outro" : null,
    [template?.overlay?.songTitle, template?.overlay?.artistName, template?.overlay?.sessionLabel].filter(Boolean).length
      ? "Overlay"
      : null,
  ].filter(Boolean);

  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-white">{template.name}</p>
          <p className="mt-1 text-xs text-zinc-500">Updated {formatDateTime(template.updatedAt)}</p>
        </div>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-300">
          {summary.length ? summary.join(" • ") : "Basic"}
        </span>
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <Button type="button" onClick={() => applyTemplate(template)} disabled={busy}>
          <Palette size={17} />
          Apply
        </Button>
        <Button type="button" variant="danger" onClick={() => removeTemplate(template)} disabled={busy}>
          Delete
        </Button>
      </div>
    </div>
  );
}

function ExportHistoryCard({ item, active, onDelete, busy }) {
  return (
    <div className={`rounded-lg border p-3 ${active ? "border-teal-200/30 bg-teal-300/10" : "border-white/10 bg-black/15"}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-semibold text-white">{item.label}</p>
            {active ? <span className="rounded-full border border-teal-200/30 bg-teal-300/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-teal-100">Latest</span> : null}
          </div>
          <p className="mt-1 text-xs text-zinc-500">{formatDateTime(item.createdAt)} • {item.exportPreset || item.settings?.exportPreset || "MP4"}</p>
          <p className="mt-1 text-xs text-zinc-500">{describeFinalExportAudioSource(item)} • {formatSignedMilliseconds(item.settings?.audioOffsetMs)}</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button as="a" href={item.fileUrl} target="_blank" rel="noreferrer" variant="secondary">
            <Download size={17} />
            Open
          </Button>
          <Button type="button" variant="danger" onClick={() => onDelete(item)} disabled={busy}>
            Delete
          </Button>
        </div>
      </div>
    </div>
  );
}

function WaveformSyncPanel({ waveformState, loading, offsetMs, hasOriginalAudio, hasSelectedAudio }) {
  const hasTracks = Boolean(waveformState?.rawVideo && waveformState?.selectedAudio);
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white">Waveform Sync Assist</p>
          <p className="mt-1 text-xs leading-5 text-zinc-500">Compare the primary video audio against the selected generated audio while you fine-tune the offset.</p>
        </div>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-300">
          {formatSignedMilliseconds(offsetMs)}
        </span>
      </div>

      {!hasOriginalAudio ? (
        <p className="mt-3 text-xs text-zinc-500">Upload a primary video with original audio to unlock waveform-assisted sync.</p>
      ) : !hasSelectedAudio ? (
        <p className="mt-3 text-xs text-zinc-500">Select generated audio to compare waveforms here.</p>
      ) : loading ? (
        <p className="mt-3 text-xs text-zinc-500">Loading waveform guide...</p>
      ) : hasTracks ? (
        <div className="mt-3 space-y-3">
          <WaveformCompareCanvas waveformState={waveformState} offsetMs={offsetMs} />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">Raw Video Audio</p>
              <p className="mt-1 truncate text-sm text-white">{waveformState.rawVideo.label}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">Generated Audio</p>
              <p className="mt-1 truncate text-sm text-white">{waveformState.selectedAudio.label}</p>
            </div>
          </div>
        </div>
      ) : (
        <p className="mt-3 text-xs text-zinc-500">Waveform data is unavailable for the current files.</p>
      )}
    </div>
  );
}

function WaveformCompareCanvas({ waveformState, offsetMs }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !waveformState?.rawVideo?.peaks?.length || !waveformState?.selectedAudio?.peaks?.length) return undefined;

    let frame = 0;
    const draw = () => {
      const context = prepareSyncCanvas(canvas);
      if (!context) return;
      const width = canvas.width;
      const height = canvas.height;
      const gap = Math.max(12, height * 0.08);
      const trackHeight = (height - gap * 3) / 2;
      const rawTop = gap;
      const selectedTop = gap * 2 + trackHeight;
      const windowSeconds = Number(waveformState.windowDurationSeconds) || 1;
      const shiftPx = Math.max(-width * 0.48, Math.min(width * 0.48, (Number(offsetMs) / (windowSeconds * 1000)) * width));

      context.clearRect(0, 0, width, height);
      context.fillStyle = "rgba(255,255,255,0.035)";
      context.fillRect(0, 0, width, height);
      context.strokeStyle = "rgba(255,255,255,0.08)";
      context.lineWidth = Math.max(1, window.devicePixelRatio || 1);

      for (let index = 0; index <= 4; index += 1) {
        const x = (width / 4) * index;
        context.beginPath();
        context.moveTo(x, 0);
        context.lineTo(x, height);
        context.stroke();
      }

      drawWaveformTrack(context, waveformState.rawVideo.peaks, 0, width, rawTop, trackHeight, "rgba(45, 212, 191, 0.95)");
      drawWaveformTrack(context, waveformState.selectedAudio.peaks, shiftPx, width, selectedTop, trackHeight, "rgba(251, 191, 36, 0.95)");

      context.strokeStyle = "rgba(255,255,255,0.18)";
      context.beginPath();
      context.moveTo(0, rawTop + trackHeight / 2);
      context.lineTo(width, rawTop + trackHeight / 2);
      context.moveTo(0, selectedTop + trackHeight / 2);
      context.lineTo(width, selectedTop + trackHeight / 2);
      context.stroke();
    };

    draw();
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(draw);
    });
    observer.observe(canvas);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frame);
    };
  }, [offsetMs, waveformState]);

  return <canvas ref={canvasRef} className="block h-28 w-full rounded-lg border border-white/10 bg-black/30" />;
}

function VideoFramePreview({ rawVideos, settings }) {
  const previewCards = [];
  if (settings.introCard?.enabled) {
    previewCards.push(<TitleCardPreview key="intro" label="Intro Card" card={settings.introCard} variant="intro" />);
  }
  previewCards.push(<PerformanceFramePreview key="performance" rawVideos={rawVideos} settings={settings} />);
  if (settings.outroCard?.enabled) {
    previewCards.push(<TitleCardPreview key="outro" label="Outro Card" card={settings.outroCard} variant="outro" />);
  }

  const gridClass =
    previewCards.length >= 3
      ? "grid gap-3 xl:grid-cols-3"
      : previewCards.length === 2
        ? "grid gap-3 md:grid-cols-2"
        : "grid gap-3";

  return (
    <div className="mt-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Preview Sequence</p>
        <span className="text-[11px] text-zinc-500">Intro, automatic clip assembly, and outro previews follow the current settings.</span>
      </div>
      <div className={gridClass}>{previewCards}</div>
    </div>
  );
}

function PerformanceFramePreview({ rawVideos, settings }) {
  const primaryClip = Array.isArray(rawVideos) ? rawVideos.find((clip) => clip?.role === "Primary") || rawVideos[0] : null;
  const secondaryClips = Array.isArray(rawVideos) ? rawVideos.filter((clip) => clip?.role !== "Primary") : [];
  const overlayLines = [settings.overlay.songTitle, settings.overlay.artistName, settings.overlay.sessionLabel].filter(Boolean);
  const hasOverlay = overlayLines.length > 0;
  return (
    <div className="overflow-hidden rounded-lg border border-white/10 bg-black/30">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 bg-black/25 px-3 py-2">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Performance Frame</p>
        <span className="text-[11px] text-zinc-500">1 primary + {secondaryClips.length} focus clip{secondaryClips.length === 1 ? "" : "s"} - {settings.assembly?.transitionStyle || "Crossfade"}</span>
      </div>
      <div className="relative aspect-video">
        {primaryClip?.fileUrl ? (
          <video className="h-full w-full object-contain opacity-80" src={primaryClip.fileUrl} muted preload="metadata" />
        ) : (
          <div className="grid h-full w-full place-items-center bg-zinc-950 text-sm text-zinc-500">Preview frame</div>
        )}
        {hasOverlay ? (
          <div className={`absolute ${previewPositionClass(settings.overlay.position)} ${previewOverlayClass(settings.overlay.style)} ${previewSizeClass(settings.overlay.size)}`}>
            {overlayLines.map((line, index) => (
              <p key={`${line}-${index}`} className={index === 0 ? "font-semibold" : "opacity-85"}>
                {line}
              </p>
            ))}
          </div>
        ) : null}
        {settings.watermark.enabled && settings.watermark.logo?.fileUrl ? (
          <img
            src={settings.watermark.logo.fileUrl}
            alt=""
            className={`absolute max-h-16 max-w-28 object-contain opacity-80 ${previewPositionClass(settings.watermark.position)}`}
            style={{ opacity: settings.watermark.opacity }}
          />
        ) : null}
        {secondaryClips.length ? (
          <div className="absolute inset-x-3 bottom-3 flex items-center gap-2 overflow-hidden rounded-full bg-black/55 px-3 py-2 text-[11px] text-zinc-200">
            {secondaryClips.slice(0, 4).map((clip, index) => (
              <span key={clip.id} className="truncate">
                Focus {index + 1}. {clip.originalFilename}
              </span>
            ))}
            {secondaryClips.length > 4 ? <span>+{secondaryClips.length - 4} more</span> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TitleCardPreview({ label, card, variant }) {
  const fallbackTitle = variant === "intro" ? "Live Session" : "Thanks for watching";
  const title = card?.title || fallbackTitle;
  const subtitle = card?.subtitle || "";
  return (
    <div className="overflow-hidden rounded-lg border border-white/10 bg-black/30">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 bg-black/25 px-3 py-2">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</p>
        <span className="text-[11px] text-zinc-500">{formatDuration(card?.durationSeconds)}</span>
      </div>
      <div className="grid aspect-video place-items-center bg-[radial-gradient(circle_at_top,_rgba(45,212,191,0.18),_transparent_36%),linear-gradient(180deg,_#071019,_#0b1322)] px-6 text-center">
        <div className="max-w-[75%]">
          <p className="text-lg font-semibold text-white sm:text-xl">{title}</p>
          {subtitle ? <p className="mt-3 text-sm text-cyan-100 sm:text-base">{subtitle}</p> : null}
        </div>
      </div>
    </div>
  );
}

function TitleCardControls({ label, card, onLocalChange, onCommit }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <label className="flex items-center gap-2 text-sm font-semibold text-zinc-300">
        <input
          type="checkbox"
          checked={Boolean(card.enabled)}
          onChange={(event) => {
            onLocalChange({ enabled: event.target.checked });
            onCommit({ enabled: event.target.checked });
          }}
          className="h-4 w-4 rounded border-white/20 bg-black/30 accent-teal-300"
        />
        {label}
      </label>
      <div className="mt-3 grid gap-3">
        <TextControl
          label="Title"
          value={card.title}
          placeholder={label === "Intro Card" ? "Live Session" : "Thanks for watching"}
          onChange={(value) => onLocalChange({ title: value })}
          onCommit={(value) => onCommit({ title: value })}
        />
        <TextControl
          label="Subtitle"
          value={card.subtitle}
          placeholder={label === "Intro Card" ? "Artist - Song" : "Sixram Band Studio"}
          onChange={(value) => onLocalChange({ subtitle: value })}
          onCommit={(value) => onCommit({ subtitle: value })}
        />
        <NumberControl
          label="Duration"
          suffix="sec"
          min={0.5}
          max={10}
          step={0.5}
          value={card.durationSeconds}
          helper="Length of the still card."
          onChange={(value) => onLocalChange({ durationSeconds: value })}
          onCommit={(value) => onCommit({ durationSeconds: value })}
        />
      </div>
    </div>
  );
}

function prefixTitleCardPayload(prefix, updates) {
  const cap = prefix === "intro" ? "intro" : "outro";
  const payload = {};
  if ("enabled" in updates) payload[`${cap}Enabled`] = updates.enabled;
  if ("durationSeconds" in updates) payload[`${cap}DurationSeconds`] = updates.durationSeconds;
  if ("title" in updates) payload[`${cap}Title`] = updates.title;
  if ("subtitle" in updates) payload[`${cap}Subtitle`] = updates.subtitle;
  return payload;
}

function getValidationMessages({ primaryVideo, secondaryVideos, selectedAudioAsset, settings, trimInvalid, originalAudioChoiceValid }) {
  const messages = [];
  const assembledDuration = estimateAssemblyDuration(primaryVideo);
  if (!primaryVideo) messages.push("Upload a primary video");
  if (trimInvalid) messages.push("Fix trim end");
  if (Number.isFinite(assembledDuration) && assembledDuration > 0 && Number(settings.trimStartSeconds || 0) >= assembledDuration) messages.push("Trim start is past the primary timeline");
  if (!settings.useSelectedMasterAudio && !settings.useOriginalVideoAudio) messages.push("Choose an audio source");
  if (settings.useSelectedMasterAudio && !selectedAudioAsset) messages.push("Select generated audio");
  if (!originalAudioChoiceValid) messages.push("Primary video has no original audio");
  if (settings.watermark.enabled && !settings.watermark.logo) messages.push("Upload a logo or disable watermark");
  if (secondaryVideos?.some((clip) => !clip?.durationSeconds)) messages.push("Focused clip metadata is still loading");
  return messages;
}

function previewPositionClass(position) {
  if (position === "Top Left") return "left-4 top-4";
  if (position === "Top Right") return "right-4 top-4";
  if (position === "Lower Right" || position === "Bottom Right") return "bottom-4 right-4";
  return "bottom-4 left-4";
}

function previewOverlayClass(style) {
  if (style === "Clean") return "text-white drop-shadow-[0_2px_8px_rgba(0,0,0,0.9)]";
  if (style === "Shadow") return "text-white drop-shadow-[0_3px_10px_rgba(0,0,0,1)]";
  return "rounded bg-black/55 px-3 py-2 text-white";
}

function previewSizeClass(size) {
  if (size === "Small") return "text-xs";
  if (size === "Large") return "text-lg";
  return "text-sm";
}

function estimateAssemblyDuration(primaryVideo) {
  const duration = Number(primaryVideo?.durationSeconds);
  return Number.isFinite(duration) && duration > 0 ? duration : Number.NaN;
}

function calculateFocusInsertPlan(primaryVideo, secondaryVideos, settings) {
  const manualPlacements = normalizeManualFocusPlacements(primaryVideo, secondaryVideos, settings);
  if (manualPlacements.length) return manualPlacements;
  return calculateAutomaticFocusInsertPlan(primaryVideo, secondaryVideos, settings);
}

function calculateAutomaticFocusInsertPlan(primaryVideo, secondaryVideos, settings) {
  const primaryDuration = Math.max(0, Number(primaryVideo?.durationSeconds) || 0);
  if (!primaryDuration || !Array.isArray(secondaryVideos) || !secondaryVideos.length) return [];
  if (usesFullSongFocusMode(primaryVideo, secondaryVideos)) {
    return calculateAutomaticFullSongFocusPlan(primaryVideo, secondaryVideos);
  }

  const requestedDurations = secondaryVideos.map((clip) => Math.max(0.5, Number(clip?.durationSeconds) || 0.5));
  const transitionDuration = calculateEffectiveTransitionDuration(primaryVideo, secondaryVideos, settings);
  const minGap = Math.max(1.0, transitionDuration * 1.5);
  const maxInsertTotal = Math.min(primaryDuration * 0.6, Math.max(0, primaryDuration - minGap * (secondaryVideos.length + 1)));
  if (maxInsertTotal <= 0) return [];

  const requestedTotal = requestedDurations.reduce((sum, duration) => sum + duration, 0);
  const scale = requestedTotal > 0 ? Math.min(1, maxInsertTotal / requestedTotal) : 0;
  const inserts = [];

  requestedDurations.forEach((duration, index) => {
    const scaledDuration = Number((duration * scale).toFixed(3));
    if (scaledDuration >= 0.25) {
      inserts.push({ clip: secondaryVideos[index], durationSeconds: scaledDuration });
    }
  });

  if (!inserts.length) return [];

  const totalInsertDuration = inserts.reduce((sum, insert) => sum + insert.durationSeconds, 0);
  const gap = Math.max(0, primaryDuration - totalInsertDuration) / (inserts.length + 1);
  let cursor = gap;
  return inserts.map((insert, index) => {
    const durationSeconds = Number(Math.max(0.25, Math.min(Number(insert.clip?.durationSeconds) || insert.durationSeconds, insert.durationSeconds)).toFixed(3));
    const maxStart = Math.max(0, primaryDuration - durationSeconds);
    const startSeconds = Number(Math.max(0, Math.min(maxStart, cursor)).toFixed(3));
    const endSeconds = Number((startSeconds + durationSeconds).toFixed(3));
    cursor += insert.durationSeconds + gap;
    return {
      id: `auto-${insert.clip.id}-${index}`,
      ...insert,
      durationSeconds,
      sourceStartSeconds: 0,
      startSeconds,
      endSeconds,
      displayLabel: `Focus ${index + 1}`,
    };
  }).sort((left, right) => left.startSeconds - right.startSeconds);
}

function normalizeManualFocusPlacements(primaryVideo, secondaryVideos, settings) {
  const primaryDuration = Math.max(0, Number(primaryVideo?.durationSeconds) || 0);
  const placements = Array.isArray(settings?.assembly?.focusPlacements) ? settings.assembly.focusPlacements : [];
  if (!primaryDuration || !Array.isArray(secondaryVideos) || !secondaryVideos.length || !placements.length) return [];
  const clipById = new Map(secondaryVideos.map((clip) => [clip.id, clip]));
  return placements
    .map((placement, index) => {
      const clip = clipById.get(placement?.clipId);
      if (!clip) return null;
      const clipDuration = Math.max(0.25, Math.min(primaryDuration, Number(clip.durationSeconds) || 0.25));
      const durationSeconds = Number(Math.max(0.25, Math.min(clipDuration, Number(placement.durationSeconds) || defaultFocusCutDuration(primaryVideo, clip))).toFixed(3));
      const startSeconds = Number(Math.max(0, Math.min(primaryDuration - durationSeconds, Number(placement.startSeconds) || 0)).toFixed(3));
      const sourceStartSeconds = Number(Math.max(0, Math.min(Math.max(0, (Number(clip.durationSeconds) || durationSeconds) - durationSeconds), Number(placement.sourceStartSeconds ?? startSeconds) || 0)).toFixed(3));
      return {
        id: placement.id || `manual-${clip.id}-${index}`,
        clip,
        durationSeconds,
        sourceStartSeconds,
        startSeconds,
        endSeconds: Number((startSeconds + durationSeconds).toFixed(3)),
        displayLabel: `Focus Cut ${index + 1}`,
      };
    })
    .filter(Boolean)
    .sort((left, right) => left.startSeconds - right.startSeconds);
}

function usesFullSongFocusMode(primaryVideo, secondaryVideos) {
  const primaryDuration = Math.max(0, Number(primaryVideo?.durationSeconds) || 0);
  return primaryDuration > 0 && secondaryVideos.some((clip) => Number(clip?.durationSeconds) >= primaryDuration * 0.75);
}

function calculateAutomaticFullSongFocusPlan(primaryVideo, secondaryVideos) {
  const primaryDuration = Math.max(0, Number(primaryVideo?.durationSeconds) || 0);
  if (primaryDuration < 8 || !secondaryVideos.length) return [];
  const segmentCount = Math.min(12, Math.max(3, Math.max(Math.floor(primaryDuration / 35), secondaryVideos.length * 2)));
  const cutDuration = defaultFocusCutDuration(primaryVideo, secondaryVideos[0]);
  const gap = primaryDuration / (segmentCount + 1);
  return Array.from({ length: segmentCount }, (_, index) => {
    const clip = secondaryVideos[index % secondaryVideos.length];
    const durationSeconds = Math.min(cutDuration, Number(clip.durationSeconds) || cutDuration, primaryDuration);
    const center = gap * (index + 1);
    const startSeconds = Number(Math.max(0, Math.min(primaryDuration - durationSeconds, center - durationSeconds / 2)).toFixed(3));
    const sourceStartSeconds = Number(Math.max(0, Math.min(Math.max(0, Number(clip.durationSeconds || 0) - durationSeconds), startSeconds)).toFixed(3));
    return {
      id: `auto-full-${clip.id}-${index}`,
      clip,
      durationSeconds: Number(durationSeconds.toFixed(3)),
      sourceStartSeconds,
      startSeconds,
      endSeconds: Number((startSeconds + durationSeconds).toFixed(3)),
      displayLabel: `Focus Cut ${index + 1}`,
    };
  });
}

function defaultFocusCutDuration(primaryVideo, clip) {
  const primaryDuration = Math.max(0.25, Number(primaryVideo?.durationSeconds) || 0.25);
  const clipDuration = Math.max(0.25, Number(clip?.durationSeconds) || primaryDuration);
  return Number(Math.min(10, Math.max(5, primaryDuration / 24), clipDuration, primaryDuration).toFixed(3));
}

function buildFocusPlacementPayload(focusPlan) {
  return focusPlan.map((insert, index) => ({
    id: insert.id || newFocusCutId(index),
    clipId: insert.clip.id,
    startSeconds: Number((Number(insert.startSeconds) || 0).toFixed(3)),
    durationSeconds: Number(Math.max(0.25, Number(insert.durationSeconds) || 0.25).toFixed(3)),
    sourceStartSeconds: Number(Math.max(0, Number(insert.sourceStartSeconds) || 0).toFixed(3)),
  }));
}

function newFocusCutId(index = 0) {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `focus-cut-${crypto.randomUUID()}`;
  }
  return `focus-cut-${Date.now()}-${index}-${Math.round(Math.random() * 100000)}`;
}

function calculateEffectiveTransitionDuration(primaryVideo, secondaryVideos, settings) {
  const style = settings?.assembly?.transitionStyle || "Crossfade";
  if (style === "Cut") return 0;
  const requested = Math.max(0, Math.min(2, Number(settings?.assembly?.transitionDurationSeconds) || 0.45));
  const durations = (Array.isArray(secondaryVideos) && secondaryVideos.length ? secondaryVideos : [primaryVideo]).map((clip) =>
    Math.max(0.1, Number(clip?.durationSeconds) || 0.1),
  );
  const maxTransition = Math.min(...durations.map((duration) => Math.max(0, duration - 0.05)));
  return Number(Math.min(requested, Number.isFinite(maxTransition) ? maxTransition : 0).toFixed(3));
}

function formatSignedMilliseconds(value) {
  const numeric = Number.isFinite(Number(value)) ? Number(value) : 0;
  return `${numeric > 0 ? "+" : ""}${numeric} ms`;
}

function formatSecondsLabel(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "0s";
  return `${numeric % 1 === 0 ? numeric.toFixed(0) : numeric.toFixed(1)}s`;
}

function describeFinalExportAudioSource(finalExport) {
  if (!finalExport?.settings?.useSelectedMasterAudio) {
    return finalExport?.settings?.useOriginalVideoAudio ? "Original video audio" : "No soundtrack";
  }
  const label = finalExport?.sourceAudioAssetLabel || "Selected generated audio";
  return finalExport?.sourceAudioAssetKind ? `${label} (${finalExport.sourceAudioAssetKind})` : label;
}

function describeFinalExportAudioBlend(finalExport) {
  const settings = finalExport?.settings || {};
  if (settings.useSelectedMasterAudio && settings.useOriginalVideoAudio) return "Generated + original";
  if (settings.useSelectedMasterAudio) return "Generated only";
  if (settings.useOriginalVideoAudio) return "Original only";
  return "Muted";
}

function describeFinalExportTrim(finalExport) {
  const settings = finalExport?.settings || {};
  const start = Math.max(0, Number(settings.trimStartSeconds) || 0);
  const end = Math.max(0, Number(settings.trimEndSeconds) || 0);
  if (!start && !end) return "Full source";
  if (end > start) return `${formatSecondsLabel(start)} to ${formatSecondsLabel(end)}`;
  return `${formatSecondsLabel(start)} to video end`;
}

function describeFinalExportFades(finalExport) {
  const settings = finalExport?.settings || {};
  const fadeIn = Math.max(0, Number(settings.fadeInSeconds) || 0);
  const fadeOut = Math.max(0, Number(settings.fadeOutSeconds) || 0);
  if (!fadeIn && !fadeOut) return "None";
  const parts = [];
  if (fadeIn) parts.push(`In ${formatSecondsLabel(fadeIn)}`);
  if (fadeOut) parts.push(`Out ${formatSecondsLabel(fadeOut)}`);
  return parts.join(" • ");
}

function describeFinalExportOverlay(finalExport) {
  const overlay = finalExport?.settings?.overlay || {};
  const lines = [overlay.songTitle, overlay.artistName, overlay.sessionLabel].filter(Boolean).length;
  if (!lines) return "No text";
  const placement = overlay.position || "Lower Left";
  const style = overlay.style || "Boxed";
  return `${lines} line${lines === 1 ? "" : "s"} • ${placement} • ${style}`;
}

function describeFinalExportCards(finalExport) {
  const settings = finalExport?.settings || {};
  const intro = settings.introCard || {};
  const outro = settings.outroCard || {};
  const parts = [];
  if (intro.enabled) parts.push(`Intro ${formatSecondsLabel(intro.durationSeconds)}`);
  if (outro.enabled) parts.push(`Outro ${formatSecondsLabel(outro.durationSeconds)}`);
  return parts.length ? parts.join(" • ") : "No cards";
}

function describeFinalExportAssembly(finalExport) {
  const assembly = finalExport?.settings?.assembly || {};
  const style = assembly.transitionStyle || "Crossfade";
  const duration = Number(assembly.transitionDurationSeconds) || 0;
  const secondaryCount = Array.isArray(finalExport?.secondaryVideoFilenames) ? finalExport.secondaryVideoFilenames.length : Math.max(0, (Number(finalExport?.clipCount) || 1) - 1);
  const clipLabel = `1 primary + ${secondaryCount} focus clip${secondaryCount === 1 ? "" : "s"}`;
  if (!secondaryCount) return `${clipLabel} - Primary only`;
  if (style === "Cut" || duration <= 0) return `${clipLabel} - ${style}`;
  return `${clipLabel} - ${style} ${formatSecondsLabel(duration)}`;
}

function describeFinalExportWatermark(finalExport) {
  const watermark = finalExport?.settings?.watermark || {};
  if (!watermark.enabled) return "Off";
  const position = watermark.position || "Top Right";
  const opacity = Number.isFinite(Number(watermark.opacity)) ? `${Math.round(Number(watermark.opacity) * 100)}%` : "--";
  return `${position} • ${opacity}`;
}

function isPreviewOutdated(previewRender, settings, rawVideo) {
  if (!previewRender) return true;
  const previewSettings = previewRender.settings || {};
  const previewVideoNames = Array.isArray(previewRender.sourceVideoFilenames) ? previewRender.sourceVideoFilenames : previewRender.sourceVideoFilename ? [previewRender.sourceVideoFilename] : [];
  const currentVideoNames = Array.isArray(settings.rawVideos) ? settings.rawVideos.map((clip) => clip.originalFilename) : rawVideo?.originalFilename ? [rawVideo.originalFilename] : [];
  if (JSON.stringify(previewVideoNames) !== JSON.stringify(currentVideoNames)) return true;
  if ((previewRender.sourceVideoFilename || "") !== (rawVideo?.originalFilename || "")) return true;
  if ((previewRender.sourceAudioAssetId || "") !== (settings.useSelectedMasterAudio ? settings.selectedAudioAssetId || "" : "")) return true;
  if (Boolean(previewSettings.useSelectedMasterAudio) !== Boolean(settings.useSelectedMasterAudio)) return true;
  if (Boolean(previewSettings.useOriginalVideoAudio) !== Boolean(settings.useOriginalVideoAudio)) return true;
  if (Number(previewSettings.audioOffsetMs || 0) !== Number(settings.audioOffsetMs || 0)) return true;
  if (Number(previewSettings.trimStartSeconds || 0) !== Number(settings.trimStartSeconds || 0)) return true;
  if (Number(previewSettings.trimEndSeconds || 0) !== Number(settings.trimEndSeconds || 0)) return true;
  if (Number(previewSettings.fadeInSeconds || 0) !== Number(settings.fadeInSeconds || 0)) return true;
  if (Number(previewSettings.fadeOutSeconds || 0) !== Number(settings.fadeOutSeconds || 0)) return true;
  if (JSON.stringify(previewSettings.assembly || {}) !== JSON.stringify(settings.assembly || {})) return true;
  if (JSON.stringify(previewSettings.overlay || {}) !== JSON.stringify(settings.overlay || {})) return true;
  if (JSON.stringify(previewSettings.introCard || {}) !== JSON.stringify(settings.introCard || {})) return true;
  if (JSON.stringify(previewSettings.outroCard || {}) !== JSON.stringify(settings.outroCard || {})) return true;
  const previewWatermark = previewSettings.watermark || {};
  const currentWatermark = settings.watermark || {};
  if (Boolean(previewWatermark.enabled) !== Boolean(currentWatermark.enabled)) return true;
  if ((previewWatermark.position || "Top Right") !== (currentWatermark.position || "Top Right")) return true;
  if (Number(previewWatermark.opacity || 0.82) !== Number(currentWatermark.opacity || 0.82)) return true;
  if (Number(previewWatermark.scale || 0.14) !== Number(currentWatermark.scale || 0.14)) return true;
  const previewLogoPath = previewWatermark.logoFilePath || "";
  const currentLogoPath = currentWatermark.logo?.filePath || "";
  if (previewLogoPath !== currentLogoPath) return true;
  return false;
}

function prepareSyncCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const pixelRatio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(rect.width * pixelRatio));
  const height = Math.max(1, Math.floor(rect.height * pixelRatio));
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  return canvas.getContext("2d");
}

function drawWaveformTrack(context, peaks, shiftPx, width, top, height, color) {
  if (!peaks?.length) return;
  context.strokeStyle = color;
  context.lineWidth = Math.max(1, window.devicePixelRatio || 1);
  context.beginPath();
  const center = top + height / 2;
  const step = width / Math.max(1, peaks.length - 1);
  for (let index = 0; index < peaks.length; index += 1) {
    const x = shiftPx + index * step;
    if (x < 0 || x > width) continue;
    const amplitude = Math.max(0, Math.min(1, Number(peaks[index]) || 0));
    const lineHeight = amplitude * height * 0.46;
    context.moveTo(x, center - lineHeight);
    context.lineTo(x, center + lineHeight);
  }
  context.stroke();
}

function SelectControl({ label, value, options, onChange }) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</span>
      <select value={value || ""} onChange={(event) => onChange(event.target.value)} className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white">
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function NumberControl({ label, suffix, value, min = 0, max, step = 1, helper, onChange, onCommit }) {
  const numericValue = Number.isFinite(Number(value)) ? Number(value) : 0;
  return (
    <label className="block">
      <span className="mb-2 flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">
        <span>{label}</span>
        <span className="normal-case tracking-normal text-zinc-300">{numericValue}{suffix ? ` ${suffix}` : ""}</span>
      </span>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={numericValue}
        onChange={(event) => onChange(Number(event.target.value))}
        onBlur={(event) => onCommit(Number(event.currentTarget.value))}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
        className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white"
      />
      <p className="mt-2 text-xs leading-5 text-zinc-500">{helper}</p>
    </label>
  );
}

function TextControl({ label, value, placeholder, onChange, onCommit }) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</span>
      <input
        type="text"
        value={value || ""}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onBlur={(event) => onCommit(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
        className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white placeholder:text-zinc-600"
      />
    </label>
  );
}

function Readout({ label, value }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-zinc-100">{value || "--"}</p>
    </div>
  );
}

function actionPanelFor(actionLoading, renderJob, previewJob, uploadProgress, logoProgress) {
  if (previewJob && runningStatuses.has(previewJob.status)) {
    return {
      title: "Rendering Edited Preview",
      message: previewJob.message || "Preparing a lightweight preview MP4 from the current edit.",
      progress: previewJob.progress || 0,
    };
  }
  if (renderJob && runningStatuses.has(renderJob.status)) {
    return {
      title: "Rendering Video",
      message: renderJob.message || "Combining the primary video, focused cutaways, selected audio, sync, transitions, and branding.",
      progress: renderJob.progress || 0,
    };
  }
  if (actionLoading === "upload") return { title: "Uploading Video", message: "Copying the selected primary or focused video into local project storage.", progress: uploadProgress };
  if (actionLoading === "logo") return { title: "Uploading Logo", message: "Copying watermark logo into local project storage.", progress: logoProgress };
  if (actionLoading === "autoSync") return { title: "Estimating Sync", message: "Comparing the primary video audio against the selected generated audio." };
  if (actionLoading === "refresh") return { title: "Refreshing Video Editor", message: "Reading video assets and render settings." };
  if (actionLoading === "settings") return { title: "Saving Video Settings", message: "Updating sync, trim, audio, overlay, watermark, and card controls." };
  if (actionLoading === "templateSave") return { title: "Saving Branding Template", message: "Capturing the current overlay, watermark, and card settings for reuse." };
  if (actionLoading === "templateApply") return { title: "Applying Branding Template", message: "Loading saved overlay, watermark, and card settings." };
  if (actionLoading === "templateDelete") return { title: "Deleting Branding Template", message: "Removing the saved branding setup from this project." };
  if (actionLoading === "exportDelete") return { title: "Deleting Video Export", message: "Removing the selected MP4 from local project storage and history." };
  if (actionLoading === "preview") return { title: "Rendering Edited Preview", message: "Preparing a lightweight draft MP4 from the current edit settings." };
  if (actionLoading === "render") return { title: "Rendering Video", message: "Preparing the final MP4 export with selected finishing options." };
  return null;
}

function getExtension(filename) {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
}
