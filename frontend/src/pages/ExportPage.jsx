import { ArrowLeft, Archive, CheckCircle2, Download, FileAudio, Gauge, RefreshCw, Scissors, ShieldCheck, Sparkles, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  createProjectBackup,
  deleteExports,
  deleteMasters,
  exportInstrumental,
  exportMixWithoutMastering,
  getProcessingJob,
  getProject,
  listMasteringPresets,
  startMasteringJob,
  updateMasteringControls,
} from "../api.js";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import WaveformPreview from "../components/WaveformPreview.jsx";
import WorkflowGuide from "../components/WorkflowGuide.jsx";
import { formatBytes, formatDateTime, formatDb, formatDuration, formatLufs, formatPercent } from "../utils/format.js";

const defaultControls = {
  selectedMixVersionId: null,
  preset: "Streaming",
  brightness: 0,
  warmth: 0,
  compressionAmount: 45,
  limiterStrength: 55,
  stereoWidth: 55,
  outputFormat: "WAV 16-bit",
  trimStartSeconds: 0,
  trimEndSeconds: 0,
};
const runningStatuses = new Set(["Pending", "Processing"]);

export default function ExportPage() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [presetPayload, setPresetPayload] = useState({ presets: [], outputFormats: [], truePeakCeilingDb: -1 });
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [latestMaster, setLatestMaster] = useState(null);
  const [latestExport, setLatestExport] = useState(null);
  const [masterJob, setMasterJob] = useState(null);
  const [updatedMasterId, setUpdatedMasterId] = useState("");
  const [includeOriginals, setIncludeOriginals] = useState(false);
  const [compareA, setCompareA] = useState("");
  const [compareB, setCompareB] = useState("");
  const [selectedMixDuration, setSelectedMixDuration] = useState(Number.NaN);

  const mixVersions = project?.mixSettings?.mixVersions || [];
  const masteringSettings = project?.masteringSettings || {};
  const controls = { ...defaultControls, ...(masteringSettings.controls || {}) };
  const masterVersions = masteringSettings.masterVersions || [];
  const exportFiles = masteringSettings.exportFiles || [];
  const selectedMixId = controls.selectedMixVersionId || project?.mixSettings?.latestMixVersionId || mixVersions[mixVersions.length - 1]?.id || "";
  const selectedMix = mixVersions.find((version) => version.id === selectedMixId) || null;
  const selectedMixUrl = selectedMix?.mp3Url || selectedMix?.wavUrl || "";
  const selectedPreset = presetPayload.presets.find((preset) => preset.name === controls.preset);
  const selectedFormat = presetPayload.outputFormats.find((format) => format.name === controls.outputFormat);
  const selectedMixHasVocals = selectedMix?.sourceFiles?.some((source) => ["Lead Vocal", "Backing Vocal"].includes(source.stemType));
  const masterRunning = Boolean(masterJob && runningStatuses.has(masterJob.status));
  const trimStartSeconds = Math.max(0, Number(controls.trimStartSeconds) || 0);
  const trimEndSeconds = Math.max(0, Number(controls.trimEndSeconds) || 0);
  const trimActive = trimStartSeconds > 0 || trimEndSeconds > 0;
  const estimatedTrimmedDuration = Number.isFinite(selectedMixDuration) ? Math.max(0, selectedMixDuration - trimStartSeconds - trimEndSeconds) : Number.NaN;
  const trimTooAggressive = Number.isFinite(estimatedTrimmedDuration) && estimatedTrimmedDuration < 0.5;

  const comparisonOptions = useMemo(() => {
    const options = [];
    if (selectedMix) {
      options.push({
        id: `mix-${selectedMix.id}`,
        label: selectedMix.label || "Selected mix",
        kind: "Mix",
        url: selectedMix.mp3Url || selectedMix.wavUrl,
        path: selectedMix.mp3Path || selectedMix.wavPath,
      });
    }
    masterVersions.forEach((master) => {
      options.push({
        id: master.id,
        label: master.label,
        kind: master.preset,
        url: master.fileUrl,
        path: master.filePath,
        master,
      });
    });
    return options;
  }, [selectedMix, masterVersions]);

  const loadProject = async () => {
    setError("");
    try {
      const [nextProject, presets] = await Promise.all([getProject(projectId), listMasteringPresets()]);
      setProject(nextProject);
      setPresetPayload(presets);
      const nextControls = { ...defaultControls, ...(nextProject.masteringSettings?.controls || {}) };
      const nextSelected = nextControls.selectedMixVersionId || nextProject.mixSettings?.latestMixVersionId || nextProject.mixSettings?.mixVersions?.at(-1)?.id;
      if (nextSelected && !nextControls.selectedMixVersionId) {
        await updateMasteringControls(projectId, { selectedMixVersionId: nextSelected });
        setProject(await getProject(projectId));
      }
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
    if (!masterJob?.id || !runningStatuses.has(masterJob.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getProcessingJob(projectId, masterJob.id);
        setMasterJob(nextJob);
        if (!runningStatuses.has(nextJob.status)) {
          const nextProject = await getProject(projectId);
          setProject(nextProject);
          const masters = nextProject.masteringSettings?.masterVersions || [];
          const latest = masters.find((master) => master.id === nextProject.masteringSettings?.latestMasterVersionId) || masters[masters.length - 1] || null;
          if (latest) {
            setLatestMaster(latest);
            setCompareA(latest.id);
            setUpdatedMasterId(latest.id);
            setNotice(`Master updated: ${latest.label} is ready to review.`);
          }
          setActionLoading("");
          if (nextJob.status === "Failed") {
            setError(nextJob.errors?.[0]?.error || nextJob.message || "Mastering failed.");
          }
        }
      } catch (err) {
        setError(err.message);
        setActionLoading("");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [projectId, masterJob?.id, masterJob?.status]);

  useEffect(() => {
    if (!comparisonOptions.length) return;
    if (!compareA || !comparisonOptions.some((item) => item.id === compareA)) {
      setCompareA(comparisonOptions[comparisonOptions.length - 1].id);
    }
    if (!compareB || !comparisonOptions.some((item) => item.id === compareB)) {
      setCompareB(comparisonOptions[0].id);
    }
  }, [comparisonOptions, compareA, compareB]);

  useEffect(() => {
    if (!selectedMixUrl) {
      setSelectedMixDuration(Number.NaN);
      return undefined;
    }
    const audio = new Audio();
    const handleLoadedMetadata = () => setSelectedMixDuration(audio.duration);
    const handleError = () => setSelectedMixDuration(Number.NaN);
    audio.preload = "metadata";
    audio.addEventListener("loadedmetadata", handleLoadedMetadata);
    audio.addEventListener("error", handleError);
    audio.src = selectedMixUrl;
    return () => {
      audio.removeEventListener("loadedmetadata", handleLoadedMetadata);
      audio.removeEventListener("error", handleError);
      audio.src = "";
    };
  }, [selectedMixUrl]);

  const refreshProject = async () => {
    setActionLoading("refresh");
    try {
      await loadProject();
    } finally {
      setActionLoading("");
    }
  };

  const updateControlLocal = (updates) => {
    setNotice("Mastering controls changed. Generate a new master to hear the update.");
    setProject((current) => {
      if (!current) return current;
      return {
        ...current,
        masteringSettings: {
          ...(current.masteringSettings || {}),
          controls: { ...defaultControls, ...(current.masteringSettings?.controls || {}), ...updates },
        },
      };
    });
  };

  const commitControls = async (updates) => {
    setActionLoading("controls");
    setError("");
    try {
      setProject(await updateMasteringControls(projectId, updates));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runMaster = async () => {
    if (!selectedMixId) {
      setError("Generate or select a mix version before mastering.");
      return;
    }
    setActionLoading("master");
    setError("");
    setNotice("");
    setUpdatedMasterId("");
    let queued = false;
    try {
      const payload = {
        selectedMixVersionId: selectedMixId,
        preset: controls.preset,
        outputFormat: controls.outputFormat,
        brightness: controls.brightness,
        warmth: controls.warmth,
        compressionAmount: controls.compressionAmount,
        limiterStrength: controls.limiterStrength,
        stereoWidth: controls.stereoWidth,
        trimStartSeconds,
        trimEndSeconds,
      };
      const job = await startMasteringJob(projectId, payload);
      setMasterJob(job);
      setNotice("Mastering job queued. Progress will update here.");
      queued = true;
    } catch (err) {
      setError(err.message);
    } finally {
      if (!queued) setActionLoading("");
    }
  };

  const runExportMix = async () => {
    setActionLoading("exportMix");
    setError("");
    try {
      const exported = await exportMixWithoutMastering(projectId, {
        selectedMixVersionId: selectedMixId,
        outputFormat: controls.outputFormat,
        trimStartSeconds,
        trimEndSeconds,
      });
      setLatestExport(exported);
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runExportInstrumental = async () => {
    setActionLoading("instrumental");
    setError("");
    try {
      const exported = await exportInstrumental(projectId, {
        selectedMixVersionId: selectedMixId,
        outputFormat: controls.outputFormat,
        trimStartSeconds,
        trimEndSeconds,
      });
      setLatestExport(exported);
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runBackup = async () => {
    setActionLoading("backup");
    setError("");
    try {
      const backup = await createProjectBackup(projectId, { includeOriginalStems: includeOriginals });
      setLatestExport(backup);
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const removeMasters = async () => {
    if (!window.confirm("Delete all master files and reports? Mix versions and original stems are kept.")) return;
    setActionLoading("deleteMasters");
    setError("");
    setNotice("");
    try {
      setProject(await deleteMasters(projectId));
      setLatestMaster(null);
      setUpdatedMasterId("");
      setCompareA("");
      setCompareB("");
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const removeExports = async () => {
    if (!window.confirm("Delete exported mix, instrumental, and backup files? Masters and original stems are kept.")) return;
    setActionLoading("deleteExports");
    setError("");
    setNotice("");
    try {
      setProject(await deleteExports(projectId));
      setLatestExport(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  if (loading) {
    return <ProcessingPanel title="Loading Export" message="Reading mix versions, mastering settings, and previous masters." />;
  }

  const actionPanel = actionPanelFor(actionLoading, masterJob);
  const selectedA = comparisonOptions.find((option) => option.id === compareA);
  const selectedB = comparisonOptions.find((option) => option.id === compareB);
  const shownLatestMaster = latestMaster || masterVersions.find((master) => master.id === masteringSettings.latestMasterVersionId) || masterVersions[masterVersions.length - 1] || null;
  const masterJustUpdated = Boolean(shownLatestMaster && shownLatestMaster.id === updatedMasterId);

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>

      <div className="mt-5 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Mastering & Export</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">{project?.songTitle || project?.name || "Final master"}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">Master a selected mix version, export final files, and save local reports/backups.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button type="button" variant="secondary" onClick={refreshProject} disabled={actionLoading === "refresh"}>
            <RefreshCw size={17} />
            Refresh
          </Button>
          <Button type="button" onClick={runMaster} disabled={!selectedMixId || actionLoading === "master" || masterRunning}>
            <Sparkles size={17} />
            Generate Master
          </Button>
          <Button type="button" variant="danger" onClick={removeMasters} disabled={!masterVersions.length || actionLoading === "deleteMasters" || masterRunning}>
            <Trash2 size={17} />
            Delete Masters
          </Button>
        </div>
      </div>

      <WorkflowGuide project={project} currentStep="export" className="mt-6" onProjectRefresh={loadProject} />

      {error ? <p className="mt-5 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}
      {notice ? <p className="mt-5 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">{notice}</p> : null}

      {actionPanel ? (
        <div className="mt-5">
          <ProcessingPanel {...actionPanel} />
        </div>
      ) : null}

      {!mixVersions.length ? (
        <section className="mt-6">
          <EmptyState
            icon={FileAudio}
            title="No mix versions yet"
            description="Generate an advanced mix in the Mixer before mastering or exporting."
            action={
              <Button as={Link} to={`/projects/${projectId}/mixer`}>
                Open Mixer
              </Button>
            }
          />
        </section>
      ) : (
        <>
          <section className="mt-6 grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
            <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h2 className="font-semibold text-white">Mastering Controls</h2>
                  <p className="mt-1 text-sm text-zinc-400">{selectedPreset?.description || "Choose a loudness target and output format."}</p>
                </div>
                <StatusBadge status={shownLatestMaster ? "Master Ready" : "Pending"} />
              </div>

              {selectedPreset?.warning ? <p className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">{selectedPreset.warning}</p> : null}

              <MasteringPresetCards
                presets={presetPayload.presets}
                selectedPreset={controls.preset}
                onSelect={(preset) => {
                  updateControlLocal({ preset });
                  commitControls({ preset });
                }}
              />

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <SelectControl
                  label="Mix Version"
                  value={selectedMixId}
                  onChange={(value) => {
                    updateControlLocal({ selectedMixVersionId: value });
                    commitControls({ selectedMixVersionId: value });
                  }}
                  options={mixVersions.map((version) => ({ label: `${version.label} - ${version.preset}`, value: version.id }))}
                />
                <SelectControl
                  label="Loudness Preset"
                  value={controls.preset}
                  onChange={(value) => {
                    updateControlLocal({ preset: value });
                    commitControls({ preset: value });
                  }}
                  options={presetPayload.presets.map((preset) => ({ label: `${preset.name} (${formatLufs(preset.targetLufs)})`, value: preset.name }))}
                />
                <SelectControl
                  label="Output Format"
                  value={controls.outputFormat}
                  onChange={(value) => {
                    updateControlLocal({ outputFormat: value });
                    commitControls({ outputFormat: value });
                  }}
                  options={presetPayload.outputFormats.map((format) => ({ label: format.name, value: format.name }))}
                />
                <Readout label="True Peak Ceiling" value={formatDb(presetPayload.truePeakCeilingDb)} />
              </div>

              <CropPanel
                selectedMix={selectedMix}
                selectedMixUrl={selectedMixUrl}
                selectedMixDuration={selectedMixDuration}
                estimatedTrimmedDuration={estimatedTrimmedDuration}
                trimStartSeconds={trimStartSeconds}
                trimEndSeconds={trimEndSeconds}
                trimActive={trimActive}
                trimTooAggressive={trimTooAggressive}
                onChange={(key, value) => updateControlLocal({ [key]: value })}
                onCommit={(key, value) => commitControls({ [key]: value })}
                onReset={() => {
                  updateControlLocal({ trimStartSeconds: 0, trimEndSeconds: 0 });
                  commitControls({ trimStartSeconds: 0, trimEndSeconds: 0 });
                }}
              />

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <ControlSlider label="Brightness" value={controls.brightness} min={-50} max={50} display={signedPercent(controls.brightness)} onChange={(value) => updateControlLocal({ brightness: value })} onCommit={(value) => commitControls({ brightness: value })} />
                <ControlSlider label="Warmth" value={controls.warmth} min={-50} max={50} display={signedPercent(controls.warmth)} onChange={(value) => updateControlLocal({ warmth: value })} onCommit={(value) => commitControls({ warmth: value })} />
                <ControlSlider label="Compression" value={controls.compressionAmount} onChange={(value) => updateControlLocal({ compressionAmount: value })} onCommit={(value) => commitControls({ compressionAmount: value })} />
                <ControlSlider label="Limiter" value={controls.limiterStrength} onChange={(value) => updateControlLocal({ limiterStrength: value })} onCommit={(value) => commitControls({ limiterStrength: value })} />
                <ControlSlider label="Stereo Width" value={controls.stereoWidth} onChange={(value) => updateControlLocal({ stereoWidth: value })} onCommit={(value) => commitControls({ stereoWidth: value })} />
                <Readout label="Selected Format" value={selectedFormat?.description || controls.outputFormat} />
              </div>

              <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                <Button type="button" onClick={runMaster} disabled={!selectedMixId || actionLoading === "master" || masterRunning}>
                  <Sparkles size={17} />
                  Generate Master
                </Button>
                <Button type="button" variant="secondary" onClick={runExportMix} disabled={!selectedMixId || actionLoading === "exportMix"}>
                  <Download size={17} />
                  Export Mix
                </Button>
                <Button type="button" variant="secondary" onClick={runExportInstrumental} disabled={!selectedMixId || selectedMixHasVocals || actionLoading === "instrumental"} title={selectedMixHasVocals ? "Select a mix version with vocals muted to export instrumental." : "Export instrumental"}>
                  <FileAudio size={17} />
                  Export Instrumental
                </Button>
              </div>
            </div>

            <LatestMasterPanel master={shownLatestMaster} selectedMix={selectedMix} recentlyUpdated={masterJustUpdated} />
          </section>

          <section className="mt-6 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
            <ComparisonPanel options={comparisonOptions} compareA={compareA} compareB={compareB} setCompareA={setCompareA} setCompareB={setCompareB} selectedA={selectedA} selectedB={selectedB} />
            <ExportFilesPanel exportFiles={exportFiles} latestExport={latestExport} includeOriginals={includeOriginals} setIncludeOriginals={setIncludeOriginals} runBackup={runBackup} onDeleteExports={removeExports} backupBusy={actionLoading === "backup"} deleteBusy={actionLoading === "deleteExports"} />
          </section>
        </>
      )}
    </div>
  );
}

function MasteringPresetCards({ presets, selectedPreset, onSelect }) {
  if (!presets.length) return null;
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
      {presets.map((preset) => {
        const selected = preset.name === selectedPreset;
        return (
          <button
            key={preset.name}
            type="button"
            onClick={() => onSelect(preset.name)}
            className={`rounded-lg border p-3 text-left transition ${
              selected
                ? "border-teal-200/30 bg-teal-300/10 shadow-[0_0_24px_rgba(45,212,191,0.12)]"
                : "border-white/10 bg-black/20 hover:border-teal-200/25 hover:bg-white/[0.06]"
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-white">{preset.name}</p>
                <p className="mt-1 text-xs text-zinc-500">{preset.description || "Mastering preset"}</p>
              </div>
              <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border ${selected ? "border-teal-200/30 bg-teal-300/10 text-teal-100" : "border-white/10 bg-white/[0.04] text-zinc-300"}`}>
                <Gauge size={16} />
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between gap-3">
              <span className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Target</span>
              <span className="text-sm font-semibold text-zinc-100">{formatLufs(preset.targetLufs)}</span>
            </div>
            {preset.warning ? (
              <p className="mt-3 line-clamp-2 rounded-lg border border-amber-300/20 bg-amber-300/10 px-2 py-1 text-xs text-amber-100">{preset.warning}</p>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function LatestMasterPanel({ master, selectedMix, recentlyUpdated }) {
  return (
    <div className={`rounded-lg border bg-white/[0.04] p-4 ${recentlyUpdated ? "border-emerald-300/25 shadow-[0_0_32px_rgba(16,185,129,0.12)]" : "border-white/10"}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-semibold text-white">Loudness Report</h2>
          <p className="mt-1 text-sm text-zinc-400">{master ? `${master.label} - ${master.preset} - ${formatDateTime(master.createdAt)}` : selectedMix ? `Ready to master ${selectedMix.label}` : "No selected mix."}</p>
        </div>
        {master ? <StatusBadge status="Completed" /> : <StatusBadge status="Pending" />}
      </div>

      {master ? (
        <div className="mt-4 space-y-4">
          {recentlyUpdated ? (
            <div className="rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-3 py-2">
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-emerald-100">
                <CheckCircle2 size={16} />
                Master Updated
              </p>
              <p className="mt-1 text-xs leading-5 text-zinc-300">This output was refreshed by the latest mastering run and is ready for review.</p>
            </div>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-3">
            <Readout label="LUFS" value={formatLufs(master.integratedLufs)} />
            <Readout label="Peak" value={formatDb(master.peakDbfs)} />
            <Readout label="True Peak" value={formatDb(master.truePeakDbfs)} />
            <Readout label="Dynamic Range" value={Number.isFinite(master.dynamicRangeDb) ? `${master.dynamicRangeDb.toFixed(1)} dB` : "--"} />
            <Readout label="Target" value={formatLufs(master.targetLufs)} />
            <Readout label="Clipping" value={master.clippingDetected ? "Detected" : "Clear"} />
          </div>
          <ReportPreview master={master} />
          <p className="truncate text-xs text-zinc-500">{master.filePath}</p>
          <WaveformPreview src={master.fileUrl} variant="teal" />
          <audio className="w-full" src={master.fileUrl} controls />
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <Button as="a" href={master.fileUrl} target="_blank" rel="noreferrer" variant="secondary">
              <Download size={17} />
              Open Master
            </Button>
            <Button as="a" href={master.reportJsonUrl} target="_blank" rel="noreferrer" variant="secondary">
              Report JSON
            </Button>
            <Button as="a" href={master.reportTxtUrl} target="_blank" rel="noreferrer" variant="secondary">
              Report TXT
            </Button>
          </div>
          {master.warnings?.length ? <p className="rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">{master.warnings[0]}</p> : null}
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">Generate a master to create WAV/MP3/FLAC output and loudness reports.</p>
      )}
    </div>
  );
}

function ReportPreview({ master }) {
  const warnings = master.warnings || [];
  const clear = !master.clippingDetected && !warnings.length;
  return (
    <div className={`rounded-lg border p-3 ${clear ? "border-emerald-300/20 bg-emerald-300/10" : "border-amber-300/20 bg-amber-300/10"}`}>
      <div className="flex items-start gap-3">
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border ${clear ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100" : "border-amber-300/20 bg-amber-300/10 text-amber-100"}`}>
          {clear ? <ShieldCheck size={17} /> : <TriangleAlert size={17} />}
        </span>
        <div className="min-w-0">
          <p className={`text-sm font-semibold ${clear ? "text-emerald-100" : "text-amber-100"}`}>{clear ? "Master safety clear" : "Review mastering warnings"}</p>
          <p className="mt-1 text-xs leading-5 text-zinc-300">
            Preset {master.preset} rendered to {master.outputFormat || "selected format"} with {formatLufs(master.integratedLufs)} integrated loudness and {formatDb(master.truePeakDbfs)} true peak.
          </p>
          {warnings.length ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {warnings.slice(0, 3).map((warning) => (
                <span key={warning} className="rounded-full border border-amber-300/20 bg-black/20 px-2 py-1 text-xs text-amber-100">
                  {warning}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ComparisonPanel({ options, compareA, compareB, setCompareA, setCompareB, selectedA, selectedB }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <h2 className="font-semibold text-white">A/B Compare</h2>
      <p className="mt-1 text-sm text-zinc-400">Compare the selected mix against previous masters.</p>
      {options.length ? (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <CompareSlot label="A" options={options} selected={compareA} onChange={setCompareA} item={selectedA} variant="teal" />
          <CompareSlot label="B" options={options} selected={compareB} onChange={setCompareB} item={selectedB} variant="amber" />
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">Generate a mix or master to compare versions.</p>
      )}
    </div>
  );
}

function CompareSlot({ label, options, selected, onChange, item, variant }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <label className="block">
        <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Compare {label}</span>
        <select value={selected} onChange={(event) => onChange(event.target.value)} className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white">
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {item?.url ? (
        <div className="mt-3 space-y-2">
          <p className="truncate text-xs text-zinc-500">{item.path}</p>
          <WaveformPreview src={item.url} variant={variant} />
          <audio className="w-full" src={item.url} controls />
        </div>
      ) : null}
    </div>
  );
}

function ExportFilesPanel({ exportFiles, latestExport, includeOriginals, setIncludeOriginals, runBackup, onDeleteExports, backupBusy, deleteBusy }) {
  const files = latestExport ? [latestExport, ...exportFiles.filter((file) => file.id !== latestExport.id)] : exportFiles;
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-semibold text-white">Exports & Backup</h2>
          <p className="mt-1 text-sm text-zinc-400">Save unmastered mixes, instrumental-ready mixes, and project backups.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button type="button" variant="secondary" onClick={runBackup} disabled={backupBusy}>
            <Archive size={17} />
            Backup ZIP
          </Button>
          <Button type="button" variant="danger" onClick={onDeleteExports} disabled={!files.length || deleteBusy}>
            <Trash2 size={17} />
            Delete Exports
          </Button>
        </div>
      </div>
      <label className="mt-4 inline-flex items-center gap-2 text-sm text-zinc-300">
        <input type="checkbox" checked={includeOriginals} onChange={(event) => setIncludeOriginals(event.target.checked)} className="h-4 w-4 rounded border-white/20 bg-black/30 accent-teal-300" />
        Include original stems in backup
      </label>
      <div className="mt-4 space-y-3">
        {files.length ? (
          files.map((file) => (
            <div key={file.id} className="rounded-lg border border-white/10 bg-black/20 p-3">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate font-semibold text-white">{file.label}</p>
                  <p className="mt-1 truncate text-xs text-zinc-500">{file.filePath}</p>
                  <p className="mt-1 text-xs text-zinc-500">{file.outputFormat || file.type} - {formatBytes(file.sizeBytes)}</p>
                  {file.warnings?.length ? <p className="mt-2 text-xs text-amber-100">{file.warnings[0]}</p> : null}
                </div>
                <Button as="a" href={file.fileUrl} target="_blank" rel="noreferrer" variant="secondary" className="shrink-0">
                  <Download size={17} />
                  Open
                </Button>
              </div>
            </div>
          ))
        ) : (
          <p className="rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">No extra exports yet.</p>
        )}
      </div>
    </div>
  );
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

function CropPanel({
  selectedMix,
  selectedMixUrl,
  selectedMixDuration,
  estimatedTrimmedDuration,
  trimStartSeconds,
  trimEndSeconds,
  trimActive,
  trimTooAggressive,
  onChange,
  onCommit,
  onReset,
}) {
  return (
    <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="inline-flex items-center gap-2 text-sm font-semibold text-white">
            <Scissors size={16} />
            Crop Before Master/Export
          </p>
          <p className="mt-1 text-sm text-zinc-400">Trim the intro or tail for every master and export generated from this page. The original mix version stays untouched.</p>
        </div>
        <Button type="button" variant="secondary" onClick={onReset} disabled={!trimActive} className="sm:w-auto">
          Reset Crop
        </Button>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px_220px]">
        <div className="min-w-0">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Selected Mix Preview</p>
          {selectedMixUrl ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-0.5 text-xs font-semibold text-zinc-300">{selectedMix?.label || "Selected mix"}</span>
                <span className="rounded-full border border-white/10 bg-black/25 px-2 py-0.5 text-xs font-semibold text-zinc-400">
                  {Number.isFinite(selectedMixDuration) ? `Length ${formatDuration(selectedMixDuration)}` : "Length pending"}
                </span>
                {trimActive && Number.isFinite(estimatedTrimmedDuration) ? (
                  <span className="rounded-full border border-teal-300/20 bg-teal-300/10 px-2 py-0.5 text-xs font-semibold text-teal-100">
                    Output {formatDuration(estimatedTrimmedDuration)}
                  </span>
                ) : null}
              </div>
              <WaveformPreview src={selectedMixUrl} variant="teal" />
              <audio className="w-full" src={selectedMixUrl} controls preload="metadata" />
            </div>
          ) : (
            <p className="rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">Select a mix version to set the crop range.</p>
          )}
        </div>

        <SecondsControl
          label="Trim Intro"
          helper="Seconds removed from the beginning."
          value={trimStartSeconds}
          onChange={(value) => onChange("trimStartSeconds", value)}
          onCommit={(value) => onCommit("trimStartSeconds", value)}
        />
        <SecondsControl
          label="Trim Tail"
          helper="Optional seconds removed from the end."
          value={trimEndSeconds}
          onChange={(value) => onChange("trimEndSeconds", value)}
          onCommit={(value) => onCommit("trimEndSeconds", value)}
        />
      </div>

      {trimTooAggressive ? (
        <p className="mt-4 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">The current crop range leaves less than half a second of audio. Reduce the trim before exporting.</p>
      ) : trimActive ? (
        <p className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">Crop is active. New master and export renders from this page will use the trimmed range.</p>
      ) : null}
    </div>
  );
}

function SecondsControl({ label, helper, value, onChange, onCommit }) {
  const safeValue = Number.isFinite(value) ? value : 0;
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</span>
      <input
        type="number"
        min="0"
        step="0.1"
        value={safeValue}
        onChange={(event) => onChange(Math.max(0, Number(event.target.value) || 0))}
        onBlur={(event) => onCommit(Math.max(0, Number(event.currentTarget.value) || 0))}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
        className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white"
      />
      <p className="mt-2 text-xs leading-5 text-zinc-500">{helper}</p>
    </label>
  );
}

function ControlSlider({ label, value, min = 0, max = 100, step = 1, display, onChange, onCommit }) {
  const numericValue = Number.isFinite(value) ? value : 0;
  return (
    <label className="block">
      <span className="mb-2 flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">
        <span>{label}</span>
        <span className="normal-case tracking-normal text-zinc-300">{display || `${Math.round(numericValue)}%`}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={numericValue}
        onChange={(event) => onChange(Number(event.target.value))}
        onPointerUp={(event) => onCommit(Number(event.currentTarget.value))}
        onBlur={(event) => onCommit(Number(event.currentTarget.value))}
        className="w-full accent-teal-300"
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

function actionPanelFor(actionLoading, masterJob) {
  if (masterJob && runningStatuses.has(masterJob.status)) {
    return {
      title: "Generating Master",
      message: masterJob.message || "Analyzing loudness, applying mastering chain, and writing reports.",
      progress: masterJob.progress || 0,
    };
  }
  if (actionLoading === "refresh") return { title: "Refreshing Export", message: "Reading latest masters and reports." };
  if (actionLoading === "controls") return { title: "Saving Mastering Controls", message: "Updating mastering settings." };
  if (actionLoading === "master") return { title: "Generating Master", message: "Analyzing loudness, applying mastering chain, and writing reports." };
  if (actionLoading === "exportMix") return { title: "Exporting Mix", message: "Writing selected mix to the chosen format." };
  if (actionLoading === "instrumental") return { title: "Exporting Instrumental", message: "Writing the vocal-free selected mix." };
  if (actionLoading === "backup") return { title: "Creating Backup", message: "Packaging project metadata, reports, logs, and exports." };
  if (actionLoading === "deleteMasters") return { title: "Deleting Masters", message: "Removing master files and loudness reports." };
  if (actionLoading === "deleteExports") return { title: "Deleting Exports", message: "Removing exported mixes, instrumentals, and backup ZIPs." };
  return null;
}

function signedPercent(value) {
  if (!Number.isFinite(value)) return "--";
  return `${value > 0 ? "+" : ""}${Math.round(value)}%`;
}
