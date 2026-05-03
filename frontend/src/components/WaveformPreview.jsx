import { useEffect, useRef, useState } from "react";

const colors = {
  teal: "rgba(45, 212, 191, 0.95)",
  amber: "rgba(251, 191, 36, 0.95)",
};

export default function WaveformPreview({ src, disabled = false, variant = "teal" }) {
  const canvasRef = useRef(null);
  const [status, setStatus] = useState(disabled ? "Not ready" : "Loading");

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let cancelled = false;
    let audioContext = null;
    let resizeObserver = null;

    const drawEmpty = (message = disabled ? "Not ready" : "Loading") => {
      const context = prepareCanvas(canvas);
      if (!context) return;
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "rgba(255,255,255,0.035)";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.strokeStyle = "rgba(255,255,255,0.14)";
      context.lineWidth = Math.max(1, window.devicePixelRatio || 1);
      context.beginPath();
      context.moveTo(0, canvas.height / 2);
      context.lineTo(canvas.width, canvas.height / 2);
      context.stroke();
      setStatus(message);
    };

    if (!src || disabled) {
      drawEmpty("Not ready");
      return undefined;
    }

    const drawBuffer = (buffer) => {
      const context = prepareCanvas(canvas);
      if (!context) return;

      const samples = downmix(buffer);
      const width = canvas.width;
      const height = canvas.height;
      const center = height / 2;
      const step = Math.max(1, Math.floor(samples.length / width));
      const waveColor = colors[variant] || colors.teal;

      context.clearRect(0, 0, width, height);
      context.fillStyle = "rgba(255,255,255,0.035)";
      context.fillRect(0, 0, width, height);
      context.strokeStyle = waveColor;
      context.lineWidth = Math.max(1, window.devicePixelRatio || 1);
      context.beginPath();

      for (let x = 0; x < width; x += 1) {
        const start = x * step;
        let min = 0;
        let max = 0;
        for (let index = 0; index < step && start + index < samples.length; index += 1) {
          const value = samples[start + index];
          if (value < min) min = value;
          if (value > max) max = value;
        }
        context.moveTo(x, center + min * center * 0.92);
        context.lineTo(x, center + max * center * 0.92);
      }

      context.stroke();
      setStatus("");
    };

    const load = async () => {
      drawEmpty("Loading");
      try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) throw new Error("Waveform preview is not supported in this browser.");
        audioContext = new AudioContextClass();
        const response = await fetch(src);
        if (!response.ok) throw new Error("Audio file could not be loaded.");
        const arrayBuffer = await response.arrayBuffer();
        const decoded = await audioContext.decodeAudioData(arrayBuffer);
        if (cancelled) return;
        drawBuffer(decoded);
        resizeObserver = new ResizeObserver(() => drawBuffer(decoded));
        resizeObserver.observe(canvas);
      } catch {
        if (!cancelled) drawEmpty("Waveform unavailable");
      }
    };

    load();

    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      audioContext?.close?.();
    };
  }, [src, disabled, variant]);

  return (
    <div className="relative overflow-hidden rounded-lg border border-white/10 bg-black/20">
      <canvas ref={canvasRef} className="block h-14 w-full" />
      {status ? <span className="absolute inset-0 grid place-items-center text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">{status}</span> : null}
    </div>
  );
}

function prepareCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const pixelRatio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(rect.width * pixelRatio));
  const height = Math.max(1, Math.floor(rect.height * pixelRatio));
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  return canvas.getContext("2d");
}

function downmix(buffer) {
  const output = new Float32Array(buffer.length);
  for (let channelIndex = 0; channelIndex < buffer.numberOfChannels; channelIndex += 1) {
    const channel = buffer.getChannelData(channelIndex);
    for (let index = 0; index < channel.length; index += 1) {
      output[index] += channel[index] / buffer.numberOfChannels;
    }
  }
  return output;
}
