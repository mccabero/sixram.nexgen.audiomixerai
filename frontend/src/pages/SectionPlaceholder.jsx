import { ArrowLeft, BarChart3, Download, Eraser, SlidersHorizontal, Sparkles } from "lucide-react";
import { Link, useParams } from "react-router-dom";

const sections = {
  analyze: {
    title: "Analyze",
    phase: "Phase 2",
    icon: BarChart3,
    description: "Audio metadata, loudness, spectral balance, silence checks, and problem detection will live here.",
  },
  mixer: {
    title: "Mixer",
    phase: "Phase 3",
    icon: SlidersHorizontal,
    description: "Automatic track balancing, panning, gain staging, and mix settings will live here.",
  },
  cleaning: {
    title: "Cleaning",
    phase: "Phase 4",
    icon: Eraser,
    description: "Stem cleanup, hum removal, noise reduction, and cleaned preview management will live here.",
  },
  mastering: {
    title: "Mastering",
    phase: "Phase 6",
    icon: Sparkles,
    description: "Final loudness targeting, EQ polish, compression, limiting, and master preview live on the Export page.",
  },
  export: {
    title: "Export",
    phase: "Phase 6",
    icon: Download,
    description: "WAV, MP3, FLAC, report, and backup management live on the Export page.",
  },
};

export default function SectionPlaceholder() {
  const { projectId, section } = useParams();
  const config = sections[section] || sections.analyze;
  const Icon = config.icon;

  return (
    <div>
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-zinc-300 hover:text-white">
        <ArrowLeft size={16} />
        Back to project
      </Link>
      <section className="mt-5 rounded-lg border border-white/10 bg-white/[0.045] p-8 shadow-glow">
        <span className="grid h-14 w-14 place-items-center rounded-lg border border-teal-300/20 bg-teal-300/10 text-teal-200">
          <Icon size={25} />
        </span>
        <p className="mt-6 text-sm font-semibold uppercase tracking-[0.18em] text-amber-100/80">{config.phase}</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">{config.title}</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">{config.description}</p>
        <div className="mt-6 rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-300">
          This page is reserved for a later phase while analysis, auto-balance, and rough mix preview are built first.
        </div>
      </section>
    </div>
  );
}
