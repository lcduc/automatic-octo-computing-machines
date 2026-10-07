import { useState, type FormEvent } from "react";
import { useToast } from "../ui/Toast";
import { useApi } from "../../lib/use-api";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import type { KnowledgeDocument, Source } from "../../lib/types";
import { Modal } from "../ui/Modal";
import { Callout, Field } from "../ui/primitives";

const ACCEPTED_FILES = ".pdf,.docx,.txt,.md,.csv,.xlsx";
/** Keep in sync with the backend's MAX_FILE_SIZE default. */
const MAX_FILE_MB = 50;
/** The tier every visitor satisfies; the backend default for a new document. */
const ANONYMOUS_TIER = "anonymous";

interface NewDocumentDialogProps {
  mode: "upload" | "text";
  sources: Source[];
  onClose: () => void;
  onCreated: (document: KnowledgeDocument) => void;
}

/** Create a document from an uploaded file or typed text, with the same lifecycle settings its page offers. */
export function NewDocumentDialog({ mode, sources, onClose, onCreated }: NewDocumentDialogProps) {
  const { t } = useI18n();
  const toast = useToast();
  const tiers = useApi<string[]>("knowledge/access-tiers").data ?? [];
  const [source, setSource] = useState(sources[0]?.name ?? "");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [accessTier, setAccessTier] = useState(ANONYMOUS_TIER);
  const [language, setLanguage] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [effectiveTo, setEffectiveTo] = useState("");
  const [hold, setHold] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
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
        form.set("enabled", String(!hold));
        created = await adminApi<KnowledgeDocument>("knowledge/documents/upload", { method: "POST", body: form });
      } else {
        created = await adminApi<KnowledgeDocument>("knowledge/documents/text", {
          method: "POST",
          body: { source, title: title.trim(), content },
        });
      }
      const settings = {
        ...(accessTier !== ANONYMOUS_TIER && { access_tier: accessTier }),
        ...(language && { language }),
        ...(effectiveFrom && { effective_from: effectiveFrom }),
        ...(effectiveTo && { effective_to: effectiveTo }),
      };
      if (Object.keys(settings).length > 0) {
        // The create endpoints take no lifecycle fields, so apply them right after. The document
        // already exists, so a failure here must not make the admin submit (and duplicate) it again.
        try {
          created = await adminApi<KnowledgeDocument>(`knowledge/documents/${created.id}`, { method: "PATCH", body: settings });
        } catch (reason) {
          toast.error(t("documents.settingsNotApplied", { message: (reason as Error).message }));
        }
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
          <Field label={t("documents.accessTier")}>
            <select className="select" value={accessTier} onChange={(event) => setAccessTier(event.target.value)}>
              {(tiers.length > 0 ? tiers : [ANONYMOUS_TIER]).map((tier) => (
                <option key={tier} value={tier}>
                  {tier === ANONYMOUS_TIER ? t("documents.tierEveryone") : t("documents.tierAndAbove", { tier })}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("documents.language")}>
            <select className="select" value={language} onChange={(event) => setLanguage(event.target.value)}>
              <option value="">—</option>
              <option value="vi">Tiếng Việt</option>
              <option value="en">English</option>
              <option value="mixed">{t("documents.languageMixed")}</option>
            </select>
          </Field>
          <Field label={t("documents.effectiveFrom")} hint={t("documents.effectiveHint")}>
            <input className="input" type="date" value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} />
          </Field>
          <Field label={t("documents.effectiveTo")}>
            <input className="input" type="date" value={effectiveTo} onChange={(event) => setEffectiveTo(event.target.value)} />
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

        {mode === "upload" && (
          <label className="checkbox">
            <input type="checkbox" checked={hold} onChange={(event) => setHold(event.target.checked)} />
            <span>
              {t("documents.hold")}
              <span className="field__hint"> — {t("documents.holdHint")}</span>
            </span>
          </label>
        )}

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
