import { ArrowLeft, Download, Loader2, Pause, Play, RotateCcw, TriangleAlert, Volume2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { archiveSplitStems, exportSplitMix, getSplit } from "../api.js";
import Button from "../components/Button.jsx";
import StemChannelStrip from "../components/StemChannelStrip.jsx";
import StemPlayer from "../utils/stemPlayback.js";

function mediaUrl(path) {
  if (!path) return null;
  return `/media/${String(path).replace(/^\/+/, "")}`;
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export default function StemPlayerPage() {
  const { splitId } = useParams();
  const [split, setSplit] = useState(null);
  const [error, setError] = useState("");
  const [loadProgress, setLoadProgress] = useState({ loaded: 0, total: 0 });
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [masterVolume, setMasterVolume] = useState(0.85);
  const [channels, setChannels] = useState({});
  const [soloId, setSoloId] = useState(null);
  const [peaks, setPeaks] = useState({});
  const [archiving, setArchiving] = useState(false);
  const [archive, setArchive] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(null);

  const playerRef = useRef(null);
  const frameRef = useRef(null);

  // --- load split metadata --------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    getSplit(splitId)
      .then((row) => {
        if (!cancelled) setSplit(row);
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message);
      });
    return () => {
      cancelled = true;
    };
  }, [splitId]);

  // --- decode stems into the audio graph -----------------------------------
  useEffect(() => {
    if (!split || split.status !== "Ready" || !split.stems?.length) return undefined;

    const player = new StemPlayer();
    playerRef.current = player;
    let cancelled = false;

    const sources = split.stems.map((stem) => ({
      id: stem.id,
      // Previews are 192k MP3. Six decoded WAVs would be ~285MB of browser memory.
      url: mediaUrl(stem.previewPath || stem.filePath),
    }));

    setLoadProgress({ loaded: 0, total: sources.length });

    player
      .load(sources, (loaded, total) => {
        if (!cancelled) setLoadProgress({ loaded, total });
      })
      .then(() => {
        if (cancelled) return;
        setDuration(player.duration);
        setChannels(
          Object.fromEntries(split.stems.map((stem) => [stem.id, { gainDb: 0, muted: false }]))
        );
        setPeaks(Object.fromEntries(split.stems.map((stem) => [stem.id, player.getPeaks(stem.id, 220)])));
        player.setMasterVolume(masterVolume);
        setReady(true);
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message);
      });

    return () => {
      cancelled = true;
      player.destroy();
      playerRef.current = null;
    };
    // masterVolume intentionally excluded: it is pushed imperatively below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [split]);

  // --- playhead -------------------------------------------------------------
  useEffect(() => {
    if (!playing) {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
      return undefined;
    }
    const tick = () => {
      const player = playerRef.current;
      if (player) {
        setPosition(player.currentTime);
        if (player.currentTime >= player.duration - 0.05) {
          player.pause();
          player.seek(0);
          setPlaying(false);
          setPosition(0);
          return;
        }
      }
      frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    };
  }, [playing]);

  const togglePlay = useCallback(async () => {
    const player = playerRef.current;
    if (!player || !ready) return;
    if (playing) {
      player.pause();
      setPlaying(false);
      setPosition(player.currentTime);
    } else {
      await player.play();
      setPlaying(true);
    }
  }, [playing, ready]);

  const seekTo = useCallback(
    async (seconds) => {
      const player = playerRef.current;
      if (!player || !ready) return;
      await player.seek(seconds);
      setPosition(seconds);
    },
    [ready]
  );

  function onScrub(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    seekTo(Math.max(0, Math.min(1, ratio)) * duration);
  }

  function toggleMute(stemId) {
    setChannels((current) => {
      const next = { ...current, [stemId]: { ...current[stemId], muted: !current[stemId]?.muted } };
      playerRef.current?.setStemMuted(stemId, next[stemId].muted);
      return next;
    });
  }

  function toggleSolo(stemId) {
    setSoloId((current) => {
      const next = current === stemId ? null : stemId;
      playerRef.current?.setSolo(next);
      return next;
    });
  }

  function changeGain(stemId, db) {
    setChannels((current) => {
      const next = { ...current, [stemId]: { ...current[stemId], gainDb: db } };
      playerRef.current?.setStemGain(stemId, db);
      return next;
    });
  }

  function changeMaster(value) {
    setMasterVolume(value);
    playerRef.current?.setMasterVolume(value);
  }

  async function onArchive() {
    if (!split) return;
    setArchiving(true);
    setError("");
    try {
      setArchive(await archiveSplitStems(split.id));
    } catch (exc) {
      setError(exc.message);
    } finally {
      setArchiving(false);
    }
  }

  async function onExport() {
    if (!split) return;
    setExporting(true);
    setExported(null);
    setError("");
    try {
      const result = await exportSplitMix(split.id, {
        stems: split.stems.map((stem) => ({
          stemId: stem.id,
          gainDb: channels[stem.id]?.gainDb ?? 0,
          muted: channels[stem.id]?.muted || (soloId !== null && soloId !== stem.id),
        })),
        format: "wav",
      });
      setExported(result);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setExporting(false);
    }
  }

  const limitedStems = useMemo(
    () => (split?.stems || []).filter((stem) => stem.quality === "limited").map((stem) => stem.label),
    [split]
  );

  if (error && !split) {
    return (
      <div className="rounded-xl border border-rose-300/30 bg-rose-400/10 px-5 py-4 text-sm text-rose-100">
        {error}
      </div>
    );
  }

  if (!split) {
    return <p className="text-sm text-zinc-500">Loading split...</p>;
  }

  if (split.status !== "Ready") {
    return (
      <div className="flex flex-col gap-4">
        <Button as={Link} to="/stem-splitter" variant="ghost" className="self-start">
          <ArrowLeft size={15} />
          Stem Splitter
        </Button>
        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-5 py-6">
          <p className="text-sm font-semibold text-zinc-200">This split is {split.status.toLowerCase()}.</p>
          <p className="mt-1 text-[13px] text-zinc-500">{split.job?.message || split.error}</p>
        </div>
      </div>
    );
  }

  const progressRatio = duration ? position / duration : 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button as={Link} to="/stem-splitter" variant="ghost">
          <ArrowLeft size={15} />
          Stem Splitter
        </Button>
        <div className="min-w-0 flex-grow">
          <h1 className="truncate text-2xl font-semibold text-white">{split.title}</h1>
          <p className="mt-1 text-[12px] text-zinc-500">
            {split.stems.length} stems · {split.modelName}
            {split.elapsedSeconds ? ` · separated in ${(split.elapsedSeconds / 60).toFixed(1)} min` : ""}
          </p>
        </div>
        <Button type="button" variant="secondary" onClick={onArchive} disabled={archiving}>
          {archiving ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
          {archiving ? "Zipping..." : "Download all stems"}
        </Button>
        <Button type="button" variant="secondary" onClick={onExport} disabled={exporting || !ready}>
          {exporting ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
          {exporting ? "Rendering..." : "Export custom mix"}
        </Button>
      </div>

      {archive ? (
        <div className="flex items-center gap-3 rounded-lg border border-teal-300/30 bg-teal-300/[0.08] px-4 py-3">
          <Download size={16} className="shrink-0 text-teal-300" />
          <p className="min-w-0 flex-grow truncate text-[13px] text-teal-100">
            {archive.stemCount} stems zipped ({(archive.bytes / 1048576).toFixed(0)} MB)
          </p>
          <a
            href={mediaUrl(archive.filePath)}
            download
            className="shrink-0 text-[13px] font-semibold text-teal-200 underline"
          >
            Download zip
          </a>
        </div>
      ) : null}

      {!ready ? (
        <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-white/[0.04] px-4 py-3 text-sm text-zinc-300">
          <Loader2 size={16} className="animate-spin text-teal-300" />
          Decoding stems {loadProgress.loaded}/{loadProgress.total}...
        </div>
      ) : null}

      <div className="flex items-center gap-4 rounded-xl border border-white/10 bg-white/[0.04] px-5 py-3">
        <button
          type="button"
          onClick={togglePlay}
          disabled={!ready}
          aria-label={playing ? "Pause" : "Play"}
          className="grid h-12 w-12 shrink-0 place-items-center rounded-full border border-teal-300/55 bg-gradient-to-b from-teal-300 to-teal-500 text-teal-950 transition disabled:opacity-40"
        >
          {playing ? <Pause size={19} fill="currentColor" /> : <Play size={19} fill="currentColor" />}
        </button>
        <button
          type="button"
          onClick={() => seekTo(0)}
          disabled={!ready}
          aria-label="Back to start"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.05] text-zinc-400 transition hover:text-white disabled:opacity-40"
        >
          <RotateCcw size={16} />
        </button>

        <span className="shrink-0 text-sm font-semibold tabular-nums text-zinc-200">{formatTime(position)}</span>

        <button
          type="button"
          onClick={onScrub}
          aria-label="Seek"
          className="h-2 flex-grow cursor-pointer overflow-hidden rounded-full bg-white/[0.09] p-0"
        >
          <span className="block h-full rounded-full bg-teal-300" style={{ width: `${progressRatio * 100}%` }} />
        </button>

        <span className="shrink-0 text-sm tabular-nums text-zinc-500">{formatTime(duration)}</span>

        <div className="flex shrink-0 items-center gap-2">
          <Volume2 size={17} className="text-zinc-400" />
          <label htmlFor="master-volume" className="sr-only">
            Master volume
          </label>
          <input
            id="master-volume"
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={masterVolume}
            onChange={(event) => changeMaster(Number(event.target.value))}
            className="w-[108px]"
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {split.stems.map((stem) => (
          <StemChannelStrip
            key={stem.id}
            stem={stem}
            peaks={peaks[stem.id]}
            muted={channels[stem.id]?.muted || false}
            soloed={soloId === stem.id}
            soloActive={soloId !== null}
            gainDb={channels[stem.id]?.gainDb ?? 0}
            progress={progressRatio}
            onToggleMute={() => toggleMute(stem.id)}
            onToggleSolo={() => toggleSolo(stem.id)}
            onGainChange={(db) => changeGain(stem.id, db)}
            downloadHref={mediaUrl(stem.filePath)}
          />
        ))}
      </div>

      {exported ? (
        <div className="flex items-center gap-3 rounded-lg border border-teal-300/30 bg-teal-300/[0.08] px-4 py-3">
          <Download size={16} className="shrink-0 text-teal-300" />
          <p className="min-w-0 flex-grow truncate text-[13px] text-teal-100">
            Rendered {exported.fileName} from {exported.stems.join(", ")}
          </p>
          <a
            href={mediaUrl(exported.filePath)}
            download
            className="shrink-0 text-[13px] font-semibold text-teal-200 underline"
          >
            Download
          </a>
        </div>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">{error}</div>
      ) : null}

      {limitedStems.length ? (
        <div className="flex items-start gap-2.5 rounded-lg border border-amber-300/28 bg-amber-300/[0.08] px-4 py-3">
          <TriangleAlert size={16} className="mt-0.5 shrink-0 text-amber-300" />
          <p className="text-[13px] leading-6 text-amber-100/90">
            Separated stems are not studio multitracks. {limitedStems.join(" and ")} in particular carries bleed from
            other instruments — good for playing along, not for mixing.
          </p>
        </div>
      ) : null}
    </div>
  );
}
