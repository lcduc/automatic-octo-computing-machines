/**
 * Light / dark theme. The choice (light, dark or follow the system) is kept in
 * localStorage like the language; the resolved theme is set as
 * `<html data-theme>`, which tokens.css switches on.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type Theme = "light" | "dark";

const STORAGE_KEY = "admin.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";
/** The order the topbar button cycles through. */
export const THEME_CYCLE: ThemePreference[] = ["light", "dark", "system"];

/** The theme to show for a preference, given whether the OS asks for dark. */
export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): Theme {
  if (preference === "system") return systemPrefersDark ? "dark" : "light";
  return preference;
}

function storedPreference(): ThemePreference {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark" || saved === "system") return saved;
  } catch {
    // Storage can be blocked (private mode); following the system is fine.
  }
  return "system";
}

function darkQuery(): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY) : null;
}

function apply(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

/** Set the stored theme before the first render, so the page does not flash light. */
export function applyStoredTheme(): void {
  apply(resolveTheme(storedPreference(), darkQuery()?.matches ?? false));
}

interface ThemeValue {
  preference: ThemePreference;
  theme: Theme;
  setPreference: (preference: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(storedPreference);
  const [systemDark, setSystemDark] = useState(() => darkQuery()?.matches ?? false);
  const theme = resolveTheme(preference, systemDark);

  useEffect(() => {
    const query = darkQuery();
    if (!query) return;
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  useEffect(() => apply(theme), [theme]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not persisted when storage is blocked; the choice still applies to this visit.
    }
  }, []);

  const value = useMemo(() => ({ preference, theme, setPreference }), [preference, theme, setPreference]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
