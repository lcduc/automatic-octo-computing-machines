import { CircleCheck, Clock, Hourglass, MailCheck } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { Transcript } from "../components/conversations/Transcript";
import { LegalHoldButton } from "../components/privacy/LegalHoldButton";
import { Drawer } from "../components/ui/Modal";
import { Badge, Callout, EmptyState, ErrorState, Field, KpiCard, LoadingState, PageHeader, Pagination } from "../components/ui/primitives";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n/I18nProvider";
import type { MessageKey } from "../i18n/vi";
import { adminApi, query } from "../lib/api";
import { HANDOFF_STATUS_TONES } from "../lib/labels";
import { useSession } from "../lib/session";
import { HANDOFF_REASONS, type ConversationDetail, type Handoff, type HandoffContact, type HandoffStatus, type Page } from "../lib/types";
import { useApi } from "../lib/use-api";

const PAGE_SIZE = 50;
const STATUSES: HandoffStatus[] = ["open", "assigned", "answered", "closed"];
/** The queue is watched live by agents. */
const QUEUE_REFRESH_MS = 20_000;

/** An open or assigned ticket past its due time (the SLA timer, HND-16). */
function overdue(handoff: Handoff): boolean {
  return (handoff.status === "open" || handoff.status === "assigned") && !!handoff.due_at && new Date(handoff.due_at) < new Date();
}

function reasonLabel(reason: string): MessageKey {
  return (HANDOFF_REASONS as readonly string[]).includes(reason) ? (`handoffReason.${reason}` as MessageKey) : "handoffReason.other";
}

