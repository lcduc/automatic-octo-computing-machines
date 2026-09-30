import { Database, ExternalLink, Filter, PowerOff, RotateCcw, Send, ShieldCheck, Sparkles, Square } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import { ConfirmDialog } from "../../components/ui/Modal";
import { PlannedBadge } from "../../components/ui/Planned";
import { Callout } from "../../components/ui/primitives";
import { useI18n } from "../../i18n/I18nProvider";
import type { Source } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { ChatMessageView } from "./ChatMessageView";
import { ChatSidePanel } from "./ChatSidePanel";
import { SourcesDrawer } from "./SourcesDrawer";
import { useDemoChat } from "./use-demo-chat";

/** Longest question the backend accepts (MAX_MESSAGE_LENGTH default). */
const MAX_MESSAGE_LENGTH = 2000;

/** Talk to the assistant exactly as a visitor would, with tools to inspect each answer. */
export function ChatPage() {
  const { t } = useI18n();
  const chat = useDemoChat();
  const sources = useApi<Source[]>("knowledge/sources");
  const [draft, setDraft] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
    // Every new message or streamed piece must scroll the thread to its end.
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [chat.messages]);

  const enabled = (sources.data ?? []).filter((source) => source.enabled);
  const submit = () => {
    if (!draft.trim() || chat.busy) return;
    void chat.send(draft);
    setDraft("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };
  const newSession = () => (chat.messages.length ? setConfirmReset(true) : chat.reset());

  return (
    <div className="chat-page">
      <ChatSidePanel chat={chat} onNewSession={newSession} />

      <section className="chat-main" aria-labelledby="chat-title">
        <header className="chat-banner">
          <div>
            <span className="chat-banner__kicker">
              <Sparkles size={12} aria-hidden />
              {t("chat.kicker")}
            </span>
            <h1 id="chat-title">{t("nav.chat")}</h1>
            <p>{chat.config ? t("chat.bannerBody", { title: chat.config.title }) : t("chat.bannerFallback")}</p>
          </div>
          <div className="chat-banner__actions">
            <span className={enabled.length ? "chat-status" : "chat-status chat-status--off"}>
              <span className="chat-status__dot" aria-hidden />
              {chat.sources.length
                ? t("chat.statusFiltered", { count: chat.sources.length })
                : t("chat.statusAll", { count: enabled.length })}
            </span>
            <button type="button" className="chat-banner__btn" disabled title={t("planned.hint")}>
              <PowerOff size={12} aria-hidden />
              {t("chat.ragOff")}
              <PlannedBadge />
            </button>
            <button type="button" className="chat-banner__btn" onClick={() => setDrawerOpen(true)}>
              {chat.sources.length ? <Filter size={12} aria-hidden /> : <Database size={12} aria-hidden />}
              {t("chat.sourcesButton", { count: sources.data?.length ?? 0 })}
            </button>
            {chat.conversationId && (
              <Link className="chat-banner__btn" to={`/conversations/${chat.conversationId}`}>
                <ExternalLink size={12} aria-hidden />
                {t("chat.openConversation")}
              </Link>
            )}
            <button type="button" className="chat-banner__btn chat-banner__btn--icon" onClick={newSession} aria-label={t("chat.newSession")}>
              <RotateCcw size={13} aria-hidden />
            </button>
          </div>
        </header>

        {!enabled.length && sources.data && (
          <div className="chat-alert" role="alert">
            {t("chat.noSourcesOn")} <Link to="/knowledge?tab=sources">{t("chat.manageSources")}</Link>
          </div>
        )}

        <div className="chat-thread">
          {chat.configError && (
            <div className="chat-thread__inner">
              <Callout tone="danger">{t("chat.unreachable", { message: chat.configError })}</Callout>
            </div>
          )}
          {chat.messages.length === 0 ? (
            <div className="chat-welcome">
              <span className="chat-welcome__logo" aria-hidden>
                <Sparkles size={32} />
              </span>
              <h2>{chat.config?.title ?? t("chat.welcomeTitle")}</h2>
              <p className="prewrap">{chat.config?.welcome_message || t("chat.welcomeBody")}</p>
              {chat.config && chat.config.suggested_questions.length > 0 && (
                <div className="chat-welcome__grid">
                  {chat.config.suggested_questions.slice(0, 4).map((question) => (
                    <button key={question} type="button" className="chat-welcome__card" disabled={chat.busy} onClick={() => void chat.send(question)}>
                      {question}
                    </button>
                  ))}
                </div>
              )}
              <span className="chat-welcome__notice">
                <ShieldCheck size={14} aria-hidden />
                {t("chat.privacy")}
              </span>
            </div>
          ) : (
            <div className="chat-thread__inner">
              {chat.messages.map((message) => (
                <ChatMessageView
                  key={message.id}
                  message={message}
                  conversationId={chat.conversationId}
                  onRate={(id, rating, comment) => void chat.rate(id, rating, comment)}
                  onContact={chat.submitContact}
                />
              ))}
              <div ref={endRef} />
            </div>
          )}
        </div>

        <div className="chat-composer">
          <div className="chat-composer__inner">
            {chat.notice && <Callout tone="warning">{chat.notice}</Callout>}
            <div className="chat-composer__box">
              <textarea
                rows={2}
                value={draft}
                maxLength={MAX_MESSAGE_LENGTH}
                aria-label={t("chat.inputLabel")}
                placeholder={t("chat.placeholder")}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onKeyDown}
              />
              <div className="row row--between">
                <span className="small muted row">
                  <ShieldCheck size={13} aria-hidden />
                  {t("chat.inputHint")}
                </span>
                {chat.busy ? (
                  <button type="button" className="btn btn--sm" onClick={chat.stop}>
                    <Square size={13} aria-hidden />
                    {t("chat.stop")}
                  </button>
                ) : (
                  <button type="button" className="btn btn--primary btn--sm" disabled={!draft.trim()} onClick={submit}>
                    <Send size={15} aria-hidden />
                    {t("chat.send")}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      {drawerOpen && <SourcesDrawer sources={sources} selected={chat.sources} onSelect={chat.setSources} onClose={() => setDrawerOpen(false)} />}
      {confirmReset && (
        <ConfirmDialog
          title={t("chat.newSession")}
          message={t("chat.resetConfirm")}
          confirmLabel={t("common.confirm")}
          onConfirm={() => {
            setConfirmReset(false);
            chat.reset();
          }}
          onCancel={() => setConfirmReset(false)}
        />
      )}
    </div>
  );
}
