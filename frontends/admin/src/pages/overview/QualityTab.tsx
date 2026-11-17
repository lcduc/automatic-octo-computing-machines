import { Archive, CircleAlert, CircleCheck, DoorOpen, Quote, ThumbsDown } from "lucide-react";
import { Card, KpiCard } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/vi";
import { BreakdownBars } from "./BreakdownBars";
import { DocumentHealth } from "./DocumentHealth";
import { answerRate, countTurns, formatShare, share, type OverviewData } from "./rollup";

/** Quality panel: answered share, user feedback, not-helpful rate and the outcome breakdown. */
export function QualityTab({ summary, history }: OverviewData) {
  const { t, formatNumber } = useI18n();
  const turns = countTurns(summary);
  const answered = summary.outcomes.answered ?? 0;
  const ratings = summary.feedback.positive + summary.feedback.negative;
  const grounded = answerRate(history, "cited_answers");
  const lowConfidence = answerRate(history, "low_confidence_answers");
  const cached = answerRate(history, "cached_answers");
  const conversations = summary.latency.conversations;
  const singleTurn = summary.single_turn_conversations;
  const outcomes: Record<string, number> = {};
  for (const [outcome, count] of Object.entries(summary.outcomes)) {
    if (count !== undefined) outcomes[outcome] = count;
  }

  return (
    <>
      <div className="kpi-grid">
        <KpiCard
          icon={<CircleCheck size={20} />}
          tone="teal"
          label={t("overview.answeredShare")}
          value={formatShare(share(answered, turns), formatNumber)}
          hint={t("overview.answeredShareHint", { count: formatNumber(answered), total: formatNumber(turns) })}
        />
        <KpiCard
          icon={<ThumbsDown size={20} />}
          tone="rose"
          label={t("overview.notHelpfulRate")}
          value={formatShare(share(summary.feedback.negative, ratings), formatNumber)}
          hint={t("overview.ratingsCount", { count: formatNumber(ratings) })}
        />
        <KpiCard
          icon={<Quote size={20} />}
          label={t("overview.groundedAnswers")}
          value={formatShare(grounded.rate, formatNumber)}
          hint={t("overview.answerRateHint", { count: formatNumber(grounded.count), total: formatNumber(grounded.answered) })}
        />
        <KpiCard
          icon={<CircleAlert size={20} />}
          tone="rose"
          label={t("overview.lowConfidenceAnswers")}
          value={formatShare(lowConfidence.rate, formatNumber)}
          hint={t("overview.answerRateHint", { count: formatNumber(lowConfidence.count), total: formatNumber(lowConfidence.answered) })}
        />
        <KpiCard
          label={t("overview.singleTurn")}
          icon={<DoorOpen size={20} />}
          value={singleTurn === undefined ? "—" : formatShare(share(singleTurn, conversations), formatNumber)}
          hint={singleTurn === undefined ? undefined : t("overview.singleTurnHint", { count: formatNumber(singleTurn), total: formatNumber(conversations) })}
        />
        <KpiCard
          icon={<Archive size={20} />}
          label={t("overview.cacheHits")}
          value={formatShare(cached.rate, formatNumber)}
          hint={t("overview.answerRateHint", { count: formatNumber(cached.count), total: formatNumber(cached.answered) })}
        />
      </div>
      <p className="small muted">{t("overview.qualityRollupNote")}</p>

      <Card title={t("overview.outcomes")}>
        <BreakdownBars counts={outcomes} label={(outcome) => t(`outcome.${outcome}` as MessageKey)} empty={t("overview.noData")} />
      </Card>

      <DocumentHealth />
    </>
  );
}
