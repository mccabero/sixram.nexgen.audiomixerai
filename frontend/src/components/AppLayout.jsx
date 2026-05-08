import { CircleHelp, Mic2, MoonStar, SlidersHorizontal, Sparkles, SunMedium, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import sixramLogo from "../assets/sixram-band-studio-logo.png";
import { applyDocumentTheme, persistTheme, readStoredTheme } from "../utils/theme.js";
import Button from "./Button.jsx";
import GlobalJobStatus from "./GlobalJobStatus.jsx";

export default function AppLayout() {
  const [theme, setTheme] = useState(() => readStoredTheme());
  const [timeGuideOpen, setTimeGuideOpen] = useState(false);
  const [vocalGuideOpen, setVocalGuideOpen] = useState(false);

  useEffect(() => {
    applyDocumentTheme(theme);
    persistTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (!timeGuideOpen && !vocalGuideOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") setTimeGuideOpen(false);
      if (event.key === "Escape") setVocalGuideOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [timeGuideOpen, vocalGuideOpen]);

  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <div className={`min-h-screen ${theme === "light" ? "theme-light" : "theme-dark"}`}>
      <header className="app-shell-header sticky top-0 z-30 border-b border-white/10 bg-zinc-950/78 shadow-[0_18px_50px_rgba(0,0,0,0.22)] backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1760px] items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <Link to="/" className="flex min-w-0 items-center gap-3">
            <span className="grid h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-lg border border-red-300/25 bg-zinc-950 shadow-[0_0_30px_rgba(239,68,68,0.18)] sm:h-14 sm:w-14">
              <img
                src={sixramLogo}
                alt="Sixram Band Studio logo"
                className="h-full w-full object-contain"
              />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold uppercase tracking-[0.16em] text-teal-100/80">
                Sixram Band Studio
              </span>
              <span className="block truncate text-lg font-semibold text-white">Studio Pilot AI</span>
            </span>
          </Link>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              className="min-h-11 px-3"
              onClick={() => setTimeGuideOpen(true)}
              aria-label="Open workflow time guide"
              title="Workflow time guide"
            >
              <CircleHelp size={17} />
              <span className="hidden md:inline">Time guide</span>
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="min-h-11 px-3"
              onClick={() => setVocalGuideOpen(true)}
              aria-label="Open vocal effects and mixing guide"
              title="Vocal effects and mixing guide"
            >
              <Mic2 size={17} />
              <span className="hidden md:inline">Vocal guide</span>
              <span className="md:hidden">Vocal</span>
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="theme-toggle min-h-11 px-3 sm:w-auto"
              onClick={() => setTheme(nextTheme)}
              aria-label={`Switch to ${nextTheme} mode`}
              title={`Switch to ${nextTheme} mode`}
            >
              {theme === "dark" ? <SunMedium size={17} /> : <MoonStar size={17} />}
              <span className="hidden sm:inline">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
              <span className="sm:hidden">{theme === "dark" ? "Light" : "Dark"}</span>
            </Button>
          </div>
        </div>
      </header>
      {timeGuideOpen ? <WorkflowTimeGuide onClose={() => setTimeGuideOpen(false)} /> : null}
      {vocalGuideOpen ? <VocalSunoGuide onClose={() => setVocalGuideOpen(false)} /> : null}
      <GlobalJobStatus />
      <main className="mx-auto max-w-[1760px] px-4 py-7 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}

const vocalEnhancementGuide = [
  ["Preset", "Suno Clean Dry", "Clean, forward vocal tone without printed reverb or delay."],
  ["FX Style", "Dry", "Keep space out of the stem so the mixer can control it later."],
  ["Pitch", "Natural or Medium", "Use the song key/scale when known; keep humanize above 25%."],
  ["Tone", "Presence + Air", "Add clarity first, then body only if the vocal gets thin."],
];

const vocalMixGuide = [
  ["Level", "+1.5 to +3 dB vocal boost", "Bring the lead forward without making it feel detached."],
  ["Space", "Mixer reverb/delay later", "Start subtle, then widen only after the dry vocal is stable."],
  ["Width", "Lead centered, backing wider", "Avoid wide lead vocals unless the song intentionally needs that sound."],
  ["Check", "A/B source vs enhanced", "Re-render any stem where settings changed before final mix/master."],
];

function VocalSunoGuide({ onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 px-4 py-6 backdrop-blur-md sm:items-center" role="presentation" onMouseDown={onClose}>
      <section
        className="w-full max-w-4xl rounded-lg border border-white/10 bg-zinc-950 p-5 shadow-[0_28px_90px_rgba(0,0,0,0.48)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="vocal-suno-guide-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-teal-100/75">Vocal Reference</p>
            <h2 id="vocal-suno-guide-title" className="mt-1 text-2xl font-semibold text-white">Suno-Style Vocal Stem Guide</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
              Aim for a clean, dry, centered vocal first. Add reverb, delay, and width later in the mixer so the final vocal stays clear and controllable.
            </p>
          </div>
          <button
            type="button"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.06] text-zinc-300 transition hover:bg-white/[0.1] hover:text-white"
            onClick={onClose}
            aria-label="Close vocal guide"
          >
            <X size={18} />
          </button>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-3">
          <GuideCallout icon={Mic2} label="Step 4" title="Enhance dry" detail="Use Suno Clean Dry with FX Style set to Dry." />
          <GuideCallout icon={SlidersHorizontal} label="Step 5" title="Mix the space" detail="Add reverb, delay, and width after the stem is rendered." />
          <GuideCallout icon={Sparkles} label="Step 6" title="Master last" detail="Master only after the vocal sits naturally in the mix." />
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <GuideTable title="Vocal Enhancer Settings" rows={vocalEnhancementGuide} />
          <GuideTable title="Mixer Moves" rows={vocalMixGuide} />
        </div>

        <div className="mt-5 rounded-lg border border-amber-300/20 bg-amber-300/10 p-4">
          <p className="text-sm font-semibold text-amber-100">Avoid printing too much effect into the vocal stem.</p>
          <p className="mt-1 text-sm leading-6 text-zinc-300">
            Non-dry FX can sound good, but they are harder to undo. For the safest Suno-like workflow: Dry enhancement first, mixer FX later.
          </p>
        </div>
      </section>
    </div>
  );
}

function GuideCallout({ icon: Icon, label, title, detail }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.04] p-4">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-teal-300/20 bg-teal-300/10 text-teal-100">
          <Icon size={18} />
        </span>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-100/75">{label}</p>
          <h3 className="mt-1 font-semibold text-white">{title}</h3>
          <p className="mt-1 text-sm leading-5 text-zinc-400">{detail}</p>
        </div>
      </div>
    </div>
  );
}

function GuideTable({ title, rows }) {
  return (
    <div className="overflow-hidden rounded-lg border border-white/10">
      <div className="border-b border-white/10 bg-white/[0.055] px-3 py-3">
        <h3 className="font-semibold text-white">{title}</h3>
      </div>
      {rows.map(([setting, value, detail]) => (
        <div key={setting} className="grid gap-1 border-b border-white/10 bg-white/[0.025] px-3 py-3 last:border-b-0 sm:grid-cols-[120px_minmax(150px,0.8fr)_1fr] sm:items-center">
          <p className="text-sm font-semibold text-zinc-100">{setting}</p>
          <p className="text-sm font-semibold text-teal-100">{value}</p>
          <p className="text-sm leading-6 text-zinc-400">{detail}</p>
        </div>
      ))}
    </div>
  );
}

const workflowTimeRows = [
  ["Upload", "Seconds to 2 min", "Depends mostly on file size."],
  ["Analyze / detect", "1-3 min", "Reads each stem and prepares workflow suggestions."],
  ["Cleaning", "2-10 min", "Longer with many stems or stronger cleanup."],
  ["Vocal enhancement", "1-5 min per vocal", "Pitch, denoise, and leveling add the most time."],
  ["Mixer render", "30 sec to 2 min", "Usually quick after stems are prepared."],
  ["Master / export", "1-4 min", "Depends on song length and export format."],
];

function WorkflowTimeGuide({ onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 px-4 py-6 backdrop-blur-md sm:items-center" role="presentation" onMouseDown={onClose}>
      <section
        className="w-full max-w-3xl rounded-lg border border-white/10 bg-zinc-950 p-5 shadow-[0_28px_90px_rgba(0,0,0,0.48)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="workflow-time-guide-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-teal-100/75">Reference</p>
            <h2 id="workflow-time-guide-title" className="mt-1 text-2xl font-semibold text-white">Workflow Time Guide</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">
              A normal 3-5 minute song usually takes 10-25 minutes from upload to master when cleaning and vocal enhancement are included.
            </p>
          </div>
          <button
            type="button"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.06] text-zinc-300 transition hover:bg-white/[0.1] hover:text-white"
            onClick={onClose}
            aria-label="Close workflow time guide"
          >
            <X size={18} />
          </button>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <TimeEstimate label="Fast path" value="3-8 min" detail="No cleaning or vocal polish." />
          <TimeEstimate label="Full workflow" value="10-25 min" detail="Typical clean, vocals, mix, master." />
          <TimeEstimate label="Heavy repair" value="30-45+ min" detail="Many stems or dirty vocals." />
        </div>

        <div className="mt-5 overflow-hidden rounded-lg border border-white/10">
          {workflowTimeRows.map(([step, time, detail]) => (
            <div key={step} className="grid gap-1 border-b border-white/10 bg-white/[0.035] px-3 py-3 last:border-b-0 sm:grid-cols-[150px_150px_1fr] sm:items-center">
              <p className="text-sm font-semibold text-white">{step}</p>
              <p className="text-sm font-semibold text-teal-100">{time}</p>
              <p className="text-sm leading-6 text-zinc-400">{detail}</p>
            </div>
          ))}
        </div>

        <p className="mt-4 text-sm leading-6 text-zinc-400">
          Biggest time factors: song length, number of stems, cleaning strength, number of vocal stems, pitch processing, and local CPU speed.
        </p>
      </section>
    </div>
  );
}

function TimeEstimate({ label, value, detail }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-3">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-sm leading-5 text-zinc-400">{detail}</p>
    </div>
  );
}
