import { useState, type FormEvent } from "react";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { fromRows, type MetadataRow } from "../../lib/metadata";
import type { ChunkingSpec, ChunkingStrategyInfo, KnowledgeDocument, Source } from "../../lib/types";
import { Modal } from "../ui/Modal";
import { Callout, Field } from "../ui/primitives";
import { MetadataEditor } from "./MetadataEditor";
import { StrategyPicker } from "./StrategyPicker";

const ACCEPTED_FILES = ".pdf,.docx,.txt,.md,.csv,.xlsx";
/** Keep in sync with the backend's MAX_FILE_SIZE default. */
const MAX_FILE_MB = 50;

interface NewDocumentDialogProps {
  mode: "upload" | "text";
  sources: Source[];
  strategies: ChunkingStrategyInfo[];
  onClose: () => void;
  onCreated: (document: KnowledgeDocument) => void;
}

/** Create a document from an uploaded file or typed text, choosing how it is chunked. */
export function NewDocumentDialog({ mode, sources, strategies, onClose, onCreated }: NewDocumentDialogProps) {
  const { t } = useI18n();
  const [source, setSource] = useState(sources[0]?.name ?? "");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [rows, setRows] = useState<MetadataRow[]>([]);
  const [chunking, setChunking] = useState<ChunkingSpec>({ strategy: "auto" });
  const [hold, setHold] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const { metadata, error: metadataError } = fromRows(rows);
    if (metadataError) return setError(t(metadataError.key, metadataError.params));
    if (mode === "upload" && !file) return setError(t("documents.chooseFile"));
    if (file && file.size > MAX_FILE_MB * 1024 * 1024) return setError(t("documents.tooLarge", { max: MAX_FILE_MB }));
    setSaving(true);
    setError(null);
    try {
      let created: KnowledgeDocument;
      if (mode === "upload" && file) {
        const form = new FormData();
        form.set("file", file);
        form.set("source", source);
        if (title.trim()) form.set("title", title.trim());
        form.set("metadata", JSON.stringify(metadata));
        form.set("chunking", JSON.stringify(chunking));
        form.set("enabled", String(!hold));
        created = await adminApi<KnowledgeDocument>("knowledge/documents/upload", { method: "POST", body: form });
      } else {
        created = await adminApi<KnowledgeDocument>("knowledge/documents/text", {
          method: "POST",
          body: { source, title: title.trim(), content, metadata, chunking },
        });
      }
      onCreated(created);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={mode === "upload" ? t("documents.upload") : t("documents.write")} onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        {error && <Callout tone="danger">{error}</Callout>}
        <div className="form-grid">
          <Field label={t("documents.source")} hint={t("documents.sourceHint")}>
            <select className="select" value={source} onChange={(event) => setSource(event.target.value)} required>
              {sources.map((item) => (
                <option key={item.id} value={item.name}>
                  {item.enabled ? item.name : t("sources.disabledName", { name: item.name })}
                </option>
              ))}
            </select>
          </Field>
          <Field label={mode === "upload" ? t("documents.titleOptional") : t("documents.title")}>
            <input className="input" value={title} maxLength={512} required={mode === "text"} onChange={(event) => setTitle(event.target.value)} />
          </Field>
        </div>
        {mode === "upload" ? (
          <Field label={t("documents.file")} hint={t("documents.fileHint", { max: MAX_FILE_MB })}>
            <input className="input" type="file" accept={ACCEPTED_FILES} required onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </Field>
        ) : (
          <Field label={t("documents.content")} hint={t("documents.contentHint")}>
            <textarea className="textarea" rows={10} value={content} required onChange={(event) => setContent(event.target.value)} />
          </Field>
        )}

        <fieldset className="card card__body stack">
          <legend className="field__label">{t("chunking.title")}</legend>
          {strategies.length > 0 ? <StrategyPicker strategies={strategies} value={chunking} onChange={setChunking} /> : <p className="small muted">{t("common.loading")}</p>}
          {mode === "upload" && (
            <label className="checkbox">
              <input type="checkbox" checked={hold} onChange={(event) => setHold(event.target.checked)} />
              <span>
                {t("documents.hold")}
                <span className="field__hint"> — {t("documents.holdHint")}</span>
              </span>
            </label>
          )}
        </fieldset>

        <fieldset className="stack">
          <legend className="field__label">{t("metadata.title")}</legend>
          <p className="small muted">{t("metadata.hint")}</p>
          <MetadataEditor rows={rows} onChange={setRows} idPrefix="new-document" />
        </fieldset>

        <div className="row row--between">
          <button type="button" className="btn" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="submit" className="btn btn--primary" disabled={saving}>
            {saving ? t("common.saving") : mode === "upload" ? t("documents.uploadSubmit") : t("documents.create")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
