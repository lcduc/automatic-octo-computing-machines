/** Badge tones for backend enums (labels live in the i18n dictionaries). */
import type { Tone } from "../components/ui/primitives";
import type { DocumentStatus, HandoffStatus, Outcome } from "./types";

export const OUTCOME_TONES: Record<Outcome, Tone> = {
  answered: "success",
  smalltalk: "neutral",
  denied: "warning",
  handoff: "info",
  blocked: "danger",
  error: "danger",
};

export const DOCUMENT_STATUS_TONES: Record<DocumentStatus, Tone> = {
  processing: "info",
  ready: "success",
  failed: "danger",
};

export const HANDOFF_STATUS_TONES: Record<HandoffStatus, Tone> = {
  pending: "warning",
  in_progress: "info",
  resolved: "success",
};

/** Audit status codes: 2xx success, 4xx refused, 5xx failed. */
export function statusTone(status: number): Tone {
  if (status < 300) return "success";
  if (status < 500) return "warning";
  return "danger";
}
