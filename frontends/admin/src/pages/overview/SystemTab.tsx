import { Activity, BookOpen, Timer, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { ConfirmDialog } from "../../components/ui/Modal";
import { Card, ErrorState, KpiCard } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { guardReasonLabel } from "../../lib/labels";
import { useSession } from "../../lib/session";
import type { MessageResponse, SystemStatus } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { BreakdownBars } from "./BreakdownBars";
import { LatencyChart } from "./LatencyChart";
import { type OverviewData, countTurns, formatShare, share, slowestDay, slowestSteps, sumBreakdown } from "./rollup";
import { SecuritySummary } from "./SecuritySummary";
import { StepLatencyTable } from "./StepLatencyTable";
import { TokenChart } from "./TokenChart";

const ICON_SIZE = 20;
type Maintenance = "cache/clear" | "reindex";

/** Overview tab for system health: latency, error rate, charts, index size and maintenance actions. */
export function SystemTab({ summary, history }: OverviewData) {
  const { t, formatNumber } = useI18n();
  const { canWrite, isOwner } = useSession();
  const toast = useToast();
  const [confirming, setConfirming] = useState<Maintenance | null>(null);
  const system = useApi<SystemStatus>("system");

  const runMaintenance = async (action: Maintenance) => {
    setConfirming(null);
    try {
      const result = await adminApi<MessageResponse>(`system/${action}`, { method: "POST" });
      toast.success(result.message);
      system.reload();
    } catch (reason) {
      toast.error((reason as Error).message);
    }
  };

  const turns = countTurns(summary);
  const errors = summary.outcomes.error ?? 0;
  const firstToken = slowestDay(history, "p95_first_token_ms");
  const queue = system.data?.ingestion_queue;

  return (
    <>
      <div className="kpi-grid">
        <KpiCard
          icon={<Activity size={ICON_SIZE} />}
          tone="teal"
          label={t("overview.latency")}
          value={summary.latency.p95_ms ? `${formatNumber(Math.round(summary.latency.p95_ms))} ms` : "—"}
          hint={summary.latency.p50_ms ? t("overview.latencyHint", { p50: formatNumber(Math.round(summary.latency.p50_ms)) }) : undefined}
        />
        <KpiCard
          icon={<Timer size={ICON_SIZE} />}
          label={t("overview.firstToken")}
          value={firstToken === null ? "—" : `${formatNumber(Math.round(firstToken))} ms`}
          hint={t("overview.slowestDay")}
        />
        <KpiCard
          icon={<TriangleAlert size={ICON_SIZE} />}
          tone="rose"
          label={t("overview.errorRate")}
          value={formatShare(share(errors, turns), formatNumber)}
          hint={t("overview.errorCount", { count: formatNumber(errors) })}
        />
        <KpiCard
          icon={<BookOpen size={ICON_SIZE} />}
          label={t("overview.indexed")}
          value={formatNumber(system.data?.indexed_chunks)}
          hint={queue ? t("overview.queue", { pending: queue.pending, running: queue.in_progress }) : undefined}
        />
      </div>

      <div className="grid-2">
        <Card title={t("overview.latencyChart")}>
          <LatencyChart history={history} />
        </Card>
        <Card title={t("overview.tokensChart")}>
          <TokenChart daily={summary.daily} />
        </Card>
      </div>

      <div className="grid-2">
        <Card title={t("overview.guardReasons")}>
          <BreakdownBars counts={sumBreakdown(history, "guard_reasons")} label={(reason) => t(guardReasonLabel(reason))} empty={t("overview.noData")} />
          <p className="small muted mt-3">{t("overview.rollupNote")}</p>
        </Card>
        <Card title={t("overview.stepLatency")}>
          <StepLatencyTable steps={slowestSteps(history)} />
        </Card>
      </div>

      <Card
        title={t("overview.system")}
        actions={
          canWrite && (
            <>
              <button type="button" className="btn btn--sm" onClick={() => setConfirming("cache/clear")}>
                {t("overview.clearCache")}
              </button>
              <button type="button" className="btn btn--sm" onClick={() => setConfirming("reindex")}>
                {t("overview.reindex")}
              </button>
            </>
          )
        }
      >
        {system.error && <ErrorState message={system.error} onRetry={system.reload} />}
        {system.data && (
          <dl className="dl">
            <dt>{t("overview.database")}</dt>
            <dd>{system.data.database ? t("common.ok") : t("overview.databaseDown")}</dd>
            <dt>{t("overview.model")}</dt>
            <dd className="mono">
              {system.data.llm_provider} / {system.data.llm_model}
            </dd>
            <dt>{t("overview.embedding")}</dt>
            <dd className="mono">{system.data.embedding_model}</dd>
            <dt>{t("overview.reranker")}</dt>
            <dd>{system.data.reranker_loaded ? t("common.on") : t("common.off")}</dd>
            {system.data.model_server && (
              <>
                <dt>{t("overview.gpu")}</dt>
                <dd>
                  {system.data.model_server.gpu_free_mb !== null && system.data.model_server.gpu_total_mb !== null
                    ? t("overview.gpuMemory", {
                        free: formatNumber(system.data.model_server.gpu_free_mb),
                        total: formatNumber(system.data.model_server.gpu_total_mb),
                      })
                    : t("overview.gpuNone")}
                  {" · "}
                  {t("overview.gpuQueue", {
                    chat: system.data.model_server.chat_waiting,
                    ingestion: system.data.model_server.ingestion_waiting,
                  })}
                </dd>
              </>
            )}
            <dt>{t("overview.fallback")}</dt>
            <dd>{t(`settings.fallback.${system.data.fallback_mode}`)}</dd>
            <dt>{t("overview.cache")}</dt>
            <dd>{t("overview.cacheValue", { size: String(system.data.cache.size ?? 0), rate: String(system.data.cache.hit_rate ?? "—") })}</dd>
            <dt>{t("overview.version")}</dt>
            <dd className="mono">{system.data.version}</dd>
          </dl>
        )}
      </Card>

      {isOwner && <SecuritySummary />}

      {confirming && (
        <ConfirmDialog
          title={confirming === "reindex" ? t("overview.reindex") : t("overview.clearCache")}
          message={confirming === "reindex" ? t("overview.reindexConfirm") : t("overview.clearCacheConfirm")}
          confirmLabel={t("common.confirm")}
          onConfirm={() => void runMaintenance(confirming)}
          onCancel={() => setConfirming(null)}
        />
      )}
    </>
  );
}
