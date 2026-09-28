import { FilePlus2, PenLine, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { NewDocumentDialog } from "../../components/knowledge/NewDocumentDialog";
import { strategyLabel } from "../../components/knowledge/StrategyPicker";
import { Badge, EmptyState, ErrorState, Field, LoadingState, Pagination, Switch } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi, query } from "../../lib/api";
import { DOCUMENT_STATUS_TONES } from "../../lib/labels";
import { useSession } from "../../lib/session";
import type { ChunkingStrategyInfo, DocumentStatus, KnowledgeDocument, Page, Source } from "../../lib/types";
import { useApi } from "../../lib/use-api";

const PAGE_SIZE = 25;
/** Re-check the list this often while any document is still being parsed. */
const PROCESSING_POLL_MS = 4000;
const STATUSES: DocumentStatus[] = ["processing", "ready", "failed"];

export function DocumentsTab({ sources, strategies }: { sources: Source[]; strategies: ChunkingStrategyInfo[] }) {
  const { t, formatDateTime, formatNumber } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("search") ?? "");
  const [dialog, setDialog] = useState<"upload" | "text" | null>(null);
  const source = params.get("source") ?? "";
  const status = params.get("status") ?? "";
  const offset = Number(params.get("offset") ?? 0);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next, { replace: true });
  };

  const path = `knowledge/documents${query({ source, status, search: params.get("search"), limit: PAGE_SIZE, offset })}`;
  const [pollMs, setPollMs] = useState<number | undefined>(undefined);
  const { data, error, loading, reload, setData } = useApi<Page<KnowledgeDocument>>(path, pollMs);
  const hasProcessing = Boolean(data?.items.some((item) => item.status === "processing"));
  if (hasProcessing !== Boolean(pollMs)) setPollMs(hasProcessing ? PROCESSING_POLL_MS : undefined);

  const toggle = async (document: KnowledgeDocument, enabled: boolean) => {
    try {
      const updated = await adminApi<KnowledgeDocument>(`knowledge/documents/${document.id}`, { method: "PATCH", body: { enabled } });
      if (data) setData({ ...data, items: data.items.map((item) => (item.id === document.id ? { ...item, enabled: updated.enabled } : item)) });
      toast.success(enabled ? t("documents.enabledToast", { title: document.title }) : t("documents.disabledToast", { title: document.title }));
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setFilter("search", search.trim());
  };

  return (
    <div className="stack">
      <div className="toolbar">
        <Field label={t("documents.source")}>
          <select className="select" value={source} onChange={(event) => setFilter("source", event.target.value)}>
            <option value="">{t("common.all")}</option>
            {sources.map((item) => (
              <option key={item.id} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("documents.status")}>
          <select className="select" value={status} onChange={(event) => setFilter("status", event.target.value)}>
            <option value="">{t("common.all")}</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {t(`documentStatus.${value}`)}
              </option>
            ))}
          </select>
        </Field>
        <form className="row" onSubmit={submitSearch} role="search">
          <Field label={t("documents.search")}>
            <input className="input" type="search" value={search} onChange={(event) => setSearch(event.target.value)} />
          </Field>
          <button type="submit" className="btn btn--icon" aria-label={t("common.search")}>
            <Search size={16} aria-hidden />
          </button>
        </form>
        {canWrite && (
          <div className="row push-right">
            <button type="button" className="btn btn--primary" onClick={() => setDialog("upload")}>
              <FilePlus2 size={16} aria-hidden />
              {t("documents.upload")}
            </button>
            <button type="button" className="btn" onClick={() => setDialog("text")}>
              <PenLine size={16} aria-hidden />
              {t("documents.write")}
            </button>
          </div>
        )}
      </div>

      <section className="card">
        {error && <ErrorState message={error} onRetry={reload} />}
        {loading && <LoadingState />}
        {data && data.items.length === 0 && <EmptyState title={t("documents.empty")} hint={canWrite ? t("documents.emptyHint") : undefined} />}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t("documents.title")}</th>
                  <th scope="col">{t("documents.source")}</th>
                  <th scope="col">{t("documents.status")}</th>
                  <th scope="col">{t("chunking.strategy")}</th>
                  <th scope="col" className="table__num">
                    {t("documents.chunks")}
                  </th>
                  <th scope="col">{t("documents.updated")}</th>
                  <th scope="col">{t("documents.inRag")}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((document) => (
                  <tr key={document.id}>
                    <td>
                      <Link to={`/knowledge/${document.id}`}>
                        <strong>{document.title}</strong>
                      </Link>
                      {document.original_filename && <div className="small muted">{document.original_filename}</div>}
                    </td>
                    <td>{document.source}</td>
                    <td>
                      <Badge tone={DOCUMENT_STATUS_TONES[document.status]}>{t(`documentStatus.${document.status}`)}</Badge>
                      {document.error && <div className="small field__error truncate">{document.error}</div>}
                    </td>
                    <td className="small">{strategyLabel(t, document.chunking.strategy)}</td>
                    <td className="table__num">{formatNumber(document.chunk_count)}</td>
                    <td className="small muted">{formatDateTime(document.updated_at)}</td>
                    <td>
                      <Switch
                        checked={document.enabled}
                        disabled={!canWrite}
                        label={t("documents.inRagFor", { title: document.title })}
                        onChange={(value) => void toggle(document, value)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <Pagination
            total={data.total}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={(value) => {
              const next = new URLSearchParams(params);
              next.set("offset", String(value));
              setParams(next);
            }}
          />
        )}
      </section>

      {dialog && (
        <NewDocumentDialog
          mode={dialog}
          sources={sources}
          strategies={strategies}
          onClose={() => setDialog(null)}
          onCreated={(document) => {
            setDialog(null);
            toast.success(document.status === "processing" ? t("documents.queued", { title: document.title }) : t("documents.created", { title: document.title }));
            if (document.status === "ready") navigate(`/knowledge/${document.id}`);
            else reload();
          }}
        />
      )}
    </div>
  );
}
