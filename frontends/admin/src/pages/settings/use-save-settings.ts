import { useState } from "react";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import type { Settings } from "../../lib/types";

/** PATCH /settings with toasts; returns the saved settings to the page. */
export function useSaveSettings(onSaved: (settings: Settings) => void) {
  const { t } = useI18n();
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (changes: Partial<Settings>) => {
    setSaving(true);
    setError(null);
    try {
      const saved = await adminApi<Settings>("settings", { method: "PATCH", body: changes });
      toast.success(t("settings.saved"));
      onSaved(saved);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const reset = async (key: keyof Settings) => {
    setSaving(true);
    setError(null);
    try {
      const saved = await adminApi<Settings>(`settings/${key}`, { method: "DELETE" });
      toast.success(t("settings.resetDone"));
      onSaved(saved);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return { save, reset, saving, error };
}
