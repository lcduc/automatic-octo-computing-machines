import { ErrorState, LoadingState } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { DailyMetrics } from "../../lib/types";
import { useApi } from "../../lib/use-api";

/** A year of daily rollups; they outlive the purged raw data (OBS-03). */
const HISTORY_DAYS = 365;
const MICRO_USD_PER_USD = 1_000_000;
const MONTH_KEY_LENGTH = "YYYY-MM".length;

interface MonthRow {
  month: string;
  turns: number;
  conversations: number;
  errors: number;
  handoffs: number;
  cost: number;
  worstP95: number | null;
}

function byMonth(days: DailyMetrics[]): MonthRow[] {
  const months = new Map<string, MonthRow>();
  for (const day of days) {
    const key = day.day.slice(0, MONTH_KEY_LENGTH);
    const row = months.get(key) ?? { month: key, turns: 0, conversations: 0, errors: 0, handoffs: 0, cost: 0, worstP95: null };
    row.turns += day.turns;
    row.conversations += day.conversations;
    row.errors += day.errors;
    row.handoffs += day.handoffs;
    row.cost += day.cost_micro_usd;
    if (day.p95_latency_ms !== null) row.worstP95 = Math.max(row.worstP95 ?? 0, day.p95_latency_ms);
    months.set(key, row);
  }
  return [...months.values()].reverse();
}

/** Per-month totals from the daily rollup, newest first. */
export function MonthlyHistory() {
  const { t, formatNumber } = useI18n();
  const history = useApi<DailyMetrics[]>(`usage/history?days=${HISTORY_DAYS}`);
  if (history.error) return <ErrorState message={history.error} onRetry={history.reload} />;
  if (!history.data) return <LoadingState />;
  const rows = byMonth(history.data);
  if (rows.length === 0) return <p className="muted small">{t("history.empty")}</p>;
  const rate = (part: number, whole: number) => (whole ? `${formatNumber((part / whole) * 100, 1)}%` : "—");

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">{t("history.month")}</th>
            <th scope="col">{t("history.turns")}</th>
            <th scope="col">{t("history.conversations")}</th>
            <th scope="col">{t("history.handoffRate")}</th>
            <th scope="col">{t("history.errorRate")}</th>
            <th scope="col">{t("history.worstP95")}</th>
            <th scope="col">USD</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.month}>
              <td className="mono">{row.month}</td>
              <td>{formatNumber(row.turns)}</td>
              <td>{formatNumber(row.conversations)}</td>
              <td>{rate(row.handoffs, row.turns)}</td>
              <td>{rate(row.errors, row.turns)}</td>
              <td>{row.worstP95 === null ? "—" : `${formatNumber(row.worstP95)} ms`}</td>
              <td>{formatNumber(row.cost / MICRO_USD_PER_USD, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
