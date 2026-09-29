"use client";

import { useState } from "react";
import { Markdown } from "@/lib/markdown";
import type { ChatMessage } from "./use-chat";

interface MessageBubbleProps {
  message: ChatMessage;
  onRate: (messageId: string, rating: 1 | -1, comment?: string) => void;
  /** Opens the host site's sign-in (answers that need a signed-in user). */
  onLogin: () => void;
}

/** Outcomes whose answers can be rated (canned replies and errors cannot). */
const RATEABLE = new Set(["answered"]);

export function MessageBubble({ message, onRate, onLogin }: MessageBubbleProps) {
  const [commenting, setCommenting] = useState(false);
  const [comment, setComment] = useState("");
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-lg rounded-br-sm bg-[var(--brand)] px-3 py-2 text-sm text-white">
          {message.text}
        </p>
      </div>
    );
  }

  const canRate = !message.streaming && message.outcome !== undefined && RATEABLE.has(message.outcome) && !message.id.startsWith("local-");

  return (
    <div className="flex flex-col items-start gap-1">
      <div
        className={`max-w-[92%] space-y-2 rounded-lg rounded-bl-sm px-3 py-2 text-sm leading-relaxed ${
          message.outcome === "error" ? "bg-red-50 text-red-900" : "bg-slate-100 text-slate-900"
        }`}
      >
        {message.text ? (
          <Markdown text={message.text} />
        ) : (
          <span className="inline-flex gap-1 py-1" aria-label="Đang trả lời">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:120ms]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:240ms]" />
          </span>
        )}
        {message.outcome === "login_required" && (
          <button type="button" onClick={onLogin} className="rounded bg-[var(--brand)] px-3 py-1.5 text-xs font-semibold text-white">
            Đăng nhập
          </button>
        )}
        {message.outcome === "handoff" && (
          <p className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900">
            Yêu cầu đã được chuyển cho nhân viên hỗ trợ.
          </p>
        )}
      </div>

      {message.citations.length > 0 && (
        <details className="max-w-[92%] text-xs text-slate-600">
          <summary className="cursor-pointer select-none py-0.5">Nguồn tham khảo ({message.citations.length})</summary>
          <ul className="mt-1 space-y-1 pl-3">
            {message.citations.map((citation) => (
              <li key={citation.chunk_id}>
                {citation.url ? (
                  <a href={citation.url} target="_blank" rel="noopener noreferrer nofollow" className="underline">
                    {citation.title}
                  </a>
                ) : (
                  citation.title
                )}{" "}
                <span className="text-slate-400">· {citation.source}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {canRate && (
        <div className="flex items-center gap-1 text-xs text-slate-500">
          <button
            type="button"
            onClick={() => onRate(message.id, 1)}
            aria-pressed={message.rating === 1}
            className={`rounded px-1.5 py-0.5 hover:bg-slate-100 ${message.rating === 1 ? "text-emerald-700" : ""}`}
          >
            <span aria-hidden>👍</span> Hữu ích
          </button>
          <button
            type="button"
            onClick={() => {
              onRate(message.id, -1);
              setCommenting(true);
            }}
            aria-pressed={message.rating === -1}
            className={`rounded px-1.5 py-0.5 hover:bg-slate-100 ${message.rating === -1 ? "text-red-700" : ""}`}
          >
            <span aria-hidden>👎</span> Chưa đúng
          </button>
        </div>
      )}

      {commenting && (
        <form
          className="flex w-full max-w-[92%] gap-1"
          onSubmit={(event) => {
            event.preventDefault();
            onRate(message.id, -1, comment);
            setCommenting(false);
          }}
        >
          <label className="sr-only" htmlFor={`comment-${message.id}`}>Góp ý thêm</label>
          <input
            id={`comment-${message.id}`}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={1000}
            placeholder="Câu trả lời chưa đúng ở đâu? (không bắt buộc)"
            className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
          />
          <button type="submit" className="rounded bg-slate-800 px-2 py-1 text-xs text-white">Gửi</button>
        </form>
      )}
    </div>
  );
}
