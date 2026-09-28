"use client";

import { useState, type KeyboardEvent } from "react";

interface ComposerProps {
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

/** Keep in sync with the backend's MAX_MESSAGE_LENGTH. */
const MAX_MESSAGE_LENGTH = 2000;

export function Composer({ busy, onSend, onStop }: ComposerProps) {
  const [text, setText] = useState("");

  const submit = () => {
    if (!text.trim() || busy) return;
    onSend(text);
    setText("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      className="flex items-end gap-2 border-t border-slate-200 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label htmlFor="chat-input" className="sr-only">Nhập câu hỏi</label>
      <textarea
        id="chat-input"
        rows={1}
        value={text}
        maxLength={MAX_MESSAGE_LENGTH}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Nhập câu hỏi của bạn…"
        className="max-h-32 min-h-10 flex-1 resize-none rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-[var(--brand)] focus:outline-none focus:ring-1 focus:ring-[var(--brand)]"
      />
      {busy ? (
        <button type="button" onClick={onStop} className="h-10 rounded-md border border-slate-300 px-3 text-sm text-slate-700 hover:bg-slate-50">
          Dừng
        </button>
      ) : (
        <button
          type="submit"
          disabled={!text.trim()}
          className="h-10 rounded-md bg-[var(--brand)] px-4 text-sm font-medium text-white disabled:opacity-40"
        >
          Gửi
        </button>
      )}
    </form>
  );
}
