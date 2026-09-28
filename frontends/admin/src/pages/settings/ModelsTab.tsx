import { RotateCcw } from "lucide-react";
import { useState } from "react";
import { Badge, Callout, Card, Field } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { useSession } from "../../lib/session";
import type { Settings, SystemStatus } from "../../lib/types";
import { useSaveSettings } from "./use-save-settings";

type ModelKey = "chat_model" | "light_model";
type TuningKey = "similarity_threshold" | "semantic_weight" | "retrieval_top_k" | "max_context_chunks";

const MODELS: Array<{ key: ModelKey; label: MessageKey; hint: MessageKey }> = [
  { key: "chat_model", label: "models.chat", hint: "models.chatHint" },
  { key: "light_model", label: "models.light", hint: "models.lightHint" },
];
/** Same bounds as the backend's SettingsUpdate. */
const TUNING: Array<{ key: TuningKey; label: MessageKey; hint: MessageKey; min: number; max: number; step: number }> = [
  { key: "similarity_threshold", label: "models.threshold", hint: "models.thresholdHint", min: 0, max: 1, step: 0.01 },
  { key: "semantic_weight", label: "models.weight", hint: "models.weightHint", min: 0, max: 1, step: 0.05 },
  { key: "retrieval_top_k", label: "models.topK", hint: "models.topKHint", min: 1, max: 20, step: 1 },
  { key: "max_context_chunks", label: "models.contextChunks", hint: "models.contextChunksHint", min: 1, max: 20, step: 1 },
];

interface ModelsTabProps {
  settings: Settings;
  defaults: Settings;
  system?: SystemStatus | null;
  onSaved: (settings: Settings) => void;
}

/** Live model choice and retrieval tuning; .env values are the defaults each field can reset to. */
export function ModelsTab({ settings, defaults, system, onSaved }: ModelsTabProps) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const { save, reset, saving, error } = useSaveSettings(onSaved);
  const [draft, setDraft] = useState(settings);

  const isOverridden = (key: keyof Settings) => settings[key] !== defaults[key];

  const resetButton = (key: keyof Settings) =>
    canWrite && isOverridden(key) ? (
      <button type="button" className="btn btn--ghost btn--sm" disabled={saving} onClick={() => void reset(key)}>
        <RotateCcw size={13} aria-hidden />
        {t("models.reset", { value: String(defaults[key]) })}
      </button>
    ) : null;

  return (
    <div className="grid-2">
      <Card title={t("models.title")}>
        <div className="stack">
          <p className="small muted">{t("models.help", { provider: system?.llm_provider ?? "—" })}</p>
          {MODELS.map((model) => (
            <div key={model.key} className="stack">
              <Field label={t(model.label)} hint={t(model.hint)}>
                <input className="input mono" value={draft[model.key]} maxLength={100} disabled={!canWrite || saving} onChange={(e) => setDraft({ ...draft, [model.key]: e.target.value.trim() })} />
              </Field>
              <div className="row">
                {isOverridden(model.key) ? <Badge tone="gold">{t("models.overridden")}</Badge> : <Badge>{t("models.default")}</Badge>}
                {canWrite && (
                  <button type="button" className="btn btn--sm btn--primary" disabled={saving || !draft[model.key] || draft[model.key] === settings[model.key]} onClick={() => void save({ [model.key]: draft[model.key] })}>
                    {saving ? t("models.testing") : t("models.testAndSave")}
                  </button>
                )}
                {resetButton(model.key)}
              </div>
            </div>
          ))}
          <Callout>{t("models.envOnly", { embedding: system?.embedding_model ?? "—", reranker: system?.reranker_loaded ? t("common.on") : t("common.off") })}</Callout>
        </div>
      </Card>

      <Card title={t("models.retrieval")}>
        <div className="stack">
          {TUNING.map((item) => (
            <div key={item.key} className="stack">
              <Field label={`${t(item.label)}: ${draft[item.key]}`} hint={t(item.hint)}>
                <input type="range" min={item.min} max={item.max} step={item.step} value={draft[item.key]} disabled={!canWrite || saving} onChange={(e) => setDraft({ ...draft, [item.key]: Number(e.target.value) })} />
              </Field>
              <div className="row">
                {isOverridden(item.key) ? <Badge tone="gold">{t("models.overridden")}</Badge> : <Badge>{t("models.default")}</Badge>}
                {resetButton(item.key)}
              </div>
            </div>
          ))}
          {error && <Callout tone="danger">{error}</Callout>}
          {canWrite && (
            <div>
              <button
                type="button"
                className="btn btn--primary"
                disabled={saving || TUNING.every((item) => draft[item.key] === settings[item.key])}
                onClick={() => void save(Object.fromEntries(TUNING.filter((item) => draft[item.key] !== settings[item.key]).map((item) => [item.key, draft[item.key]])))}
              >
                {saving ? t("common.saving") : t("models.saveRetrieval")}
              </button>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
