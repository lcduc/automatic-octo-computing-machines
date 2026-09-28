import { Activity, BookOpen, Coins, Headset, MessagesSquare, ThumbsDown } from "lucide-react";
import { Fragment, useState } from "react";
import { ConfirmDialog } from "../../components/ui/Modal";
import { Card, ErrorState, Field, KpiCard, LoadingState, PageHeader } from "../../components/ui/primitives";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { adminApi } from "../../lib/api";
import { useSession } from "../../lib/session";
import { OUTCOMES, type MessageResponse, type SystemStatus, type UsageSummary } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { LiveFeed } from "./LiveFeed";
import { TokenChart } from "./TokenChart";

const PERIODS = [1, 7, 30] as const;
type Maintenance = "cache/clear" | "reindex";

export function OverviewPage() {
  const { t, formatNumber } = useI18n();
  const { canWrite } = useSession();
  const toast = useToast();
  const [days, setDays] = useState<(typeof PERIODS)[number]>(7);
  const [confirming, setConfirming] = useState<Maintenance | null>(null);
  const summary = useApi<UsageSummary>(`usage/summary?days=${days}`);
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

  const data = summary.data;
  const turns = data ? Object.values(data.outcomes).reduce((sum, count) => sum + (count ?? 0), 0) : 0;
  const unanswered = data ? (data.outcomes.denied ?? 0) + (data.outcomes.handoff ?? 0) : 0;
  const queue = system.data?.ingestion_queue;

  return (
    <>
      <PageHeader
        title={t("overview.title")}
        description={t("overview.description")}
        actions={
          <Field label={t("overview.period")}>
            <select className="select" value={days} onChange={(event) => setDays(Number(event.target.value) as (typeof PERIODS)[number])}>
              {PERIODS.map((period) => (
                <option key={period} value={period}>
                  {t(`overview.period.${period}`)}
                </option>
              ))}
            </select>
          </Field>
        }
      />

      {summary.error && <ErrorState message={summary.error} onRetry={summary.reload} />}
      {!data && !summary.error && <LoadingState />}
      {data && (
        <div className="kpi-grid">
          <KpiCard icon={<MessagesSquare size={20} />} label={t("overview.conversations")} value={formatNumber(data.latency.conversations)} hint={t("overview.turns", { count: formatNumber(turns) })} />
          <KpiCard icon={<Coins size={20} />} tone="gold" label={t("overview.tokens")} value={formatNumber(data.totals.prompt_tokens + data.totals.completion_tokens)} hint={t("overview.calls", { count: formatNumber(data.totals.calls) })} />
          <KpiCard
            icon={<Headset size={20} />}
            tone="rose"
            label={t("overview.unanswered")}
            value={formatNumber(unanswered)}
            hint={turns ? t("overview.unansweredShare", { percent: Math.round((unanswered / turns) * 100) }) : undefined}
          />
          <KpiCard
            icon={<ThumbsDown size={20} />}
            label={t("overview.feedback")}
            value={`${formatNumber(data.feedback.positive)} / ${formatNumber(data.feedback.negative)}`}
            hint={t("overview.feedbackHint")}
          />
          <KpiCard
            icon={<Activity size={20} />}
            tone="teal"
            label={t("overview.latency")}
            value={data.latency.p95_ms ? `${formatNumber(Math.round(data.latency.p95_ms))} ms` : "—"}
            hint={data.latency.p50_ms ? t("overview.latencyHint", { p50: formatNumber(Math.round(data.latency.p50_ms)) }) : undefined}
          />
          <KpiCard
            icon={<BookOpen size={20} />}
            label={t("overview.indexed")}
            value={formatNumber(system.data?.indexed_chunks)}
            hint={queue ? t("overview.queue", { pending: queue.pending, running: queue.in_progress }) : undefined}
          />
        </div>
      )}

      {data && (
        <div className="grid-2">
          <Card title={t("overview.tokensChart")}>
            <TokenChart daily={data.daily} />
          </Card>
          <Card title={t("overview.outcomes")}>
            <dl className="dl">
              {OUTCOMES.filter((outcome) => data.outcomes[outcome]).map((outcome) => (
                <Fragment key={outcome}>
                  <dt>{t(`outcome.${outcome}`)}</dt>
                  <dd>{formatNumber(data.outcomes[outcome])}</dd>
                </Fragment>
              ))}
            </dl>
            {data.by_purpose.length > 0 && (
              <p className="small muted mt-3">
                {data.by_purpose.map((row) => t("overview.purpose", { purpose: row.purpose, tokens: formatNumber(row.tokens) })).join(" · ")}
              </p>
            )}
          </Card>
        </div>
      )}

      <div className="grid-2">
        <Card title={t("overview.live")} flush>
          <LiveFeed />
        </Card>
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
              <dt>{t("overview.fallback")}</dt>
              <dd>{t(`settings.fallback.${system.data.fallback_mode}`)}</dd>
              <dt>{t("overview.cache")}</dt>
              <dd>{t("overview.cacheValue", { size: String(system.data.cache.size ?? 0), rate: String(system.data.cache.hit_rate ?? "—") })}</dd>
              <dt>{t("overview.version")}</dt>
              <dd className="mono">{system.data.version}</dd>
            </dl>
          )}
        </Card>
      </div>

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
