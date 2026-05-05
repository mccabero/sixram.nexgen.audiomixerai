import { LoaderCircle, Square } from "lucide-react";
import Button from "./Button.jsx";

export default function ProcessingPanel({ title = "Processing", message, progress, actionLabel = "Stop", actionBusy = false, actionDisabled = false, onAction }) {
  const numericProgress = typeof progress === "number" && Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : null;
  const showAction = typeof onAction === "function";

  return (
    <section aria-live="polite" className="rounded-lg border border-teal-200/20 bg-gradient-to-r from-teal-300/10 via-white/[0.045] to-black/20 px-4 py-3 shadow-[0_18px_55px_rgba(0,0,0,0.22)]">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-teal-200/20 bg-black/25 text-teal-100">
          <LoaderCircle size={18} className="animate-spin" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="font-semibold text-teal-50">{title}</h2>
            <div className="flex shrink-0 items-center gap-2">
              {numericProgress !== null ? <span className="text-sm font-semibold text-teal-50">{Math.round(numericProgress)}%</span> : null}
              {showAction ? (
                <Button type="button" variant="danger" onClick={onAction} disabled={actionDisabled || actionBusy} className="min-h-9 px-3 py-1.5 text-xs">
                  <Square size={13} />
                  {actionBusy ? "Stopping..." : actionLabel}
                </Button>
              ) : null}
            </div>
          </div>
          {message ? <p className="mt-1 text-sm leading-6 text-teal-100/80">{message}</p> : null}
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-black/40">
            {numericProgress !== null ? (
              <div className="h-full rounded-full bg-gradient-to-r from-teal-200 to-emerald-200 transition-all" style={{ width: `${numericProgress}%` }} />
            ) : (
              <div className="h-full w-1/3 animate-pulse rounded-full bg-gradient-to-r from-teal-200 to-emerald-200" />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
