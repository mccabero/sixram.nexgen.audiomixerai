import { Download, TriangleAlert } from "lucide-react";

const QUALITY_HINTS = {
  limited: "Separation quality is limited for this source",
  fair: "Some bleed from neighbouring instruments",
};

function Waveform({ peaks, color, dimmed, progress }) {
  if (!peaks?.length) {
    return <div className="h-11 w-full rounded bg-white/[0.04]" />;
  }

  const width = 400;
  const height = 42;
  const mid = height / 2;
  const step = width / peaks.length;

  const top = peaks.map((value, index) => `${(index * step).toFixed(1)},${(mid - value * mid * 0.92).toFixed(1)}`);
  const bottom = peaks
    .map((value, index) => `${(index * step).toFixed(1)},${(mid + value * mid * 0.92).toFixed(1)}`)
    .reverse();

  return (
    <div className="relative h-11 w-full">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-full w-full" aria-hidden="true">
        <polygon points={`${top.join(" ")} ${bottom.join(" ")}`} fill={dimmed ? "rgba(113,113,122,0.3)" : color} />
      </svg>
      <div
        className="pointer-events-none absolute inset-y-0 left-0 border-r border-white/50 bg-white/[0.07]"
        style={{ width: `${Math.max(0, Math.min(100, progress * 100))}%` }}
      />
    </div>
  );
}

export default function StemChannelStrip({
  stem,
  peaks,
  muted,
  soloed,
  soloActive,
  gainDb,
  progress,
  onToggleMute,
  onToggleSolo,
  onGainChange,
  downloadHref,
}) {
  const dimmed = muted || (soloActive && !soloed);
  const hint = QUALITY_HINTS[stem.quality];

  return (
    <div
      className={`flex items-center gap-3 rounded-lg border px-4 py-2.5 transition ${
        soloed
          ? "border-amber-300/45 bg-amber-300/[0.07]"
          : dimmed
            ? "border-white/[0.06] bg-white/[0.015]"
            : "border-white/10 bg-white/[0.04]"
      }`}
    >
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ background: dimmed ? "#3f3f46" : stem.color }}
      />

      <div className="w-32 shrink-0">
        <div className={`flex items-center gap-1.5 text-sm font-semibold ${dimmed ? "text-zinc-500" : "text-zinc-100"}`}>
          {stem.label}
          {stem.quality === "limited" ? (
            <TriangleAlert size={13} className="text-amber-300/80" aria-hidden="true" />
          ) : null}
        </div>
        <div className="mt-0.5 truncate text-[11px] text-zinc-500" title={hint || stem.note}>
          {stem.note}
        </div>
      </div>

      <div className="flex shrink-0 gap-1.5">
        <button
          type="button"
          onClick={onToggleMute}
          aria-pressed={muted}
          aria-label={`${muted ? "Unmute" : "Mute"} ${stem.label}`}
          className={`h-9 w-9 rounded-lg border text-[13px] font-bold transition ${
            muted
              ? "border-rose-300/55 bg-rose-400/20 text-rose-200"
              : "border-white/10 bg-white/[0.05] text-zinc-400 hover:text-white"
          }`}
        >
          M
        </button>
        <button
          type="button"
          onClick={onToggleSolo}
          aria-pressed={soloed}
          aria-label={`${soloed ? "Unsolo" : "Solo"} ${stem.label}`}
          className={`h-9 w-9 rounded-lg border text-[13px] font-bold transition ${
            soloed
              ? "border-amber-300/60 bg-amber-300/20 text-amber-200"
              : "border-white/10 bg-white/[0.05] text-zinc-400 hover:text-white"
          }`}
        >
          S
        </button>
      </div>

      <div className="flex w-[150px] shrink-0 items-center gap-2">
        <label htmlFor={`fader-${stem.id}`} className="sr-only">
          {stem.label} level
        </label>
        <input
          id={`fader-${stem.id}`}
          type="range"
          min={-24}
          max={6}
          step={0.5}
          value={gainDb}
          onChange={(event) => onGainChange(Number(event.target.value))}
          className="w-[104px]"
        />
        <span className="w-9 text-right text-[11px] tabular-nums text-zinc-500">
          {gainDb > 0 ? "+" : ""}
          {gainDb.toFixed(1)}
        </span>
      </div>

      <div className="min-w-0 flex-grow">
        <Waveform peaks={peaks} color={stem.color} dimmed={dimmed} progress={progress} />
      </div>

      <a
        href={downloadHref}
        download
        aria-label={`Download ${stem.label} stem`}
        className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.05] text-zinc-400 transition hover:text-white"
      >
        <Download size={16} />
      </a>
    </div>
  );
}
