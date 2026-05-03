import { X } from "lucide-react";
import { useEffect, useState } from "react";
import Button from "./Button.jsx";
import ProcessingPanel from "./ProcessingPanel.jsx";

const initialForm = {
  name: "",
  artistName: "",
  songTitle: "",
  notes: "",
};

export default function CreateProjectModal({
  open,
  onClose,
  onCreate,
  initialValues,
  title = "Create Project",
  description = "Set up a local song workspace for uploaded stems.",
  submitLabel = "Create project",
  submittingLabel = "Creating...",
  processingTitle = "Creating Project",
  processingMessage = "Preparing the local project folders and metadata.",
}) {
  const [form, setForm] = useState(initialForm);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setError("");
    setForm({
      name: initialValues?.name || "",
      artistName: initialValues?.artistName || "",
      songTitle: initialValues?.songTitle || "",
      notes: initialValues?.notes || "",
    });
  }, [open, initialValues]);

  if (!open) return null;

  const updateField = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");

    if (!form.name.trim()) {
      setError("Project name is required.");
      return;
    }

    setSubmitting(true);
    try {
      await onCreate({
        name: form.name.trim(),
        artistName: form.artistName.trim() || null,
        songTitle: form.songTitle.trim() || null,
        notes: form.notes.trim() || null,
      });
      setForm(initialForm);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/75 px-4 py-6 backdrop-blur-md">
      <div className="w-full max-w-2xl rounded-lg border border-white/10 bg-gradient-to-br from-zinc-900 to-zinc-950 p-5 shadow-[0_28px_90px_rgba(0,0,0,0.45)]">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-white">{title}</h2>
            <p className="mt-1 text-sm text-zinc-400">{description}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-10 w-10 place-items-center rounded-lg border border-white/10 text-zinc-300 hover:bg-white/[0.06]"
            aria-label="Close create project modal"
          >
            <X size={18} />
          </button>
        </div>
        <form className="mt-5 space-y-4" onSubmit={handleSubmit}>
          <Field label="Project name" required>
            <input
              value={form.name}
              onChange={(event) => updateField("name", event.target.value)}
              className="w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2.5 text-white placeholder:text-zinc-600"
              placeholder="Live session mix"
              maxLength={120}
            />
          </Field>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Artist or band">
              <input
                value={form.artistName}
                onChange={(event) => updateField("artistName", event.target.value)}
                className="w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2.5 text-white placeholder:text-zinc-600"
                placeholder="Sixram Band"
                maxLength={120}
              />
            </Field>
            <Field label="Song title">
              <input
                value={form.songTitle}
                onChange={(event) => updateField("songTitle", event.target.value)}
                className="w-full rounded-lg border border-white/10 bg-black/25 px-3 py-2.5 text-white placeholder:text-zinc-600"
                placeholder="Working title"
                maxLength={120}
              />
            </Field>
          </div>
          <Field label="Notes">
            <textarea
              value={form.notes}
              onChange={(event) => updateField("notes", event.target.value)}
              className="min-h-28 w-full resize-y rounded-lg border border-white/10 bg-black/25 px-3 py-2.5 text-white placeholder:text-zinc-600"
              placeholder="References, arrangement notes, tempo, or reminders"
              maxLength={2000}
            />
          </Field>
          {error ? <p className="rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">{error}</p> : null}
          {submitting ? <ProcessingPanel title={processingTitle} message={processingMessage} /> : null}
          <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? submittingLabel : submitLabel}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({ label, required, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-zinc-300">
        {label}
        {required ? <span className="text-teal-200"> *</span> : null}
      </span>
      {children}
    </label>
  );
}
