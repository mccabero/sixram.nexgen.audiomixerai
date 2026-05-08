import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
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

  useEffect(() => {
    if (!open) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

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

  return createPortal(
    <div className="create-project-modal-backdrop fixed grid place-items-center px-4 py-6 backdrop-blur-md">
      <div className="create-project-modal-panel w-full max-w-2xl rounded-lg border p-5" role="dialog" aria-modal="true" aria-labelledby="create-project-modal-title">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 id="create-project-modal-title" className="create-project-modal-title text-xl font-semibold">{title}</h2>
            <p className="create-project-modal-description mt-1 text-sm">{description}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="create-project-modal-close grid h-10 w-10 place-items-center rounded-lg border"
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
              className="create-project-modal-input w-full rounded-lg border px-3 py-2.5"
              placeholder="Live session mix"
              maxLength={120}
            />
          </Field>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Artist or band">
              <input
                value={form.artistName}
                onChange={(event) => updateField("artistName", event.target.value)}
                className="create-project-modal-input w-full rounded-lg border px-3 py-2.5"
                placeholder="Sixram Band"
                maxLength={120}
              />
            </Field>
            <Field label="Song title">
              <input
                value={form.songTitle}
                onChange={(event) => updateField("songTitle", event.target.value)}
                className="create-project-modal-input w-full rounded-lg border px-3 py-2.5"
                placeholder="Working title"
                maxLength={120}
              />
            </Field>
          </div>
          <Field label="Notes">
            <textarea
              value={form.notes}
              onChange={(event) => updateField("notes", event.target.value)}
              className="create-project-modal-input min-h-28 w-full resize-y rounded-lg border px-3 py-2.5"
              placeholder="References, arrangement notes, tempo, or reminders"
              maxLength={2000}
            />
          </Field>
          {error ? <p className="create-project-modal-error rounded-lg border px-3 py-2 text-sm">{error}</p> : null}
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
    </div>,
    document.body,
  );
}

function Field({ label, required, children }) {
  return (
    <label className="block">
      <span className="create-project-modal-label mb-1.5 block text-sm font-medium">
        {label}
        {required ? <span className="create-project-modal-required"> *</span> : null}
      </span>
      {children}
    </label>
  );
}
