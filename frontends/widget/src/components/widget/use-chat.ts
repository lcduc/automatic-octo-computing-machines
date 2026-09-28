"use client";

/**
 * Chat state for the widget: loads config, restores the last conversation,
 * streams answers, and records feedback. A signed-in host user's token is sent
 * with every call (`Authorization: Bearer`, relayed by this app's server); an
 * expired one is refreshed from the host page once, and a host logout clears
 * the private history from the screen.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { readSse } from "@/lib/sse";
import type { Citation, Outcome, WidgetConfig } from "@/lib/types";
import { useHostSession } from "./use-host-session";

export interface ChatMessage {
  /** Server id for assistant messages once known; a local id otherwise. */
  id: string;
  role: "user" | "assistant";
  text: string;
  outcome?: Outcome;
  citations: Citation[];
  streaming: boolean;
  rating?: 1 | -1;
}

const CONVERSATION_KEY = "chatbot.conversation";
const GENERIC_ERROR = "Xin lỗi, đã có lỗi kết nối. Bạn vui lòng thử lại.";

function readStoredConversation(): string | null {
  try {
    return window.localStorage.getItem(CONVERSATION_KEY);
  } catch {
    return null;
  }
}

function storeConversation(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(CONVERSATION_KEY, id);
    else window.localStorage.removeItem(CONVERSATION_KEY);
  } catch {
    /* storage unavailable (private mode / partitioned iframe): history just isn't restored */
  }
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* non-JSON error body */
  }
  return GENERIC_ERROR;
}

function rejectedToken(response: Response): boolean {
  return response.status === 401 && (response.headers.get("www-authenticate") ?? "").includes("invalid_token");
}

export function useChat(allowedOrigins: string[]) {
  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const conversationId = useRef<string | null>(null);
  const abortController = useRef<AbortController | null>(null);

  const clearConversation = useCallback(() => {
    abortController.current?.abort();
    conversationId.current = null;
    storeConversation(null);
    setMessages([]);
    setNotice(null);
  }, []);
  const session = useHostSession(allowedOrigins, clearConversation);
  const token = useRef<string | null>(null);
  useEffect(() => {
    token.current = session.token;
  }, [session.token]);

  /** fetch() with the host token; one retry with a fresh token when the server refused it. */
  const authorizedFetch = useCallback(
    async (url: string, init: RequestInit = {}): Promise<Response> => {
      const attempt = (value: string | null) =>
        fetch(url, { ...init, headers: { ...(init.headers ?? {}), ...(value ? { Authorization: `Bearer ${value}` } : {}) } });
      const response = await attempt(token.current);
      if (!token.current || !rejectedToken(response)) return response;
      const fresh = await session.refresh();
      token.current = fresh;
      return attempt(fresh);
    },
    [session],
  );

  const updateMessage = useCallback((id: string, patch: Partial<ChatMessage>) => {
    setMessages((current) => current.map((message) => (message.id === id ? { ...message, ...patch } : message)));
  }, []);

  useEffect(() => {
    // Wait for the host page's first word, so a signed-in user's history loads with their token.
    if (!session.ready) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/chat/config");
        if (response.ok && !cancelled) setConfig(await response.json());
      } catch {
        if (!cancelled) setNotice(GENERIC_ERROR);
      }
      const storedId = readStoredConversation();
      if (!storedId) return;
      const history = await authorizedFetch(`/api/chat/conversations/${storedId}`).catch(() => null);
      if (!history?.ok) {
        storeConversation(null);
        return;
      }
      const conversation = await history.json();
      if (cancelled) return;
      conversationId.current = conversation.id;
      setMessages(
        conversation.messages.map((message: {
          id: string; role: "user" | "assistant"; content: string; outcome: Outcome | null;
          citations: Citation[]; feedback_rating: 1 | -1 | null;
        }) => ({
          id: message.id,
          role: message.role,
          text: message.content,
          outcome: message.outcome ?? undefined,
          citations: message.citations ?? [],
          streaming: false,
          rating: message.feedback_rating ?? undefined,
        })),
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [session.ready, authorizedFetch]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      setNotice(null);
      setBusy(true);
      const localId = `local-${Date.now()}`;
      let assistantId = `${localId}-reply`;
      setMessages((current) => [
        ...current,
        { id: localId, role: "user", text: message, citations: [], streaming: false },
        { id: assistantId, role: "assistant", text: "", citations: [], streaming: true },
      ]);

      const controller = new AbortController();
      abortController.current = controller;
      try {
        const response = await authorizedFetch("/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, conversation_id: conversationId.current ?? undefined }),
          signal: controller.signal,
        });
        if (!response.ok) {
          if (response.status === 404 && conversationId.current) {
            conversationId.current = null;
            storeConversation(null);
          }
          updateMessage(assistantId, { text: await errorDetail(response), outcome: "error", streaming: false });
          return;
        }
        let streamed = "";
        for await (const event of readSse(response)) {
          const payload = JSON.parse(event.data);
          if (event.event === "meta") {
            conversationId.current = payload.conversation_id;
            storeConversation(payload.conversation_id);
            updateMessage(assistantId, { id: payload.message_id });
            assistantId = payload.message_id;
          } else if (event.event === "delta") {
            streamed += payload.text;
            updateMessage(assistantId, { text: streamed });
          } else if (event.event === "done") {
            updateMessage(assistantId, {
              text: payload.text || streamed,
              outcome: payload.outcome,
              citations: payload.citations ?? [],
              streaming: false,
            });
          } else if (event.event === "error") {
            updateMessage(assistantId, { text: payload.message ?? GENERIC_ERROR, outcome: "error", streaming: false });
          }
        }
      } catch (error) {
        const aborted = error instanceof DOMException && error.name === "AbortError";
        setMessages((current) =>
          current.map((item) =>
            item.id === assistantId && item.streaming
              ? { ...item, streaming: false, outcome: aborted ? item.outcome : "error", text: item.text || (aborted ? "Đã dừng." : GENERIC_ERROR) }
              : item,
          ),
        );
      } finally {
        abortController.current = null;
        setMessages((current) => current.map((item) => (item.id === assistantId ? { ...item, streaming: false } : item)));
        setBusy(false);
      }
    },
    [busy, updateMessage, authorizedFetch],
  );

  const stop = useCallback(() => abortController.current?.abort(), []);

  const rate = useCallback(
    async (messageId: string, rating: 1 | -1, comment?: string) => {
      updateMessage(messageId, { rating });
      const response = await authorizedFetch("/api/chat/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: messageId, rating, comment: comment || undefined }),
      }).catch(() => null);
      if (!response?.ok) setNotice("Không gửi được đánh giá, vui lòng thử lại.");
    },
    [updateMessage, authorizedFetch],
  );

  return {
    config, messages, busy, notice, send, stop, rate, reset: clearConversation,
    signedIn: session.token !== null, requestLogin: session.requestLogin, close: session.close,
  };
}
