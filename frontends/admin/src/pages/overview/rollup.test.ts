import { describe, expect, it } from "vitest";
import type { DailyMetrics } from "../../lib/types";
import { answerRate, averagePerDay, daysWith, heatLevel, maxCell, formatShare, share, slowestDay, slowestSteps, sumBreakdown, sumDaily, sumNumber, usd } from "./rollup";

function day(overrides: Partial<DailyMetrics>): DailyMetrics {
  return {
    day: "2026-11-01",
    turns: 0,
    conversations: 0,
    errors: 0,
    handoffs: 0,
    p50_latency_ms: null,
    p95_latency_ms: null,
    p95_first_token_ms: null,
    prompt_tokens: 0,
    completion_tokens: 0,
    cost_micro_usd: 0,
    breakdown: {},
    ...overrides,
  };
}

describe("overview rollup helpers", () => {
  it("sums a breakdown across days and skips days without it or with bad values", () => {
    const history = [
      day({ breakdown: { routes: { rag: 3, tool: 1 } } }),
      day({ breakdown: {} }),
      day({ breakdown: { routes: { rag: 2, broken: "x" } } }),
      day({ breakdown: { routes: [1, 2] } }),
    ];
    expect(sumBreakdown(history, "routes")).toEqual({ rag: 5, tool: 1 });
  });

  it("sums daily counts and picks the slowest day's percentile", () => {
    const history = [day({ handoffs: 2, p95_first_token_ms: 800 }), day({ handoffs: 3, p95_first_token_ms: null }), day({ p95_first_token_ms: 1200 })];
    expect(sumDaily(history, "handoffs")).toBe(5);
    expect(slowestDay(history, "p95_first_token_ms")).toBe(1200);
    expect(slowestDay([day({})], "p95_first_token_ms")).toBeNull();
  });

  it("returns no share for an empty whole and formats micro-dollars", () => {
    expect(share(1, 0)).toBeNull();
    expect(share(1, 4)).toBe(0.25);
    expect(usd(1_234_567)).toBe("$1.23");
    expect(usd(1_234, 4)).toBe("$0.0012");
    const plain = (value: number, digits = 0) => value.toFixed(digits);
    expect(formatShare(0.125, plain)).toBe("12.5%");
    expect(formatShare(null, plain)).toBe("—");
  });

  it("counts only days whose row has the key, so older rows never read as zero", () => {
    const history = [
      day({ conversations: 5, breakdown: { cited_answers: 3, outcomes: { answered: 4 } } }),
      day({ conversations: 9, breakdown: { outcomes: { answered: 9 } } }),
      day({ breakdown: { cited_answers: 1, outcomes: { answered: 1 } } }),
    ];
    expect(daysWith(history, "cited_answers")).toHaveLength(2);
    expect(sumNumber(history, "cited_answers")).toBe(4);
    expect(answerRate(history, "cited_answers")).toEqual({ count: 4, answered: 5, rate: 0.8 });
    expect(answerRate(history, "cached_answers")).toEqual({ count: 0, answered: 0, rate: null });
  });

  it("takes each step's slowest p50 and p95 and skips malformed entries", () => {
    const history = [
      day({ breakdown: { step_latency_ms: { retrieval: { p50: 10, p95: 50 }, generation: { p50: 1, p95: "x" } } } }),
      day({ breakdown: { step_latency_ms: { retrieval: { p50: 20, p95: 40 }, total: null } } }),
      day({ breakdown: { step_latency_ms: [1] } }),
      day({}),
    ];
    expect(slowestSteps(history)).toEqual({ retrieval: { p50: 20, p95: 50 } });
  });

  it("averages a key only over the days that have it", () => {
    const history = [day({ breakdown: { visitors: 10 } }), day({ breakdown: { visitors: 20 } }), day({}), day({ breakdown: { visitors: "x" } })];
    expect(averagePerDay(history, "visitors")).toBe(15);
    expect(averagePerDay([day({})], "visitors")).toBeNull();
  });

  it("scales heatmap cells against the busiest one", () => {
    expect(maxCell([[1, 4], [2, 0]])).toBe(4);
    expect(maxCell(undefined)).toBe(0);
    expect(heatLevel(2, 4)).toBe(0.5);
    expect(heatLevel(0, 4)).toBe(0);
    expect(heatLevel(3, 0)).toBe(0);
  });
});
