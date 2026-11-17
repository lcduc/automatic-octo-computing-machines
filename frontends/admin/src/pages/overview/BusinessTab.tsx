import { Coins, Headset, MessagesSquare, ShieldCheck, Users, Wallet } from "lucide-react";
import { Card, KpiCard } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import { routeLabel } from "../../lib/labels";
import { BreakdownBars } from "./BreakdownBars";
import { LiveFeed } from "./LiveFeed";
import { MonthlyHistory } from "./MonthlyHistory";
import { TrafficHeatmap } from "./TrafficHeatmap";
import { countTurns, daysWith, formatShare, share, sumBreakdown, sumDaily, sumNumber, usd, type OverviewData } from "./rollup";

/** Business panel: volume, cost, unanswered turns, request mix, cost by tier, live feed and monthly history. */
export function BusinessTab({ summary, history }: OverviewData) {
  const { t, formatNumber } = useI18n();
  const turns = countTurns(summary);
  const conversations = summary.latency.conversations;
  const unanswered = (summary.outcomes.denied ?? 0) + (summary.outcomes.handoff ?? 0);
  const handoffDays = daysWith(history, "conversations_handed_off");
  const handoffConversations = sumDaily(handoffDays, "conversations");
  const resolved = handoffConversations - sumNumber(handoffDays, "conversations_handed_off");
  const costPerResolved = resolved > 0 ? usd(sumDaily(handoffDays, "cost_micro_usd") / resolved, 4) : "—";
  const { projected_cost_micro_usd: projected, spend_cap_micro_usd: cap } = summary.month;
  const monthHint = [
    projected == null
      ? t("overview.costMonth", { month: usd(summary.month.cost_micro_usd) })
      : t("overview.costProjected", { month: usd(summary.month.cost_micro_usd), projected: usd(projected) }),
    cap ? t("overview.costCap", { cap: usd(cap) }) : null,
  ]
    .filter(Boolean)
    .join(" ");
  const visitors = summary.visitors;
  const costByTier = Object.fromEntries(summary.by_tier.map((row) => [row.tier, row.cost_micro_usd]));

  return (
    <>
      <div className="kpi-grid">
        <KpiCard
          icon={<Users size={20} />}
          label={t("overview.visitors")}
          value={visitors ? formatNumber(visitors.total) : "—"}
          hint={
            visitors
              ? t("overview.visitorsHint", { returning: formatNumber(visitors.returning), fresh: formatNumber(visitors.total - visitors.returning) })
              : undefined
          }
        />
        <KpiCard
          icon={<MessagesSquare size={20} />}
          label={t("overview.conversations")}
          value={formatNumber(conversations)}
          hint={t("overview.turnsPerConversation", {
            count: formatNumber(turns),
            average: conversations ? formatNumber(turns / conversations, 1) : "—",
          })}
        />
        <KpiCard
          icon={<Coins size={20} />}
          tone="gold"
          label={t("overview.costPeriod")}
          value={usd(summary.totals.cost_micro_usd)}
          hint={monthHint}
        />
        <KpiCard
          icon={<Wallet size={20} />}
          label={t("overview.costPerConversation")}
          value={conversations ? usd(summary.totals.cost_micro_usd / conversations, 4) : "—"}
          hint={t("overview.costPerResolved", { cost: costPerResolved })}
        />
        <KpiCard
          icon={<ShieldCheck size={20} />}
          tone="teal"
          label={t("overview.containment")}
          value={formatShare(share(resolved, handoffConversations), formatNumber)}
          hint={t("overview.containmentHint", { count: formatNumber(resolved) })}
        />
        <KpiCard
          icon={<Headset size={20} />}
          tone="rose"
          label={t("overview.unanswered")}
          value={formatNumber(unanswered)}
          hint={turns ? t("overview.unansweredShare", { percent: Math.round((unanswered / turns) * 100) }) : undefined}
        />
      </div>

      <div className="grid-2">
        <Card title={t("overview.requestTypes")}>
          <BreakdownBars counts={sumBreakdown(history, "routes")} label={(route) => t(routeLabel(route))} empty={t("overview.noData")} />
          <p className="small muted mt-3">{t("overview.rollupNote")}</p>
        </Card>
        <Card title={t("overview.busiestHours")}>
          <TrafficHeatmap traffic={summary.traffic} />
        </Card>
      </div>

      <div className="grid-2">
        <Card title={t("overview.visitorsByTier")}>
          <BreakdownBars counts={visitors?.by_tier ?? {}} label={(tier) => tier} empty={t("overview.noData")} />
        </Card>
        <Card title={t("overview.costByTier")}>
          <BreakdownBars counts={costByTier} label={(tier) => tier} format={(micro) => usd(micro, 4)} empty={t("overview.noData")} />
          {summary.by_purpose.length > 0 && (
            <p className="small muted mt-3">
              {summary.by_purpose.map((row) => t("overview.purpose", { purpose: row.purpose, tokens: formatNumber(row.tokens) })).join(" · ")}
            </p>
          )}
        </Card>
      </div>

      <Card title={t("overview.live")} flush>
        <LiveFeed />
      </Card>
      <Card title={t("history.title")} flush>
        <MonthlyHistory />
      </Card>
    </>
  );
}
