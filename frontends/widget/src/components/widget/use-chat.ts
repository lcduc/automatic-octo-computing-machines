"use client";

/**
 * Chat state for the widget: loads config, restores the last conversation,
 * streams answers, and records feedback.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { readSse } from "@/lib/sse";
import type { Citation, Outcome, WidgetConfig } from "@/lib/types";

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

export function useChat() {
  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const conversationId = useRef<string | null>(null);
  const abortController = useRef<AbortController | null>(null);

  const updateMessage = useCallback((id: string, patch: Partial<ChatMessage>) => {
    setMessages((current) => current.map((message) => (message.id === id ? { ...message, ...patch } : message)));
  }, []);

  useEffect(() => {
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
      const history = await fetch(`/api/chat/conversations/${storedId}`).catch(() => null);
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
  }, []);

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
        const response = await fetch("/api/chat/stream", {
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
    [busy, updateMessage],
  );

  const stop = useCallback(() => abortController.current?.abort(), []);

  const rate = useCallback(
    async (messageId: string, rating: 1 | -1, comment?: string) => {
      updateMessage(messageId, { rating });
      const response = await fetch("/api/chat/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: messageId, rating, comment: comment || undefined }),
      }).catch(() => null);
      if (!response?.ok) setNotice("Không gửi được đánh giá, vui lòng thử lại.");
    },
    [updateMessage],
  );

  const reset = useCallback(() => {
    abortController.current?.abort();
    conversationId.current = null;
    storeConversation(null);
    setMessages([]);
    setNotice(null);
  }, []);

  return { config, messages, busy, notice, send, stop, rate, reset };
}
