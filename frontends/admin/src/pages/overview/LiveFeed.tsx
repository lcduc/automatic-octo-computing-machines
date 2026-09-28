import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Badge } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import { adminStream } from "../../lib/api";
import { OUTCOME_TONES } from "../../lib/labels";
import { readSse } from "../../lib/sse";
import type { LiveEvent, Outcome } from "../../lib/types";

interface FeedEvent {
  key: string;
  at: Date;
  type: "turn" | "handoff";
  conversationId?: string;
  outcome?: Outcome;
  tokens: number;
  latencyMs?: number | null;
}

/** Events kept on screen. */
const MAX_EVENTS = 30;
/** Delay before reconnecting a dropped stream. */
const RECONNECT_MS = 5000;

/** Real-time answered turns (with their token cost) and new handoff requests. */
export function LiveFeed() {
  const { t, formatNumber } = useI18n();
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let retry: number | undefined;
    let counter = 0;

    const connect = async () => {
      try {
        const response = await adminStream("usage/live", controller.signal);
        setConnected(true);
        for await (const message of readSse(response)) {
          const payload = JSON.parse(message.data) as LiveEvent;
          if (payload.type !== "turn" && payload.type !== "handoff") continue;
          counter += 1;
          const event: FeedEvent = {
            key: `${counter}`,
            at: new Date(),
            type: payload.type,
            conversationId: payload.conversation_id,
            outcome: payload.outcome,
            tokens: (payload.prompt_tokens ?? 0) + (payload.completion_tokens ?? 0),
            latencyMs: payload.latency_ms,
          };
          setEvents((current) => [event, ...current].slice(0, MAX_EVENTS));
        }
      } catch {
        // Dropped or refused stream: fall through and reconnect unless unmounting.
      }
      setConnected(false);
      if (!controller.signal.aborted) retry = window.setTimeout(connect, RECONNECT_MS);
    };
    void connect();
    return () => {
      controller.abort();
      if (retry) window.clearTimeout(retry);
    };
  }, []);

  return (
    <div>
      <p className="row small muted card__body">
        <Badge tone={connected ? "success" : "neutral"}>{connected ? t("live.connected") : t("live.reconnecting")}</Badge>
      </p>
      {events.length === 0 ? (
        <p className="muted small card__body">{t("live.empty")}</p>
      ) : (
        <ul className="feed" aria-live="polite">
          {events.map((event) => (
            <li key={event.key}>
              <time className="small muted">{event.at.toLocaleTimeString()}</time>
              {event.type === "handoff" ? (
                <Badge tone="info">{t("live.handoff")}</Badge>
              ) : (
                event.outcome && <Badge tone={OUTCOME_TONES[event.outcome]}>{t(`outcome.${event.outcome}`)}</Badge>
              )}
              {event.type === "turn" && (
                <span className="small muted">
                  {t("live.cost", { tokens: formatNumber(event.tokens), ms: formatNumber(event.latencyMs) })}
                </span>
              )}
              {event.conversationId && (
                <Link to={`/conversations/${event.conversationId}`} className="small push-right">
                  {t("live.open")}
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
