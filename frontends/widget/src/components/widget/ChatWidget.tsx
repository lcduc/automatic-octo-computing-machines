"use client";

import { useEffect, useRef, useSyncExternalStore, type CSSProperties } from "react";
import { Composer } from "./Composer";
import { MessageBubble } from "./MessageBubble";
import { useChat } from "./use-chat";

const FALLBACK_COLOR = "#0B5FFF";

const noopSubscribe = () => () => {};

/** Ask the embedding page (embed.js) to close the widget panel. */
function requestClose() {
  window.parent?.postMessage({ type: "chatbot:close" }, "*");
}

export function ChatWidget() {
  const { config, messages, busy, notice, send, stop, rate, reset } = useChat();
  const listEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listEnd.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const title = config?.title ?? "Trợ lý ảo";
  const style = { "--brand": config?.primary_color ?? FALLBACK_COLOR } as CSSProperties;
  // Server render assumes standalone; the client snapshot knows if it runs inside an iframe.
  const embedded = useSyncExternalStore(noopSubscribe, () => window.parent !== window, () => false);

  return (
    <div style={style} className="flex h-dvh flex-col bg-white text-slate-900">
      <header className="flex items-center justify-between bg-[var(--brand)] px-4 py-3 text-white">
        <h1 className="text-base font-semibold">{title}</h1>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button type="button" onClick={reset} className="rounded px-2 py-1 text-xs hover:bg-white/15">
              Cuộc trò chuyện mới
            </button>
          )}
          {embedded && (
            <button type="button" onClick={requestClose} aria-label="Đóng cửa sổ trò chuyện" className="rounded px-2 py-1 text-lg leading-none hover:bg-white/15">
              ×
            </button>
          )}
        </div>
      </header>

      <main className="flex-1 space-y-3 overflow-y-auto px-4 py-4" aria-live="polite" aria-busy={busy}>
        {messages.length === 0 && (
          <section className="space-y-3">
            <p className="rounded-lg bg-slate-100 px-3 py-2 text-sm">{config?.welcome_message ?? "Xin chào! Bạn cần hỗ trợ gì?"}</p>
            {config?.suggested_questions?.length ? (
              <div className="flex flex-wrap gap-2">
                {config.suggested_questions.map((question) => (
                  <button
                    key={question}
                    type="button"
                    onClick={() => send(question)}
                    className="rounded-full border border-[var(--brand)] px-3 py-1 text-left text-xs text-[var(--brand)] hover:bg-slate-50"
                  >
                    {question}
                  </button>
                ))}
              </div>
            ) : null}
          </section>
        )}
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} onRate={rate} />
        ))}
        {notice && <p role="alert" className="text-center text-xs text-red-700">{notice}</p>}
        <div ref={listEnd} />
      </main>

      <Composer busy={busy} onSend={send} onStop={stop} />
      <p className="px-4 pb-2 text-center text-[11px] text-slate-400">
        Trợ lý ảo có thể trả lời chưa chính xác. Vui lòng không chia sẻ thông tin cá nhân nhạy cảm.
      </p>
    </div>
  );
}
