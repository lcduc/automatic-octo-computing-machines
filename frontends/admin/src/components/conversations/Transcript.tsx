import { ExternalLink, ThumbsDown, ThumbsUp } from "lucide-react";
import { Badge } from "../ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import { OUTCOME_TONES } from "../../lib/labels";
import type { AdminMessage } from "../../lib/types";

/** Messages of one conversation with the answer's sources, cost and rating. */
export function Transcript({ messages }: { messages: AdminMessage[] }) {
  const { t, formatDateTime, formatNumber } = useI18n();
  if (messages.length === 0) return <p className="muted">{t("conversations.noMessages")}</p>;

  return (
    <ol className="stack">
      {messages.map((message) => (
        <li key={message.id} className={message.role === "user" ? "message message--user" : "message message--assistant"}>
          <div className="chunk__meta">
            <strong>{message.role === "user" ? t("conversations.user") : t("conversations.assistant")}</strong>
            <span className="small muted">{formatDateTime(message.created_at)}</span>
            {message.outcome && <Badge tone={OUTCOME_TONES[message.outcome]}>{t(`outcome.${message.outcome}`)}</Badge>}
            {message.cached && <Badge>{t("conversations.cached")}</Badge>}
            {message.guard_reason && <Badge tone="danger">{message.guard_reason}</Badge>}
            {message.feedback && (
              <Badge tone={message.feedback.rating > 0 ? "success" : "danger"}>
                {message.feedback.rating > 0 ? <ThumbsUp size={12} aria-hidden /> : <ThumbsDown size={12} aria-hidden />}
                {message.feedback.rating > 0 ? t("feedback.positive") : t("feedback.negative")}
              </Badge>
            )}
          </div>
          <p className="prewrap">{message.content}</p>
          {message.feedback?.comment && <p className="small muted mt-3">“{message.feedback.comment}”</p>}
          {message.role === "assistant" && (message.model || message.latency_ms !== null) && (
            <p className="small muted mt-3">
              {t("conversations.cost", {
                model: message.model ?? "—",
                prompt: formatNumber(message.prompt_tokens),
                completion: formatNumber(message.completion_tokens),
                ms: formatNumber(message.latency_ms),
                confidence: message.confidence === null ? "—" : formatNumber(message.confidence, 2),
              })}
            </p>
          )}
          {message.citations.length > 0 && (
            <div className="row mt-3">
              {message.citations.map((citation) => (
                <Badge key={`${citation.document_id}-${citation.chunk_id}`} tone="gold">
                  {citation.url ? (
                    <a href={citation.url} target="_blank" rel="noreferrer noopener">
                      {citation.title} <ExternalLink size={11} aria-hidden />
                    </a>
                  ) : (
                    citation.title
                  )}
                  <span className="muted"> · {citation.source}</span>
                </Badge>
              ))}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
