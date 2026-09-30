import { Monitor, Moon, Sun } from "lucide-react";
import { useI18n } from "../../i18n/I18nProvider";
import { THEME_CYCLE, useTheme, type ThemePreference } from "../../lib/theme";

const ICONS = { light: Sun, dark: Moon, system: Monitor } as const;

/** One button cycling light → dark → follow the system. */
export function ThemeToggle({ className = "btn btn--ghost btn--icon" }: { className?: string }) {
  const { t } = useI18n();
  const { preference, setPreference } = useTheme();
  const next: ThemePreference = THEME_CYCLE[(THEME_CYCLE.indexOf(preference) + 1) % THEME_CYCLE.length] ?? "system";
  const Icon = ICONS[preference];
  return (
    <button
      type="button"
      className={className}
      onClick={() => setPreference(next)}
      aria-label={t("theme.label", { current: t(`theme.${preference}`), next: t(`theme.${next}`) })}
      title={t("theme.label", { current: t(`theme.${preference}`), next: t(`theme.${next}`) })}
    >
      <Icon size={17} aria-hidden />
    </button>
  );
}
