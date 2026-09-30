import { Headphones, Info, Lightbulb, RotateCcw } from "lucide-react";
import { Link } from "react-router";
import { useI18n } from "../../i18n/I18nProvider";
import type { DemoChat } from "./use-demo-chat";

interface ChatSidePanelProps {
  chat: DemoChat;
  onNewSession: () => void;
}

/** Left column: new session, the widget's suggested questions, how the demo works, ask for a person. */
export function ChatSidePanel({ chat, onNewSession }: ChatSidePanelProps) {
  const { t } = useI18n();
  const questions = chat.config?.suggested_questions ?? [];
  return (
    <aside className="chat-side" aria-label={t("chat.sideLabel")}>
      <div className="chat-side__top">
        <button type="button" className="btn btn--primary chat-side__new" onClick={onNewSession}>
          <RotateCcw size={15} aria-hidden />
          {t("chat.newSession")}
        </button>
      </div>

      <div className="chat-side__scroll">
        <div className="chat-side__label">
          <Lightbulb size={14} aria-hidden />
          {t("chat.suggested")}
        </div>
        <div className="chat-topic">
          {questions.length === 0 ? (
            <p className="small muted">
              {t("chat.noSuggestions")} <Link to="/settings?tab=widget">{t("chat.editSuggestions")}</Link>
            </p>
          ) : (
            questions.map((question) => (
              <button key={question} type="button" className="chat-topic__question" disabled={chat.busy} onClick={() => void chat.send(question)}>
                {question}
              </button>
            ))
          )}
        </div>

        <div className="chat-side__info">
          <div className="row">
            <Info size={14} aria-hidden />
            <strong>{t("chat.howTitle")}</strong>
          </div>
          <ul>
            <li>{t("chat.how1")}</li>
            <li>{t("chat.how2")}</li>
            <li>{t("chat.how3")}</li>
          </ul>
        </div>
      </div>

      <div className="chat-side__bottom">
        <button type="button" className="btn chat-side__human" disabled={chat.busy} onClick={() => void chat.send(t("chat.askHumanMessage"))}>
          <Headphones size={15} aria-hidden />
          {t("chat.askHuman")}
        </button>
      </div>
    </aside>
  );
}
