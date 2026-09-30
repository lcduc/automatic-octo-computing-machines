import { useState } from "react";
import { Outlet, useMatches } from "react-router";
import { useI18n } from "../../i18n/I18nProvider";
import { query } from "../../lib/api";
import { capabilitiesFor } from "../../lib/permissions";
import { SessionProvider } from "../../lib/session";
import type { AdminUser, KnowledgeDocument, Handoff, Page } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { ErrorState, LoadingState } from "../ui/primitives";
import { ChangePasswordModal } from "./ChangePasswordModal";
import { Sidebar } from "./Sidebar";
import { TopBar, type RouteHandle } from "./TopBar";

/** How often the sidebar badge and the bell re-check pending work. */
const ALERT_REFRESH_MS = 30_000;

/** Signed-in frame: loads the admin once, then renders sidebar, topbar and the current page. */
export function ConsoleLayout() {
  const { t } = useI18n();
  const { data: admin, error, reload } = useApi<AdminUser>("auth/me");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const bleed = useMatches().some((match) => (match.handle as RouteHandle | undefined)?.bleed);
  const pending = useApi<Page<Handoff>>(admin ? `handoffs${query({ status: "open", limit: 1 })}` : null, ALERT_REFRESH_MS);
  const failed = useApi<Page<KnowledgeDocument>>(admin ? `knowledge/documents${query({ status: "failed", limit: 1 })}` : null, ALERT_REFRESH_MS);

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!admin) return <LoadingState />;
  const pendingHandoffs = pending.data?.total ?? null;
  const openPasswordDialog = () => setChangingPassword(true);

  return (
    <SessionProvider admin={admin}>
      <a href="#main" className="skip-link">
        {t("nav.skip")}
      </a>
      <div className="shell">
        <Sidebar
          capabilities={capabilitiesFor(admin.role)}
          pendingHandoffs={pendingHandoffs ?? 0}
          open={sidebarOpen}
          onNavigate={() => setSidebarOpen(false)}
          onChangePassword={openPasswordDialog}
        />
        <div className="shell__main">
          <TopBar
            onMenu={() => setSidebarOpen((value) => !value)}
            onChangePassword={openPasswordDialog}
            pendingHandoffs={pendingHandoffs}
            failedDocuments={failed.data?.total ?? 0}
          />
          <main id="main" className={bleed ? "shell__content shell__content--bleed" : "shell__content"} tabIndex={-1}>
            <Outlet />
          </main>
        </div>
      </div>
      {changingPassword && <ChangePasswordModal onClose={() => setChangingPassword(false)} />}
    </SessionProvider>
  );
}
