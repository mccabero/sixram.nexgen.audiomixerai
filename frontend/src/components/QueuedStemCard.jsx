import { Pause, Play, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { formatBytes, formatDuration } from "../utils/format.js";

function getExtension(filename) {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex + 1).toLowerCase() : "audio";
}

// Read the channel count from a canonical WAV header without decoding the whole
// file. Best-effort: returns null for non-WAV or malformed files.
async function readWavChannels(file) {
  if (!/\.wav$/i.test(file.name)) return null;
  try {
    const buffer = await file.slice(0, 44).arrayBuffer();
    if (buffer.byteLength < 24) return null;
    const view = new DataView(buffer);
    const tag = (offset) => String.fromCharCode(view.getUint8(offset), view.getUint8(offset + 1), view.getUint8(offset + 2), view.getUint8(offset + 3));
    if (tag(0) !== "RIFF" || tag(8) !== "WAVE") return null;
    const channels = view.getUint16(22, true);
    return channels > 0 && channels <= 32 ? channels : null;
  } catch {
    return null;
  }
}

function channelLabel(channels) {
  if (channels === 1) return "Mono";
  if (channels === 2) return "Stereo";
  return `${channels} ch`;
}

export default function QueuedStemCard({ file, fileKey, stemGuess, isPlaying, onTogglePlay, onRemove }) {
  const audioRef = useRef(null);
  const [url, setUrl] = useState("");
  const [duration, setDuration] = useState(null);
  const [channels, setChannels] = useState(null);

  useEffect(() => {
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);

  useEffect(() => {
    let cancelled = false;
    readWavChannels(file).then((ch) => {
      if (!cancelled) setChannels(ch);
    });
    return () => {
      cancelled = true;
    };
  }, [file]);

  // Parent owns the "only one plays at a time" state; react to it here.
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    if (isPlaying) el.play().catch(() => onTogglePlay(""));
    else el.pause();
  }, [isPlaying, onTogglePlay]);

  const extension = getExtension(file.name);

  return (
    <div className={`flex min-w-0 items-start justify-between gap-3 rounded-lg border p-3 transition ${isPlaying ? "border-teal-200/40 bg-teal-300/[0.07]" : "border-white/10 bg-black/20"}`}>
      <button
        type="button"
        onClick={() => onTogglePlay(fileKey)}
        className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-teal-200/30 bg-teal-300/10 text-teal-50 transition hover:bg-teal-300/20"
        aria-label={isPlaying ? `Pause ${file.name}` : `Preview ${file.name}`}
        title={isPlaying ? "Pause preview" : "Preview"}
      >
        {isPlaying ? <Pause size={16} /> : <Play size={16} />}
      </button>

      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <p className="max-w-full truncate text-sm font-semibold text-white">{file.name}</p>
          <span className="rounded-full border border-white/10 bg-white/[0.055] px-2 py-0.5 text-[11px] font-semibold uppercase text-zinc-300">{extension}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
          <span>{formatBytes(file.size)}</span>
          {duration != null ? <span>{formatDuration(duration)}</span> : null}
          {channels != null ? <span>{channelLabel(channels)}</span> : null}
        </div>
        <span className="mt-2 inline-flex rounded-full border border-teal-300/20 bg-teal-300/10 px-2.5 py-1 text-xs font-semibold text-teal-100">{stemGuess}</span>
        <audio
          ref={audioRef}
          src={url || undefined}
          preload="metadata"
          onLoadedMetadata={(event) => {
            if (Number.isFinite(event.currentTarget.duration)) setDuration(event.currentTarget.duration);
          }}
          onEnded={() => onTogglePlay("")}
        />
      </div>

      <button
        type="button"
        className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 text-zinc-300 transition hover:bg-white/[0.06]"
        onClick={() => onRemove(file)}
        aria-label={`Remove ${file.name}`}
        title="Remove file"
      >
        <X size={16} />
      </button>
    </div>
  );
}
