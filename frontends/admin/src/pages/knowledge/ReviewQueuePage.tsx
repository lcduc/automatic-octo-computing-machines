import { CheckCircle2, Clock, XCircle } from "lucide-react";
import { Link } from "react-router";
import { ApprovalWorkflow } from "../../components/knowledge/ApprovalWorkflow";
import { PlannedBadge } from "../../components/ui/Planned";
import { Card, EmptyState, KpiCard, PageHeader } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";

/** Placeholder for the unknown count of a planned feature. */
const NO_VALUE = "—";

/**
 * giz-chatbot's four-eyes review queue. Our backend has no review states yet,
 * so the page shows the layout and the workflow without data or actions.
 */
export function ReviewQueuePage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("nav.review")} description={t("review.description")} actions={<PlannedBadge />} />
      <div className="kpi-grid">
        <KpiCard icon={<Clock size={18} />} label={t("review.pending")} value={NO_VALUE} tone="gold" />
        <KpiCard icon={<CheckCircle2 size={18} />} label={t("review.approved")} value={NO_VALUE} tone="teal" />
        <KpiCard icon={<XCircle size={18} />} label={t("review.rejected")} value={NO_VALUE} tone="rose" />
      </div>
      <ApprovalWorkflow enabled={null} />
      <Card title={t("review.queue")} flush>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("documents.title")}</th>
                <th scope="col">{t("review.submittedBy")}</th>
                <th scope="col">{t("review.submittedAt")}</th>
                <th scope="col">{t("common.actions")}</th>
              </tr>
            </thead>
          </table>
        </div>
        <EmptyState title={t("review.empty")} hint={t("review.emptyHint")} action={<Link to="/knowledge">{t("nav.knowledge")}</Link>} />
      </Card>
    </>
  );
}
