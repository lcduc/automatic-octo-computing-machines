import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { MetadataEditor } from "../../components/knowledge/MetadataEditor";
import { ConfirmDialog } from "../../components/ui/Modal";
import { Badge, Callout, Card, ErrorState, Field, LoadingState, PageHeader, Switch } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { DOCUMENT_STATUS_TONES } from "../../lib/labels";
import { fromRows, toRows, type MetadataRow } from "../../lib/metadata";
import { useSession } from "../../lib/session";
import type { ChunkingStrategyInfo, CitingAnswer, DocumentDetail, Source } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { ChunkCard } from "./ChunkCard";
import { ChunkingPanel } from "./ChunkingPanel";

/** Re-check a document this often while it is still being parsed. */
const PROCESSING_POLL_MS = 3000;

function Properties({ document, sources, onSaved }: { document: DocumentDetail; sources: Source[]; onSaved: () => void }) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const [title, setTitle] = useState(document.title);
  const [source, setSource] = useState(document.source);
  const [enabled, setEnabled] = useState(document.enabled);
  const [lifecycle, setLifecycle] = useState({
    access_tier: document.access_tier,
    language: document.language ?? "",
    version: document.version ?? "",
    effective_from: document.effective_from ?? "",
    effective_to: document.effective_to ?? "",
    supersedes_id: "",
  });
  const setField = (key: keyof typeof lifecycle, value: string) => setLifecycle((current) => ({ ...current, [key]: value }));
  const [rows, setRows] = useState<MetadataRow[]>(() => toRows(document.metadata));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const { metadata, error: metadataError } = fromRows(rows);
    if (metadataError) return setError(t(metadataError.key, metadataError.params));
    setSaving(true);
    setError(null);
    try {
      const body = {
        title, source, enabled, metadata,
        access_tier: lifecycle.access_tier,
        language: lifecycle.language || null,
        version: lifecycle.version || null,
        effective_from: lifecycle.effective_from || null,
        effective_to: lifecycle.effective_to || null,
        ...(lifecycle.supersedes_id ? { supersedes_id: lifecycle.supersedes_id } : {}),
      };
      await adminApi(`knowledge/documents/${document.id}`, { method: "PATCH", body });
      toast.success(t("documents.saved"));
      onSaved();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title={t("documents.properties")}>
      <div className="stack">
        <div className="form-grid">
          <Field label={t("documents.title")}>
            <input className="input" value={title} maxLength={512} disabled={!canWrite} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label={t("documents.source")}>
            <select className="select" value={source} disabled={!canWrite} onChange={(e) => setSource(e.target.value)}>
              {sources.map((item) => (
                <option key={item.id} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="row">
          <Switch checked={enabled} disabled={!canWrite} label={t("documents.inRag")} onChange={setEnabled} />
          <span>{enabled ? t("documents.inRagOn") : t("documents.inRagOff")}</span>
        </div>
        <div className="form-grid">
          <Field label={t("documents.accessTier")} hint={t("documents.accessTierHint")}>
            <input className="input mono" value={lifecycle.access_tier} maxLength={16} disabled={!canWrite} onChange={(e) => setField("access_tier", e.target.value.trim())} />
          </Field>
          <Field label={t("documents.language")}>
            <select className="select" value={lifecycle.language} disabled={!canWrite} onChange={(e) => setField("language", e.target.value)}>
              <option value="">—</option>
              <option value="vi">Tiếng Việt</option>
              <option value="en">English</option>
              <option value="mixed">{t("documents.languageMixed")}</option>
            </select>
          </Field>
          <Field label={t("documents.version")}>
            <input className="input" value={lifecycle.version} maxLength={32} disabled={!canWrite} onChange={(e) => setField("version", e.target.value)} />
          </Field>
          <Field label={t("documents.effectiveFrom")} hint={t("documents.effectiveHint")}>
            <input className="input" type="date" value={lifecycle.effective_from} disabled={!canWrite} onChange={(e) => setField("effective_from", e.target.value)} />
          </Field>
          <Field label={t("documents.effectiveTo")}>
            <input className="input" type="date" value={lifecycle.effective_to} disabled={!canWrite} onChange={(e) => setField("effective_to", e.target.value)} />
          </Field>
          <Field label={t("documents.supersedes")} hint={t("documents.supersedesHint")}>
            <input className="input mono" value={lifecycle.supersedes_id} placeholder={document.supersedes_id ?? ""} disabled={!canWrite} onChange={(e) => setField("supersedes_id", e.target.value.trim())} />
          </Field>
        </div>
        <fieldset className="stack">
          <legend className="field__label">{t("metadata.title")}</legend>
          <MetadataEditor rows={rows} onChange={setRows} idPrefix="document" disabled={!canWrite} />
        </fieldset>
        {error && <Callout tone="danger">{error}</Callout>}
        {canWrite && (
          <div>
            <button type="button" className="btn btn--primary" disabled={saving} onClick={() => void save()}>
              {saving ? t("common.saving") : t("common.save")}
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}

/** Recent answers that cited this document (ADM-18). */
function CitingAnswers({ documentId }: { documentId: string }) {
  const { t, formatDateTime } = useI18n();
  const answers = useApi<CitingAnswer[]>(`knowledge/documents/${documentId}/citations`);
  if (!answers.data || answers.data.length === 0) return null;
  return (
    <Card title={t("documents.citedIn", { count: answers.data.length })}>
      <ul className="stack">
        {answers.data.map((answer) => (
          <li key={answer.id} className="small">
            <Link to={`/conversations/${answer.conversation_id}`}>{formatDateTime(answer.created_at)}</Link>
            <span className="muted"> · {answer.content.slice(0, 160)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function NewChunk({ documentId, onAdded }: { documentId: string; onAdded: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");

  const add = async () => {
    try {
      await adminApi(`knowledge/documents/${documentId}/chunks`, { method: "POST", body: { content, metadata: {} } });
      setContent("");
      setOpen(false);
      onAdded();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  if (!open) {
    return (
      <button type="button" className="btn btn--sm" onClick={() => setOpen(true)}>
        <Plus size={14} aria-hidden />
        {t("chunks.add")}
      </button>
    );
  }
  return (
    <div className="chunk stack">
      <label className="field__label" htmlFor="new-chunk">
        {t("chunks.newContent")}
      </label>
      <textarea id="new-chunk" className="textarea" rows={5} value={content} onChange={(e) => setContent(e.target.value)} autoFocus />
      <div className="row">
        <button type="button" className="btn" onClick={() => setOpen(false)}>
          {t("common.cancel")}
        </button>
        <button type="button" className="btn btn--primary" disabled={!content.trim()} onClick={() => void add()}>
          {t("chunks.add")}
        </button>
      </div>
    </div>
  );
}

export function DocumentPage() {
  const { t, formatDateTime } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const navigate = useNavigate();
  const { id } = useParams();
  const [pollMs, setPollMs] = useState<number | undefined>(undefined);
  const document = useApi<DocumentDetail>(id ? `knowledge/documents/${id}` : null, pollMs);
  const sources = useApi<Source[]>("knowledge/sources");
  const strategies = useApi<ChunkingStrategyInfo[]>("knowledge/chunking/strategies");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const processing = document.data?.status === "processing";
  if (processing !== Boolean(pollMs)) setPollMs(processing ? PROCESSING_POLL_MS : undefined);

  const remove = async () => {
    setConfirmDelete(false);
    try {
      await adminApi(`knowledge/documents/${id}`, { method: "DELETE" });
      toast.success(t("documents.deleted"));
      navigate("/knowledge", { replace: true });
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  if (document.error) return <ErrorState message={document.error} onRetry={document.reload} />;
  if (!document.data || !sources.data) return <LoadingState />;
  const data = document.data;

  return (
    <>
      <Link to="/knowledge" className="row small">
        <ArrowLeft size={14} aria-hidden />
        {t("documents.back")}
      </Link>
      <PageHeader
        title={data.title}
        description={t("documents.meta", { source: data.source, type: data.file_type, by: data.created_by ?? "—", at: formatDateTime(data.created_at) })}
        actions={
          <>
            <Badge tone={DOCUMENT_STATUS_TONES[data.status]}>{t(`documentStatus.${data.status}`)}</Badge>
            {canWrite && (
              <button type="button" className="btn btn--danger" onClick={() => setConfirmDelete(true)}>
                <Trash2 size={16} aria-hidden />
                {t("documents.delete")}
              </button>
            )}
          </>
        }
      />
      {data.status === "processing" && <Callout>{t("documents.processing")}</Callout>}
      {data.status === "failed" && <Callout tone="danger">{data.error ?? t("documentStatus.failed")}</Callout>}
      {!data.enabled && <Callout tone="warning">{t("documents.heldBack")}</Callout>}

      <div className="grid-2">
        <Properties key={data.updated_at} document={data} sources={sources.data} onSaved={document.reload} />
        {data.status !== "processing" && (
          <ChunkingPanel key={`${data.updated_at}-${data.chunk_count}`} document={data} strategies={strategies.data ?? []} onRechunked={(updated) => document.setData(updated)} />
        )}
      </div>

      <CitingAnswers documentId={data.id} />

      <Card title={t("chunks.title", { count: data.chunk_count })} actions={canWrite && <NewChunk documentId={data.id} onAdded={document.reload} />}>
        {data.chunks.length === 0 ? (
          <p className="muted">{t("chunks.none")}</p>
        ) : (
          <ol className="stack">
            {data.chunks.map((chunk) => (
              <ChunkCard key={`${chunk.id}-${chunk.updated_at}`} chunk={chunk} onChanged={document.reload} />
            ))}
          </ol>
        )}
      </Card>

      {confirmDelete && (
        <ConfirmDialog title={t("documents.delete")} message={t("documents.deleteConfirm", { title: data.title })} confirmLabel={t("common.delete")} danger onConfirm={() => void remove()} onCancel={() => setConfirmDelete(false)} />
      )}
    </>
  );
}
