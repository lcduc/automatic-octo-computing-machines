import { useState } from "react";
import { Callout, Card, Field } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import { useSession } from "../../lib/session";
import type { Settings } from "../../lib/types";
import { useSaveSettings } from "./use-save-settings";

/** Same limit as the backend (MAX_SUGGESTED_QUESTIONS). */
const MAX_SUGGESTIONS = 6;
const COLOR_PATTERN = /^#[0-9a-fA-F]{6}$/;

export function WidgetTab({ settings, onSaved }: { settings: Settings; onSaved: (settings: Settings) => void }) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const { save, saving, error } = useSaveSettings(onSaved);
  const [title, setTitle] = useState(settings.widget_title);
  const [welcome, setWelcome] = useState(settings.widget_welcome_message);
  const [color, setColor] = useState(settings.widget_primary_color);
  const [suggestions, setSuggestions] = useState(settings.widget_suggested_questions.join("\n"));
  const questions = suggestions.split("\n").map((line) => line.trim()).filter(Boolean);
  const invalid = !COLOR_PATTERN.test(color) || questions.length > MAX_SUGGESTIONS;

  return (
    <Card title={t("settings.tab.widget")}>
      <div className="stack">
        <div className="form-grid">
          <Field label={t("widget.title")}>
            <input className="input" maxLength={80} value={title} disabled={!canWrite} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <div className="row">
            <Field label={t("widget.color")} hint={t("widget.colorHint")}>
              <input className="input mono" value={color} disabled={!canWrite} onChange={(e) => setColor(e.target.value)} />
            </Field>
            <input type="color" className="swatch" value={COLOR_PATTERN.test(color) ? color : "#000000"} disabled={!canWrite} onChange={(e) => setColor(e.target.value)} aria-label={t("widget.colorPicker")} />
          </div>
        </div>
        <Field label={t("widget.welcome")}>
          <textarea className="textarea" rows={3} maxLength={500} value={welcome} disabled={!canWrite} onChange={(e) => setWelcome(e.target.value)} />
        </Field>
        <Field label={t("widget.suggestions")} hint={t("widget.suggestionsHint", { max: MAX_SUGGESTIONS })} error={questions.length > MAX_SUGGESTIONS ? t("widget.tooMany", { max: MAX_SUGGESTIONS }) : undefined}>
          <textarea className="textarea" rows={5} value={suggestions} disabled={!canWrite} onChange={(e) => setSuggestions(e.target.value)} />
        </Field>
        {error && <Callout tone="danger">{error}</Callout>}
        {canWrite && (
          <div>
            <button
              type="button"
              className="btn btn--primary"
              disabled={saving || invalid}
              onClick={() => void save({ widget_title: title, widget_welcome_message: welcome, widget_primary_color: color, widget_suggested_questions: questions })}
            >
              {saving ? t("common.saving") : t("common.save")}
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}
