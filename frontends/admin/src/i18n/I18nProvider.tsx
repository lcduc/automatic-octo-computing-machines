import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { en } from "./en";
import { vi, type MessageKey } from "./vi";

export type Language = "vi" | "en";
const DICTIONARIES: Record<Language, Record<MessageKey, string>> = { vi, en };
const LOCALES: Record<Language, string> = { vi: "vi-VN", en: "en-GB" };
const STORAGE_KEY = "admin.language";

export type Translate = (key: MessageKey, params?: Record<string, string | number>) => string;

interface I18nValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: Translate;
  formatDateTime: (value: string | null | undefined) => string;
  formatNumber: (value: number | null | undefined, digits?: number) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

function initialLanguage(): Language {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "vi" || saved === "en") return saved;
  } catch {
    // Storage can be blocked (private mode); the default language is fine.
  }
  return "vi";
}

/** Replace `{name}` placeholders with values. */
export function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in params ? String(params[name]) : match));
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(initialLanguage);

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next);
    document.documentElement.lang = next;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not persisted; the choice still applies for this visit.
    }
  }, []);

  const value = useMemo<I18nValue>(() => {
    const dictionary = DICTIONARIES[language];
    const dateTime = new Intl.DateTimeFormat(LOCALES[language], { dateStyle: "short", timeStyle: "short" });
    return {
      language,
      setLanguage,
      t: (key, params) => interpolate(dictionary[key], params),
      formatDateTime: (input) => (input ? dateTime.format(new Date(input)) : "—"),
      formatNumber: (input, digits = 0) =>
        input === null || input === undefined
          ? "—"
          : new Intl.NumberFormat(LOCALES[language], { maximumFractionDigits: digits }).format(input),
    };
  }, [language, setLanguage]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
