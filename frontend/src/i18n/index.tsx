import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  SUPPORTED_LANGUAGES,
  messages,
  type Language,
} from "./messages";

type MessageVars = Record<string, string | number | undefined>;
type DateInput = string | number | Date | null | undefined;

type I18nContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: string, vars?: MessageVars) => string;
  formatDateTime: (value: DateInput, options?: Intl.DateTimeFormatOptions) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

function resolveLanguage(value: string | null | undefined): Language | null {
  if (value && SUPPORTED_LANGUAGES.includes(value as Language)) {
    return value as Language;
  }
  return null;
}

function detectInitialLanguage(): Language {
  if (typeof window === "undefined") {
    return DEFAULT_LANGUAGE;
  }

  const stored = resolveLanguage(window.localStorage.getItem(LANGUAGE_STORAGE_KEY));
  if (stored) {
    return stored;
  }

  return navigator.language.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US";
}

function interpolate(template: string, vars?: MessageVars): string {
  if (!vars) {
    return template;
  }

  return template.replace(/\{(\w+)\}/g, (_, key: string) => {
    const value = vars[key];
    return value === undefined ? "" : String(value);
  });
}

function parseDate(value: Exclude<DateInput, null | undefined>): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  if (typeof value === "string") {
    const dateOnly = /^\d{4}-\d{2}-\d{2}$/;
    const parsed = new Date(dateOnly.test(value) ? `${value}T00:00:00` : value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function LanguageProvider({ children }: { children: ReactNode }): JSX.Element {
  const [language, setLanguage] = useState<Language>(detectInitialLanguage);

  useEffect(() => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    document.documentElement.lang = language;
  }, [language]);

  const value = useMemo<I18nContextValue>(() => {
    const translate = (key: string, vars?: MessageVars): string => {
      const template = messages[language][key] ?? messages[DEFAULT_LANGUAGE][key] ?? key;
      return interpolate(template, vars);
    };

    return {
      language,
      setLanguage,
      t: translate,
      formatDateTime: (input, options) => {
        if (input === null || input === undefined || input === "") {
          return "-";
        }

        const date = parseDate(input);
        if (!date) {
          return String(input);
        }

        return new Intl.DateTimeFormat(language, options).format(date);
      },
      formatNumber: (input, options) => new Intl.NumberFormat(language, options).format(input),
    };
  }, [language]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used within LanguageProvider");
  }
  return context;
}

export type { Language };
