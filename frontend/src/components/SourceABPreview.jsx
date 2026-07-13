import { Pause, Play, Repeat } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import WaveformPreview from "./WaveformPreview.jsx";

// Compact A/B preview: flip between the original and cleaned stem at the exact
// same playback position so the effect of cleaning is easy to judge. Uses two
// audio elements (only one audible) to avoid src-swap reload glitches.
export default function SourceABPreview({ originalUrl, cleanedUrl, cleanedReady }) {
  const originalRef = useRef(null);
  const cleanedRef = useRef(null);
  const [active, setActive] = useState("original");
  const [playing, setPlaying] = useState(false);

  const canCompare = Boolean(cleanedReady && cleanedUrl);
  const activeUrl = active === "cleaned" && canCompare ? cleanedUrl : originalUrl;
  const activeRef = active === "cleaned" ? cleanedRef : originalRef;

  const play = useCallback(() => {
    const el = activeRef.current;
    if (!el || !el.src) return;
    el.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }, [activeRef]);

  const togglePlay = useCallback(() => {
    if (playing) {
      originalRef.current?.pause();
      cleanedRef.current?.pause();
      setPlaying(false);
    } else {
      play();
    }
  }, [playing, play]);

  const switchTo = useCallback(
    (next) => {
      if (next === active) return;
      if (next === "cleaned" && !canCompare) return;
      const current = activeRef.current;
      const other = (next === "cleaned" ? cleanedRef : originalRef).current;
      const time = current?.currentTime ?? 0;
      const wasPlaying = playing;
      current?.pause();
      if (other) {
        try {
          other.currentTime = time;
        } catch {
          /* metadata not ready yet — ignore */
        }
        if (wasPlaying) other.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      }
      setActive(next);
    },
    [active, activeRef, canCompare, playing]
  );

  return (
    <div>
      <audio ref={originalRef} src={originalUrl || undefined} preload="none" onEnded={() => setPlaying(false)} />
      <audio ref={cleanedRef} src={canCompare ? cleanedUrl : undefined} preload="none" onEnded={() => setPlaying(false)} />

      <WaveformPreview src={activeUrl} disabled={!activeUrl} variant={active === "cleaned" ? "teal" : "amber"} />

      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={togglePlay}
          disabled={!activeUrl}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-teal-200/30 bg-teal-300/10 text-teal-50 transition hover:bg-teal-300/20 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause size={15} /> : <Play size={15} />}
        </button>
        <div className="flex flex-1 items-center rounded-lg border border-white/10 bg-black/25 p-0.5 text-xs font-semibold">
          <button
            type="button"
            onClick={() => switchTo("original")}
            className={`flex-1 rounded-md px-2 py-1.5 transition ${active === "original" ? "bg-amber-300/20 text-amber-100" : "text-zinc-400 hover:text-zinc-200"}`}
          >
            Original
          </button>
          <Repeat size={13} className="mx-1 shrink-0 text-zinc-500" />
          <button
            type="button"
            onClick={() => switchTo("cleaned")}
            disabled={!canCompare}
            title={canCompare ? "Compare cleaned" : "Run cleaning to compare"}
            className={`flex-1 rounded-md px-2 py-1.5 transition disabled:cursor-not-allowed disabled:opacity-40 ${active === "cleaned" ? "bg-teal-300/20 text-teal-100" : "text-zinc-400 hover:text-zinc-200"}`}
          >
            Cleaned
          </button>
        </div>
      </div>
    </div>
  );
}
