import { Check, X } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import type { DocumentDetail, KnowledgeDocument } from "../../lib/types";
import { Modal } from "../ui/Modal";
import { Callout, Field } from "../ui/primitives";
import { useToast } from "../ui/Toast";

interface ReviewButtonsProps {
  document: Pick<KnowledgeDocument, "id" | "title" | "status">;
  /** Called with the reviewed document after the backend recorded the decision. */
  onReviewed: (document: DocumentDetail) => void;
}

/** Approve / reject controls for a pending document; the backend allows owners and editors only. */
export function ReviewButtons({ document, onReviewed }: ReviewButtonsProps) {
  const { t } = useI18n();
  const toast = useToast();
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const notReady = document.status !== "ready";

  const decide = async (approve: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const reviewed = await adminApi<DocumentDetail>(`knowledge/documents/${document.id}/review`, {
        method: "POST",
        body: { approve, note: note.trim() || null },
      });
      toast.success(t(approve ? "review.approvedToast" : "review.rejectedToast", { title: document.title }));
      setRejecting(false);
      onReviewed(reviewed);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" className="btn btn--primary" disabled={busy || notReady} title={notReady ? t("review.notReady") : undefined} onClick={() => void decide(true)}>
        <Check size={16} aria-hidden />
        {t("review.approve")}
      </button>
      <button type="button" className="btn btn--danger" disabled={busy} onClick={() => setRejecting(true)}>
        <X size={16} aria-hidden />
        {t("review.reject")}
      </button>
      {error && !rejecting && <span className="small field__error">{error}</span>}
      {rejecting && (
        <Modal
          title={t("review.rejectTitle", { title: document.title })}
          onClose={() => setRejecting(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setRejecting(false)}>
                {t("common.cancel")}
              </button>
              <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void decide(false)}>
                {t("review.reject")}
              </button>
            </>
          }
        >
          <div className="stack">
            <p>{t("review.rejectHint")}</p>
            {error && <Callout tone="danger">{error}</Callout>}
            <Field label={t("review.note")}>
              <textarea className="textarea" rows={3} maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} autoFocus />
            </Field>
          </div>
        </Modal>
      )}
    </>
  );
}
