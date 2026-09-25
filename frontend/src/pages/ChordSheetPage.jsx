import { ArrowLeft, Download, Loader2, Music4, RotateCcw, Search, Trash2, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  attachChordSheetLyrics,
  cancelChordSheet,
  clearChordSheetLyrics,
  exportChordSheet,
  getChordSheet,
  getChordSheetAnalysis,
  retryChordSheet,
  updateChordSheetView,
} from "../api.js";
import Button from "../components/Button.jsx";

const ACTIVE_STATUSES = new Set(["Pending", "Separating", "Analysing", "Finishing"]);

const TUNINGS = [
  { value: 0, label: "E Standard" },
  { value: 1, label: "Eb Standard (half step down)" },
  { value: 2, label: "D Standard (whole step down)" },
  { value: 3, label: "C# Standard" },
];

function formatTime(seconds) {
  if (seconds === null || seconds === undefined) return "--:--";
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function Metric({ label, value, hint }) {
  return (
    <div>
      <div className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-zinc-500">{label}</div>
      <div className="mt-0.5 text-[15px] font-bold text-zinc-50">
        {value}
        {hint ? <span className="ml-1.5 text-[12px] font-medium text-zinc-400">{hint}</span> : null}
      </div>
    </div>
  );
}

function Chord({ chord }) {
  // A chord the engine is unsure of is dimmed and underlined rather than
  // hidden: the point is to show where to look, not to pretend it is certain.
  const dim = chord.lowConfidence && !chord.edited;
  return (
    <span
      title={`${chord.label} · ${Math.round(chord.confidence * 100)}% confident · ${formatTime(chord.startSeconds)}`}
      className={
        dim
          ? "border-b border-dotted border-teal-300/55 text-teal-300/50"
          : "text-teal-300"
      }
    >
      {chord.label}
    </span>
  );
}

// Chords sit above the syllable they land on. Rendering them as one
// whitespace-preserving line keeps the alignment exact without measuring text.
function ChordLine({ chords }) {
  if (!chords.length) return null;
  let column = 0;
  const parts = [];
  chords.forEach((chord, index) => {
    const pad = Math.max(chord.charOffset - column, column === 0 ? 0 : 1);
    if (pad > 0) {
      parts.push(<span key={`pad-${index}`}>{" ".repeat(pad)}</span>);
      column += pad;
    }
    parts.push(<Chord key={`chord-${index}`} chord={chord} />);
    column += chord.label.length;
  });
  return <div className="whitespace-pre font-mono text-[15px] font-semibold leading-snug">{parts}</div>;
}

function LyricRow({ row }) {
  if (row.instrumental) {
    return (
      <div className="flex items-baseline gap-3 py-1">
        <span className="w-10 shrink-0 text-right font-mono text-[11px] tabular-nums text-zinc-600">
          {formatTime(row.startSeconds)}
        </span>
        <div className="rounded-md border border-white/[0.07] bg-white/[0.02] px-3 py-1">
          <ChordLine chords={row.chords} />
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-3 py-1.5">
      <span className="mt-5 w-10 shrink-0 text-right font-mono text-[11px] tabular-nums text-zinc-600">
        {formatTime(row.startSeconds)}
      </span>
      <div className="min-w-0">
        <ChordLine chords={row.chords} />
        <div className="whitespace-pre font-mono text-[15px] leading-snug text-zinc-200">{row.text}</div>
      </div>
    </div>
  );
}

export default function ChordSheetPage() {
  const { sheetId } = useParams();
  const navigate = useNavigate();

  const [sheet, setSheet] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [transpose, setTranspose] = useState(0);
  const [capo, setCapo] = useState(0);
  const [tuningShift, setTuningShift] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState("chart");
  const [pasting, setPasting] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [lyricBusy, setLyricBusy] = useState(false);
  const timerRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const row = await getChordSheet(sheetId);
      setSheet(row);
      if (row.status === "Ready" && !analysis) {
        setAnalysis(await getChordSheetAnalysis(sheetId));
        setTranspose(row.transpose ?? 0);
        setCapo(row.capo ?? 0);
        setTuningShift(row.tuningShift ?? 0);
      }
      return row;
    } catch (exc) {
      setError(exc.message);
      return null;
    }
  }, [sheetId, analysis]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll only while the analysis is actually running.
  useEffect(() => {
    if (!sheet || !ACTIVE_STATUSES.has(sheet.status)) {
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
      return undefined;
    }
    if (timerRef.current) return undefined;
    timerRef.current = window.setInterval(load, 2000);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
    };
  }, [sheet, load]);

  // Transpose, capo and tuning are a re-spelling on the server, never a
  // re-analysis, so they come back immediately.
  const applyView = useCallback(
    async (next) => {
      setError("");
      setBusy(true);
      try {
        setAnalysis(await updateChordSheetView(sheetId, next));
        setTranspose(next.transpose);
        setCapo(next.capo);
        setTuningShift(next.tuningShift);
      } catch (exc) {
        setError(exc.message);
      } finally {
        setBusy(false);
      }
    },
    [sheetId],
  );

  async function onFindLyrics() {
    setError("");
    setNotice("");
    setLyricBusy(true);
    try {
      const result = await attachChordSheetLyrics(sheetId, { source: "auto" });
      if (result.found === false) {
        setNotice(result.message);
        setPasting(true);
      } else {
        setAnalysis(result);
        setTab("lyrics");
        await load();
      }
    } catch (exc) {
      setError(exc.message);
    } finally {
      setLyricBusy(false);
    }
  }

  async function onPasteLyrics() {
    setError("");
    setNotice("");
    setLyricBusy(true);
    try {
      setAnalysis(await attachChordSheetLyrics(sheetId, { source: "manual", text: pasteText }));
      setPasting(false);
      setPasteText("");
      setTab("lyrics");
      await load();
    } catch (exc) {
      setError(exc.message);
    } finally {
      setLyricBusy(false);
    }
  }

  async function onClearLyrics() {
    setError("");
    try {
      setAnalysis(await clearChordSheetLyrics(sheetId));
      setTab("chart");
      await load();
    } catch (exc) {
      setError(exc.message);
    }
  }

  async function onExport(format) {
    setError("");
    try {
      const file = await exportChordSheet(sheetId, format);
      setNotice(`Saved ${file.fileName} to the chord sheet's exports folder.`);
    } catch (exc) {
      setError(exc.message);
    }
  }

  if (!sheet) {
    return (
      <div className="rounded-xl border border-white/10 bg-white/[0.03] px-5 py-6 text-sm text-zinc-400">
        {error || "Loading chord sheet..."}
      </div>
    );
  }

  const active = ACTIVE_STATUSES.has(sheet.status);
  const tuning = analysis?.tuning ?? {};
  const view = analysis?.view;
  const summary = analysis?.summary ?? {};
  const lyricRows = analysis?.lyricRows ?? [];
  const hasLyrics = lyricRows.length > 0;
  const shown = hasLyrics && tab === "lyrics" ? "lyrics" : "chart";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2.5">
        <Link to="/stem-splitter" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-zinc-400 hover:text-white">
          <ArrowLeft size={15} />
          Stem Splitter
        </Link>
      </div>

      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-grow">
          <h1 className="truncate text-[22px] font-bold tracking-tight text-zinc-50">{sheet.title}</h1>
          <p className="mt-1 text-[12px] text-zinc-500">
            {formatTime(sheet.durationSeconds)}
            {sheet.elapsedSeconds ? ` · analysed in ${sheet.elapsedSeconds}s` : ""}
            {analysis?.stemsUsed?.length ? ` · ${analysis.stemsUsed.join(" + ")}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {sheet.status === "Ready" ? (
            <>
              <Button type="button" variant="secondary" onClick={() => onExport("chordpro")}>
                <Download size={15} />
                ChordPro
              </Button>
              <Button type="button" variant="secondary" onClick={() => onExport("txt")}>
                <Download size={15} />
                Text
              </Button>
            </>
          ) : null}
          {active ? (
            <Button type="button" variant="danger" onClick={() => cancelChordSheet(sheetId).then(load).catch((e) => setError(e.message))}>
              <X size={15} />
              Cancel
            </Button>
          ) : null}
          {sheet.status === "Failed" || sheet.status === "Cancelled" ? (
            <Button type="button" variant="secondary" onClick={() => retryChordSheet(sheetId).then(load).catch((e) => setError(e.message))}>
              <RotateCcw size={15} />
              Retry
            </Button>
          ) : null}
        </div>
      </div>

      {active ? (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-5 py-5">
          <div className="flex items-center gap-2.5 text-sm font-semibold text-zinc-200">
            <Loader2 size={16} className="animate-spin text-teal-300" />
            {sheet.job?.message || sheet.status}
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/[0.09]">
            <span className="block h-full rounded-full bg-teal-300 transition-all" style={{ width: `${sheet.job?.progress ?? 0}%` }} />
          </div>
        </div>
      ) : null}

      {sheet.error ? (
        <div className="flex items-start gap-2.5 rounded-lg border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
          <TriangleAlert size={16} className="mt-0.5 shrink-0" />
          {sheet.error}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-lg border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">{error}</div>
      ) : null}

      {notice ? (
        <div className="rounded-lg border border-teal-300/30 bg-teal-300/[0.08] px-4 py-3 text-[13px] text-teal-100">{notice}</div>
      ) : null}

      {analysis ? (
        <>
          <div className="flex flex-wrap items-stretch gap-2.5">
            <div className="flex items-center gap-5 rounded-xl border border-white/10 bg-white/[0.04] px-5 py-3">
              <Metric label="Key" value={view?.readingKey || analysis.key?.key} />
              <div className="w-px self-stretch bg-white/10" />
              <Metric label="Tempo" value={`${analysis.tempo} BPM`} />
              <div className="w-px self-stretch bg-white/10" />
              <Metric
                label="Reference"
                value={`${tuning.cents > 0 ? "+" : ""}${tuning.cents}¢`}
                hint={tuning.stable ? "stable" : "drifting"}
              />
            </div>

            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2.5">
              <span className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-zinc-500">Transpose</span>
              <button
                type="button"
                aria-label="Transpose down one semitone"
                disabled={busy || transpose <= -11}
                onClick={() => applyView({ transpose: transpose - 1, capo, tuningShift })}
                className="grid h-9 w-9 place-items-center rounded-lg border border-white/12 bg-white/[0.05] text-base font-bold text-zinc-200 hover:bg-white/[0.1] disabled:opacity-40"
              >
                &minus;
              </button>
              <span className="min-w-7 text-center text-[15px] font-bold tabular-nums text-zinc-50">
                {transpose > 0 ? `+${transpose}` : transpose}
              </span>
              <button
                type="button"
                aria-label="Transpose up one semitone"
                disabled={busy || transpose >= 11}
                onClick={() => applyView({ transpose: transpose + 1, capo, tuningShift })}
                className="grid h-9 w-9 place-items-center rounded-lg border border-white/12 bg-white/[0.05] text-base font-bold text-zinc-200 hover:bg-white/[0.1] disabled:opacity-40"
              >
                +
              </button>

              <div className="mx-1 h-6 w-px bg-white/10" />

              <label htmlFor="capo" className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-zinc-500">
                Capo
              </label>
              <select
                id="capo"
                value={capo}
                disabled={busy}
                onChange={(event) => applyView({ transpose, capo: Number(event.target.value), tuningShift })}
                className="min-h-9 rounded-lg border border-white/12 bg-[#121318] px-2.5 py-1 text-sm font-semibold text-zinc-200"
              >
                <option value={0}>None</option>
                {[1, 2, 3, 4, 5, 6, 7].map((fret) => (
                  <option key={fret} value={fret}>
                    Fret {fret}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2.5">
              <label htmlFor="tuning" className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-zinc-500">
                Tuning
              </label>
              <select
                id="tuning"
                value={tuningShift}
                disabled={busy}
                onChange={(event) => applyView({ transpose, capo, tuningShift: Number(event.target.value) })}
                className="min-h-9 rounded-lg border border-white/12 bg-[#121318] px-2.5 py-1 text-sm font-semibold text-zinc-200"
              >
                {TUNINGS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {tuning.suggested ? (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-4 py-3">
              <span className="text-[12.5px] leading-relaxed text-zinc-400">
                Standard tuning is assumed. {tuning.suggested.label} would put{" "}
                <strong className="font-semibold text-zinc-200">
                  {Math.round(tuning.suggested.openShapeCoverage * 100)}%
                </strong>{" "}
                of this song on open shapes, but a flat key scores the same way, so that is a suggestion and not a
                reading{tuning.lowestGuitarNote ? ` (lowest guitar note ${tuning.lowestGuitarNote})` : ""}.
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={() => applyView({ transpose, capo, tuningShift: tuning.suggested.semitoneShift })}
                className="ml-auto min-h-8 shrink-0 rounded-lg border border-white/12 bg-white/[0.05] px-3 py-1.5 text-[12.5px] font-bold text-zinc-200 hover:bg-white/[0.1] disabled:opacity-40"
              >
                Try it
              </button>
            </div>
          ) : null}

          {summary.lowConfidenceRatio > 0 ? (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-300/28 bg-amber-300/[0.08] px-4 py-3">
              <TriangleAlert size={16} className="shrink-0 text-amber-200" />
              <span className="text-[12.5px] leading-relaxed text-amber-100/90">
                <strong className="font-bold">
                  {Math.round(summary.lowConfidenceRatio * 100)}% of this sheet is low confidence.
                </strong>{" "}
                Dimmed chords with a dotted underline are the engine's best guess, not a reading it trusts.
              </span>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-2.5">
            {hasLyrics ? (
              <div className="flex items-center rounded-xl border border-white/10 bg-white/[0.04] p-1">
                <button
                  type="button"
                  onClick={() => setTab("chart")}
                  className={`min-h-8 rounded-lg px-4 py-1.5 text-[13px] font-bold transition ${
                    shown === "chart" ? "bg-teal-300/[0.14] text-teal-100" : "text-zinc-400 hover:text-white"
                  }`}
                >
                  Chart
                </button>
                <button
                  type="button"
                  onClick={() => setTab("lyrics")}
                  className={`min-h-8 rounded-lg px-4 py-1.5 text-[13px] font-bold transition ${
                    shown === "lyrics" ? "bg-teal-300/[0.14] text-teal-100" : "text-zinc-400 hover:text-white"
                  }`}
                >
                  Lyrics
                </button>
              </div>
            ) : null}

            {hasLyrics ? (
              <>
                <span className="text-[12px] text-zinc-500">
                  {analysis.lyrics?.source === "manual" ? "Pasted" : "From LRCLIB"}
                  {analysis.lyrics?.synced ? " · timed" : " · untimed"}
                </span>
                <button
                  type="button"
                  onClick={onClearLyrics}
                  className="ml-auto inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-3 py-1.5 text-[12.5px] font-semibold text-zinc-300 hover:bg-white/[0.1]"
                >
                  <Trash2 size={14} />
                  Remove lyrics
                </button>
              </>
            ) : (
              <>
                <Button type="button" variant="secondary" disabled={lyricBusy} onClick={onFindLyrics}>
                  {lyricBusy ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
                  Find lyrics
                </Button>
                <Button type="button" variant="secondary" disabled={lyricBusy} onClick={() => setPasting((on) => !on)}>
                  Paste lyrics
                </Button>
                <span className="text-[12px] text-zinc-500">
                  Looked up on LRCLIB by title and length. No match is normal for local or unreleased tracks - paste
                  them instead.
                </span>
              </>
            )}
          </div>

          {pasting && !hasLyrics ? (
            <div className="rounded-xl border border-white/10 bg-white/[0.03] px-5 py-4">
              <label htmlFor="paste" className="text-[12.5px] font-semibold text-zinc-300">
                Paste the lyrics. Plain lines work; LRC timestamps like [01:20.70] place the chords far more accurately.
              </label>
              <textarea
                id="paste"
                rows={8}
                value={pasteText}
                onChange={(event) => setPasteText(event.target.value)}
                className="mt-2.5 w-full rounded-lg border border-white/12 bg-[#0b0c11] px-3 py-2.5 font-mono text-[13px] text-zinc-200 outline-none focus:border-teal-300/50"
                placeholder={"[00:12.50] First line of the song\n[00:17.20] Second line of the song"}
              />
              <div className="mt-2.5 flex items-center gap-2">
                <Button type="button" disabled={lyricBusy || !pasteText.trim()} onClick={onPasteLyrics}>
                  {lyricBusy ? <Loader2 size={15} className="animate-spin" /> : null}
                  Use these lyrics
                </Button>
                <Button type="button" variant="ghost" onClick={() => setPasting(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}

          {shown === "lyrics" ? (
            <div className="rounded-xl border border-white/10 bg-white/[0.025] px-6 py-5">
              <div className="flex flex-col">
                {lyricRows.map((row) => (
                  <LyricRow key={row.index} row={row} />
                ))}
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-5 border-t border-white/[0.07] pt-4 text-[11.5px] text-zinc-500">
                <span className="inline-flex items-center gap-2">
                  <span className="font-mono text-teal-300">Bb</span> confident
                </span>
                <span className="inline-flex items-center gap-2">
                  <span className="border-b border-dotted border-teal-300/55 font-mono text-teal-300/50">Bb</span> check
                  this
                </span>
                <span className="ml-auto">
                  Chord positions within a line are proportional to time, so they land close rather than exact.
                </span>
              </div>
            </div>
          ) : (
          <div className="rounded-xl border border-white/10 bg-white/[0.025] px-6 py-5">
            <div className="flex flex-col gap-1.5 font-mono text-[15px] leading-relaxed">
              {(analysis.chart || []).map((row) => (
                <div key={row.row} className="flex items-center gap-3">
                  <span className="w-10 shrink-0 text-right text-[11px] tabular-nums text-zinc-600">
                    {formatTime(row.startSeconds)}
                  </span>
                  <div className="flex flex-grow items-stretch border-l border-white/10">
                    {row.bars.map((bar) => (
                      <div
                        key={bar.bar}
                        className="flex min-w-0 flex-grow basis-0 items-center gap-1.5 border-r border-white/10 px-3 py-1"
                      >
                        {bar.held ? (
                          <span className="text-zinc-700">%</span>
                        ) : (
                          bar.chords.map((chord) => <Chord key={`${chord.bar}-${chord.startSeconds}`} chord={chord} />)
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-5 border-t border-white/[0.07] pt-4 text-[11.5px] text-zinc-500">
              <span className="inline-flex items-center gap-2">
                <span className="font-mono text-teal-300">Bb</span> confident
              </span>
              <span className="inline-flex items-center gap-2">
                <span className="border-b border-dotted border-teal-300/55 font-mono text-teal-300/50">Bb</span> check this
              </span>
              <span className="inline-flex items-center gap-2">
                <span className="font-mono text-zinc-700">%</span> held from the bar before
              </span>
              <span className="ml-auto">
                {summary.chordCount} chords · {summary.distinctChords} distinct · mean confidence{" "}
                {summary.meanConfidence}
              </span>
            </div>
          </div>
          )}
        </>
      ) : null}

      {!analysis && !active && sheet.status !== "Failed" ? (
        <div className="rounded-xl border border-dashed border-white/12 bg-white/[0.02] px-6 py-10 text-center">
          <Music4 size={26} className="mx-auto text-zinc-600" />
          <p className="mt-3 text-sm font-semibold text-zinc-300">No analysis yet</p>
        </div>
      ) : null}
    </div>
  );
}
