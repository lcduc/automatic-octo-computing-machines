import { Eye, RefreshCw } from "lucide-react";
import { useState } from "react";
import { defaultSpec, strategyLabel, StrategyPicker } from "../../components/knowledge/StrategyPicker";
import { ConfirmDialog } from "../../components/ui/Modal";
import { Badge, Callout, Card } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi, ApiError } from "../../lib/api";
import { useSession } from "../../lib/session";
import type { ChunkingPreview, ChunkingSpec, ChunkingStrategyInfo, DocumentDetail } from "../../lib/types";

/** Chunks shown in a preview (the backend still counts all of them). */
const PREVIEW_LIMIT = 50;

interface ChunkingPanelProps {
  document: DocumentDetail;
  strategies: ChunkingStrategyInfo[];
  onRechunked: (document: DocumentDetail) => void;
}

/** Try another strategy on the stored text, compare, then apply it (re-embeds every chunk). */
export function ChunkingPanel({ document, strategies, onRechunked }: ChunkingPanelProps) {
  const { t, formatNumber } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const current = strategies.find((info) => info.name === (document.chunking.strategy ?? "auto"));
  const [spec, setSpec] = useState<ChunkingSpec>(() => ({ ...(current ? defaultSpec(current) : { strategy: "auto" }), ...document.chunking }) as ChunkingSpec);
  const [preview, setPreview] = useState<ChunkingPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"apply" | "discard" | null>(null);
  const edited = document.chunks.filter((chunk) => chunk.edited).length;

  if (!document.can_rechunk) {
    return (
      <Card title={t("chunking.title")}>
        <Callout tone="warning">{t("chunking.noText")}</Callout>
      </Card>
    );
  }

  const runPreview = async () => {
    setBusy(true);
    setError(null);
    try {
      setPreview(await adminApi<ChunkingPreview>(`knowledge/documents/${document.id}/chunking/preview`, { method: "POST", body: { chunking: spec, limit: PREVIEW_LIMIT } }));
    } catch (reason) {
      setPreview(null);
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const apply = async (discardManualEdits: boolean) => {
    setConfirm(null);
    setBusy(true);
    setError(null);
    try {
      const updated = await adminApi<DocumentDetail>(`knowledge/documents/${document.id}/rechunk`, {
        method: "POST",
        body: { chunking: spec, discard_manual_edits: discardManualEdits },
      });
      setPreview(null);
      toast.success(t("chunking.applied", { count: updated.chunk_count }));
      onRechunked(updated);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409 && !discardManualEdits && edited > 0) setConfirm("discard");
      else setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title={t("chunking.title")}
      actions={<Badge tone="gold">{t("chunking.current", { strategy: strategyLabel(t, document.chunking.strategy) })}</Badge>}
    >
      <div className="stack">
        <p className="small muted">{t("chunking.help")}</p>
        {strategies.length > 0 && <StrategyPicker strategies={strategies} value={spec} onChange={(next) => { setSpec(next); setPreview(null); }} disabled={!canWrite || busy} />}
        {error && <Callout tone="danger">{error}</Callout>}
        <div className="row">
          <button type="button" className="btn" onClick={() => void runPreview()} disabled={busy || !canWrite}>
            <Eye size={16} aria-hidden />
            {t("chunking.preview")}
          </button>
          <button type="button" className="btn btn--primary" onClick={() => setConfirm("apply")} disabled={busy || !canWrite || !preview}>
            <RefreshCw size={16} aria-hidden className={busy ? "spin" : undefined} />
            {t("chunking.apply")}
          </button>
          {!preview && canWrite && <span className="small muted">{t("chunking.previewFirst")}</span>}
        </div>

        {preview && (
          <div className="stack">
            <div className="row">
              <Badge tone="info">{t("chunking.stats.count", { count: formatNumber(preview.chunk_count) })}</Badge>
              <Badge>{t("chunking.stats.size", { min: formatNumber(preview.min_chars), avg: formatNumber(preview.avg_chars), max: formatNumber(preview.max_chars) })}</Badge>
              <span className="small muted">{t("chunking.stats.before", { count: formatNumber(document.chunk_count) })}</span>
            </div>
            {preview.warnings.map((warning) => (
              <Callout key={warning} tone="warning">
                {warning}
              </Callout>
            ))}
            <ol className="stack" aria-label={t("chunking.previewList")}>
              {preview.chunks.map((chunk) => (
                <li key={chunk.position} className="chunk">
                  <div className="chunk__meta">
                    <Badge>#{chunk.position + 1}</Badge>
                    <span className="small muted">{t("chunking.chars", { count: formatNumber(chunk.char_count) })}</span>
                    {Object.entries(chunk.metadata).map(([key, value]) => (
                      <Badge key={key} tone="gold">
                        {key}: {String(value)}
                      </Badge>
                    ))}
                  </div>
                  <p className="prewrap small">{chunk.content}</p>
                </li>
              ))}
            </ol>
            {preview.chunk_count > preview.chunks.length && <p className="small muted">{t("chunking.more", { count: preview.chunk_count - preview.chunks.length })}</p>}
          </div>
        )}
      </div>

      {confirm === "apply" && (
        <ConfirmDialog
          title={t("chunking.apply")}
          message={t("chunking.applyConfirm", { strategy: strategyLabel(t, spec.strategy), count: preview?.chunk_count ?? 0 })}
          confirmLabel={t("chunking.apply")}
          busy={busy}
          onConfirm={() => void apply(false)}
          onCancel={() => setConfirm(null)}
        />
      )}
      {confirm === "discard" && (
        <ConfirmDialog
          title={t("chunking.editedTitle")}
          message={t("chunking.editedConfirm", { count: edited })}
          confirmLabel={t("chunking.discardAndApply")}
          danger
          busy={busy}
          onConfirm={() => void apply(true)}
          onCancel={() => setConfirm(null)}
        />
      )}
    </Card>
  );
}
