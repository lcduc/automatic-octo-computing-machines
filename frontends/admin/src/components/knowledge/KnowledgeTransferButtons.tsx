import { Download, Upload } from "lucide-react";
import { useRef, useState, type ChangeEvent } from "react";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { downloadJson } from "../../lib/download";
import { useSession } from "../../lib/session";
import type { KnowledgeImportResult } from "../../lib/types";
import { useToast } from "../ui/Toast";

const EXPORT_FILENAME = "knowledge.json";

/** Export the knowledge base to a file, and import one exported from another server (e.g. dev to production). */
export function KnowledgeTransferButtons({ onImported }: { onImported: () => void }) {
  const { t } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const exportKnowledge = async () => {
    setBusy(true);
    try {
      downloadJson(EXPORT_FILENAME, await adminApi<unknown>("knowledge/export"));
    } catch (reason) {
      toast.error((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const importKnowledge = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      const bundle: unknown = JSON.parse(await file.text());
      const result = await adminApi<KnowledgeImportResult>("knowledge/import", { method: "POST", body: bundle });
      toast.success(
        t("knowledgeTransfer.done", {
          imported: result.documents_imported,
          skipped: result.documents_skipped,
        }),
      );
      onImported();
    } catch (reason) {
      toast.error(reason instanceof SyntaxError ? t("knowledgeTransfer.notJson") : (reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" className="btn" disabled={busy} onClick={() => void exportKnowledge()}>
        <Download size={16} aria-hidden />
        {t("knowledgeTransfer.export")}
      </button>
      {canWrite && (
        <>
          <button type="button" className="btn" disabled={busy} onClick={() => fileInput.current?.click()}>
            <Upload size={16} aria-hidden />
            {t("knowledgeTransfer.import")}
          </button>
          <input ref={fileInput} type="file" accept="application/json,.json" hidden onChange={(event) => void importKnowledge(event)} />
        </>
      )}
    </>
  );
}
