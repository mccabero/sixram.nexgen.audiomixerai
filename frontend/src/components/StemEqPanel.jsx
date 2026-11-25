import { RotateCcw } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  EQ_MAX_FREQUENCY,
  EQ_MAX_GAIN_DB,
  EQ_MAX_Q,
  EQ_MIN_FREQUENCY,
  EQ_MIN_GAIN_DB,
  EQ_MIN_Q,
  bandLabel,
  defaultEqBands,
  eqResponseDb,
  isEqFlat,
  logFrequencies,
  normalizeEqBands,
} from "../utils/eq.js";

const VIEW_W = 300;
const VIEW_H = 104;
const PAD_Y = 6;
const GRID_HZ = [100, 1000, 10000];
const CURVE_FREQUENCIES = logFrequencies(150);

const toX = (hz) =>
  (Math.log(hz / EQ_MIN_FREQUENCY) / Math.log(EQ_MAX_FREQUENCY / EQ_MIN_FREQUENCY)) * VIEW_W;

const fromX = (x) =>
  EQ_MIN_FREQUENCY *
  Math.exp((Math.min(VIEW_W, Math.max(0, x)) / VIEW_W) * Math.log(EQ_MAX_FREQUENCY / EQ_MIN_FREQUENCY));

const toY = (db) => {
  const usable = VIEW_H - PAD_Y * 2;
  return PAD_Y + ((EQ_MAX_GAIN_DB - db) / (EQ_MAX_GAIN_DB - EQ_MIN_GAIN_DB)) * usable;
};

const fromY = (y) => {
  const usable = VIEW_H - PAD_Y * 2;
  const ratio = (Math.min(VIEW_H - PAD_Y, Math.max(PAD_Y, y)) - PAD_Y) / usable;
  return EQ_MAX_GAIN_DB - ratio * (EQ_MAX_GAIN_DB - EQ_MIN_GAIN_DB);
};

const formatHz = (hz) => (hz >= 1000 ? `${(hz / 1000).toFixed(hz >= 10000 ? 1 : 2)}k` : `${Math.round(hz)}`);
const formatDb = (db) => `${db > 0 ? "+" : ""}${db.toFixed(1)} dB`;

