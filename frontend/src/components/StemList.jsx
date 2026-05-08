import { Trash2 } from "lucide-react";
import { STEM_TYPES } from "../constants.js";
import { formatBytes, formatDateTime } from "../utils/format.js";
import Button from "./Button.jsx";
import StatusBadge from "./StatusBadge.jsx";

export default function StemList({ stems, onChangeType, onAcceptDetection, onDelete, busyStemId }) {
  const hasActions = Boolean(onAcceptDetection || onDelete);
  const gridColumns = hasActions
    ? "xl:grid-cols-[minmax(220px,1.4fr)_190px_170px_110px_120px_120px]"
    : "xl:grid-cols-[minmax(220px,1.4fr)_190px_170px_110px_120px]";

  if (!stems?.length) {
    return (
      <div className="rounded-lg border border-dashed border-white/14 bg-white/[0.03] px-5 py-10 text-center">
        <p className="text-sm text-zinc-400">No stems uploaded yet.</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-white/10 bg-white/[0.035]">
      <div className="overflow-x-auto">
        <div className="xl:min-w-[1060px]">
          <div className={`hidden ${gridColumns} gap-4 border-b border-white/10 px-4 py-3 text-xs font-semibold uppercase tracking-[0.14em] text-zinc-500 xl:grid`}>
            <span>Stem</span>
            <span>Type</span>
            <span>Detected</span>
            <span>Size</span>
            <span>Status</span>
            {hasActions ? <span className="text-right">Actions</span> : null}
          </div>
          <div className="divide-y divide-white/10">
            {stems.map((stem) => {
              const detection = stem.detectionResult;
              const canAccept = detection && detection.suggestedStemType !== "Unknown" && detection.confidence >= 60 && !detection.accepted;
              return (
                <div key={stem.id} className={`grid gap-4 px-4 py-4 ${gridColumns} xl:items-center`}>
                  <div className="min-w-0">
                    <div className="flex items-start justify-between gap-3">
                      <p className="min-w-0 truncate font-medium text-white">{stem.originalFilename}</p>
                      {onDelete ? (
                        <Button
                          type="button"
                          variant="danger"
                          className="h-9 w-9 shrink-0 px-0 xl:hidden"
                          onClick={() => onDelete(stem.id)}
                          disabled={busyStemId === stem.id}
                          aria-label={`Delete ${stem.originalFilename}`}
                          title="Delete stem"
                        >
                          <Trash2 size={16} />
                        </Button>
                      ) : null}
                    </div>
                    <p className="mt-1 truncate text-xs text-zinc-500">{stem.filePath}</p>
                    <p className="mt-1 text-xs text-zinc-500">{formatDateTime(stem.uploadedAt)}</p>
                  </div>
                  <div>
                    <select
                      value={stem.stemType}
                      onChange={(event) => onChangeType(stem.id, event.target.value)}
                      disabled={busyStemId === stem.id}
                      className="h-10 w-full rounded-lg border border-white/10 bg-black/25 px-3 text-sm text-white disabled:opacity-50"
                    >
                      {STEM_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-xs text-zinc-500">{stem.stemTypeSource === "Detected" ? "Accepted detection" : stem.stemTypeSource === "Manual" ? "Manual" : "Unset"}</p>
                  </div>
                  <div className="min-w-0">
                    <span className="mb-1 block text-xs uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Detected</span>
                    <DetectionSummary detection={detection} />
                  </div>
                  <span className="text-sm text-zinc-300">
                    <span className="mr-2 text-xs uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Size</span>
                    {formatBytes(stem.fileSize)}
                  </span>
                  <div>
                    <span className="mb-2 block text-xs uppercase tracking-[0.12em] text-zinc-500 xl:hidden">Status</span>
                    <StatusBadge status={stem.status} />
                  </div>
                  {hasActions ? (
                    <div className="flex justify-start gap-2 xl:justify-end">
                      {onAcceptDetection ? (
                        <Button
                          type="button"
                          variant="secondary"
                          className="h-10 px-3"
                          onClick={() => onAcceptDetection(stem.id)}
                          disabled={!canAccept || busyStemId === stem.id}
                          title={canAccept ? "Accept detected stem type" : "No confident detection to accept"}
                        >
                          Accept
                        </Button>
                      ) : null}
                      {onDelete ? (
                        <Button
                          type="button"
                          variant="danger"
                          className="hidden h-10 w-10 px-0 xl:inline-flex"
                          onClick={() => onDelete(stem.id)}
                          disabled={busyStemId === stem.id}
                          aria-label={`Delete ${stem.originalFilename}`}
                          title="Delete stem"
                        >
                          <Trash2 size={16} />
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function DetectionSummary({ detection }) {
  if (!detection) {
    return <span className="text-sm text-zinc-500">Not detected</span>;
  }
  return (
    <div className="min-w-0">
      <p className="truncate text-sm font-medium text-zinc-200">
        {detection.suggestedStemType} - {detection.confidence}%
      </p>
      <p className="mt-1 line-clamp-2 text-xs leading-5 text-zinc-500">{detection.reason}</p>
      {detection.accepted ? <p className="mt-1 text-xs font-semibold text-teal-200">Accepted</p> : null}
    </div>
  );
}
