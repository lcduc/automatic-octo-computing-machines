import { CheckCircle2, Clock, XCircle } from "lucide-react";
import { useI18n } from "../../i18n/I18nProvider";
import type { ReviewCounts } from "../../lib/types";
import { KpiCard } from "../ui/primitives";

/** How many documents wait for review, were approved and were rejected. */
export function ReviewStats({ counts }: { counts: ReviewCounts | null }) {
  const { t, formatNumber } = useI18n();
  const shown = (key: keyof ReviewCounts) => (counts ? formatNumber(counts[key]) : "—");
  return (
    <div className="kpi-grid">
      <KpiCard icon={<Clock size={18} />} label={t("review.pending")} value={shown("pending")} tone="gold" />
      <KpiCard icon={<CheckCircle2 size={18} />} label={t("review.approved")} value={shown("approved")} tone="teal" />
      <KpiCard icon={<XCircle size={18} />} label={t("review.rejected")} value={shown("rejected")} tone="rose" />
    </div>
  );
}