function HandoffDrawer({ handoff, onClose, onUpdated }: { handoff: Handoff; onClose: () => void; onUpdated: (handoff: Handoff) => void }) {
  const { t, formatDateTime } = useI18n();
  const { admin, canHandoff, isOwner } = useSession();
  const toast = useToast();
  const conversation = useApi<ConversationDetail>(`conversations/${handoff.conversation_id}`);
  const [note, setNote] = useState(handoff.note ?? "");
  const [answer, setAnswer] = useState("");
  const [contact, setContact] = useState<HandoffContact | null>(null);
  const [saving, setSaving] = useState(false);

  const call = async (path: string, body: object) => {
    setSaving(true);
    try {
      const updated = await adminApi<Handoff>(path, { method: path.endsWith("/answer") ? "POST" : "PATCH", body });
      toast.success(t("handoffs.updated"));
      onUpdated(updated);
      conversation.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const reveal = async () => {
    try {
      setContact(await adminApi<HandoffContact>(`handoffs/${handoff.id}/reveal-contact`, { method: "POST" }));
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <Drawer title={t("handoffs.detail")} onClose={onClose}>
      <dl className="dl">
        <dt>{t("handoffs.reason")}</dt>
        <dd>{t(reasonLabel(handoff.reason))}</dd>
        <dt>{t("handoffs.status")}</dt>
        <dd><Badge tone={HANDOFF_STATUS_TONES[handoff.status]}>{t(`handoffStatus.${handoff.status}`)}</Badge></dd>
        <dt>{t("handoffs.due")}</dt>
        <dd>{handoff.due_at ? formatDateTime(handoff.due_at) : "—"} {overdue(handoff) && <Badge tone="danger">{t("handoffs.overdue")}</Badge>}</dd>
        <dt>{t("handoffs.contact")}</dt>
        <dd>
          {contact
            ? [contact.name, contact.email, contact.phone].filter(Boolean).join(" · ")
            : [handoff.contact_email, handoff.contact_phone].filter(Boolean).join(" · ") || (handoff.signed_in ? t("handoffs.inChat") : "—")}
          {isOwner && handoff.has_contact && !contact && (
            <button type="button" className="btn btn--sm btn--ghost" onClick={() => void reveal()}>{t("handoffs.reveal")}</button>
          )}
        </dd>
        {handoff.details && (<><dt>{t("handoffs.details")}</dt><dd>{handoff.details}</dd></>)}
        <dt>{t("handoffs.assignedTo")}</dt>
        <dd>{handoff.assigned_to ?? "—"}</dd>
        <dt>{t("legalHold.label")}</dt>
        <dd>
          <LegalHoldButton path={`handoffs/${handoff.id}`} held={handoff.legal_hold} onChange={(held) => onUpdated({ ...handoff, legal_hold: held })} />
          {!handoff.legal_hold && !isOwner && "—"}
        </dd>
        {handoff.answered_at && (<><dt>{t("handoffs.answeredAt")}</dt><dd>{formatDateTime(handoff.answered_at)} {handoff.emailed_at && <MailCheck size={14} aria-label={t("handoffs.emailed")} />}</dd></>)}
      </dl>
      {canHandoff ? (
        <div className="stack card card__body">
          {handoff.status !== "closed" && (
            <>
              <Field label={t("handoffs.answer")} hint={t("handoffs.answerHint")}>
                <textarea className="textarea" rows={4} maxLength={5000} value={answer} onChange={(e) => setAnswer(e.target.value)} />
              </Field>
              <div className="toolbar">
                <button type="button" className="btn btn--primary" disabled={saving || !answer.trim()} onClick={() => void call(`handoffs/${handoff.id}/answer`, { text: answer })}>
                  {t("handoffs.sendAnswer")}
                </button>
                {handoff.assigned_to !== admin.email && (
                  <button type="button" className="btn" disabled={saving} onClick={() => void call(`handoffs/${handoff.id}`, { assigned_to: admin.email })}>
                    {t("handoffs.assignToMe")}
                  </button>
                )}
                <button type="button" className="btn" disabled={saving} onClick={() => void call(`handoffs/${handoff.id}`, { status: "closed" })}>
                  {t("handoffs.close")}
                </button>
              </div>
            </>
          )}
          {handoff.status === "closed" && (
            <div>
              <button type="button" className="btn" disabled={saving} onClick={() => void call(`handoffs/${handoff.id}`, { status: "open" })}>{t("handoffs.reopen")}</button>
            </div>
          )}
          <Field label={t("handoffs.note")} hint={t("handoffs.noteHint")}>
            <textarea className="textarea" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div>
            <button type="button" className="btn" disabled={saving} onClick={() => void call(`handoffs/${handoff.id}`, { note: note.trim() })}>
              {t("common.save")}
            </button>
          </div>
        </div>
      ) : (
        <Callout>{t("handoffs.readOnly")}</Callout>
      )}
      <h3>{t("handoffs.conversation")}</h3>
      {conversation.error && <ErrorState message={conversation.error} onRetry={conversation.reload} />}
      {conversation.loading && <LoadingState />}
      {conversation.data && <Transcript messages={conversation.data.messages} />}
    </Drawer>
  );
}

/** Support tickets (HND-13..16): counters, queue with due times, detail drawer to answer. */
export function HandoffsPage() {
  const { t, formatDateTime, formatNumber } = useI18n();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const [selected, setSelected] = useState<Handoff | null>(null);
  const list = useApi<Page<Handoff>>(`handoffs${query({ status, limit: PAGE_SIZE, offset })}`, QUEUE_REFRESH_MS);
  const open = useApi<Page<Handoff>>(`handoffs${query({ status: "open", limit: 1 })}`, QUEUE_REFRESH_MS);
  const assigned = useApi<Page<Handoff>>(`handoffs${query({ status: "assigned", limit: 1 })}`, QUEUE_REFRESH_MS);
  const answered = useApi<Page<Handoff>>(`handoffs${query({ status: "answered", limit: 1 })}`, QUEUE_REFRESH_MS);

  const refreshAll = () => [list, open, assigned, answered].forEach((state) => state.reload());

  return (
    <>
      <PageHeader title={t("handoffs.title")} description={t("handoffs.description")} />
      <div className="kpi-grid">
        <KpiCard icon={<Hourglass size={20} />} tone="rose" label={t("handoffStatus.open")} value={formatNumber(open.data?.total)} />
        <KpiCard icon={<Clock size={20} />} tone="gold" label={t("handoffStatus.assigned")} value={formatNumber(assigned.data?.total)} />
        <KpiCard icon={<CircleCheck size={20} />} tone="teal" label={t("handoffStatus.answered")} value={formatNumber(answered.data?.total)} />
      </div>
      <div className="toolbar">
        <Field label={t("handoffs.status")}>
          <select className="select" value={status} onChange={(e) => setParams(e.target.value ? { status: e.target.value } : {})}>
            <option value="">{t("common.all")}</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {t(`handoffStatus.${value}`)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <section className="card">
        {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
        {list.loading && <LoadingState />}
        {list.data && list.data.items.length === 0 && <EmptyState title={t("handoffs.empty")} />}
        {list.data && list.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t("handoffs.created")}</th>
                  <th scope="col">{t("handoffs.reason")}</th>
                  <th scope="col">{t("handoffs.status")}</th>
                  <th scope="col">{t("handoffs.due")}</th>
                  <th scope="col">{t("handoffs.assignedTo")}</th>
                  <th scope="col">
                    <span className="sr-only">{t("common.actions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((handoff) => (
                  <tr key={handoff.id}>
                    <td className="small">{formatDateTime(handoff.created_at)}</td>
                    <td>{t(reasonLabel(handoff.reason))}</td>
                    <td>
                      <Badge tone={HANDOFF_STATUS_TONES[handoff.status]}>{t(`handoffStatus.${handoff.status}`)}</Badge>
                    </td>
                    <td className="small">
                      {handoff.due_at ? formatDateTime(handoff.due_at) : "—"} {overdue(handoff) && <Badge tone="danger">{t("handoffs.overdue")}</Badge>}
                    </td>
                    <td className="small">{handoff.assigned_to ?? "—"}</td>
                    <td>
                      <button type="button" className="btn btn--sm" onClick={() => setSelected(handoff)}>
                        {t("handoffs.open")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.data && (
          <Pagination total={list.data.total} limit={PAGE_SIZE} offset={offset} onChange={(value) => setParams({ ...Object.fromEntries(params), offset: String(value) })} />
        )}
      </section>
      {selected && (
        <HandoffDrawer
          key={`${selected.id}-${selected.updated_at}`}
          handoff={selected}
          onClose={() => setSelected(null)}
          onUpdated={(updated) => {
            setSelected(updated);
            refreshAll();
          }}
        />
      )}
    </>
  );
}