export default function StemEqPanel({ bands, stemType, sampleRate = 44100, onChange, onCommit }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const svgRef = useRef(null);
  const dragRef = useRef(null);

  const safeBands = useMemo(() => normalizeEqBands(bands, stemType), [bands, stemType]);
  const activeBand = safeBands[activeIndex] ?? safeBands[0];
  const flat = isEqFlat(safeBands);

  const curve = useMemo(() => {
    const response = eqResponseDb(safeBands, CURVE_FREQUENCIES, sampleRate);
    return CURVE_FREQUENCIES.map((hz, index) => {
      const db = Math.max(EQ_MIN_GAIN_DB, Math.min(EQ_MAX_GAIN_DB, response[index]));
      return `${index === 0 ? "M" : "L"}${toX(hz).toFixed(1)} ${toY(db).toFixed(1)}`;
    }).join(" ");
  }, [safeBands, sampleRate]);

  const writeBand = useCallback(
    (index, patch, commit) => {
      const next = safeBands.map((band, position) => (position === index ? { ...band, ...patch } : band));
      onChange(next);
      if (commit) onCommit(next);
    },
    [safeBands, onChange, onCommit],
  );

  const pointerPosition = (event) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * VIEW_W,
      y: ((event.clientY - rect.top) / rect.height) * VIEW_H,
    };
  };

  const handlePointerDown = (index) => (event) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setActiveIndex(index);
    dragRef.current = index;
  };

  const handlePointerMove = (event) => {
    const index = dragRef.current;
    if (index === null || index === undefined) return;
    const position = pointerPosition(event);
    if (!position) return;
    writeBand(index, {
      frequency: Math.round(fromX(position.x)),
      gainDb: Number(fromY(position.y).toFixed(1)),
    });
  };

  const endDrag = () => {
    if (dragRef.current === null || dragRef.current === undefined) return;
    dragRef.current = null;
    onCommit(safeBands);
  };

  const reset = () => {
    const defaults = defaultEqBands(stemType);
    onChange(defaults);
    onCommit(defaults);
  };

  return (
    <div className="rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-[0.12em] text-zinc-500">Channel EQ</span>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-medium ${flat ? "text-zinc-500" : "text-teal-200"}`}>
            {flat ? "Flat" : "Active"}
          </span>
          <button
            type="button"
            onClick={reset}
            disabled={flat}
            aria-label="Reset EQ to flat"
            title="Reset EQ to flat"
            className="grid h-7 w-7 place-items-center rounded-md border border-white/10 text-zinc-400 transition hover:bg-white/[0.06] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            <RotateCcw size={13} />
          </button>
        </div>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="w-full touch-none rounded-md bg-black/30"
        role="img"
        aria-label="EQ response curve"
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        onPointerCancel={endDrag}
      >
        <line x1="0" y1={toY(0)} x2={VIEW_W} y2={toY(0)} stroke="rgba(255,255,255,0.16)" strokeWidth="1" />
        {GRID_HZ.map((hz) => (
          <g key={hz}>
            <line x1={toX(hz)} y1="0" x2={toX(hz)} y2={VIEW_H} stroke="rgba(255,255,255,0.07)" strokeWidth="1" />
            <text x={toX(hz) + 3} y={VIEW_H - 3} fontSize="8" fill="rgba(255,255,255,0.3)">
              {formatHz(hz)}
            </text>
          </g>
        ))}
        <path d={curve} fill="none" stroke="rgb(94,234,212)" strokeWidth="1.75" strokeLinejoin="round" />
        {safeBands.map((band, index) => {
          const selected = index === activeIndex;
          return (
            <circle
              key={index}
              cx={toX(band.frequency)}
              cy={toY(Math.max(EQ_MIN_GAIN_DB, Math.min(EQ_MAX_GAIN_DB, band.gainDb)))}
              r={selected ? 6 : 4.5}
              fill={selected ? "rgb(94,234,212)" : "rgba(94,234,212,0.35)"}
              stroke="rgba(0,0,0,0.55)"
              strokeWidth="1"
              className="cursor-grab"
              onPointerDown={handlePointerDown(index)}
            />
          );
        })}
      </svg>

      <div className="mt-2 grid grid-cols-4 gap-1">
        {safeBands.map((band, index) => (
          <button
            key={index}
            type="button"
            onClick={() => setActiveIndex(index)}
            aria-pressed={index === activeIndex}
            className={`rounded-md border px-1 py-1 text-[10px] font-semibold uppercase tracking-wide transition ${
              index === activeIndex
                ? "border-teal-200/40 bg-teal-300/15 text-teal-100"
                : "border-white/10 bg-black/25 text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <span className="block truncate">{bandLabel(index)}</span>
            <span className="block normal-case tracking-normal text-zinc-500">
              {band.gainDb > 0 ? "+" : ""}
              {band.gainDb.toFixed(1)}
            </span>
          </button>
        ))}
      </div>

      {activeBand ? (
        <div className="mt-3 flex flex-col gap-3">
          <EqSlider
            label="Frequency"
            value={activeBand.frequency}
            min={EQ_MIN_FREQUENCY}
            max={EQ_MAX_FREQUENCY}
            step={1}
            display={`${formatHz(activeBand.frequency)} Hz`}
            logarithmic
            onChange={(value) => writeBand(activeIndex, { frequency: Math.round(value) })}
            onCommit={(value) => writeBand(activeIndex, { frequency: Math.round(value) }, true)}
          />
          <EqSlider
            label="Gain"
            value={activeBand.gainDb}
            min={EQ_MIN_GAIN_DB}
            max={EQ_MAX_GAIN_DB}
            step={0.1}
            display={formatDb(activeBand.gainDb)}
            onChange={(value) => writeBand(activeIndex, { gainDb: Number(value.toFixed(1)) })}
            onCommit={(value) => writeBand(activeIndex, { gainDb: Number(value.toFixed(1)) }, true)}
          />
          <EqSlider
            label={activeBand.type === "peaking" ? "Q" : "Slope"}
            value={activeBand.q}
            min={EQ_MIN_Q}
            max={EQ_MAX_Q}
            step={0.05}
            display={activeBand.q.toFixed(2)}
            onChange={(value) => writeBand(activeIndex, { q: Number(value.toFixed(2)) })}
            onCommit={(value) => writeBand(activeIndex, { q: Number(value.toFixed(2)) }, true)}
          />
        </div>
      ) : null}
    </div>
  );
}

function EqSlider({ label, value, min, max, step, display, logarithmic, onChange, onCommit }) {
  // Frequency needs a log taper or the bottom three octaves are unusable in
  // the first few pixels of the track.
  const toSlider = (raw) =>
    logarithmic ? (Math.log(raw / min) / Math.log(max / min)) * 1000 : raw;
  const fromSlider = (position) =>
    logarithmic ? min * Math.exp((position / 1000) * Math.log(max / min)) : position;

  return (
    <label className="block">
      <span className="mb-1.5 flex items-center justify-between gap-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
        <span>{label}</span>
        <span className="normal-case tracking-normal text-zinc-300">{display}</span>
      </span>
      <input
        type="range"
        min={logarithmic ? 0 : min}
        max={logarithmic ? 1000 : max}
        step={logarithmic ? 1 : step}
        value={toSlider(value)}
        onChange={(event) => onChange(fromSlider(Number(event.target.value)))}
        onPointerUp={(event) => onCommit(fromSlider(Number(event.currentTarget.value)))}
        onBlur={(event) => onCommit(fromSlider(Number(event.currentTarget.value)))}
        className="w-full accent-teal-300"
      />
    </label>
  );
}
