import { useState } from "react";
import { useSearchParams } from "react-router";
import { Drawer } from "../components/ui/Modal";
import { Badge, EmptyState, ErrorState, Field, JsonBlock, LoadingState, PageHeader, Pagination } from "../components/ui/primitives";
import { useI18n } from "../i18n/I18nProvider";
import { query } from "../lib/api";
import { statusTone } from "../lib/labels";
import type { AuditEntry, Page } from "../lib/types";
import { useApi } from "../lib/use-api";

const PAGE_SIZE = 50;
const METHODS = ["POST", "PATCH", "DELETE"];

/** Append-only record of every admin change and sign-in attempt (owner only). */
export function AuditPage() {
  const { t, formatDateTime } = useI18n();
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const filters = {
    actor: params.get("actor") ?? "",
    method: params.get("method") ?? "",
    path_contains: params.get("path") ?? "",
    since: params.get("since") ?? "",
  };
  const offset = Number(params.get("offset") ?? 0);
  const { data, error, loading, reload } = useApi<Page<AuditEntry>>(
    `audit${query({ ...filters, since: filters.since ? new Date(filters.since).toISOString() : undefined, limit: PAGE_SIZE, offset })}`,
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
      <PageHeader title={t("audit.title")} description={t("audit.description")} />
      <div className="toolbar">
        <Field label={t("audit.actor")}>
          <input className="input" value={filters.actor} onChange={(e) => setFilter("actor", e.target.value)} />
        </Field>
        <Field label={t("audit.method")}>
          <select className="select" value={filters.method} onChange={(e) => setFilter("method", e.target.value)}>
            <option value="">{t("common.all")}</option>
            {METHODS.map((method) => (
              <option key={method} value={method}>
                {method}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("audit.path")}>
          <input className="input mono" value={filters.path_contains} onChange={(e) => setFilter("path", e.target.value)} placeholder="settings" />
        </Field>
        <Field label={t("common.since")}>
          <input className="input" type="date" value={filters.since} onChange={(e) => setFilter("since", e.target.value)} />
        </Field>
      </div>
      <section className="card">
        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && <LoadingState />}
        {data && data.items.length === 0 && <EmptyState title={t("audit.empty")} />}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t("audit.when")}</th>
                  <th scope="col">{t("audit.actor")}</th>
                  <th scope="col">{t("audit.action")}</th>
                  <th scope="col">{t("audit.result")}</th>
                  <th scope="col">
                    <span className="sr-only">{t("common.actions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((entry) => (
                  <tr key={entry.id}>
                    <td className="small">{formatDateTime(entry.created_at)}</td>
                    <td>
                      {entry.actor_email ?? "—"}
                      {entry.actor_role && <div className="small muted">{t(`role.${entry.actor_role}`)}</div>}
                    </td>
                    <td className="mono">
                      {entry.method} {entry.path.replace("/api/v1/admin", "")}
                    </td>
                    <td>
                      <Badge tone={statusTone(entry.status_code)}>{entry.status_code}</Badge>
                    </td>
                    <td>
                      <button type="button" className="btn btn--sm" onClick={() => setSelected(entry)}>
                        {t("audit.details")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pagination total={data.total} limit={PAGE_SIZE} offset={offset} onChange={(value) => setParams({ ...Object.fromEntries(params), offset: String(value) })} />}
      </section>
      {selected && (
        <Drawer title={`${selected.method} ${selected.path.replace("/api/v1/admin", "")}`} onClose={() => setSelected(null)}>
          <dl className="dl">
            <dt>{t("audit.when")}</dt>
            <dd>{formatDateTime(selected.created_at)}</dd>
            <dt>{t("audit.actor")}</dt>
            <dd>{selected.actor_email ?? "—"}</dd>
            <dt>{t("audit.result")}</dt>
            <dd>{selected.status_code}</dd>
            <dt>{t("audit.ip")}</dt>
            <dd className="mono">{selected.client_ip ?? "—"}</dd>
            <dt>{t("logs.requestId")}</dt>
            <dd className="mono">{selected.request_id ?? "—"}</dd>
          </dl>
          <h3>{t("audit.change")}</h3>
          <JsonBlock value={selected.request_body} />
          <h3>{t("audit.resultState")}</h3>
          <JsonBlock value={selected.response_body} />
        </Drawer>
      )}
    </>
  );
}
