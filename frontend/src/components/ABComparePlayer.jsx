import { Pause, Play, Repeat, SkipBack } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import WaveformPreview from "./WaveformPreview.jsx";
import { formatDuration, formatLufs } from "../utils/format.js";

// Convert a LUFS delta into a linear volume multiplier (0..1). We can only
// attenuate with the HTML audio element, so the louder track is turned down to
// match the quieter one; the quieter track stays at unity.
function matchGains(lufsA, lufsB, enabled) {
  if (!enabled || !Number.isFinite(lufsA) || !Number.isFinite(lufsB)) return { a: 1, b: 1 };
  const quieter = Math.min(lufsA, lufsB);
  return {
    a: Math.min(1, 10 ** ((quieter - lufsA) / 20)),
    b: Math.min(1, 10 ** ((quieter - lufsB) / 20)),
  };
}

function isTypingTarget(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

export default function ABComparePlayer({ options, compareA, compareB, setCompareA, setCompareB, selectedA, selectedB }) {
  const audioA = useRef(null);
  const audioB = useRef(null);
  const [active, setActive] = useState("A");
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [loop, setLoop] = useState(false);
  const [loudnessMatch, setLoudnessMatch] = useState(false);

  const lufsA = selectedA?.version?.integratedLufs;
  const lufsB = selectedB?.version?.integratedLufs;
  const canLoudnessMatch = Number.isFinite(lufsA) && Number.isFinite(lufsB);

  const gains = useMemo(() => matchGains(lufsA, lufsB, loudnessMatch && canLoudnessMatch), [lufsA, lufsB, loudnessMatch, canLoudnessMatch]);

  const activeRef = active === "A" ? audioA : audioB;
  const inactiveRef = active === "A" ? audioB : audioA;

  // Keep element volumes in sync with the loudness-match setting.
  useEffect(() => {
    if (audioA.current) audioA.current.volume = gains.a;
    if (audioB.current) audioB.current.volume = gains.b;
  }, [gains, selectedA?.url, selectedB?.url]);

  // Reset transport when either source changes.
  useEffect(() => {
    setPlaying(false);
    setPosition(0);
    setDuration(0);
    if (audioA.current) audioA.current.pause();
    if (audioB.current) audioB.current.pause();
  }, [selectedA?.url, selectedB?.url]);

  const play = useCallback(() => {
    const el = activeRef.current;
    if (!el || !el.src) return;
    el.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }, [activeRef]);

  const pause = useCallback(() => {
    audioA.current?.pause();
    audioB.current?.pause();
    setPlaying(false);
  }, []);

  const togglePlay = useCallback(() => {
    if (playing) pause();
    else play();
  }, [playing, play, pause]);

  const restart = useCallback(() => {
    if (audioA.current) audioA.current.currentTime = 0;
    if (audioB.current) audioB.current.currentTime = 0;
    setPosition(0);
  }, []);

  // Switch which track is audible, preserving the exact playback position.
  const switchTo = useCallback(
    (next) => {
      if (next === active) return;
      const current = activeRef.current;
      const other = inactiveRef.current;
      const time = current?.currentTime ?? 0;
      const wasPlaying = playing;
      current?.pause();
      if (other) {
        try {
          other.currentTime = time;
        } catch {
          /* seeking before metadata is ready — ignore */
        }
        if (wasPlaying) other.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      }
      setActive(next);
    },
    [active, activeRef, inactiveRef, playing]
  );

  const toggleActive = useCallback(() => switchTo(active === "A" ? "B" : "A"), [active, switchTo]);

  // Keyboard: space = play/pause, A/B = switch. Ignored while typing.
  useEffect(() => {
    const onKey = (event) => {
      if (isTypingTarget(event.target)) return;
      if (event.code === "Space") {
        // Let space activate a focused button/link instead of hijacking transport.
        if (event.target?.tagName === "BUTTON" || event.target?.tagName === "A") return;
        event.preventDefault();
        togglePlay();
      } else if (event.key === "a" || event.key === "A") {
        switchTo("A");
      } else if (event.key === "b" || event.key === "B") {
        switchTo("B");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [togglePlay, switchTo]);

  const onTimeUpdate = () => {
    const el = activeRef.current;
    if (!el) return;
    setPosition(el.currentTime || 0);
    if (Number.isFinite(el.duration)) setDuration(el.duration);
  };

  const onEnded = () => {
    if (loop) {
      restart();
      play();
    } else {
      setPlaying(false);
    }
  };

  const onSeek = (value) => {
    const time = Number(value);
    if (audioA.current) audioA.current.currentTime = time;
    if (audioB.current) audioB.current.currentTime = time;
    setPosition(time);
  };

  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-4">
      <audio ref={audioA} src={selectedA?.url || undefined} preload="metadata" onTimeUpdate={active === "A" ? onTimeUpdate : undefined} onEnded={active === "A" ? onEnded : undefined} />
      <audio ref={audioB} src={selectedB?.url || undefined} preload="metadata" onTimeUpdate={active === "B" ? onTimeUpdate : undefined} onEnded={active === "B" ? onEnded : undefined} />

      <div className="grid gap-3 sm:grid-cols-2">
        <SourcePicker label="A" options={options} selected={compareA} onChange={setCompareA} active={active === "A"} onActivate={() => switchTo("A")} item={selectedA} variant="teal" lufs={lufsA} />
        <SourcePicker label="B" options={options} selected={compareB} onChange={setCompareB} active={active === "B"} onActivate={() => switchTo("B")} item={selectedB} variant="amber" lufs={lufsB} />
      </div>

      <div className="mt-4 flex flex-col gap-3 rounded-lg border border-white/10 bg-white/[0.03] p-3">
        <div className="flex items-center gap-3">
          <button
            type="button"
            aria-label={playing ? "Pause" : "Play"}
            onClick={togglePlay}
            className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-teal-200/30 bg-teal-300/20 text-teal-50 transition hover:bg-teal-300/30"
          >
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <button type="button" aria-label="Restart" onClick={restart} className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-white/10 bg-black/25 text-zinc-200 transition hover:bg-white/[0.08]">
            <SkipBack size={16} />
          </button>
          <button
            type="button"
            onClick={toggleActive}
            className="flex h-11 flex-1 items-center justify-center gap-2 rounded-lg border border-white/10 bg-black/25 text-sm font-bold uppercase tracking-[0.14em] text-white transition hover:bg-white/[0.08]"
            title="Switch between A and B at the same position (keyboard: A / B)"
          >
            <span className={active === "A" ? "text-teal-200" : "text-zinc-500"}>A</span>
            <Repeat size={15} className="text-zinc-400" />
            <span className={active === "B" ? "text-amber-200" : "text-zinc-500"}>B</span>
          </button>
        </div>

        <div className="flex items-center gap-3">
          <span className="w-10 shrink-0 text-right text-xs tabular-nums text-zinc-400">{formatDuration(position)}</span>
          <input type="range" min={0} max={duration || 0} step={0.01} value={Math.min(position, duration || 0)} onChange={(event) => onSeek(event.target.value)} className="w-full accent-teal-300" aria-label="Seek" />
          <span className="w-10 shrink-0 text-xs tabular-nums text-zinc-500">{formatDuration(duration)}</span>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-zinc-500">
            Now playing <span className={active === "A" ? "font-semibold text-teal-200" : "font-semibold text-amber-200"}>{active === "A" ? selectedA?.label || "A" : selectedB?.label || "B"}</span>
          </span>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-xs text-zinc-400">
              <input type="checkbox" checked={loop} onChange={(event) => setLoop(event.target.checked)} className="accent-teal-300" />
              Loop
            </label>
            <label className={`flex items-center gap-2 text-xs ${canLoudnessMatch ? "text-zinc-400" : "cursor-not-allowed text-zinc-600"}`} title={canLoudnessMatch ? "Attenuate the louder track to match loudness" : "Both versions need LUFS metrics"}>
              <input type="checkbox" checked={loudnessMatch && canLoudnessMatch} disabled={!canLoudnessMatch} onChange={(event) => setLoudnessMatch(event.target.checked)} className="accent-teal-300" />
              Loudness match
            </label>
          </div>
        </div>
      </div>

      <p className="mt-3 text-center text-[11px] text-zinc-600">Space play/pause · A / B switch instantly at the same spot</p>
    </div>
  );
}

function SourcePicker({ label, options, selected, onChange, active, onActivate, item, variant, lufs }) {
  const accent = variant === "amber" ? "border-amber-300/40 bg-amber-300/[0.06]" : "border-teal-300/40 bg-teal-300/[0.06]";
  return (
    <button type="button" onClick={onActivate} className={`block rounded-lg border p-3 text-left transition ${active ? accent : "border-white/10 bg-black/20 hover:bg-white/[0.04]"}`}>
      <label className="block" onClick={(event) => event.stopPropagation()}>
        <span className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">
          <span>Compare {label}</span>
          {Number.isFinite(lufs) ? <span className="normal-case tracking-normal text-zinc-400">{formatLufs(lufs)}</span> : null}
        </span>
        <select value={selected} onChange={(event) => onChange(event.target.value)} className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white">
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {item?.url ? (
        <div className="mt-3">
          <WaveformPreview src={item.url} variant={variant} />
        </div>
      ) : null}
    </button>
  );
}
