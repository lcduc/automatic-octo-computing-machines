import { CheckCircle2, ChevronDown, ChevronUp, Clock, UserCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Callout } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { HandoffContact } from "./use-demo-chat";

interface HandoffCardProps {
  handoffId: string;
  replyBy?: string;
  onSubmit: (contact: HandoffContact) => Promise<string | null>;
}

/** The ticket a turn opened, with the visitor's contact form (e-mail or phone, plus consent). */
export function HandoffCard({ handoffId, replyBy, onSubmit }: HandoffCardProps) {
  const { t, formatDateTime } = useI18n();
  const [formOpen, setFormOpen] = useState(false);
  const [contact, setContact] = useState<HandoffContact>({ name: "", email: "", phone: "", details: "", consent: false });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const change = (patch: Partial<HandoffContact>) => setContact((current) => ({ ...current, ...patch }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const reachable = Boolean(contact.email?.trim() || contact.phone?.trim());
    if (!reachable) return setError(t("chat.contactNeeded"));
    if (!contact.consent) return setError(t("chat.consentNeeded"));
    setBusy(true);
    const problem = await onSubmit(contact);
    setBusy(false);
    if (problem) return setError(problem);
    setSent(true);
  };

  return (
    <div className="handoff-card">
      <div className="handoff-card__head">
        <span className="handoff-card__icon" aria-hidden>
          <UserCheck size={18} />
        </span>
        <div>
          <strong>{t("chat.handoffTitle")}</strong>
          <p className="small">{t("chat.handoffBody")}</p>
        </div>
      </div>
      <div className="handoff-card__ticket">
        <span>{t("chat.ticket", { code: handoffId.slice(0, 8).toUpperCase() })}</span>
        <span className="row">
          <Clock size={13} aria-hidden />
          {replyBy ? t("chat.replyBy", { time: formatDateTime(replyBy) }) : t("chat.waiting")}
        </span>
      </div>
      {sent ? (
        <p className="handoff-card__sent" role="status">
          <CheckCircle2 size={16} aria-hidden />
          {t("chat.contactSaved")}
        </p>
      ) : (
        <>
          <button type="button" className="handoff-card__toggle" aria-expanded={formOpen} onClick={() => setFormOpen((value) => !value)}>
            {formOpen ? t("chat.hideContact") : t("chat.leaveContact")}
            {formOpen ? <ChevronUp size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
          </button>
          {formOpen && (
            <form className="handoff-card__form" onSubmit={submit}>
              {error && <Callout tone="danger">{error}</Callout>}
              <input className="input" aria-label={t("chat.contactName")} placeholder={t("chat.contactName")} maxLength={128} value={contact.name} onChange={(e) => change({ name: e.target.value })} />
              <div className="grid-2 grid-2--tight">
                <input className="input" type="email" aria-label={t("login.email")} placeholder={t("login.email")} maxLength={255} value={contact.email} onChange={(e) => change({ email: e.target.value })} />
                <input className="input" type="tel" aria-label={t("chat.contactPhone")} placeholder={t("chat.contactPhone")} maxLength={32} value={contact.phone} onChange={(e) => change({ phone: e.target.value })} />
              </div>
              <textarea className="textarea" rows={2} aria-label={t("chat.contactDetails")} placeholder={t("chat.contactDetails")} maxLength={2000} value={contact.details} onChange={(e) => change({ details: e.target.value })} />
              <label className="checkbox small">
                <input type="checkbox" checked={contact.consent} onChange={(e) => change({ consent: e.target.checked })} />
                {t("chat.consent")}
              </label>
              <div className="row row--between">
                <Link to="/handoffs?status=open" className="small">
                  {t("chat.openHandoffs")}
                </Link>
                <button type="submit" className="btn btn--primary btn--sm" disabled={busy}>
                  {t("chat.sendContact")}
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </div>
  );
}
