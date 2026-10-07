import { Loader2, UploadCloud } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { useI18n } from "../../i18n/I18nProvider";
import type { Source } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { useToast } from "../ui/Toast";
import { NewDocumentDialog } from "./NewDocumentDialog";

/** Topbar shortcut: upload a document from any page, then open it in the knowledge base. */
export function QuickUpload() {
  const { t } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const sources = useApi<Source[]>(open ? "knowledge/sources" : null);
  const ready = open && sources.data;

  return (
    <>
      <button type="button" className="btn topbar__upload" onClick={() => setOpen(true)} disabled={open && !ready}>
        {open && !ready ? <Loader2 size={14} className="spin" aria-hidden /> : <UploadCloud size={14} aria-hidden />}
        <span>{t("topbar.upload")}</span>
      </button>
      {ready && (
        <NewDocumentDialog
          mode="upload"
          sources={sources.data ?? []}
          onClose={() => setOpen(false)}
          onCreated={(document) => {
            setOpen(false);
            toast.success(document.status === "processing" ? t("documents.queued", { title: document.title }) : t("documents.created", { title: document.title }));
            navigate(`/knowledge/${document.id}`);
          }}
        />
      )}
    </>
  );
}
