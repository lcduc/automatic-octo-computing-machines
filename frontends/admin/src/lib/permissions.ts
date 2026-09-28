/**
 * What each role may do, mirroring api/dependencies.py. The backend enforces
 * every rule; this only decides which controls to show.
 */
import type { Role } from "./types";

export interface Capabilities {
  /** Change knowledge, settings and run maintenance (owner, editor). */
  canWrite: boolean;
  /** Take on and close handoffs (owner, editor, support agent). */
  canHandoff: boolean;
  /** Accounts, API keys and the audit log (owner). */
  isOwner: boolean;
}

const WRITE_ROLES: readonly Role[] = ["owner", "editor"];
const HANDOFF_ROLES: readonly Role[] = ["owner", "editor", "support_agent"];

export function capabilitiesFor(role: Role): Capabilities {
  return {
    canWrite: WRITE_ROLES.includes(role),
    canHandoff: HANDOFF_ROLES.includes(role),
    isOwner: role === "owner",
  };
}
