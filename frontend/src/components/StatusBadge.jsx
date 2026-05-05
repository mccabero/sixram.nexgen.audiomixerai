const styles = {
  Created: "border-amber-300/20 bg-amber-300/10 text-amber-100",
  "Stems Uploaded": "border-teal-300/20 bg-teal-300/10 text-teal-100",
  Analyzed: "border-cyan-300/20 bg-cyan-300/10 text-cyan-100",
  "Auto Balance Ready": "border-violet-300/20 bg-violet-300/10 text-violet-100",
  "Auto Balanced": "border-fuchsia-300/20 bg-fuchsia-300/10 text-fuchsia-100",
  "Rough Mix Ready": "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
  "Advanced Mix Ready": "border-lime-300/20 bg-lime-300/10 text-lime-100",
  "Master Ready": "border-indigo-300/20 bg-indigo-300/10 text-indigo-100",
  Exported: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
  "Stem Detection Ready": "border-sky-300/20 bg-sky-300/10 text-sky-100",
  Cleaned: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
  "Vocals Enhanced": "border-teal-300/20 bg-teal-300/10 text-teal-100",
  "Not Enhanced": "border-zinc-400/20 bg-zinc-400/10 text-zinc-200",
  Enhanced: "border-teal-300/20 bg-teal-300/10 text-teal-100",
  "Not Cleaned": "border-zinc-400/20 bg-zinc-400/10 text-zinc-200",
  Disabled: "border-zinc-400/20 bg-zinc-400/10 text-zinc-300",
  "Cleaning Failed": "border-rose-300/20 bg-rose-300/10 text-rose-100",
  Uploaded: "border-cyan-300/20 bg-cyan-300/10 text-cyan-100",
  Pending: "border-zinc-400/20 bg-zinc-400/10 text-zinc-200",
  Processing: "border-teal-300/20 bg-teal-300/10 text-teal-100",
  Cancelling: "border-amber-300/20 bg-amber-300/10 text-amber-100",
  Cancelled: "border-zinc-400/20 bg-zinc-400/10 text-zinc-200",
  Completed: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
  Failed: "border-rose-300/20 bg-rose-300/10 text-rose-100",
};

export default function StatusBadge({ status }) {
  return (
    <span className={`inline-flex shrink-0 whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-semibold ${styles[status] || styles.Created}`}>
      {status}
    </span>
  );
}
