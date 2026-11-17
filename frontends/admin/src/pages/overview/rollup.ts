/** Pure helpers that turn the usage summary and the daily rollup into overview numbers. */
import type { DailyMetrics, UsageSummary } from "../../lib/types";

const MICRO_USD_PER_USD = 1_000_000;
const PERCENT = 100;

/** What every overview panel receives: raw-row totals for the period and its daily rollups. */
export interface OverviewData {
  summary: UsageSummary;
  history: DailyMetrics[];
}

type DailyCount = "turns" | "conversations" | "errors" | "handoffs" | "cost_micro_usd";
type DailyPercentile = "p50_latency_ms" | "p95_latency_ms" | "p95_first_token_ms";

/** Every answered turn in the period, whatever its outcome. */
export function countTurns(summary: UsageSummary): number {
  return Object.values(summary.outcomes).reduce((total, count) => total + (count ?? 0), 0);
}

/** Sum one `breakdown` dict (e.g. `routes`) across days; missing or malformed entries are skipped. */
export function sumBreakdown(history: DailyMetrics[], key: string): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const day of history) {
    const counts = day.breakdown[key];
    if (!counts || typeof counts !== "object" || Array.isArray(counts)) continue;
    for (const [name, value] of Object.entries(counts)) {
      if (typeof value === "number" && Number.isFinite(value)) totals[name] = (totals[name] ?? 0) + value;
    }
  }
  return totals;
}

/** Sum a daily count across the period. */
export function sumDaily(history: DailyMetrics[], field: DailyCount): number {
  return history.reduce((total, day) => total + day[field], 0);
}

/** The slowest day's percentile (daily percentiles cannot be merged); null when no day has one. */
export function slowestDay(history: DailyMetrics[], field: DailyPercentile): number | null {
  let slowest: number | null = null;
  for (const day of history) {
    const value = day[field];
    if (value !== null) slowest = Math.max(slowest ?? value, value);
  }
  return slowest;
}

/** `part / whole` as a fraction, or null when there is nothing to divide by. */
export function share(part: number, whole: number): number | null {
  return whole > 0 ? part / whole : null;
}

/** A fraction from `share()` as a percentage with one decimal, or "—" when there is none. */
export function formatShare(fraction: number | null, formatNumber: (value: number, digits?: number) => string): string {
  return fraction === null ? "—" : `${formatNumber(fraction * PERCENT, 1)}%`;
}

/** Micro-dollars as dollars, e.g. `$1.23`; per-conversation costs need more `digits`. */
export function usd(microUsd: number, digits = 2): string {
  return `$${(microUsd / MICRO_USD_PER_USD).toFixed(digits)}`;
}

/** Days whose rollup row has `key` in its breakdown (rows rolled up before the key existed are left out). */
export function daysWith(history: DailyMetrics[], key: string): DailyMetrics[] {
  return history.filter((day) => day.breakdown[key] !== undefined && day.breakdown[key] !== null);
}

/** Sum a numeric breakdown key across the days that have it; non-numbers are skipped. */
export function sumNumber(history: DailyMetrics[], key: string): number {
  let total = 0;
  for (const day of history) {
    const value = day.breakdown[key];
    if (typeof value === "number" && Number.isFinite(value)) total += value;
  }
  return total;
}

/** p50 and p95 of one pipeline step, in milliseconds. */
export interface StepPercentiles {
  p50: number;
  p95: number;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Per step, the highest p50 and p95 over the days (daily percentiles cannot be merged); malformed entries are skipped. */
export function slowestSteps(history: DailyMetrics[]): Record<string, StepPercentiles> {
  const slowest: Record<string, StepPercentiles> = {};
  for (const day of history) {
    const steps = day.breakdown.step_latency_ms;
    if (!steps || typeof steps !== "object" || Array.isArray(steps)) continue;
    for (const [step, entry] of Object.entries(steps as Record<string, unknown>)) {
      if (!entry || typeof entry !== "object") continue;
      const { p50, p95 } = entry as Record<string, unknown>;
      if (!isFiniteNumber(p50) || !isFiniteNumber(p95)) continue;
      const known = slowest[step];
      slowest[step] = known ? { p50: Math.max(known.p50, p50), p95: Math.max(known.p95, p95) } : { p50, p95 };
    }
  }
  return slowest;
}

/** `part / whole` over the rollup days that have `key`, with the part and answered counts (answered is the whole). */
export function answerRate(history: DailyMetrics[], key: string): { count: number; answered: number; rate: number | null } {
  const days = daysWith(history, key);
  const answered = sumBreakdown(days, "outcomes").answered ?? 0;
  const count = sumNumber(days, key);
  return { count, answered, rate: share(count, answered) };
}

/** Mean of a numeric breakdown key over the days that have it; null when no day does. */
export function averagePerDay(history: DailyMetrics[], key: string): number | null {
  const days = daysWith(history, key).filter((day) => isFiniteNumber(day.breakdown[key]));
  return days.length > 0 ? sumNumber(days, key) / days.length : null;
}

/** Heatmap intensity of one cell in [0, 1], relative to the busiest cell; 0 when there is no traffic. */
export function heatLevel(count: number, max: number): number {
  return max > 0 && count > 0 ? Math.min(count / max, 1) : 0;
}

/** The largest cell of a weekday x hour grid (0 for an empty or missing grid). */
export function maxCell(traffic: number[][] | undefined): number {
  return Math.max(0, ...(traffic ?? []).flat().filter(isFiniteNumber));
}
