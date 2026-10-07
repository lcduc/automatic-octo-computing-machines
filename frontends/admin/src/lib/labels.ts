/** Badge tones for backend enums (labels live in the i18n dictionaries). */
import type { Tone } from "../components/ui/primitives";
import type { DocumentStatus, HandoffStatus, Outcome, ReviewStatus } from "./types";

export const OUTCOME_TONES: Record<Outcome, Tone> = {
  answered: "success",
  smalltalk: "neutral",
  denied: "warning",
  handoff: "info",
  blocked: "danger",
  login_required: "warning",
  agent_reply: "info",
  error: "danger",
};

export const DOCUMENT_STATUS_TONES: Record<DocumentStatus, Tone> = {
  processing: "info",
  ready: "success",
  failed: "danger",
};

export const REVIEW_STATUS_TONES: Record<ReviewStatus, Tone> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
};

export const HANDOFF_STATUS_TONES: Record<HandoffStatus, Tone> = {
  open: "warning",
  assigned: "info",
  answered: "success",
  closed: "neutral",
};

/** Conversation lifecycle: waiting for staff is a warning, staff on it is info, closed is quiet. */
export const CONVERSATION_STATUS_TONES: Record<string, Tone> = {
  active: "success",
  handoff_pending: "warning",
  staff_active: "info",
  closed: "neutral",
};

/** Audit status codes: 2xx success, 4xx refused, 5xx failed. */
export function statusTone(status: number): Tone {
  if (status < 300) return "success";
  if (status < 500) return "warning";
  return "danger";
}
