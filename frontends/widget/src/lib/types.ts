/** Shapes returned by the public chat API (see the backend's api/schemas/chat.py). */

export type Outcome = "answered" | "smalltalk" | "denied" | "handoff" | "blocked" | "login_required" | "agent_reply" | "error";

export interface Citation {
  document_id: string;
  chunk_id: string;
  title: string;
  source: string;
  url?: string | null;
  /** Where in the document, e.g. "Chương II · Điều 35" (GEN-03). */
  section?: string | null;
  score: number;
}

export interface WidgetConfig {
  title: string;
  welcome_message: string;
  primary_color: string;
  suggested_questions: string[];
}
