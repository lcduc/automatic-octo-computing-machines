import { Link, useSearchParams } from "react-router";
import { Badge, EmptyState, ErrorState, Field, LoadingState, PageHeader, Pagination } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import { query } from "../../lib/api";
import { OUTCOMES, type ConversationSummary, type Page } from "../../lib/types";
import { useApi } from "../../lib/use-api";

const PAGE_SIZE = 50;
const STATUSES = ["active", "handoff_pending", "staff_active", "closed"] as const;

export function ConversationsPage() {
  const { t, formatDateTime, formatNumber } = useI18n();
  const [params, setParams] = useSearchParams();
  const outcome = params.get("outcome") ?? "";
  const status = params.get("status") ?? "";
  const since = params.get("since") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const { data, error, loading, reload } = useApi<Page<ConversationSummary>>(
    `conversations${query({ outcome, status, since: since ? new Date(since).toISOString() : undefined, limit: PAGE_SIZE, offset })}`,
  );

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader title={t("conversations.title")} description={t("conversations.description")} />
      <div className="toolbar">
        <Field label={t("conversations.outcome")}>
          <select className="select" value={outcome} onChange={(e) => setFilter("outcome", e.target.value)}>
            <option value="">{t("common.all")}</option>
            {OUTCOMES.map((value) => (
              <option key={value} value={value}>
                {t(`outcome.${value}`)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("conversations.status")}>
          <select className="select" value={status} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">{t("common.all")}</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {t(`conversationStatus.${value}`)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("common.since")}>
          <input className="input" type="date" value={since} onChange={(e) => setFilter("since", e.target.value)} />
        </Field>
      </div>
      <section className="card">
        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && <LoadingState />}
        {data && data.items.length === 0 && <EmptyState title={t("conversations.empty")} />}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t("conversations.visitor")}</th>
                  <th scope="col">{t("conversations.status")}</th>
                  <th scope="col" className="table__num">
                    {t("conversations.messages")}
                  </th>
                  <th scope="col">{t("conversations.started")}</th>
                  <th scope="col">{t("conversations.lastActivity")}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((conversation) => (
                  <tr key={conversation.id}>
                    <td>
                      <Link to={`/conversations/${conversation.id}`} className="mono">
                        {conversation.end_user_id}
                      </Link>
                      <div className="small muted">{conversation.channel}</div>
                    </td>
                    <td>
                      <Badge tone={conversation.status === "handoff_pending" ? "warning" : "neutral"}>
                        {t(`conversationStatus.${conversation.status as (typeof STATUSES)[number]}`)}
                      </Badge>
                    </td>
                    <td className="table__num">{formatNumber(conversation.message_count)}</td>
                    <td className="small muted">{formatDateTime(conversation.created_at)}</td>
                    <td className="small muted">{formatDateTime(conversation.last_activity_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <Pagination total={data.total} limit={PAGE_SIZE} offset={offset} onChange={(value) => setParams({ ...Object.fromEntries(params), offset: String(value) })} />
        )}
      </section>
    </>
  );
}
