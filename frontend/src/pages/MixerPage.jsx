import { ArrowLeft, Check, Gauge, Headphones, MicOff, Pencil, Play, RefreshCw, RotateCcw, SlidersHorizontal, Sparkles, Trash2, Volume2, WandSparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  applyAutoBalance,
  deleteMixVersion,
  generateAutoBalance,
  generateRoughMix,
  getProcessingJob,
  getProject,
  listMixPresets,
  renameMixVersion,
  resetAdvancedMix,
  startAdvancedMix,
  startInstrumentalMix,
  updateCleaningSettings,
  updateMixControls,
  updateMixStem,
} from "../api.js";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ProcessingPanel from "../components/ProcessingPanel.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import WaveformPreview from "../components/WaveformPreview.jsx";
import WorkflowGuide from "../components/WorkflowGuide.jsx";
import { MIX_PRESETS } from "../constants.js";
import { formatDateTime, formatDb, formatLufs, formatPan } from "../utils/format.js";

const defaultControls = {
  preset: "Balanced",
  vocalBoost: 1.5,
  drumPunch: 50,
  bassWeight: 50,
  brightness: 0,
  warmth: 0,
  width: 55,
  reverbAmount: 35,
  vocalReverbAmount: 35,
  roomSize: 45,
};
const runningStatuses = new Set(["Pending", "Processing"]);

