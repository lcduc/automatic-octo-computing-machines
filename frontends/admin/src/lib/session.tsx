import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { adminApi } from "./api";
import { capabilitiesFor, type Capabilities } from "./permissions";
import type { AdminUser } from "./types";

interface SessionValue extends Capabilities {
  admin: AdminUser;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ admin, children }: { admin: AdminUser; children: ReactNode }) {
  const signOut = useCallback(async () => {
    await adminApi("auth/logout", { method: "POST", allowUnauthorized: true }).catch(() => undefined);
    // A full navigation drops every cached screen of the signed-out admin.
    window.location.assign("/login");
  }, []);

  const value = useMemo(() => ({ admin, signOut, ...capabilitiesFor(admin.role) }), [admin, signOut]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** The signed-in admin and what they may do; only usable inside the console layout. */
export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
