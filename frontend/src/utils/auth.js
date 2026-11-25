// Static PIN gate for Studio Pilot AI.
// No database: the PIN below is the single valid credential.
export const APP_PIN = "121387";
export const PIN_LENGTH = 6;

const AUTH_STORAGE_KEY = "audio-mixer-ai-auth";
const AUTH_TOKEN = "pin-unlocked";

export function isAuthenticated() {
  if (typeof window === "undefined") return false;
  try {
    return window.sessionStorage.getItem(AUTH_STORAGE_KEY) === AUTH_TOKEN;
  } catch {
    return false;
  }
}

export function normalizePin(value) {
  return String(value ?? "").replace(/\D/g, "").slice(0, PIN_LENGTH);
}

export function verifyPin(value) {
  return normalizePin(value) === APP_PIN;
}

/** Returns true when the PIN matched and the session was unlocked. */
export function signIn(value) {
  if (!verifyPin(value)) return false;
  if (typeof window === "undefined") return true;
  try {
    window.sessionStorage.setItem(AUTH_STORAGE_KEY, AUTH_TOKEN);
  } catch {
    // Session storage can be blocked; the current page stays unlocked anyway.
  }
  return true;
}

export function signOut() {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(AUTH_STORAGE_KEY);
  } catch {
    // Ignore storage failures.
  }
}
