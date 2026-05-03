import { AudioLines, FolderKanban, Waves } from "lucide-react";
import { Link, Outlet } from "react-router-dom";
import GlobalJobStatus from "./GlobalJobStatus.jsx";

export default function AppLayout() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-white/10 bg-zinc-950/78 shadow-[0_18px_50px_rgba(0,0,0,0.22)] backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <Link to="/" className="flex min-w-0 items-center gap-3">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-lg border border-teal-200/25 bg-gradient-to-br from-teal-300/20 to-amber-200/10 text-teal-100 shadow-[0_0_28px_rgba(45,212,191,0.14)]">
              <AudioLines size={21} />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold uppercase tracking-[0.16em] text-teal-100/80">
                Sixram Band Studio
              </span>
              <span className="block truncate text-lg font-semibold text-white">Local Stem Mixer AI</span>
            </span>
          </Link>
          <div className="hidden items-center gap-2 sm:flex">
            <span className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.055] px-3 py-2 text-sm text-zinc-300">
              <Waves size={16} className="text-teal-200" />
              Workstation
            </span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-3 py-2 text-sm text-emerald-100">
              <FolderKanban size={16} />
              Local-only
            </span>
          </div>
        </div>
      </header>
      <GlobalJobStatus />
      <main className="mx-auto max-w-7xl px-4 py-7 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}
