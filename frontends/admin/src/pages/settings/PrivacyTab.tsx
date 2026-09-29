import { useState, type FormEvent } from "react";
import { Callout, Card, Field } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { useSession } from "../../lib/session";
import type { Settings } from "../../lib/types";
import { DataSubjectCard } from "./DataSubjectCard";
import { useSaveSettings } from "./use-save-settings";

/** Same bounds as the backend's SettingsUpdate (models/retention_policy.py). */
const MIN_RETENTION_DAYS = 7;
const MIN_AUDIT_RETENTION_DAYS = 365;
const MAX_RETENTION_DAYS = 3650;

type RetentionKey =
  | "retention_chat_days"
  | "retention_anonymous_chat_days"
  | "retention_trace_days"
  | "retention_ticket_days"
  | "retention_audit_days";

const RETENTION_KEYS: readonly RetentionKey[] = [
  "retention_chat_days",
  "retention_anonymous_chat_days",
  "retention_trace_days",
  "retention_ticket_days",
  "retention_audit_days",
];

/** Retention periods (PRV-04, owners only) and data-subject requests (PRV-03). */
export function PrivacyTab({ settings, onSaved }: { settings: Settings; onSaved: (settings: Settings) => void }) {
  const { t } = useI18n();
  const { isOwner } = useSession();
  const { save, saving, error } = useSaveSettings(onSaved);
  const [days, setDays] = useState<Record<RetentionKey, number>>(
    () => Object.fromEntries(RETENTION_KEYS.map((key) => [key, settings[key]])) as Record<RetentionKey, number>,
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void save(days);
  };

  return (
    <div className="grid-2">
      <form onSubmit={submit}>
        <Card title={t("privacy.retention")}>
          <div className="stack">
            <p className="small muted">{t("privacy.retentionHelp")}</p>
            {RETENTION_KEYS.map((key) => (
              <Field key={key} label={t(`privacy.${key}` as MessageKey)}>
                <input
                  className="input"
                  type="number"
                  required
                  min={key === "retention_audit_days" ? MIN_AUDIT_RETENTION_DAYS : MIN_RETENTION_DAYS}
                  max={MAX_RETENTION_DAYS}
                  value={days[key]}
                  disabled={!isOwner}
                  onChange={(e) => setDays({ ...days, [key]: Number(e.target.value) })}
                />
              </Field>
            ))}
            {!isOwner && <Callout>{t("privacy.ownerOnly")}</Callout>}
            {error && <Callout tone="danger">{error}</Callout>}
            {isOwner && (
              <div>
                <button type="submit" className="btn btn--primary" disabled={saving}>{saving ? t("common.saving") : t("privacy.save")}</button>
              </div>
            )}
          </div>
        </Card>
      </form>
      {isOwner && <DataSubjectCard />}
    </div>
  );
}
