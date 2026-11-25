import { FolderOpen, LogOut, MoonStar, Scissors, SunMedium } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import sixramLogo from "../assets/sixram-band-studio-logo.png";
import { signOut } from "../utils/auth.js";
import { applyDocumentTheme, persistTheme, readStoredTheme } from "../utils/theme.js";
import Button from "./Button.jsx";
import GlobalJobStatus from "./GlobalJobStatus.jsx";

const navItems = [
  { to: "/", label: "Projects", end: true, icon: FolderOpen },
  { to: "/stem-splitter", label: "Stem Splitter", end: false, icon: Scissors },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const [theme, setTheme] = useState(() => readStoredTheme());

  useEffect(() => {
    applyDocumentTheme(theme);
    persistTheme(theme);
  }, [theme]);

  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <div className={`min-h-screen ${theme === "light" ? "theme-light" : "theme-dark"}`}>
      <header className="app-shell-header sticky top-0 z-30 border-b border-white/10 bg-zinc-950/78 shadow-[0_18px_50px_rgba(0,0,0,0.22)] backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1760px] items-center justify-between gap-2 px-4 py-3 sm:gap-4 sm:px-6 sm:py-4 lg:px-8">
          <Link to="/" className="flex min-w-0 items-center gap-2 sm:gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-lg border border-red-300/25 bg-zinc-950 shadow-[0_0_30px_rgba(239,68,68,0.18)] sm:h-14 sm:w-14">
              <img
                src={sixramLogo}
                alt="Sixram Band Studio logo"
                className="h-full w-full object-contain"
              />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-xs font-semibold uppercase tracking-[0.16em] text-teal-100/80 sm:text-sm">
                Sixram Band Studio
              </span>
              <span className="block truncate text-base font-semibold text-white sm:text-lg">Studio Pilot AI</span>
            </span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden items-center gap-1.5 md:flex">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-semibold transition ${
                    isActive
                      ? "border-teal-300/45 bg-teal-300/[0.12] text-teal-100"
                      : "border-white/10 bg-white/[0.06] text-zinc-300 hover:text-white"
                  }`
                }
              >
                <item.icon size={16} />
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
            <Button
              type="button"
              variant="secondary"
              className="min-h-11 px-3"
              onClick={() => setTheme(nextTheme)}
              aria-label={`Switch to ${nextTheme} mode`}
              title={`Switch to ${nextTheme} mode`}
            >
              {theme === "dark" ? <SunMedium size={17} /> : <MoonStar size={17} />}
              <span className="hidden sm:inline">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="min-h-11 px-3"
              onClick={() => {
                signOut();
                navigate("/login", { replace: true });
              }}
              aria-label="Log out"
              title="Log out"
            >
              <LogOut size={17} />
              <span className="hidden sm:inline">Log out</span>
            </Button>
          </div>
        </div>
      </header>

      <GlobalJobStatus />

      <main className="mx-auto max-w-[1760px] px-4 pb-24 pt-7 sm:px-6 sm:pb-8 lg:px-8">
        <Outlet />
      </main>

      {/* Mobile bottom navigation — hidden on md+ where the header nav is shown */}
      <nav
        className="fixed bottom-0 left-0 right-0 z-30 flex border-t border-white/10 bg-zinc-950/95 backdrop-blur-xl md:hidden"
        aria-label="Main navigation"
      >
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center justify-center gap-1 py-3 text-xs font-semibold transition ${
                isActive ? "text-teal-300" : "text-zinc-400 active:text-zinc-200"
              }`
            }
          >
            {({ isActive }) => (
              <>
                <item.icon size={22} strokeWidth={isActive ? 2.5 : 1.75} />
                <span>{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
