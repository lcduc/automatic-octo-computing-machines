import { Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Badge, EmptyState, ErrorState, Field, LoadingState, PageHeader, type Tone } from "../components/ui/primitives";
import { useI18n } from "../i18n/I18nProvider";
import { query } from "../lib/api";
import type { LogEntry } from "../lib/types";
import { useApi } from "../lib/use-api";

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];
const LEVEL_TONES: Record<string, Tone> = { WARNING: "warning", ERROR: "danger", CRITICAL: "danger", INFO: "info" };
const LOG_LIMIT = 200;

export function LogsPage() {
  const { t, formatDateTime } = useI18n();
  const [level, setLevel] = useState("INFO");
  const [draft, setDraft] = useState({ contains: "", request_id: "" });
  const [filters, setFilters] = useState(draft);
  const { data, error, loading, reload } = useApi<LogEntry[]>(`logs${query({ level, contains: filters.contains, request_id: filters.request_id, limit: LOG_LIMIT })}`);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setFilters({ contains: draft.contains.trim(), request_id: draft.request_id.trim() });
  };

  return (
    <>
      <PageHeader title={t("logs.title")} description={t("logs.description")} actions={<button type="button" className="btn" onClick={reload}>{t("common.refresh")}</button>} />
      <form className="toolbar" onSubmit={submit} role="search">
        <Field label={t("logs.level")}>
          <select className="select" value={level} onChange={(e) => setLevel(e.target.value)}>
            {LEVELS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("logs.contains")}>
          <input className="input" value={draft.contains} onChange={(e) => setDraft({ ...draft, contains: e.target.value })} />
        </Field>
        <Field label={t("logs.requestId")}>
          <input className="input mono" value={draft.request_id} onChange={(e) => setDraft({ ...draft, request_id: e.target.value })} />
        </Field>
        <button type="submit" className="btn">
          <Search size={16} aria-hidden />
          {t("common.search")}
        </button>
      </form>
      <section className="card">
        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && <LoadingState />}
        {data && data.length === 0 && <EmptyState title={t("logs.empty")} />}
        {data && data.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t("logs.time")}</th>
                  <th scope="col">{t("logs.level")}</th>
                  <th scope="col">{t("logs.message")}</th>
                  <th scope="col">{t("logs.requestId")}</th>
                </tr>
              </thead>
              <tbody>
                {data.map((entry, index) => (
                  <tr key={`${entry.ts}-${index}`}>
                    <td className="small muted">{formatDateTime(entry.ts)}</td>
                    <td>
                      <Badge tone={LEVEL_TONES[entry.level] ?? "neutral"}>{entry.level}</Badge>
                    </td>
                    <td>
                      <div className="prewrap small">{entry.message}</div>
                      <div className="small muted mono">{entry.logger}</div>
                      {entry.exception && <pre className="json mt-3">{entry.exception}</pre>}
                    </td>
                    <td className="mono">{entry.request_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
