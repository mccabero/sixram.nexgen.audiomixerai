export const THEME_STORAGE_KEY = "audio-mixer-ai-theme";

export function normalizeTheme(value) {
  return value === "dark" ? "dark" : "light";
}

export function readStoredTheme() {
  if (typeof window === "undefined") return "light";
  try {
    return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "light";
  }
}

export function applyDocumentTheme(theme) {
  if (typeof document === "undefined") return;
  const normalized = normalizeTheme(theme);
  document.documentElement.dataset.theme = normalized;
  document.documentElement.style.colorScheme = normalized;
}

export function persistTheme(theme) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, normalizeTheme(theme));
  } catch {
    // Ignore storage failures and keep the theme in-memory.
  }
}
