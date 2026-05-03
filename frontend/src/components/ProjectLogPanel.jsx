import { RefreshCw, ScrollText } from "lucide-react";
import { useEffect, useState } from "react";
import { getProjectLogs } from "../api.js";
import Button from "./Button.jsx";
import ProcessingPanel from "./ProcessingPanel.jsx";

export default function ProjectLogPanel({ projectId, className = "" }) {
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadLogs = async () => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      const payload = await getProjectLogs(projectId);
      setLines(payload.lines || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, [projectId]);

  return (
    <section className={`rounded-lg border border-white/10 bg-white/[0.035] p-4 ${className}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-lg border border-white/10 bg-black/25 text-teal-200">
            <ScrollText size={17} />
          </span>
          <div>
            <h2 className="font-semibold text-white">Recent Processing Log</h2>
            <p className="mt-1 text-sm text-zinc-400">{lines.length ? `${lines.length} latest entries` : "No log entries yet."}</p>
          </div>
        </div>
        <Button type="button" variant="secondary" onClick={loadLogs} disabled={loading} className="sm:w-auto">
          <RefreshCw size={17} />
          Refresh
        </Button>
      </div>

      {error ? <p className="mt-4 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}

      {loading ? (
        <div className="mt-4">
          <ProcessingPanel title="Loading Logs" message="Reading local project processing log." />
        </div>
      ) : (
        <div className="mt-4 max-h-72 overflow-auto rounded-lg border border-white/10 bg-black/25">
          {lines.length ? (
            <div className="divide-y divide-white/10">
              {lines.slice().reverse().map((line, index) => (
                <div key={`${line.raw}-${index}`} className="grid gap-1 px-3 py-2 text-sm md:grid-cols-[220px_1fr]">
                  <span className="font-mono text-xs text-zinc-500">{formatTimestamp(line.timestamp)}</span>
                  <span className="break-words text-zinc-300">{line.message}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="px-3 py-8 text-center text-sm text-zinc-500">Logs will appear here after project actions or processing jobs.</p>
          )}
        </div>
      )}
    </section>
  );
}

function formatTimestamp(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
