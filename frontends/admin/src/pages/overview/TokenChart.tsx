import { useI18n } from "../../i18n/I18nProvider";
import type { UsageSummary } from "../../lib/types";

const CHART_HEIGHT = 160;
const BAR_WIDTH = 36;
const BAR_GAP = 8;

/** Daily prompt + completion tokens as stacked bars (plain SVG, no chart library). */
export function TokenChart({ daily }: { daily: UsageSummary["daily"] }) {
  const { t, formatNumber } = useI18n();
  const byDay = new Map<string, { prompt: number; completion: number }>();
  for (const row of daily) {
    const entry = byDay.get(row.day) ?? { prompt: 0, completion: 0 };
    entry.prompt += row.prompt_tokens;
    entry.completion += row.completion_tokens;
    byDay.set(row.day, entry);
  }
  const days = [...byDay.entries()].sort(([a], [b]) => a.localeCompare(b));
  if (days.length === 0) return <p className="muted small">{t("overview.noTokens")}</p>;

  const max = Math.max(...days.map(([, value]) => value.prompt + value.completion), 1);
  const width = days.length * (BAR_WIDTH + BAR_GAP);

  return (
    <figure className="stack">
      <svg viewBox={`0 0 ${width} ${CHART_HEIGHT + 20}`} className="chart" role="img" aria-label={t("overview.tokensChart")} preserveAspectRatio="xMinYMid meet">
        {days.map(([day, value], index) => {
          const x = index * (BAR_WIDTH + BAR_GAP);
          const promptHeight = (value.prompt / max) * CHART_HEIGHT;
          const completionHeight = (value.completion / max) * CHART_HEIGHT;
          return (
            <g key={day}>
              <title>{t("overview.tokensDay", { day, prompt: formatNumber(value.prompt), completion: formatNumber(value.completion) })}</title>
              <rect x={x} y={CHART_HEIGHT - promptHeight} width={BAR_WIDTH} height={promptHeight} rx={3} className="chart__prompt" />
              <rect x={x} y={CHART_HEIGHT - promptHeight - completionHeight} width={BAR_WIDTH} height={completionHeight} rx={3} className="chart__completion" />
              <text x={x + BAR_WIDTH / 2} y={CHART_HEIGHT + 14} textAnchor="middle" className="chart__label">
                {day.slice(5)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="row small muted">
        <span className="legend" aria-hidden /> {t("overview.promptTokens")}
        <span className="legend legend--completion" aria-hidden /> {t("overview.completionTokens")}
      </figcaption>
    </figure>
  );
}
