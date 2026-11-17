import { useI18n } from "../../i18n/I18nProvider";
import type { DailyMetrics } from "../../lib/types";

const CHART_HEIGHT = 160;
const BAR_WIDTH = 36;
const BAR_GAP = 8;
const BAR_PAIR_GAP = 2;
const HALF_BAR_WIDTH = (BAR_WIDTH - BAR_PAIR_GAP) / 2;
const LABEL_OFFSET = 14;
const LABEL_SPACE = 20;
const BAR_RADIUS = 3;
const MISSING = "—";

/** Daily p95 full-answer and first-token latency as paired bars (plain SVG, no chart library). */
export function LatencyChart({ history }: { history: DailyMetrics[] }) {
  const { t, formatNumber } = useI18n();
  const days = history
    .filter((row) => row.p95_latency_ms !== null || row.p95_first_token_ms !== null)
    .sort((a, b) => a.day.localeCompare(b.day));
  if (days.length === 0) return <p className="muted small">{t("overview.noLatency")}</p>;

  const max = Math.max(...days.flatMap((row) => [row.p95_latency_ms ?? 0, row.p95_first_token_ms ?? 0]), 1);
  const width = days.length * (BAR_WIDTH + BAR_GAP);
  const show = (value: number | null) => (value === null ? MISSING : formatNumber(Math.round(value)));

  return (
    <figure className="stack">
      <svg viewBox={`0 0 ${width} ${CHART_HEIGHT + LABEL_SPACE}`} className="chart" role="img" aria-label={t("overview.latencyChart")} preserveAspectRatio="xMinYMid meet">
        {days.map((row, index) => {
          const x = index * (BAR_WIDTH + BAR_GAP);
          const totalHeight = ((row.p95_latency_ms ?? 0) / max) * CHART_HEIGHT;
          const firstHeight = ((row.p95_first_token_ms ?? 0) / max) * CHART_HEIGHT;
          return (
            <g key={row.day}>
              <title>{t("overview.latencyDay", { day: row.day, total: show(row.p95_latency_ms), first: show(row.p95_first_token_ms) })}</title>
              {row.p95_latency_ms !== null && (
                <rect x={x} y={CHART_HEIGHT - totalHeight} width={HALF_BAR_WIDTH} height={totalHeight} rx={BAR_RADIUS} className="chart__prompt" />
              )}
              {row.p95_first_token_ms !== null && (
                <rect x={x + HALF_BAR_WIDTH + BAR_PAIR_GAP} y={CHART_HEIGHT - firstHeight} width={HALF_BAR_WIDTH} height={firstHeight} rx={BAR_RADIUS} className="chart__first-token" />
              )}
              <text x={x + BAR_WIDTH / 2} y={CHART_HEIGHT + LABEL_OFFSET} textAnchor="middle" className="chart__label">
                {row.day.slice(5)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="row small muted">
        <span className="legend" aria-hidden /> {t("overview.latencyTotal")}
        <span className="legend legend--first-token" aria-hidden /> {t("overview.latencyFirstToken")}
      </figcaption>
    </figure>
  );
}
