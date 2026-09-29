import { Download, Trash2 } from "lucide-react";
import { useState } from "react";
import { Card, EmptyState, ErrorState, LoadingState, Pagination } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi, query } from "../../lib/api";
import { downloadJson } from "../../lib/download";
import { useSession } from "../../lib/session";
import type { EvalCase, Page } from "../../lib/types";
import { useApi } from "../../lib/use-api";

const PAGE_SIZE = 20;

/** The golden eval set built from real answers (ADM-12); export feeds scripts/eval_rag.py. */
export function EvalCasesCard() {
  const { t, formatDateTime } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const [offset, setOffset] = useState(0);
  const { data, error, loading, reload } = useApi<Page<EvalCase>>(`eval-cases${query({ limit: PAGE_SIZE, offset })}`);

  const exportSet = async () => {
    try {
      downloadJson("golden_queries.json", await adminApi<unknown>("eval-cases/export"));
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  const remove = async (id: string) => {
    try {
      await adminApi(`eval-cases/${id}`, { method: "DELETE" });
      reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  return (
    <Card
      title={t("eval.title")}
      actions={
        <button type="button" className="btn btn--sm" disabled={!data?.total} onClick={() => void exportSet()}>
          <Download size={14} aria-hidden />
          {t("eval.export")}
        </button>
      }
    >
      <p className="small muted">{t("eval.help")}</p>
      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && <LoadingState />}
      {data && data.items.length === 0 && <EmptyState title={t("eval.empty")} />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("feedback.question")}</th>
                <th scope="col">{t("eval.expected")}</th>
                <th scope="col">{t("eval.sources")}</th>
                <th scope="col">{t("feedback.when")}</th>
                {canWrite && <th scope="col"><span className="sr-only">{t("common.actions")}</span></th>}
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.id}>
                  <td className="prewrap">{item.question}</td>
                  <td className="prewrap small">{item.expected_answer}</td>
                  <td className="small">{item.expected_sources.join(", ") || "—"}</td>
                  <td className="small muted">{formatDateTime(item.created_at)}</td>
                  {canWrite && (
                    <td>
                      <button type="button" className="btn btn--sm btn--ghost" aria-label={t("common.delete")} onClick={() => void remove(item.id)}>
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pagination total={data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />}
    </Card>
  );
}
