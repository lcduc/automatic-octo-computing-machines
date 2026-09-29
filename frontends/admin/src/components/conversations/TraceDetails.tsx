import { useState } from "react";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageTrace } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { ErrorState, LoadingState } from "../ui/primitives";

/** Chunks listed in the trace view; the rest are summarised by count. */
const MAX_CHUNKS_SHOWN = 12;
const MICRO_USD_PER_USD = 1_000_000;

/** How one answer was produced (ADM-05), fetched only when opened. */
export function TraceDetails({ messageId }: { messageId: string }) {
  const { t, formatNumber } = useI18n();
  const [open, setOpen] = useState(false);
  const trace = useApi<MessageTrace>(open ? `messages/${messageId}/trace` : null);

  return (
    <details className="mt-3" onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary className="small">{t("trace.title")}</summary>
      {trace.loading && <LoadingState />}
      {trace.error && <ErrorState message={trace.error} onRetry={trace.reload} />}
      {trace.data && (
        <div className="stack small mt-3">
          <dl className="dl">
            <dt>{t("trace.route")}</dt>
            <dd>{[trace.data.route, trace.data.intent].filter(Boolean).join(" · ") || "—"}</dd>
            {trace.data.rewritten_query && (<><dt>{t("trace.rewritten")}</dt><dd>{trace.data.rewritten_query}</dd></>)}
            <dt>{t("trace.steps")}</dt>
            <dd className="mono">{Object.entries(trace.data.steps_ms).map(([step, ms]) => `${step} ${formatNumber(ms)} ms`).join(" · ")}</dd>
            <dt>{t("trace.prompt")}</dt>
            <dd className="mono">{trace.data.prompt_version ?? "—"}</dd>
            {Object.keys(trace.data.filters).length > 0 && (
              <><dt>{t("trace.filters")}</dt><dd className="mono">{JSON.stringify(trace.data.filters)}</dd></>
            )}
          </dl>
          {trace.data.calls.length > 0 && (
            <table className="table">
              <thead>
                <tr><th scope="col">{t("trace.purpose")}</th><th scope="col">{t("trace.model")}</th><th scope="col">{t("trace.tokens")}</th><th scope="col">USD</th></tr>
              </thead>
              <tbody>
                {trace.data.calls.map((call, index) => (
                  <tr key={index}>
                    <td>{call.purpose}</td>
                    <td className="mono">{call.model}</td>
                    <td>{formatNumber(call.prompt_tokens)} + {formatNumber(call.completion_tokens)}</td>
                    <td>{formatNumber(call.cost_micro_usd / MICRO_USD_PER_USD, 5)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {trace.data.tool_calls.length > 0 && (
            <ul>
              {trace.data.tool_calls.map((call, index) => (
                <li key={index} className="mono">
                  {call.name}({call.argument_names.join(", ")}) · {call.ok ? "ok" : t("trace.failed")} · {formatNumber(call.duration_ms)} ms
                </li>
              ))}
            </ul>
          )}
          {trace.data.chunks.length > 0 && (
            <table className="table">
              <thead>
                <tr><th scope="col">{t("trace.chunk")}</th><th scope="col">{t("trace.relevance")}</th><th scope="col">{t("trace.scores")}</th></tr>
              </thead>
              <tbody>
                {trace.data.chunks.slice(0, MAX_CHUNKS_SHOWN).map((chunk) => (
                  <tr key={chunk.chunk_id} className={chunk.matched ? undefined : "muted"}>
                    <td className="mono">{chunk.chunk_id}</td>
                    <td>{formatNumber(chunk.relevance, 3)}</td>
                    <td className="mono">
                      {formatNumber(chunk.semantic, 3)} / {formatNumber(chunk.keyword, 3)}
                      {chunk.rerank !== null && ` / ${formatNumber(chunk.rerank, 3)}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </details>
  );
}
