import { Download, Drum, Guitar, Mic2, Music2, Piano, TriangleAlert, Waves } from "lucide-react";

const STEM_ICONS = {
  Vocals: Mic2,
  Drums: Drum,
  Bass: Waves,
  Guitar: Guitar,
  Piano: Piano,
  Other: Music2,
};

const QUALITY_HINTS = {
  limited: "Separation quality is limited for this source",
  fair: "Some bleed from neighbouring instruments",
};

function Waveform({ peaks, color, dimmed, progress }) {
  if (!peaks?.length) {
    return <div className="h-10 w-full rounded-md bg-white/[0.04]" />;
  }

  const width = 400;
  const height = 40;
  const mid = height / 2;
  const step = width / peaks.length;

  const top = peaks.map((v, i) => `${(i * step).toFixed(1)},${(mid - v * mid * 0.9).toFixed(1)}`);
  const bottom = peaks
    .map((v, i) => `${(i * step).toFixed(1)},${(mid + v * mid * 0.9).toFixed(1)}`)
    .reverse();

  return (
    <div className="relative h-10 w-full overflow-hidden rounded-md">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="h-full w-full"
        aria-hidden="true"
      >
        <polygon
          points={`${top.join(" ")} ${bottom.join(" ")}`}
          fill={dimmed ? "rgba(113,113,122,0.25)" : color}
          fillOpacity={dimmed ? 1 : 0.65}
        />
      </svg>
      <div
        className="pointer-events-none absolute inset-y-0 left-0 border-r border-white/40 bg-white/[0.06]"
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
  const StemIcon = STEM_ICONS[stem.label] ?? Music2;

  const iconStyle = dimmed
    ? { color: "#71717a", backgroundColor: "rgba(255,255,255,0.03)", borderColor: "rgba(255,255,255,0.07)" }
    : { color: stem.color, backgroundColor: `${stem.color}1a`, borderColor: `${stem.color}44` };

  return (
    <div
      className={`flex flex-col gap-2.5 rounded-xl border px-3.5 py-3 transition sm:flex-row sm:items-center sm:gap-3 sm:py-2.5 ${
        soloed
          ? "border-amber-300/40 bg-amber-300/[0.07]"
          : dimmed
            ? "border-white/[0.06] bg-white/[0.015]"
            : "border-white/10 bg-white/[0.045]"
      }`}
    >
      {/* ── Top row (mobile) / Left section (desktop) ─────────────── */}
      <div className="flex items-center gap-3">
        {/* Instrument icon badge */}
        <span
          className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border"
          style={iconStyle}
          aria-hidden="true"
        >
          <StemIcon size={17} strokeWidth={1.9} />
        </span>

        {/* Label + note */}
        <div className="min-w-0 flex-grow sm:w-28 sm:flex-none">
          <div
            className={`flex items-center gap-1 text-[13px] font-semibold leading-tight ${
              dimmed ? "text-zinc-500" : "text-zinc-100"
            }`}
          >
            <span className="truncate">{stem.label}</span>
            {stem.quality === "limited" ? (
              <TriangleAlert
                size={12}
                className="shrink-0 text-amber-300/80"
                aria-label={hint}
              />
            ) : null}
          </div>
          <div
            className="mt-0.5 truncate text-[11px] text-zinc-500"
            title={hint || stem.note}
          >
            {stem.note}
          </div>
        </div>

        {/* Mute + Solo */}
        <div className="flex shrink-0 gap-1.5">
          <button
            type="button"
            onClick={onToggleMute}
            aria-pressed={muted}
            aria-label={`${muted ? "Unmute" : "Mute"} ${stem.label}`}
            className={`h-8 w-8 rounded-lg border text-[12px] font-bold transition sm:h-9 sm:w-9 ${
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
            className={`h-8 w-8 rounded-lg border text-[12px] font-bold transition sm:h-9 sm:w-9 ${
              soloed
                ? "border-amber-300/60 bg-amber-300/20 text-amber-200"
                : "border-white/10 bg-white/[0.05] text-zinc-400 hover:text-white"
            }`}
          >
            S
          </button>
        </div>

        {/* Download — mobile only (right-aligned) */}
        <a
          href={downloadHref}
          download
          aria-label={`Download ${stem.label} stem`}
          className="ml-auto grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.05] text-zinc-400 transition hover:text-white sm:hidden"
        >
          <Download size={15} />
        </a>
      </div>

      {/* ── Bottom row (mobile) / Right section (desktop) ──────────── */}
      <div className="flex items-center gap-2 sm:flex-grow">
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
          onChange={(e) => onGainChange(Number(e.target.value))}
          className="flex-grow sm:w-[110px] sm:flex-none"
        />
        <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-zinc-500">
          {gainDb > 0 ? "+" : ""}
          {gainDb.toFixed(1)}
        </span>

        {/* Waveform — desktop only */}
        <div className="hidden min-w-0 flex-grow sm:block">
          <Waveform peaks={peaks} color={stem.color} dimmed={dimmed} progress={progress} />
        </div>

        {/* Download — desktop only */}
        <a
          href={downloadHref}
          download
          aria-label={`Download ${stem.label} stem`}
          className="hidden h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.05] text-zinc-400 transition hover:text-white sm:grid"
        >
          <Download size={15} />
        </a>
      </div>
    </div>
  );
}
