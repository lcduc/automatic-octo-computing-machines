import { useState, type FormEvent } from "react";
import { Callout, Card, Field } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { useSession } from "../../lib/session";
import type { Settings } from "../../lib/types";
import { useSaveSettings } from "./use-save-settings";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
/** Same bound as the backend's SettingsUpdate. */
const MAX_TICKET_REPLY_HOURS = 240;

function lines(text: string): string[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean);
}

/** Support hours, holidays, reply time and always-escalated topics (HND-06, HND-07, HND-14). */
export function SupportTab({ settings, onSaved }: { settings: Settings; onSaved: (settings: Settings) => void }) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const { save, saving, error } = useSaveSettings(onSaved);
  const [hours, setHours] = useState<Record<string, string>>(settings.support_hours);
  const [holidays, setHolidays] = useState(settings.support_holidays.join("\n"));
  const [replyHours, setReplyHours] = useState(settings.ticket_reply_hours);
  const [topics, setTopics] = useState(settings.handoff_topics.join("\n"));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void save({ support_hours: hours, support_holidays: lines(holidays), ticket_reply_hours: replyHours, handoff_topics: lines(topics) });
  };

  return (
    <form className="grid-2" onSubmit={submit}>
      <Card title={t("support.title")}>
        <div className="stack">
          <p className="small muted">{t("support.help")}</p>
          {DAYS.map((day) => (
            <Field key={day} label={t(`support.day.${day}` as MessageKey)}>
              <input className="input mono" placeholder="08:00-17:30" pattern="^$|^\d{2}:\d{2}-\d{2}:\d{2}$" value={hours[day] ?? ""} disabled={!canWrite}
                onChange={(e) => setHours({ ...hours, [day]: e.target.value.trim() })} />
            </Field>
          ))}
          <Field label={t("support.holidays")} hint={t("support.holidaysHint")}>
            <textarea className="textarea mono" rows={6} value={holidays} disabled={!canWrite} onChange={(e) => setHolidays(e.target.value)} />
          </Field>
        </div>
      </Card>
      <Card title={t("support.replyHours")}>
        <div className="stack">
          <Field label={t("support.replyHours")}>
            <input className="input" type="number" min={1} max={MAX_TICKET_REPLY_HOURS} step="0.5" required value={replyHours} disabled={!canWrite}
              onChange={(e) => setReplyHours(Number(e.target.value))} />
          </Field>
          <Field label={t("support.topics")} hint={t("support.topicsHint")}>
            <textarea className="textarea" rows={10} value={topics} disabled={!canWrite} onChange={(e) => setTopics(e.target.value)} />
          </Field>
          {error && <Callout tone="danger">{error}</Callout>}
          {canWrite && (
            <div>
              <button type="submit" className="btn btn--primary" disabled={saving}>{saving ? t("common.saving") : t("support.save")}</button>
            </div>
          )}
        </div>
      </Card>
    </form>
  );
}
