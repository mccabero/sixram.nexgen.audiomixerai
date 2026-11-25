import { Delete, Eye, EyeOff, Lock, MoonStar, SunMedium } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import sixramLogo from "../assets/sixram-band-studio-logo.png";
import Button from "../components/Button.jsx";
import { PIN_LENGTH, isAuthenticated, signIn } from "../utils/auth.js";
import { applyDocumentTheme, persistTheme, readStoredTheme } from "../utils/theme.js";

const KEYPAD_DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];
const emptyPin = () => Array(PIN_LENGTH).fill("");

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [digits, setDigits] = useState(emptyPin);
  const [error, setError] = useState("");
  const [shake, setShake] = useState(false);
  const [visible, setVisible] = useState(false);
  const [theme, setTheme] = useState(() => readStoredTheme());
  const inputsRef = useRef([]);

  const redirectTo = location.state?.from?.pathname ?? "/";
  const nextTheme = theme === "dark" ? "light" : "dark";

  useEffect(() => {
    applyDocumentTheme(theme);
    persistTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (isAuthenticated()) {
      navigate(redirectTo, { replace: true });
      return;
    }
    inputsRef.current[0]?.focus();
  }, [navigate, redirectTo]);

  useEffect(() => {
    if (!shake) return undefined;
    const timer = window.setTimeout(() => setShake(false), 420);
    return () => window.clearTimeout(timer);
  }, [shake]);

  function focusInput(index) {
    const target = inputsRef.current[Math.max(0, Math.min(PIN_LENGTH - 1, index))];
    target?.focus();
    target?.select?.();
  }

  function unlock(pin) {
    if (signIn(pin)) {
      navigate(redirectTo, { replace: true });
      return;
    }
    setDigits(emptyPin());
    setError("Incorrect PIN. Please try again.");
    setShake(true);
    focusInput(0);
  }

  function commit(next, caretIndex) {
    setDigits(next);
    setError("");
    const pin = next.join("");
    if (pin.length === PIN_LENGTH && next.every(Boolean)) {
      unlock(pin);
      return;
    }
    if (typeof caretIndex === "number") focusInput(caretIndex);
  }

  function handleChange(index, rawValue) {
    const typed = String(rawValue).replace(/\D/g, "");
    if (!typed) {
      const next = [...digits];
      next[index] = "";
      commit(next, index);
      return;
    }
    const next = [...digits];
    typed.split("").forEach((digit, offset) => {
      if (index + offset < PIN_LENGTH) next[index + offset] = digit;
    });
    commit(next, index + typed.length);
  }

  function handleKeyDown(index, event) {
    if (event.key === "Backspace") {
      event.preventDefault();
      const next = [...digits];
      if (next[index]) {
        next[index] = "";
        commit(next, index);
      } else {
        next[Math.max(0, index - 1)] = "";
        commit(next, index - 1);
      }
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      focusInput(index - 1);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      focusInput(index + 1);
    }
  }

  function handlePaste(event) {
    const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, PIN_LENGTH);
    if (!pasted) return;
    event.preventDefault();
    const next = emptyPin();
    pasted.split("").forEach((digit, offset) => {
      next[offset] = digit;
    });
    commit(next, pasted.length);
  }

  function pressDigit(digit) {
    const firstEmpty = digits.findIndex((value) => !value);
    if (firstEmpty === -1) return;
    const next = [...digits];
    next[firstEmpty] = digit;
    commit(next, firstEmpty + 1);
  }

  function pressBackspace() {
    const lastFilled = digits.map((value) => Boolean(value)).lastIndexOf(true);
    if (lastFilled === -1) return;
    const next = [...digits];
    next[lastFilled] = "";
    commit(next, lastFilled);
  }

  function handleSubmit(event) {
    event.preventDefault();
    const pin = digits.join("");
    if (pin.length < PIN_LENGTH) {
      setError(`Enter all ${PIN_LENGTH} digits.`);
      setShake(true);
      focusInput(digits.findIndex((value) => !value));
      return;
    }
    unlock(pin);
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4 py-10">
      <button
        type="button"
        onClick={() => {
          setTheme(nextTheme);
          const firstEmpty = digits.findIndex((value) => !value);
          focusInput(firstEmpty === -1 ? PIN_LENGTH - 1 : firstEmpty);
        }}
        className="pin-theme-toggle absolute right-4 top-4 inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-semibold transition sm:right-6 sm:top-6"
        aria-label={`Switch to ${nextTheme} mode`}
        title={`Switch to ${nextTheme} mode`}
      >
        {theme === "dark" ? <SunMedium size={16} /> : <MoonStar size={16} />}
        <span className="hidden sm:inline">{theme === "dark" ? "Light" : "Dark"}</span>
      </button>

      <div className="w-full max-w-sm">
        <div className="pin-card rounded-2xl border p-7 shadow-glow sm:p-8">
          <div className="flex flex-col items-center text-center">
            <span className="grid h-16 w-16 place-items-center overflow-hidden rounded-xl border border-red-300/25 bg-zinc-950 shadow-[0_0_30px_rgba(239,68,68,0.18)]">
              <img src={sixramLogo} alt="Sixram Band Studio logo" className="h-full w-full object-contain" />
            </span>
            <span className="mt-4 text-xs font-semibold uppercase tracking-[0.18em] text-teal-300">
              Sixram Band Studio
            </span>
            <h1 className="pin-title mt-1 text-2xl font-semibold">Studio Pilot AI</h1>
            <p className="pin-subtitle mt-2 inline-flex items-center gap-1.5 text-sm">
              <Lock size={14} />
              Enter your {PIN_LENGTH}-digit PIN to continue
            </p>
          </div>

          <form onSubmit={handleSubmit} className="mt-7">
            <div className={`flex justify-center gap-2 ${shake ? "pin-shake" : ""}`}>
              {digits.map((digit, index) => (
                <input
                  key={index}
                  ref={(element) => {
                    inputsRef.current[index] = element;
                  }}
                  type={visible ? "text" : "password"}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  aria-label={`PIN digit ${index + 1}`}
                  value={digit}
                  maxLength={PIN_LENGTH}
                  onChange={(event) => handleChange(index, event.target.value)}
                  onKeyDown={(event) => handleKeyDown(index, event)}
                  onPaste={handlePaste}
                  onFocus={(event) => event.target.select()}
                  className={`pin-digit h-14 w-11 rounded-xl border text-center text-2xl font-semibold outline-none transition sm:w-12 ${
                    digit ? "pin-digit-filled" : ""
                  } ${error ? "pin-digit-error" : ""}`}
                />
              ))}
            </div>

            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="pin-error text-sm" role="alert" aria-live="polite">
                {error}
              </p>
              <button
                type="button"
                onClick={() => {
                  setVisible((current) => !current);
                  const firstEmpty = digits.findIndex((value) => !value);
                  focusInput(firstEmpty === -1 ? PIN_LENGTH - 1 : firstEmpty);
                }}
                className="pin-link inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold"
              >
                {visible ? <EyeOff size={14} /> : <Eye size={14} />}
                {visible ? "Hide" : "Show"}
              </button>
            </div>

            <div className="mt-5 grid grid-cols-3 gap-2">
              {KEYPAD_DIGITS.map((digit) => (
                <button
                  key={digit}
                  type="button"
                  onClick={() => pressDigit(digit)}
                  className="pin-key min-h-12 rounded-xl border text-lg font-semibold transition"
                >
                  {digit}
                </button>
              ))}
              <button
                type="button"
                onClick={() => commit(emptyPin(), 0)}
                className="pin-key min-h-12 rounded-xl border text-xs font-semibold uppercase tracking-wider transition"
              >
                Clear
              </button>
              <button
                type="button"
                onClick={() => pressDigit("0")}
                className="pin-key min-h-12 rounded-xl border text-lg font-semibold transition"
              >
                0
              </button>
              <button
                type="button"
                onClick={pressBackspace}
                aria-label="Delete last digit"
                className="pin-key inline-flex min-h-12 items-center justify-center rounded-xl border transition"
              >
                <Delete size={18} />
              </button>
            </div>

            <Button type="submit" className="mt-5 w-full">
              Unlock studio
            </Button>
          </form>
        </div>

        <p className="pin-footnote mt-5 text-center text-xs">
          Local studio access only. Your session ends when you close this tab.
        </p>
      </div>
    </div>
  );
}
