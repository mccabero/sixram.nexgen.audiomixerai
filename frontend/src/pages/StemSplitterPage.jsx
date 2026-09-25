import {
  AudioLines,
  Clock3,
  Link2,
  Loader2,
  Music4,
  RotateCcw,
  ServerOff,
  SlidersHorizontal,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  cancelSplit,
  createChordSheet,
  createSplit,
  deleteSplit,
  getSplitEnvironment,
  listChordSheets,
  listSplits,
  retrySplit,
} from "../api.js";
import Button from "../components/Button.jsx";
import { formatDateTime } from "../utils/format.js";

const ACTIVE_STATUSES = new Set(["Pending", "Downloading", "Preparing", "Separating", "Finishing"]);

const STEM_SETS = [
  { value: "6", label: "6 stems", detail: "Vocals · Drums · Bass · Guitar · Piano · Other" },
  { value: "4", label: "4 stems", detail: "Vocals · Drums · Bass · Other — faster, cleaner" },
];

function formatDuration(seconds) {
  if (!seconds) return "--:--";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}

function StatusPill({ split }) {
  const active = ACTIVE_STATUSES.has(split.status);
  const tone =
    split.status === "Ready"
      ? "border-teal-300/35 bg-teal-300/10 text-teal-100"
      : split.status === "Failed"
        ? "border-rose-300/35 bg-rose-400/10 text-rose-200"
        : active
          ? "border-amber-300/35 bg-amber-300/10 text-amber-100"
          : "border-white/12 bg-white/[0.05] text-zinc-400";

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-bold uppercase tracking-[0.1em] ${tone}`}>
      {active ? <Loader2 size={12} className="animate-spin" /> : null}
      {split.status}
    </span>
  );
}

export default function StemSplitterPage() {
  const navigate = useNavigate();
  const [splits, setSplits] = useState([]);
  const [environment, setEnvironment] = useState(null);
  const [url, setUrl] = useState("");
  const [stemSet, setStemSet] = useState("6");
  const [deep, setDeep] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // splitId -> sheetId, so the card knows whether to create or open.
  const [sheetsBySplit, setSheetsBySplit] = useState({});
  const [chordBusy, setChordBusy] = useState(null);
  const timerRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const rows = await listSplits();
      setSplits(rows);
      // Chord sheets live in their own list; mapping them by splitId here
      // keeps the Split model free of a back-reference it does not need.
      try {
        const sheets = await listChordSheets();
        const bySplit = {};
        for (const sheet of sheets) {
          if (sheet.status === "Ready" && !bySplit[sheet.splitId]) bySplit[sheet.splitId] = sheet.id;
        }
        setSheetsBySplit(bySplit);
      } catch {
        setSheetsBySplit({});
      }
      return rows;
    } catch (exc) {
      setError(exc.message);
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    getSplitEnvironment().then(setEnvironment).catch(() => setEnvironment(null));
    load();
  }, [load]);

  // Poll only while something is actually running.
  useEffect(() => {
    const hasActive = splits.some((split) => ACTIVE_STATUSES.has(split.status));
    if (!hasActive) {
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
      return undefined;
    }
    if (timerRef.current) return undefined;
    timerRef.current = window.setInterval(load, 3000);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
    };
  }, [splits, load]);

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const split = await createSplit({
        url: url.trim(),
        stemSet,
        depth: deep && stemSet === "6" ? "deep" : "standard",
      });
      setUrl("");
      const rows = await load();
      // A cached split comes back Ready, so go straight to the player.
      if (split.status === "Ready") {
        navigate(`/stem-splitter/${split.id}`);
      } else if (!rows.length) {
        setSplits([split]);
      }
    } catch (exc) {
      setError(exc.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function onCancel(splitId) {
    try {
      await cancelSplit(splitId);
      await load();
    } catch (exc) {
      setError(exc.message);
    }
  }

  async function onChordSheet(split) {
    setError("");
    const existing = sheetsBySplit[split.id];
    if (existing) {
      navigate(`/chord-sheets/${existing}`);
      return;
    }
    setChordBusy(split.id);
    try {
      const sheet = await createChordSheet({ splitId: split.id });
      navigate(`/chord-sheets/${sheet.id}`);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setChordBusy(null);
    }
  }

  async function onRetry(splitId) {
    setError("");
    try {
      await retrySplit(splitId);
      await load();
    } catch (exc) {
      setError(exc.message);
    }
  }

  async function onDelete(splitId) {
    try {
      await deleteSplit(splitId);
      await load();
    } catch (exc) {
      setError(exc.message);
    }
  }

  const envMissing = environment && !environment.ok;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-100/75">Standalone module</p>
        <h1 className="mt-1.5 text-3xl font-semibold text-white">Stem Splitter</h1>
        <p className="mt-1.5 max-w-3xl text-sm leading-6 text-zinc-400">
          Paste a link and split the song into isolated instrument tracks you can mute and play over. This is separate
          from your mix and mastering projects and never touches them.
        </p>
      </div>

      {envMissing ? (
        <div className="flex items-start gap-3 rounded-lg border border-amber-300/30 bg-amber-300/[0.08] px-4 py-3.5">
          <ServerOff size={18} className="mt-0.5 shrink-0 text-amber-300" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-amber-100">
              Splitting needs {environment.missing.join(", ")}
            </p>
            <p className="mt-1 text-[13px] leading-6 text-amber-100/80">
              Everything else in the app works without it. To enable splitting, run:
            </p>
            <code className="mt-1.5 block overflow-x-auto rounded border border-amber-300/20 bg-black/40 px-3 py-2 text-[12px] text-amber-100">
              {environment.installHint}
            </code>
          </div>
        </div>
      ) : null}

      <form
        onSubmit={onSubmit}
        className="flex flex-col gap-4 rounded-xl border border-white/10 bg-white/[0.035] px-6 py-5"
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex min-w-0 flex-grow flex-col gap-2">
            <label htmlFor="split-url" className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-100/75">
              Source URL
            </label>
            <div className="flex h-[52px] items-center gap-2.5 rounded-lg border border-teal-300/35 bg-black/45 px-3.5">
              <Link2 size={19} className="shrink-0 text-teal-300" />
              <input
                id="split-url"
                type="url"
                required
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://www.youtube.com/watch?v=..."
                className="h-full min-w-0 flex-grow border-0 bg-transparent text-[15px] text-zinc-100 outline-none placeholder:text-zinc-600"
              />
            </div>
          </div>
          <Button type="submit" disabled={submitting || !url.trim()} className="h-[52px] px-7 text-[15px]">
            {submitting ? <Loader2 size={17} className="animate-spin" /> : <AudioLines size={17} />}
            {submitting ? "Starting..." : "Split stems"}
          </Button>
        </div>

        <fieldset className="flex flex-col gap-2">
          <legend className="text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400">Stem set</legend>
          <div className="flex flex-wrap gap-2.5">
            {STEM_SETS.map((option) => (
              <label
                key={option.value}
                className={`flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg border px-4 py-2 transition ${
                  stemSet === option.value
                    ? "border-teal-300/55 bg-teal-300/[0.14]"
                    : "border-white/12 bg-white/[0.04] hover:border-white/20"
                }`}
              >
                <input
                  type="radio"
                  name="stemSet"
                  value={option.value}
                  checked={stemSet === option.value}
                  onChange={() => setStemSet(option.value)}
                  className="accent-teal-300"
                />
                <span>
                  <span className={`block text-[13px] font-semibold ${stemSet === option.value ? "text-teal-100" : "text-zinc-300"}`}>
                    {option.label}
                  </span>
                  <span className="block text-[11px] text-zinc-500">{option.detail}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <label
          className={`flex items-start gap-3 rounded-lg border px-4 py-3 transition ${
            stemSet !== "6"
              ? "cursor-not-allowed border-white/[0.06] bg-white/[0.015] opacity-50"
              : deep
                ? "cursor-pointer border-teal-300/45 bg-teal-300/[0.10]"
                : "cursor-pointer border-white/12 bg-white/[0.04] hover:border-white/20"
          }`}
        >
          <input
            type="checkbox"
            checked={deep && stemSet === "6"}
            disabled={stemSet !== "6"}
            onChange={(event) => setDeep(event.target.checked)}
            className="mt-0.5 h-4 w-4 accent-teal-300"
          />
          <span className="min-w-0">
            <span className="block text-[13px] font-semibold text-zinc-200">
              Deep split &mdash; better guitar and piano
            </span>
            <span className="mt-0.5 block text-[12px] leading-5 text-zinc-500">
              Separates 4 stems first, then pulls guitar and piano out of what is left instead of out of the full mix.
              Roughly doubles the time. Only applies to the 6-stem set.
            </span>
          </span>
        </label>

        <div className="flex items-start gap-2.5 rounded-lg border border-amber-300/25 bg-amber-300/[0.07] px-3.5 py-2.5">
          <Clock3 size={16} className="mt-0.5 shrink-0 text-amber-300" />
          <p className="text-[13px] leading-6 text-amber-100/90">
            Separation runs on the CPU, so expect several minutes per song and one split at a time. You can leave this
            page while it works.
          </p>
        </div>
      </form>

      {error ? (
        <div className="flex items-center gap-2.5 rounded-lg border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
          <TriangleAlert size={16} className="shrink-0" />
          {error}
        </div>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="text-[15px] font-semibold text-white">Splits</h2>

        {loading ? (
          <p className="text-sm text-zinc-500">Loading...</p>
        ) : splits.length === 0 ? (
          <div className="rounded-xl border border-dashed border-white/12 bg-white/[0.02] px-6 py-10 text-center">
            <SlidersHorizontal size={26} className="mx-auto text-zinc-600" />
            <p className="mt-3 text-sm font-semibold text-zinc-300">No splits yet</p>
            <p className="mt-1 text-[13px] text-zinc-500">Paste a link above to separate your first song.</p>
          </div>
        ) : (
          splits.map((split) => {
            const active = ACTIVE_STATUSES.has(split.status);
            const progress = split.job?.progress ?? 0;

            return (
              <div key={split.id} className="rounded-xl border border-white/10 bg-white/[0.03] px-5 py-4">
                <div className="flex flex-wrap items-center gap-4">
                  <div className="min-w-0 flex-grow">
                    <div className="flex items-center gap-2.5">
                      <h3 className="truncate text-[15px] font-semibold text-zinc-100">{split.title}</h3>
                      <StatusPill split={split} />
                    </div>
                    <p className="mt-1 truncate text-[12px] text-zinc-500">
                      {formatDuration(split.durationSeconds)} · {split.stemSet} stems ·{" "}
                      {split.depth === "deep" ? "deep · " : ""}
                      {split.modelName}
                      {split.completedAt ? ` · ${formatDateTime(split.completedAt)}` : ""}
                      {split.elapsedSeconds ? ` · took ${(split.elapsedSeconds / 60).toFixed(1)} min` : ""}
                    </p>
                  </div>

                  <div className="flex shrink-0 items-center gap-2">
                    {split.status === "Ready" ? (
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={chordBusy === split.id}
                        onClick={() => onChordSheet(split)}
                      >
                        {chordBusy === split.id ? <Loader2 size={15} className="animate-spin" /> : <Music4 size={15} />}
                        {sheetsBySplit[split.id] ? "Open chord sheet" : "Chord sheet"}
                      </Button>
                    ) : null}
                    {split.status === "Ready" ? (
                      <Button as={Link} to={`/stem-splitter/${split.id}`} variant="secondary">
                        Open player
                      </Button>
                    ) : null}
                    {!active && (split.status === "Failed" || split.status === "Cancelled") ? (
                      <Button type="button" variant="secondary" onClick={() => onRetry(split.id)}>
                        <RotateCcw size={15} />
                        Retry
                      </Button>
                    ) : null}
                    {active ? (
                      <Button type="button" variant="danger" onClick={() => onCancel(split.id)}>
                        <X size={15} />
                        Cancel
                      </Button>
                    ) : (
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => onDelete(split.id)}
                        aria-label={`Delete split ${split.title}`}
                      >
                        <Trash2 size={15} />
                      </Button>
                    )}
                  </div>
                </div>

                {active ? (
                  <div className="mt-3.5 flex flex-col gap-1.5">
                    <div className="h-2 overflow-hidden rounded-full bg-white/[0.07]">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-teal-500 to-teal-300 transition-[width] duration-500"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                    <p className="text-[12px] text-zinc-500">{split.job?.message}</p>
                  </div>
                ) : null}

                {split.status === "Failed" && split.error ? (
                  <p className="mt-3 rounded-lg border border-rose-300/25 bg-rose-400/[0.08] px-3 py-2 text-[12px] text-rose-100">
                    {split.error}
                  </p>
                ) : null}
              </div>
            );
          })
        )}
      </section>
    </div>
  );
}
