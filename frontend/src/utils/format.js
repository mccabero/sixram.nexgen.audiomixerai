export function formatDate(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

export function formatDateTime(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "Unknown";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "Pending";
  const totalSeconds = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remainder = totalSeconds % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export function formatDb(value) {
  if (!Number.isFinite(value)) return "--";
  return `${value.toFixed(1)} dB`;
}

export function formatLufs(value) {
  if (!Number.isFinite(value)) return "--";
  return `${value.toFixed(1)} LUFS`;
}

export function formatPercent(value) {
  if (!Number.isFinite(value)) return "--";
  return `${value.toFixed(value >= 10 ? 0 : 1)}%`;
}

export function formatPan(value) {
  if (!Number.isFinite(value)) return "C";
  if (Math.abs(value) < 1) return "C";
  return value < 0 ? `L ${Math.abs(Math.round(value))}` : `R ${Math.abs(Math.round(value))}`;
}
