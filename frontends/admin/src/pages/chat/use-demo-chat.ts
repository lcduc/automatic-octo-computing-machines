/**
 * State of the admin's demo chat. It talks to the chat widget's own server
 * (`/api/chat/*`, proxied onto the admin origin), so every answer goes through
 * exactly the pipeline visitors get, and the turn is stored like any other
 * anonymous conversation (visible under Conversations with its trace).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { describeError } from "../../lib/api";
import { readSse } from "../../lib/sse";
import { applyStreamEvent, STREAM_ERROR, type DemoMessage } from "./chat-stream";

/** The widget server's chat routes, reachable on the admin origin. */
export const CHAT_API_BASE = "/api/chat";

export interface WidgetConfig {
  title: string;
  welcome_message: string;
  primary_color: string;
  suggested_questions: string[];
}

export interface HandoffContact {
  name?: string;
  email?: string;
  phone?: string;
  details?: string;
  consent: boolean;
}

async function failure(response: Response): Promise<string> {
  const body = await response.json().catch(() => null);
  return describeError(body, response.status);
}

function post(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  return fetch(`${CHAT_API_BASE}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
    signal,
  });
}

export function useDemoChat() {
  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [messages, setMessages] = useState<DemoMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sources, setSources] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${CHAT_API_BASE}/config`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(await failure(response));
        setConfig((await response.json()) as WidgetConfig);
      })
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") setConfigError(reason.message);
      });
    return () => controller.abort();
  }, []);

  const replace = useCallback((id: string, next: DemoMessage) => {
    setMessages((current) => current.map((message) => (message.id === id ? next : message)));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || busy) return;
      setBusy(true);
      setNotice(null);
      const now = new Date().toISOString();
      const localId = `local-${Date.now()}`;
      let reply: DemoMessage = { id: `${localId}-reply`, role: "assistant", text: "", createdAt: now, streaming: true, citations: [] };
      setMessages((current) => [...current, { id: localId, role: "user", text: question, createdAt: now, streaming: false, citations: [] }, reply]);

      const controller = new AbortController();
      abort.current = controller;
      const body = { message: question, conversation_id: conversationId ?? undefined, sources: sources.length ? sources : undefined };
      try {
        const response = await post("stream", body, controller.signal);
        if (!response.ok) {
          if (response.status === 404 && conversationId) setConversationId(null);
          const next = { ...reply, text: await failure(response), outcome: "error" as const, streaming: false };
          replace(reply.id, next);
          reply = next;
          return;
        }
        for await (const event of readSse(response)) {
          const step = applyStreamEvent(reply, event);
          if (step.conversationId) setConversationId(step.conversationId);
          replace(reply.id, step.message);
          reply = step.message;
        }
      } catch (error) {
        const aborted = error instanceof DOMException && error.name === "AbortError";
        const next: DemoMessage = { ...reply, streaming: false, outcome: aborted ? reply.outcome : "error", text: reply.text || (aborted ? "" : STREAM_ERROR) };
        replace(reply.id, next);
        reply = next;
      } finally {
        abort.current = null;
        if (reply.streaming) replace(reply.id, { ...reply, streaming: false });
        setBusy(false);
      }
    },
    [busy, conversationId, sources, replace],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  const reset = useCallback(() => {
    abort.current?.abort();
    setMessages([]);
    setConversationId(null);
    setNotice(null);
  }, []);

  const rate = useCallback(async (messageId: string, rating: 1 | -1, comment?: string) => {
    setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, rating } : message)));
    const response = await post("feedback", { message_id: messageId, rating, comment: comment || undefined }).catch(() => null);
    if (!response?.ok) {
      setNotice(response ? await failure(response) : STREAM_ERROR);
      return;
    }
    // A second thumbs-down in a row may open a ticket for a person to answer.
    const result = (await response.json().catch(() => null)) as { handoff_id?: string | null } | null;
    if (result?.handoff_id) {
      const handoffId = result.handoff_id;
      setMessages((current) => current.map((message) => (message.id === messageId ? { ...message, handoffId } : message)));
    }
  }, []);

  /** Send a ticket's contact details; resolves with an error message, or null when accepted. */
  const submitContact = useCallback(async (handoffId: string, contact: HandoffContact): Promise<string | null> => {
    const response = await post(`handoffs/${handoffId}/contact`, contact).catch(() => null);
    if (!response) return STREAM_ERROR;
    return response.ok ? null : failure(response);
  }, []);

  return { config, configError, messages, conversationId, sources, setSources, busy, notice, send, stop, reset, rate, submitContact };
}

export type DemoChat = ReturnType<typeof useDemoChat>;
