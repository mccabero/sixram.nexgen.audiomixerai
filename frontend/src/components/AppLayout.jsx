import { CircleHelp, FolderKanban, MoonStar, SunMedium, Waves, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import sixramLogo from "../assets/sixram-band-studio-logo.png";
import { applyDocumentTheme, persistTheme, readStoredTheme } from "../utils/theme.js";
import Button from "./Button.jsx";
import GlobalJobStatus from "./GlobalJobStatus.jsx";

export default function AppLayout() {
  const [theme, setTheme] = useState(() => readStoredTheme());
  const [timeGuideOpen, setTimeGuideOpen] = useState(false);

  useEffect(() => {
    applyDocumentTheme(theme);
    persistTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (!timeGuideOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") setTimeGuideOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [timeGuideOpen]);

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
              className="theme-toggle min-h-11 px-3 sm:w-auto"
              onClick={() => setTheme(nextTheme)}
              aria-label={`Switch to ${nextTheme} mode`}
              title={`Switch to ${nextTheme} mode`}
            >
              {theme === "dark" ? <SunMedium size={17} /> : <MoonStar size={17} />}
              <span className="hidden sm:inline">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
              <span className="sm:hidden">{theme === "dark" ? "Light" : "Dark"}</span>
            </Button>
            <span className="hidden items-center gap-2 rounded-lg border border-white/10 bg-white/[0.055] px-3 py-2 text-sm text-zinc-300 sm:inline-flex">
              <Waves size={16} className="text-teal-200" />
              Workstation
            </span>
            <span className="hidden items-center gap-2 rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-3 py-2 text-sm text-emerald-100 sm:inline-flex">
              <FolderKanban size={16} />
              Local-only
            </span>
          </div>
        </div>
      </header>
      {timeGuideOpen ? <WorkflowTimeGuide onClose={() => setTimeGuideOpen(false)} /> : null}
      <GlobalJobStatus />
      <main className="mx-auto max-w-[1760px] px-4 py-7 sm:px-6 lg:px-8">
        <Outlet />
      </main>
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
