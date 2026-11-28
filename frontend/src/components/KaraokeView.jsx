import { memo, useEffect, useMemo, useRef } from "react";

/**
 * Follow-along lyrics for singing to.
 *
 * Timing is line-level, because that is what LRC carries. The current line is
 * highlighted whole rather than wiped word by word - a word-level wipe would
 * need forced alignment against the vocal stem, which is a different feature
 * with a different cost.
 *
 * Everything here scales from a phone held at arm's length to a TV across a
 * room. Viewport width alone cannot tell those apart (a 1080p TV and a laptop
 * report similar widths), so the size is a viewport-aware base that the singer
 * can multiply by hand.
 */

const LEAD_IN_SECONDS = 4;
const LEAD_IN_DOTS = 4;

/** Last row that has started at or before `time`. Binary search: this runs ~10x a second. */
function activeRowIndex(rows, time) {
  let low = 0;
  let high = rows.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (rows[mid].startSeconds <= time) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

/**
 * Split a line into the segments its chords sit above.
 *
 * charOffset is an index into the text, so the chord belongs above whatever
 * starts there. Rendering each segment as its own column keeps the chord with
 * its syllable when the line wraps, which absolute positioning would not.
 */
function segmentsFor(row) {
  const text = row.text || "";
  const chords = (row.chords || []).slice().sort((a, b) => a.charOffset - b.charOffset);
  if (!chords.length) return [{ chord: null, text }];

  const segments = [];
  const firstOffset = Math.max(0, Math.min(text.length, chords[0].charOffset));
  if (firstOffset > 0) segments.push({ chord: null, text: text.slice(0, firstOffset) });

  chords.forEach((chord, index) => {
    const start = Math.max(0, Math.min(text.length, chord.charOffset));
    const next = chords[index + 1];
    const end = next ? Math.max(start, Math.min(text.length, next.charOffset)) : text.length;
    segments.push({ chord, text: text.slice(start, end) });
  });
  return segments;
}

const Line = memo(function Line({ row, state, showChords }) {
  const tone =
    state === "active"
      ? "text-white"
      : state === "next"
        ? "text-zinc-400"
        : state === "past"
          ? "text-zinc-600"
          : "text-zinc-500";

  if (row.instrumental) {
    return (
      <div className={`flex flex-wrap items-center gap-2 py-[0.35em] ${state === "active" ? "opacity-100" : "opacity-60"}`}>
        {(row.chords || []).map((chord, index) => (
          <span
            key={index}
            className={`rounded-md border px-[0.45em] py-[0.12em] text-[0.62em] font-bold ${
              state === "active"
                ? "border-teal-300/50 bg-teal-300/15 text-teal-100"
                : "border-white/10 bg-black/25 text-zinc-400"
            }`}
          >
            {chord.label}
          </span>
        ))}
        {!(row.chords || []).length ? <span className={`text-[0.6em] ${tone}`}>♪</span> : null}
      </div>
    );
  }

  const segments = showChords ? segmentsFor(row) : [{ chord: null, text: row.text || "" }];

  // The line is ordinary inline text with each chord positioned above its own
  // span. Laying the segments out as flex columns instead would turn every
  // chord boundary into a line-break opportunity, which splits words in half
  // on a narrow screen.
  return (
    <div
      className={`font-semibold leading-tight transition-colors duration-200 ${tone} ${
        showChords ? "pt-[1.35em]" : ""
      } py-[0.22em] ${state === "active" ? "drop-shadow-[0_0_18px_rgba(45,212,191,0.25)]" : ""}`}
    >
      {segments.map((segment, index) => (
        <span key={index} className="relative">
          {showChords && segment.chord ? (
            <span
// -2.2em, not -1.1em: `em` here resolves against the chord's own 0.5em
              // font size, so the offset has to be doubled to clear the lyric.
              className={`absolute -top-[2.2em] left-0 whitespace-pre text-[0.5em] font-bold leading-none ${
                state === "active" ? "text-teal-200" : "text-teal-200/35"
              }`}
            >
              {segment.chord.label}
            </span>
          ) : null}
          {segment.text}
        </span>
      ))}
    </div>
  );
});

function LeadIn({ secondsAway }) {
  const lit = Math.max(0, Math.ceil(LEAD_IN_DOTS * (1 - secondsAway / LEAD_IN_SECONDS)));
  return (
    <div className="flex items-center gap-[0.3em] py-[0.3em]" aria-label="Line starting soon">
      {Array.from({ length: LEAD_IN_DOTS }, (_, index) => (
        <span
          key={index}
          className={`h-[0.3em] w-[0.3em] rounded-full transition ${
            index < lit ? "bg-teal-300" : "bg-white/20"
          }`}
        />
      ))}
    </div>
  );
}

export default function KaraokeView({ rows, currentTime, showChords = true, scale = 1 }) {
  const activeRef = useRef(null);
  const containerRef = useRef(null);
  const lastActive = useRef(-2);

  const timed = useMemo(
    () => (rows || []).filter((row) => typeof row.startSeconds === "number"),
    [rows],
  );

  const activeIndex = useMemo(() => activeRowIndex(timed, currentTime), [timed, currentTime]);

  // Scroll only when the line changes, never on every clock tick.
  useEffect(() => {
    if (activeIndex === lastActive.current) return;
    lastActive.current = activeIndex;
    const node = activeRef.current;
    const container = containerRef.current;
    if (!node || !container) return;
    const target = node.offsetTop - container.clientHeight / 2 + node.clientHeight / 2;
    container.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
  }, [activeIndex]);

  if (!timed.length) {
    return (
      <div className="grid h-full place-items-center px-6 text-center">
        <p className="text-sm text-zinc-400">
          This song has no timed lyrics, so there is nothing to follow. Attach synced lyrics to its chord sheet first.
        </p>
      </div>
    );
  }

  const upcoming = timed[activeIndex + 1];
  const secondsAway = upcoming ? upcoming.startSeconds - currentTime : Infinity;
  const waiting = secondsAway > 0 && secondsAway <= LEAD_IN_SECONDS;

  // One base size for every screen, multiplied by the singer's own choice.
  // The floor is what matters on a phone: vw alone leaves this at reading
  // size, and it is meant to be sung from, not read.
  const fontSize = `calc(clamp(1.5rem, 4vw, 3rem) * ${scale})`;

  return (
    <div
      ref={containerRef}
      className="karaoke-scroll h-full overflow-y-auto px-[0.6em] py-[35vh]"
      style={{ fontSize }}
    >
      {timed.map((row, index) => {
        const state =
          index === activeIndex ? "active" : index === activeIndex + 1 ? "next" : index < activeIndex ? "past" : "ahead";
        const sectionChanged = index === 0 || row.section !== timed[index - 1].section;
        return (
          <div key={row.index ?? index} ref={index === activeIndex ? activeRef : null}>
            {row.section && sectionChanged ? (
              <div className="mt-[0.8em] text-[0.42em] font-bold uppercase tracking-[0.18em] text-teal-300/60">
                {row.section}
              </div>
            ) : null}
            {index === activeIndex + 1 && waiting ? <LeadIn secondsAway={secondsAway} /> : null}
            <Line row={row} state={state} showChords={showChords} />
          </div>
        );
      })}
    </div>
  );
}
