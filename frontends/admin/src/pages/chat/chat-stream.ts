/**
 * The demo chat's message model and how each Server-Sent Event of
 * `POST /api/chat/stream` changes it (events: meta, delta, done, error).
 */
import type { SseEvent } from "../../lib/sse";
import type { Citation, Outcome } from "../../lib/types";

export interface DemoMessage {
  /** The server's message id once `meta` arrived; a local id before that. */
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: string;
  streaming: boolean;
  outcome?: Outcome;
  citations: Citation[];
  confidence?: number | null;
  cached?: boolean;
  rating?: 1 | -1;
  /** Ticket opened by this turn, waiting for contact details. */
  handoffId?: string;
  /** When staff are expected to answer the ticket (ISO time). */
  replyBy?: string;
}

export interface StreamStep {
  message: DemoMessage;
  /** Set by `meta`: the conversation the turn belongs to. */
  conversationId?: string;
}

/** Text shown when the stream fails without a message of its own. */
export const STREAM_ERROR = "stream_error";

/**
 * Apply one stream event to the assistant message being written.
 *
 * `delta` appends text; `done` replaces it with the final text (canned replies
 * arrive only there) and adds outcome, citations and any ticket.
 */
export function applyStreamEvent(message: DemoMessage, event: SseEvent): StreamStep {
  const payload = JSON.parse(event.data) as Record<string, unknown>;
  switch (event.event) {
    case "meta":
      return { message: { ...message, id: String(payload.message_id) }, conversationId: String(payload.conversation_id) };
    case "delta":
      return { message: { ...message, text: message.text + String(payload.text ?? "") } };
    case "done":
      return {
        message: {
          ...message,
          text: (payload.text as string) || message.text,
          outcome: payload.outcome as Outcome,
          citations: (payload.citations as Citation[] | undefined) ?? [],
          confidence: (payload.confidence as number | null | undefined) ?? null,
          cached: Boolean(payload.cached),
          handoffId: (payload.handoff_id as string | null) ?? undefined,
          replyBy: (payload.reply_expected_by as string | null) ?? undefined,
          streaming: false,
        },
      };
    case "error":
      return { message: { ...message, text: (payload.message as string) || STREAM_ERROR, outcome: "error", streaming: false } };
    default:
      return { message };
  }
}
