import { useState } from "react";
import { Callout, Card, Field } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { useSession } from "../../lib/session";
import type { Settings } from "../../lib/types";
import { useSaveSettings } from "./use-save-settings";

type ReplyKey = "deny_message" | "handoff_message" | "guard_block_message" | "greeting_message" | "thanks_message";
const REPLIES: Array<{ key: ReplyKey; label: MessageKey; hint: MessageKey }> = [
  { key: "deny_message", label: "settings.deny", hint: "settings.denyHint" },
  { key: "handoff_message", label: "settings.handoff", hint: "settings.handoffHint" },
  { key: "guard_block_message", label: "settings.guard", hint: "settings.guardHint" },
  { key: "greeting_message", label: "settings.greeting", hint: "settings.greetingHint" },
  { key: "thanks_message", label: "settings.thanks", hint: "settings.thanksHint" },
];
/** Same limits as the backend's SettingsUpdate. */
const MAX_REPLY = 2000;
const MAX_INSTRUCTIONS = 4000;

export function ChatBehaviorTab({ settings, onSaved }: { settings: Settings; onSaved: (settings: Settings) => void }) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const [draft, setDraft] = useState(settings);
  const { save, saving, error } = useSaveSettings(onSaved);
  const changed = (Object.keys(draft) as Array<keyof Settings>).filter((key) => JSON.stringify(draft[key]) !== JSON.stringify(settings[key]));

  return (
    <Card title={t("settings.tab.chat")}>
      <div className="stack">
        <Field label={t("settings.fallback")} hint={t("settings.fallbackHint")}>
          <select className="select" value={draft.fallback_mode} disabled={!canWrite} onChange={(e) => setDraft({ ...draft, fallback_mode: e.target.value as Settings["fallback_mode"] })}>
            <option value="deny">{t("settings.fallback.deny")}</option>
            <option value="handoff">{t("settings.fallback.handoff")}</option>
          </select>
        </Field>
        <Field label={t("settings.instructions")} hint={t("settings.instructionsHint", { max: MAX_INSTRUCTIONS })}>
          <textarea className="textarea" rows={5} maxLength={MAX_INSTRUCTIONS} disabled={!canWrite} value={draft.assistant_instructions} onChange={(e) => setDraft({ ...draft, assistant_instructions: e.target.value })} />
        </Field>
        {REPLIES.map((reply) => (
          <Field key={reply.key} label={t(reply.label)} hint={t(reply.hint)}>
            <textarea className="textarea" rows={3} maxLength={MAX_REPLY} disabled={!canWrite} value={draft[reply.key]} onChange={(e) => setDraft({ ...draft, [reply.key]: e.target.value })} />
          </Field>
        ))}
        {error && <Callout tone="danger">{error}</Callout>}
        {canWrite && (
          <div className="row">
            <button type="button" className="btn btn--primary" disabled={saving || changed.length === 0} onClick={() => void save(Object.fromEntries(changed.map((key) => [key, draft[key]])))}>
              {saving ? t("common.saving") : t("common.save")}
            </button>
            {changed.length > 0 && <span className="small muted">{t("settings.unsaved", { count: changed.length })}</span>}
          </div>
        )}
      </div>
    </Card>
  );
}
