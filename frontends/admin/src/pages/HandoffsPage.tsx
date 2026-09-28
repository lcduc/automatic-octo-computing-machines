import { useState } from "react";
import { useSearchParams } from "react-router";
import { Transcript } from "../components/conversations/Transcript";
import { Drawer } from "../components/ui/Modal";
import { Badge, Callout, EmptyState, ErrorState, Field, KpiCard, LoadingState, PageHeader, Pagination } from "../components/ui/primitives";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n/I18nProvider";
import { adminApi, query } from "../lib/api";
import { HANDOFF_STATUS_TONES } from "../lib/labels";
import { useSession } from "../lib/session";
import type { ConversationDetail, Handoff, HandoffStatus, Page } from "../lib/types";
import { useApi } from "../lib/use-api";
import { CircleCheck, Clock, Hourglass } from "lucide-react";

const PAGE_SIZE = 50;
const STATUSES: HandoffStatus[] = ["pending", "in_progress", "resolved"];
/** The queue is watched live by agents. */
const QUEUE_REFRESH_MS = 20_000;

function HandoffDrawer({ handoff, onClose, onUpdated }: { handoff: Handoff; onClose: () => void; onUpdated: (handoff: Handoff) => void }) {
  const { t, formatDateTime } = useI18n();
  const { canHandoff } = useSession();
  const toast = useToast();
  const conversation = useApi<ConversationDetail>(`conversations/${handoff.conversation_id}`);
  const [status, setStatus] = useState<HandoffStatus>(handoff.status);
  const [note, setNote] = useState(handoff.note ?? "");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await adminApi<Handoff>(`handoffs/${handoff.id}`, { method: "PATCH", body: { status, note: note.trim() || null } });
      toast.success(t("handoffs.updated"));
      onUpdated(updated);
    } catch (reason) {
      toast.error((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer title={t("handoffs.detail")} onClose={onClose}>
      <dl className="dl">
        <dt>{t("handoffs.reason")}</dt>
        <dd>{t(`handoffReason.${handoff.reason === "no_knowledge" ? "no_knowledge" : "user_request"}`)}</dd>
        <dt>{t("handoffs.created")}</dt>
        <dd>{formatDateTime(handoff.created_at)}</dd>
        <dt>{t("handoffs.updatedAt")}</dt>
        <dd>{formatDateTime(handoff.updated_at)}</dd>
      </dl>
      {canHandoff ? (
        <div className="stack card card__body">
          <Field label={t("handoffs.status")}>
            <select className="select" value={status} onChange={(e) => setStatus(e.target.value as HandoffStatus)}>
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {t(`handoffStatus.${value}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("handoffs.note")} hint={t("handoffs.noteHint")}>
            <textarea className="textarea" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div>
            <button type="button" className="btn btn--primary" disabled={saving} onClick={() => void save()}>
              {saving ? t("common.saving") : t("common.save")}
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

/** Transfer-to-human queue in the giz HandoffDesk layout: counters, table, detail drawer. */
export function HandoffsPage() {
  const { t, formatDateTime, formatNumber } = useI18n();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const [selected, setSelected] = useState<Handoff | null>(null);
  const list = useApi<Page<Handoff>>(`handoffs${query({ status, limit: PAGE_SIZE, offset })}`, QUEUE_REFRESH_MS);
  const pending = useApi<Page<Handoff>>(`handoffs${query({ status: "pending", limit: 1 })}`, QUEUE_REFRESH_MS);
  const running = useApi<Page<Handoff>>(`handoffs${query({ status: "in_progress", limit: 1 })}`, QUEUE_REFRESH_MS);
  const resolved = useApi<Page<Handoff>>(`handoffs${query({ status: "resolved", limit: 1 })}`, QUEUE_REFRESH_MS);

  const refreshAll = () => [list, pending, running, resolved].forEach((state) => state.reload());

  return (
    <>
      <PageHeader title={t("handoffs.title")} description={t("handoffs.description")} />
      <div className="kpi-grid">
        <KpiCard icon={<Hourglass size={20} />} tone="rose" label={t("handoffStatus.pending")} value={formatNumber(pending.data?.total)} />
        <KpiCard icon={<Clock size={20} />} tone="gold" label={t("handoffStatus.in_progress")} value={formatNumber(running.data?.total)} />
        <KpiCard icon={<CircleCheck size={20} />} tone="teal" label={t("handoffStatus.resolved")} value={formatNumber(resolved.data?.total)} />
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
                  <th scope="col">{t("handoffs.note")}</th>
                  <th scope="col">
                    <span className="sr-only">{t("common.actions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((handoff) => (
                  <tr key={handoff.id}>
                    <td className="small">{formatDateTime(handoff.created_at)}</td>
                    <td>{t(`handoffReason.${handoff.reason === "no_knowledge" ? "no_knowledge" : "user_request"}`)}</td>
                    <td>
                      <Badge tone={HANDOFF_STATUS_TONES[handoff.status]}>{t(`handoffStatus.${handoff.status}`)}</Badge>
                    </td>
                    <td className="small truncate">{handoff.note ?? "—"}</td>
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
          key={selected.id}
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