export default function MixerPage() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [presets, setPresets] = useState(MIX_PRESETS.map((name) => ({ name })));
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [savingStemId, setSavingStemId] = useState("");
  const [roughMix, setRoughMix] = useState(null);
  const [advancedMix, setAdvancedMix] = useState(null);
  const [mixJob, setMixJob] = useState(null);
  const [error, setError] = useState("");
  const [balanceNotice, setBalanceNotice] = useState("");
  const [previewNotice, setPreviewNotice] = useState("");
  const [compareA, setCompareA] = useState("");
  const [compareB, setCompareB] = useState("");
  const [editingVersionId, setEditingVersionId] = useState("");
  const [versionDraft, setVersionDraft] = useState("");

  const stems = project?.stems || [];
  const mixSettings = project?.mixSettings || {};
  const controls = { ...defaultControls, ...(mixSettings.controls || {}) };
  const mixVersions = mixSettings.mixVersions || [];
  const latestVersion = advancedMix || mixVersions.find((version) => version.id === mixSettings.latestMixVersionId) || mixVersions[mixVersions.length - 1] || null;
  const analysisComplete = stems.length > 0 && stems.every((stem) => stem.analysisStatus === "Completed");
  const mixRunning = Boolean(mixJob && runningStatuses.has(mixJob.status));

  const settingsByStem = useMemo(() => {
    const map = new Map();
    (mixSettings.stems || []).forEach((setting) => map.set(setting.stemId, setting));
    return map;
  }, [mixSettings.stems]);

  const suggestionCount = stems.filter((stem) => stem.autoBalanceSuggestion).length;
  const appliedCount = (mixSettings.stems || []).filter((setting) => setting.autoBalanceApplied).length;
  const balanceStateNotice =
    balanceNotice || (suggestionCount > 0 && appliedCount === 0 ? `${suggestionCount} suggested gain and pan move${suggestionCount === 1 ? "" : "s"} ready.` : "");

  const roughPreview = {
    id: "rough",
    label: "Rough mix",
    url: roughMix?.mp3Url || roughMix?.wavUrl || mixSettings.roughMixMp3Url || mixSettings.roughMixWavUrl,
    path: roughMix?.mp3Path || roughMix?.wavPath || mixSettings.roughMixMp3Path || mixSettings.roughMixWavPath,
    kind: "Rough",
  };

  const comparisonOptions = useMemo(() => {
    const options = [];
    if (roughPreview.url) options.push(roughPreview);
    mixVersions.forEach((version) => {
      options.push({
        id: version.id,
        label: version.label || `Mix v${String(version.versionNumber).padStart(3, "0")}`,
        url: version.mp3Url || version.wavUrl,
        path: version.mp3Path || version.wavPath,
        kind: version.preset,
        version,
      });
    });
    return options;
  }, [roughPreview.url, roughPreview.path, mixVersions]);

  const loadProject = async () => {
    setError("");
    try {
      const [nextProject, presetPayload] = await Promise.all([getProject(projectId), listMixPresets().catch(() => null)]);
      setProject(nextProject);
      if (presetPayload?.presets?.length) setPresets(presetPayload.presets);
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
    if (!comparisonOptions.length) return;
    if (!compareA || !comparisonOptions.some((option) => option.id === compareA)) {
      setCompareA(comparisonOptions[comparisonOptions.length - 1].id);
    }
    if (!compareB || !comparisonOptions.some((option) => option.id === compareB)) {
      setCompareB(comparisonOptions[0].id);
    }
  }, [comparisonOptions, compareA, compareB]);

  useEffect(() => {
    if (!mixJob?.id || !runningStatuses.has(mixJob.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await getProcessingJob(projectId, mixJob.id);
        setMixJob(nextJob);
        if (!runningStatuses.has(nextJob.status)) {
          const nextProject = await getProject(projectId);
          setProject(nextProject);
          const latestId = nextProject.mixSettings?.latestMixVersionId;
          if (latestId) setCompareA(latestId);
          setActionLoading("");
          if (nextJob.status === "Failed") {
            setError(nextJob.errors?.[0]?.error || nextJob.message || "Mix rendering failed.");
          }
        }
      } catch (err) {
        setError(err.message);
        setActionLoading("");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [projectId, mixJob?.id, mixJob?.status]);

  const refreshProject = async () => {
    setActionLoading("refresh");
    try {
      await loadProject();
    } finally {
      setActionLoading("");
    }
  };

  const runGenerateAutoBalance = async () => {
    setActionLoading("generate");
    setError("");
    setBalanceNotice("");
    try {
      const nextProject = await generateAutoBalance(projectId);
      const nextSuggestionCount = nextProject.stems.filter((stem) => stem.autoBalanceSuggestion).length;
      setProject(nextProject);
      setBalanceNotice(`${nextSuggestionCount} suggested gain and pan move${nextSuggestionCount === 1 ? "" : "s"} ready.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runApplyAutoBalance = async () => {
    setActionLoading("apply");
    setError("");
    setBalanceNotice("");
    setPreviewNotice("");
    setRoughMix(null);
    try {
      const nextProject = await applyAutoBalance(projectId);
      const nextAppliedCount = (nextProject.mixSettings?.stems || []).filter((setting) => setting.autoBalanceApplied).length;
      setProject(nextProject);
      setBalanceNotice(`Auto balance applied to ${nextAppliedCount} stem${nextAppliedCount === 1 ? "" : "s"}.`);
      setPreviewNotice("Generate a new preview or mix version to hear the updated settings.");
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runResetAdvancedMix = async () => {
    setActionLoading("reset");
    setError("");
    try {
      setProject(await resetAdvancedMix(projectId));
      setPreviewNotice("Auto mix settings reset. Generate a new mix version to hear the update.");
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runRoughMix = async () => {
    setActionLoading("preview");
    setError("");
    setPreviewNotice("");
    try {
      const result = await generateRoughMix(projectId);
      setRoughMix(result);
      await loadProject();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const runAdvancedMix = async () => {
    setActionLoading("advanced");
    setError("");
    setPreviewNotice("");
    try {
      const job = await startAdvancedMix(projectId);
      setMixJob(job);
      if (!compareB && roughPreview.url) setCompareB("rough");
    } catch (err) {
      setError(err.message);
      setActionLoading("");
    }
  };

  const runInstrumentalMix = async () => {
    setActionLoading("instrumental");
    setError("");
    setPreviewNotice("");
    try {
      const job = await startInstrumentalMix(projectId);
      setMixJob(job);
      if (!compareB && roughPreview.url) setCompareB("rough");
    } catch (err) {
      setError(err.message);
      setActionLoading("");
    }
  };

  const saveVersionLabel = async (versionId) => {
    const label = versionDraft.trim();
    if (!label) return;
    setActionLoading("version");
    setError("");
    try {
      const updated = await renameMixVersion(projectId, versionId, label);
      setProject((current) => ({
        ...current,
        mixSettings: {
          ...(current.mixSettings || {}),
          mixVersions: (current.mixSettings?.mixVersions || []).map((version) => (version.id === versionId ? updated : version)),
        },
      }));
      setEditingVersionId("");
      setVersionDraft("");
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const removeMixVersion = async (version) => {
    if (!window.confirm(`Delete "${version.label || "this mix version"}"? This removes its generated mix files but never touches original stems.`)) return;
    setActionLoading("deleteVersion");
    setError("");
    try {
      await deleteMixVersion(projectId, version.id);
      const nextProject = await getProject(projectId);
      setProject(nextProject);
      if (compareA === version.id) setCompareA(nextProject.mixSettings?.latestMixVersionId || "rough");
      if (compareB === version.id) setCompareB("rough");
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const updateControlLocal = (updates) => {
    setPreviewNotice("Mix controls changed. Generate a new mix version to hear the update.");
    setProject((current) => {
      if (!current) return current;
      return {
        ...current,
        mixSettings: {
          ...(current.mixSettings || {}),
          controls: { ...defaultControls, ...(current.mixSettings?.controls || {}), ...updates },
        },
      };
    });
  };

  const commitControls = async (updates) => {
    setActionLoading("controls");
    setError("");
    try {
      setProject(await updateMixControls(projectId, updates));
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const changePreset = async (preset) => {
    setActionLoading("preset");
    setError("");
    try {
      const nextProject = await updateMixControls(projectId, { preset });
      setProject(nextProject);
      setPreviewNotice("Preset changed. Generate a new mix version to hear the update.");
    } catch (err) {
      setError(err.message);
    } finally {
      setActionLoading("");
    }
  };

  const updateLocalSetting = (stemId, updates) => {
    setBalanceNotice("");
    setRoughMix(null);
    setPreviewNotice("Stem settings changed. Generate a new preview or mix version to hear the update.");
    setProject((current) => {
      if (!current) return current;
      const stemsSettings = [...(current.mixSettings?.stems || [])];
      const index = stemsSettings.findIndex((setting) => setting.stemId === stemId);
      const existing = index >= 0 ? stemsSettings[index] : defaultSetting(stemId);
      const next = { ...existing, ...updates };
      if (index >= 0) stemsSettings[index] = next;
      else stemsSettings.push(next);
      return {
        ...current,
        mixSettings: {
          ...(current.mixSettings || {}),
          stems: stemsSettings,
          roughMixWavPath: null,
          roughMixMp3Path: null,
          roughMixWavUrl: null,
          roughMixMp3Url: null,
        },
      };
    });
  };

  const commitSetting = async (stemId, updates) => {
    setSavingStemId(stemId);
    setError("");
    try {
      setProject(await updateMixStem(projectId, stemId, updates));
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingStemId("");
    }
  };

  const toggleCleanedSource = async (stem, checked) => {
    setSavingStemId(stem.id);
    setError("");
    setPreviewNotice("Source selection changed. Generate a new mix version to hear the update.");
    try {
      const updated = await updateCleaningSettings(projectId, stem.id, { useCleanedInMix: checked });
      setProject((current) => ({
        ...current,
        stems: current.stems.map((item) => (item.id === stem.id ? updated : item)),
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingStemId("");
    }
  };

  if (loading) {
    return <ProcessingPanel title="Loading Mixer" message="Reading mix settings, versions, and preview references." />;
  }

  const actionPanel = actionPanelFor(actionLoading, savingStemId, mixJob);
  const selectedA = comparisonOptions.find((option) => option.id === compareA);
  const selectedB = comparisonOptions.find((option) => option.id === compareB);

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>

      <div className="mt-5 flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-teal-100/70">Mixer</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">{project?.songTitle || project?.name || "Auto mix"}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">Preset-based stem processing with versioned local mix previews.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button type="button" variant="secondary" onClick={refreshProject} disabled={actionLoading === "refresh"}>
            <RefreshCw size={17} />
            Refresh
          </Button>
          <Button type="button" variant="secondary" onClick={runGenerateAutoBalance} disabled={!analysisComplete || actionLoading === "generate"} title={analysisComplete ? "Generate auto balance" : "Analyze all stems first"}>
            <WandSparkles size={17} />
            Generate Auto Balance
          </Button>
          <Button type="button" onClick={runAdvancedMix} disabled={!stems.length || mixRunning}>
            <Sparkles size={17} />
            Generate Mix
          </Button>
        </div>
      </div>

      <WorkflowGuide project={project} currentStep="mixer" className="mt-6" />

      {error ? <p className="mt-5 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}

      {actionPanel ? (
        <div className="mt-5">
          <ProcessingPanel {...actionPanel} />
        </div>
      ) : null}

      {balanceStateNotice ? (
        <section className="mt-5 flex flex-col gap-3 rounded-lg border border-teal-200/20 bg-teal-300/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm font-medium text-teal-50">{balanceStateNotice}</p>
          {suggestionCount > 0 && appliedCount === 0 ? (
            <Button type="button" onClick={runApplyAutoBalance} disabled={actionLoading === "apply"} className="sm:w-auto">
              <SlidersHorizontal size={17} />
              Apply Auto Balance
            </Button>
          ) : null}
        </section>
      ) : null}

      {!analysisComplete && stems.length ? (
        <p className="mt-5 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">Analyze all stems before generating auto-balance. Advanced mix can still render from current settings.</p>
      ) : null}

      {previewNotice ? (
        <section className="mt-5 flex flex-col gap-3 rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm font-medium text-amber-100">{previewNotice}</p>
          <Button type="button" variant="secondary" onClick={runAdvancedMix} disabled={!stems.length || mixRunning} className="sm:w-auto">
            <Sparkles size={17} />
            Generate Mix
          </Button>
        </section>
      ) : null}

      <section className="mt-6 grid gap-5">
        <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-semibold text-white">Auto Mix Controls</h2>
              <p className="mt-1 text-sm text-zinc-400">{presetDescription(presets, controls.preset)}</p>
            </div>
            <Button type="button" variant="secondary" onClick={runResetAdvancedMix} disabled={actionLoading === "reset"} className="sm:w-auto">
              <RotateCcw size={17} />
              Reset to Auto Mix
            </Button>
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Preset</span>
              <select value={controls.preset} onChange={(event) => changePreset(event.target.value)} className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white">
                {presets.map((preset) => (
                  <option key={preset.name} value={preset.name}>
                    {preset.name}
                  </option>
                ))}
              </select>
            </label>
            <Readout label="Target" value={formatLufs(currentPreset(presets, controls.preset)?.targetLufsRecommendation)} />
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <ControlSlider label="Vocal Boost" value={controls.vocalBoost} min={-6} max={6} step={0.5} display={formatDb(controls.vocalBoost)} onChange={(value) => updateControlLocal({ vocalBoost: value })} onCommit={(value) => commitControls({ vocalBoost: value })} />
            <ControlSlider label="Drum Punch" value={controls.drumPunch} onChange={(value) => updateControlLocal({ drumPunch: value })} onCommit={(value) => commitControls({ drumPunch: value })} />
            <ControlSlider label="Bass Weight" value={controls.bassWeight} onChange={(value) => updateControlLocal({ bassWeight: value })} onCommit={(value) => commitControls({ bassWeight: value })} />
            <ControlSlider label="Brightness" value={controls.brightness} min={-50} max={50} display={signedPercent(controls.brightness)} onChange={(value) => updateControlLocal({ brightness: value })} onCommit={(value) => commitControls({ brightness: value })} />
            <ControlSlider label="Warmth" value={controls.warmth} min={-50} max={50} display={signedPercent(controls.warmth)} onChange={(value) => updateControlLocal({ warmth: value })} onCommit={(value) => commitControls({ warmth: value })} />
            <ControlSlider label="Width" value={controls.width} onChange={(value) => updateControlLocal({ width: value })} onCommit={(value) => commitControls({ width: value })} />
            <ControlSlider label="Reverb" value={controls.reverbAmount} onChange={(value) => updateControlLocal({ reverbAmount: value })} onCommit={(value) => commitControls({ reverbAmount: value })} />
            <ControlSlider label="Vocal Reverb" value={controls.vocalReverbAmount} onChange={(value) => updateControlLocal({ vocalReverbAmount: value })} onCommit={(value) => commitControls({ vocalReverbAmount: value })} />
            <ControlSlider label="Room Size" value={controls.roomSize} onChange={(value) => updateControlLocal({ roomSize: value })} onCommit={(value) => commitControls({ roomSize: value })} />
          </div>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <Button type="button" variant="secondary" onClick={runApplyAutoBalance} disabled={!analysisComplete || actionLoading === "apply"}>
              <SlidersHorizontal size={17} />
              Apply Auto Balance
            </Button>
            <Button type="button" variant="secondary" onClick={runRoughMix} disabled={!stems.length || actionLoading === "preview"}>
              <Play size={17} />
              Preview Rough Mix
            </Button>
            <Button type="button" onClick={runAdvancedMix} disabled={!stems.length || mixRunning}>
              <Sparkles size={17} />
              Generate Mix
            </Button>
            <Button type="button" variant="secondary" onClick={runInstrumentalMix} disabled={!stems.length || mixRunning}>
              <MicOff size={17} />
              Instrumental Mix
            </Button>
          </div>
        </div>

        <MixPreviewPanel
          latestVersion={latestVersion}
          mixVersions={mixVersions}
          comparisonOptions={comparisonOptions}
          compareA={compareA}
          compareB={compareB}
          setCompareA={setCompareA}
          setCompareB={setCompareB}
          selectedA={selectedA}
          selectedB={selectedB}
          editingVersionId={editingVersionId}
          versionDraft={versionDraft}
          setEditingVersionId={setEditingVersionId}
          setVersionDraft={setVersionDraft}
          onSaveVersionLabel={saveVersionLabel}
          onDeleteVersion={removeMixVersion}
        />
      </section>

      <section className="mt-6">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-white">Stem Processing</h2>
            <p className="mt-1 text-sm text-zinc-400">Per-stem balance, source, dynamics, and send levels.</p>
          </div>
          {latestVersion ? <StatusBadge status="Advanced Mix Ready" /> : null}
        </div>
        {stems.length ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
            {stems.map((stem) => {
              const setting = { ...defaultSetting(stem.id), ...(settingsByStem.get(stem.id) || {}) };
              return (
                <StemProcessingCard
                  key={stem.id}
                  stem={stem}
                  setting={setting}
                  saving={savingStemId === stem.id}
                  onLocalChange={updateLocalSetting}
                  onCommit={commitSetting}
                  onToggleCleaned={toggleCleanedSource}
                />
              );
            })}
          </div>
        ) : (
          <EmptyState
            icon={SlidersHorizontal}
            title="No stems in the mixer"
            description="Upload stems before building an advanced mix."
            action={
              <Button as={Link} to={`/projects/${projectId}/upload`}>
                Upload stems
              </Button>
            }
          />
        )}
      </section>
    </div>
  );
}

function MixPreviewPanel({
  latestVersion,
  mixVersions,
  comparisonOptions,
  compareA,
  compareB,
  setCompareA,
  setCompareB,
  selectedA,
  selectedB,
  editingVersionId,
  versionDraft,
  setEditingVersionId,
  setVersionDraft,
  onSaveVersionLabel,
  onDeleteVersion,
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-semibold text-white">Mix Versions</h2>
          <p className="mt-1 text-sm text-zinc-400">{latestVersion ? `${latestVersion.label} - ${latestVersion.preset} - ${formatDateTime(latestVersion.createdAt)}` : "No advanced mix rendered yet."}</p>
        </div>
        {latestVersion ? <StatusBadge status="Completed" /> : <StatusBadge status="Pending" />}
      </div>

      {latestVersion ? (
        <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-3">
          <div className="grid gap-3 sm:grid-cols-4">
            <Readout label="LUFS" value={formatLufs(latestVersion.integratedLufs)} />
            <Readout label="Peak" value={formatDb(latestVersion.peakDbfs)} />
            <Readout label="True Peak" value={formatDb(latestVersion.truePeakDbfs)} />
            <Readout label="Safety Gain" value={formatDb(latestVersion.limiterGainDb)} />
          </div>
          <p className="mt-3 truncate text-xs text-zinc-500">{latestVersion.mp3Path || latestVersion.wavPath}</p>
          <WaveformPreview src={latestVersion.mp3Url || latestVersion.wavUrl} variant="teal" />
          <audio className="mt-3 w-full" src={latestVersion.mp3Url || latestVersion.wavUrl} controls />
          {latestVersion.warnings?.length ? <p className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs text-amber-100">{latestVersion.warnings[0]}</p> : null}
        </div>
      ) : null}

      {comparisonOptions.length ? (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <CompareSlot label="A" options={comparisonOptions} selected={compareA} onChange={setCompareA} item={selectedA} variant="teal" />
          <CompareSlot label="B" options={comparisonOptions} selected={compareB} onChange={setCompareB} item={selectedB} variant="amber" />
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-white/10 bg-black/20 px-3 py-3 text-sm text-zinc-500">Render a rough mix or advanced mix to compare versions.</p>
      )}

      {mixVersions.length ? (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Version Library</p>
          {mixVersions.slice().reverse().map((version) => (
            <div key={version.id} className="grid gap-3 rounded-lg border border-white/10 bg-black/20 p-3 lg:grid-cols-[minmax(190px,0.85fr)_minmax(150px,0.55fr)_minmax(320px,1.25fr)_auto] lg:items-center">
              <div className="min-w-0">
                {editingVersionId === version.id ? (
                  <input
                    value={versionDraft}
                    onChange={(event) => setVersionDraft(event.target.value)}
                    className="h-9 w-full rounded-lg border border-white/10 bg-black/30 px-3 text-sm text-white"
                    autoFocus
                  />
                ) : (
                  <p className="truncate text-sm font-semibold text-white">{version.label}</p>
                )}
                <p className="mt-1 truncate text-xs text-zinc-500">{version.mp3Path || version.wavPath}</p>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs text-zinc-400 lg:grid-cols-1 lg:gap-1">
                <span>{version.preset}</span>
                <span>{formatLufs(version.integratedLufs)}</span>
                <span>{formatDb(version.peakDbfs)}</span>
              </div>
              <audio className="h-9 w-full min-w-0" src={version.mp3Url || version.wavUrl} controls preload="none" />
              <div className="flex gap-2 lg:justify-end">
                {editingVersionId === version.id ? (
                  <>
                    <IconButton label="Save label" onClick={() => onSaveVersionLabel(version.id)}>
                      <Check size={16} />
                    </IconButton>
                    <IconButton label="Cancel rename" onClick={() => {
                      setEditingVersionId("");
                      setVersionDraft("");
                    }}>
                      <X size={16} />
                    </IconButton>
                  </>
                ) : (
                  <IconButton label="Rename mix" onClick={() => {
                    setEditingVersionId(version.id);
                    setVersionDraft(version.label || "");
                  }}>
                    <Pencil size={16} />
                  </IconButton>
                )}
                <IconButton label="Delete mix" onClick={() => onDeleteVersion(version)} tone="danger">
                  <Trash2 size={16} />
                </IconButton>
              </div>
            </div>
          ))}
        </div>
      ) : null}
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

function StemProcessingCard({ stem, setting, saving, onLocalChange, onCommit, onToggleCleaned }) {
  const analysis = stem.analysisResult || {};
  const suggestion = stem.autoBalanceSuggestion;
  const cleanedReady = stem.cleaningResult?.status === "Completed" && stem.cleaningResult?.cleanedFileUrl;
  const useCleaned = Boolean(stem.cleaningSettings?.useCleanedInMix);

  return (
    <article className="group flex min-h-[620px] flex-col rounded-lg border border-white/10 bg-gradient-to-b from-white/[0.07] via-white/[0.035] to-black/40 p-4 shadow-[0_20px_70px_rgba(0,0,0,0.25)] transition hover:border-teal-200/25">
      <div className="min-w-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate font-semibold text-white" title={stem.originalFilename}>{stem.originalFilename}</h3>
            <p className="mt-1 truncate text-xs text-zinc-500">{saving ? "Saving settings..." : setting.autoBalanceApplied ? "Auto balance applied" : "Manual balance"}</p>
          </div>
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/25 text-teal-200">
            <Volume2 size={17} />
          </span>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="inline-flex rounded-full border border-teal-300/20 bg-teal-300/10 px-2.5 py-1 text-xs font-semibold text-teal-100">{stem.stemType || "Unknown"}</span>
          <span className="inline-flex rounded-full border border-white/10 bg-black/25 px-2.5 py-1 text-xs font-semibold text-zinc-300">{cleanedReady && useCleaned ? "Cleaned" : "Original"}</span>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-white/10 bg-black/25 p-3">
        <div className="flex items-center justify-between gap-3">
          <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">
            <Gauge size={14} />
            Meter
          </p>
          <span className="text-xs text-zinc-500">{formatDb(analysis.peakDbfs)}</span>
        </div>
        <div className="mt-3 space-y-3">
          <LevelMeter label="LUFS" value={analysis.integratedLufs} min={-60} max={-6} display={formatLufs(analysis.integratedLufs)} />
          <LevelMeter label="Peak" value={analysis.peakDbfs} min={-48} max={0} display={formatDb(analysis.peakDbfs)} danger={analysis.peakDbfs > -1} />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <Toggle label="Mute" checked={setting.mute} onChange={(checked) => {
          onLocalChange(stem.id, { mute: checked });
          onCommit(stem.id, { mute: checked });
        }} />
        <Toggle label="Solo" checked={setting.solo} onChange={(checked) => {
          onLocalChange(stem.id, { solo: checked });
          onCommit(stem.id, { solo: checked });
        }} />
        <Toggle label="Chain" checked={setting.processingChainEnabled} onChange={(checked) => {
          onLocalChange(stem.id, { processingChainEnabled: checked });
          onCommit(stem.id, { processingChainEnabled: checked });
        }} />
        <Toggle label="Clean" checked={useCleaned && cleanedReady} disabled={!cleanedReady} onChange={(checked) => onToggleCleaned(stem, checked)} />
      </div>

      <div className="mt-4 flex flex-1 flex-col gap-4">
        <div className="rounded-lg border border-teal-300/20 bg-teal-300/[0.045] p-3">
          <ControlSlider label="Volume Fader" value={setting.gainDb} min={-24} max={12} step={0.5} display={formatDb(setting.gainDb)} onChange={(value) => onLocalChange(stem.id, { gainDb: value, autoBalanceApplied: false })} onCommit={(value) => onCommit(stem.id, { gainDb: value })} />
          {suggestion ? <p className="mt-2 text-xs text-zinc-500">Suggested {formatDb(suggestion.suggestedGainDb)}, {formatPan(suggestion.suggestedPan)}</p> : null}
        </div>
        <ControlSlider label="Pan" value={setting.pan} min={-100} max={100} step={1} display={formatPan(setting.pan)} onChange={(value) => onLocalChange(stem.id, { pan: value, autoBalanceApplied: false })} onCommit={(value) => onCommit(stem.id, { pan: value })} />
        <ControlSlider label="Reverb Send" value={setting.reverbSend} onChange={(value) => onLocalChange(stem.id, { reverbSend: value })} onCommit={(value) => onCommit(stem.id, { reverbSend: value })} />
        <ControlSlider label="Delay Send" value={setting.delaySend} onChange={(value) => onLocalChange(stem.id, { delaySend: value })} onCommit={(value) => onCommit(stem.id, { delaySend: value })} />
        <ControlSlider label="Presence" value={setting.presenceAmount} min={-50} max={50} display={signedPercent(setting.presenceAmount)} onChange={(value) => onLocalChange(stem.id, { presenceAmount: value })} onCommit={(value) => onCommit(stem.id, { presenceAmount: value })} />
        <ControlSlider label="Compression" value={setting.compressionAmount} onChange={(value) => onLocalChange(stem.id, { compressionAmount: value })} onCommit={(value) => onCommit(stem.id, { compressionAmount: value })} />
      </div>

      <div className="mt-4 border-t border-white/10 pt-3">
        <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">
          <Headphones size={14} />
          Chain
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {processingChain(stem.stemType, setting).slice(0, 6).map((item) => (
            <span key={item} className="rounded-full border border-white/10 bg-black/25 px-2 py-1 text-xs font-medium text-zinc-300">
              {item}
            </span>
          ))}
        </div>
      </div>
    </article>
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

function Toggle({ label, checked, disabled, onChange }) {
  return (
    <button
      type="button"
      aria-pressed={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`min-h-10 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
        checked ? "border-teal-200/30 bg-teal-300/20 text-teal-50 shadow-[0_0_18px_rgba(45,212,191,0.12)]" : "border-white/10 bg-black/20 text-zinc-300 hover:bg-white/[0.06]"
      }`}
    >
      {label}
    </button>
  );
}

function LevelMeter({ label, value, min, max, display, danger }) {
  const percent = Number.isFinite(value) ? Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100)) : 0;
  const fill = danger ? "from-amber-300 to-rose-300" : "from-teal-300 to-emerald-200";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
        <span>{label}</span>
        <span className="normal-case tracking-normal text-zinc-300">{display || "--"}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className={`h-full rounded-full bg-gradient-to-r ${fill}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function IconButton({ label, children, onClick, tone = "default" }) {
  const toneClass = tone === "danger" ? "text-rose-100 hover:border-rose-300/30 hover:bg-rose-400/10" : "text-zinc-200 hover:border-teal-300/30 hover:bg-white/[0.08]";
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className={`grid h-9 w-9 place-items-center rounded-lg border border-white/10 bg-white/[0.04] transition ${toneClass}`}>
      {children}
    </button>
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

function actionPanelFor(actionLoading, savingStemId, mixJob) {
  if (mixJob && runningStatuses.has(mixJob.status)) {
    return {
      title: mixJob.type === "Instrumental Mix" ? "Rendering Instrumental Mix" : "Rendering Advanced Mix",
      message: mixJob.message || "Processing stems and writing a versioned mix.",
      progress: mixJob.progress || 0,
    };
  }
  if (actionLoading === "refresh") return { title: "Refreshing Mixer", message: "Reading the latest mix settings and version metadata." };
  if (actionLoading === "generate") return { title: "Generating Auto Balance", message: "Calculating suggested gain and pan from analyzed stems." };
  if (actionLoading === "apply") return { title: "Applying Auto Balance", message: "Writing suggested gain and pan into mixer settings." };
  if (actionLoading === "reset") return { title: "Resetting Auto Mix", message: "Restoring preset controls and stem processing defaults." };
  if (actionLoading === "preview") return { title: "Rendering Rough Mix", message: "Exporting the gain-and-pan preview." };
  if (actionLoading === "advanced") return { title: "Starting Advanced Mix", message: "Creating the local mix render job." };
  if (actionLoading === "instrumental") return { title: "Starting Instrumental Mix", message: "Creating a vocal-muted mix render job." };
  if (actionLoading === "version") return { title: "Saving Mix Version", message: "Updating the mix version label." };
  if (actionLoading === "deleteVersion") return { title: "Deleting Mix Version", message: "Removing generated mix files and metadata." };
  if (actionLoading === "controls" || actionLoading === "preset") return { title: "Saving Mix Controls", message: "Updating advanced mix controls." };
  if (savingStemId) return { title: "Saving Stem Setting", message: "Updating the selected stem setting." };
  return null;
}

function currentPreset(presets, name) {
  return presets.find((preset) => preset.name === name);
}

function presetDescription(presets, name) {
  return currentPreset(presets, name)?.description || "Local advanced mix preset.";
}

function signedPercent(value) {
  if (!Number.isFinite(value)) return "--";
  return `${value > 0 ? "+" : ""}${Math.round(value)}%`;
}

function processingChain(stemType, setting) {
  if (!setting.processingChainEnabled) return ["Chain off", `Verb ${Math.round(setting.reverbSend)}%`, `Delay ${Math.round(setting.delaySend || 0)}%`];
  const chains = {
    "Lead Vocal": ["HPF", "Cleanup EQ", "Presence", "De-ess", "Comp", "Delay/Reverb"],
    "Backing Vocal": ["HPF", "Cleanup EQ", "Comp", "Spread", "Reverb"],
    Drums: ["HPF", "Mud Ctrl", "Bus Comp", "Punch", "Room"],
    Kick: ["HPF", "Low Ctrl", "Weight", "Comp"],
    Snare: ["HPF", "Body Ctrl", "Crack", "Comp", "Room"],
    Bass: ["HPF", "Low Ctrl", "Mud Ctrl", "Comp", "Saturation", "Mono"],
    "Electric Guitar": ["HPF", "Mud Ctrl", "Bite", "Comp", "Width"],
    "Acoustic Guitar": ["HPF", "Boom Ctrl", "Presence", "Comp"],
    "Keys/Piano": ["HPF", "Vocal Space", "Width", "Light Comp"],
    "Pads/Strings": ["HPF", "Background EQ", "Wide"],
    "FX/Ambience": ["HPF", "Wide", "Space"],
  };
  return [...(chains[stemType] || ["HPF", "Cleanup EQ", "Comp"]), `Verb ${Math.round(setting.reverbSend)}%`, `Delay ${Math.round(setting.delaySend || 0)}%`, `Presence ${signedPercent(setting.presenceAmount || 0)}`];
}

function defaultSetting(stemId) {
  return {
    stemId,
    gainDb: 0,
    pan: 0,
    mute: false,
    solo: false,
    autoBalanceApplied: false,
    processingChainEnabled: true,
    reverbSend: 35,
    delaySend: 0,
    presenceAmount: 0,
    compressionAmount: 50,
  };
}
