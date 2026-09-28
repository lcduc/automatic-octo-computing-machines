import { Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { MetadataEditor } from "../../components/knowledge/MetadataEditor";
import { ConfirmDialog } from "../../components/ui/Modal";
import { Badge, Callout } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { fromRows, toRows } from "../../lib/metadata";
import { useSession } from "../../lib/session";
import type { Chunk } from "../../lib/types";

/** One chunk: read view, inline editor (text is re-embedded by the backend) and delete. */
export function ChunkCard({ chunk, onChanged }: { chunk: Chunk; onChanged: () => void }) {
  const { t, formatDateTime, formatNumber } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(chunk.content);
  const [rows, setRows] = useState(() => toRows(chunk.metadata));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const cancel = () => {
    setContent(chunk.content);
    setRows(toRows(chunk.metadata));
    setError(null);
    setEditing(false);
  };

  const save = async () => {
    const { metadata, error: metadataError } = fromRows(rows);
    if (metadataError) return setError(t(metadataError.key, metadataError.params));
    if (!content.trim()) return setError(t("chunks.empty"));
    setSaving(true);
    setError(null);
    try {
      await adminApi(`knowledge/chunks/${chunk.id}`, { method: "PATCH", body: { ...(content !== chunk.content ? { content } : {}), metadata } });
      setEditing(false);
      toast.success(t("chunks.saved", { position: chunk.position + 1 }));
      onChanged();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    setConfirmDelete(false);
    try {
      await adminApi(`knowledge/chunks/${chunk.id}`, { method: "DELETE" });
      onChanged();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <li className="chunk" aria-label={t("chunks.label", { position: chunk.position + 1 })}>
      <div className="chunk__meta">
        <Badge>#{chunk.position + 1}</Badge>
        <span className="small muted">
          {t("chunking.chars", { count: formatNumber(chunk.content.length) })} · {formatDateTime(chunk.updated_at)}
        </span>
        {chunk.edited && <Badge tone="warning">{t("chunks.edited")}</Badge>}
        {!editing &&
          Object.entries(chunk.metadata).map(([key, value]) => (
            <Badge key={key} tone="gold">
              {key}: {Array.isArray(value) ? value.join(", ") : String(value)}
            </Badge>
          ))}
        {canWrite && !editing && (
          <span className="row push-right">
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setEditing(true)}>
              <Pencil size={14} aria-hidden />
              {t("common.edit")}
            </button>
            <button type="button" className="btn btn--ghost btn--sm btn--danger" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={14} aria-hidden />
              {t("common.delete")}
            </button>
          </span>
        )}
      </div>
      {editing ? (
        <div className="stack">
          <label className="sr-only" htmlFor={`chunk-${chunk.id}`}>
            {t("chunks.content")}
          </label>
          <textarea id={`chunk-${chunk.id}`} className="textarea" rows={Math.min(16, Math.max(5, content.split("\n").length + 1))} value={content} onChange={(e) => setContent(e.target.value)} />
          <MetadataEditor rows={rows} onChange={setRows} idPrefix={`chunk-${chunk.id}`} />
          {error && <Callout tone="danger">{error}</Callout>}
          <div className="row">
            <button type="button" className="btn" onClick={cancel}>
              {t("common.cancel")}
            </button>
            <button type="button" className="btn btn--primary" disabled={saving} onClick={() => void save()}>
              {saving ? t("common.saving") : t("chunks.save")}
            </button>
          </div>
        </div>
      ) : (
        <p className="prewrap">{chunk.content}</p>
      )}
      {confirmDelete && (
        <ConfirmDialog
          title={t("chunks.delete")}
          message={t("chunks.deleteConfirm", { position: chunk.position + 1 })}
          confirmLabel={t("common.delete")}
          danger
          onConfirm={() => void remove()}
          onCancel={() => setConfirmDelete(false)}
        />
      )}
    </li>
  );
}
