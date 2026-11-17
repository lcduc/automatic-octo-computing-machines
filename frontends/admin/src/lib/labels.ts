/** Badge tones for backend enums (labels live in the i18n dictionaries). */
import type { Tone } from "../components/ui/primitives";
import type { MessageKey } from "../i18n/vi";
import { HANDOFF_REASONS, ROUTES, type DocumentStatus, type HandoffStatus, type Outcome, type ReviewStatus } from "./types";

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

/** i18n key for a handoff reason; unknown reasons read as "Other". */
export function handoffReasonLabel(reason: string): MessageKey {
  return (HANDOFF_REASONS as readonly string[]).includes(reason) ? (`handoffReason.${reason}` as MessageKey) : "handoffReason.other";
}

/** i18n key for a trace route; unknown routes read as "Other". */
export function routeLabel(route: string): MessageKey {
  return (ROUTES as readonly string[]).includes(route) ? (`route.${route}` as MessageKey) : "route.other";
}

const GUARD_REASONS = ["prompt_injection", "moderation_flagged", "timeout", "error", "no_result", "client_disconnected"] as const;

/** i18n key for a guard/error reason on a turn; unknown reasons read as "Other". */
export function guardReasonLabel(reason: string): MessageKey {
  return (GUARD_REASONS as readonly string[]).includes(reason) ? (`guardReason.${reason}` as MessageKey) : "guardReason.other";
}

const PIPELINE_STEPS = ["guard", "router", "intent", "moderation", "rewrite", "retrieval", "generation", "first_token", "total"] as const;

/** Pipeline steps in the order a turn runs them. */
export const STEP_ORDER: readonly string[] = PIPELINE_STEPS;

/** i18n key for a pipeline step, or null for a step this admin does not know (show the raw name). */
export function stepLabel(step: string): MessageKey | null {
  return STEP_ORDER.includes(step) ? (`step.${step}` as MessageKey) : null;
}
