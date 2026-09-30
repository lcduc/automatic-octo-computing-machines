import { BookOpen, Check, Copy, Loader2, Sparkles, ThumbsDown, ThumbsUp, User } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Badge } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import { OUTCOME_TONES } from "../../lib/labels";
import { Markdown } from "../../lib/markdown";
import { STREAM_ERROR, type DemoMessage } from "./chat-stream";
import { CitationCard } from "./CitationCard";
import { HandoffCard } from "./HandoffCard";
import type { HandoffContact } from "./use-demo-chat";

/** How long the "copied" tick stays visible. */
const COPIED_MS = 2000;

interface ChatMessageViewProps {
  message: DemoMessage;
  conversationId: string | null;
  onRate: (messageId: string, rating: 1 | -1, comment?: string) => void;
  onContact: (handoffId: string, contact: HandoffContact) => Promise<string | null>;
}

export function ChatMessageView({ message, conversationId, onRate, onContact }: ChatMessageViewProps) {
  const { t, formatNumber } = useI18n();
  const [copied, setCopied] = useState(false);
  const [commenting, setCommenting] = useState(false);
  const [comment, setComment] = useState("");
  const isUser = message.role === "user";
  const text = message.text === STREAM_ERROR ? t("chat.connectionError") : message.text;
  // Canned replies and errors cannot be rated; the backend only accepts stored answers.
  const rateable = !message.streaming && message.outcome === "answered" && !message.id.startsWith("local-");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      // Clipboard blocked (permissions/insecure origin): nothing to copy into.
    }
  };

  const sendComment = (event: FormEvent) => {
    event.preventDefault();
    onRate(message.id, -1, comment);
    setCommenting(false);
  };

  return (
    <div className={isUser ? "chat-msg chat-msg--user" : "chat-msg"}>
      <span className="chat-msg__avatar" aria-hidden>
        {isUser ? <User size={18} /> : <Sparkles size={20} />}
      </span>
      <div className="chat-msg__body">
        <div className={message.outcome === "error" ? "chat-msg__bubble chat-msg__bubble--error" : "chat-msg__bubble"}>
          {isUser ? (
            <span className="prewrap">{text}</span>
          ) : text ? (
            <Markdown text={text} />
          ) : (
            <span className="row muted">
              <Loader2 size={16} className="spin" aria-hidden />
              {t("chat.thinking")}
            </span>
          )}
        </div>

        {message.outcome === "login_required" && <p className="chat-msg__note">{t("chat.loginRequired")}</p>}

        {message.citations.length > 0 && (
          <div className="chat-msg__citations">
            <div className="chat-msg__label">
              <BookOpen size={13} aria-hidden />
              {t("chat.citations", { count: message.citations.length })}
            </div>
            {message.citations.map((citation) => (
              <CitationCard key={citation.chunk_id} citation={citation} />
            ))}
          </div>
        )}

        {message.handoffId && (
          <HandoffCard handoffId={message.handoffId} replyBy={message.replyBy} onSubmit={(contact) => onContact(message.handoffId ?? "", contact)} />
        )}

        {!isUser && !message.streaming && (
          <div className="chat-msg__actions">
            {message.outcome && <Badge tone={OUTCOME_TONES[message.outcome]}>{t(`outcome.${message.outcome}`)}</Badge>}
            {typeof message.confidence === "number" && (
              <span>{t("chat.confidence", { value: formatNumber(message.confidence * 100, 0) })}</span>
            )}
            {message.cached && <Badge tone="gold">{t("chat.cached")}</Badge>}
            <button type="button" onClick={() => void copy()}>
              {copied ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
              {copied ? t("chat.copied") : t("chat.copy")}
            </button>
            {rateable && (
              <>
                <button type="button" aria-pressed={message.rating === 1} className="chat-msg__up" onClick={() => onRate(message.id, 1)}>
                  <ThumbsUp size={12} aria-hidden />
                  {t("chat.helpful")}
                </button>
                <button
                  type="button"
                  aria-pressed={message.rating === -1}
                  className="chat-msg__down"
                  aria-label={t("chat.notHelpful")}
                  onClick={() => {
                    onRate(message.id, -1);
                    setCommenting(true);
                  }}
                >
                  <ThumbsDown size={12} aria-hidden />
                </button>
              </>
            )}
            {conversationId && !message.id.startsWith("local-") && (
              <Link to={`/conversations/${conversationId}`}>{t("chat.trace")}</Link>
            )}
            <span className="chat-msg__time">{new Date(message.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          </div>
        )}

        {commenting && (
          <form className="row" onSubmit={sendComment}>
            <input
              className="input chat-msg__comment"
              aria-label={t("chat.commentLabel")}
              placeholder={t("chat.commentLabel")}
              maxLength={1000}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
            />
            <button type="submit" className="btn btn--sm">
              {t("chat.sendComment")}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
