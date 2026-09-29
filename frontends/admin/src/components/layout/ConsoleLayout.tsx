import { useState } from "react";
import { Outlet } from "react-router";
import { useI18n } from "../../i18n/I18nProvider";
import { query } from "../../lib/api";
import { capabilitiesFor } from "../../lib/permissions";
import { SessionProvider } from "../../lib/session";
import type { AdminUser, KnowledgeDocument, Handoff, Page } from "../../lib/types";
import { useApi } from "../../lib/use-api";
import { ErrorState, LoadingState } from "../ui/primitives";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

/** How often the sidebar badge and the bell re-check pending work. */
const ALERT_REFRESH_MS = 30_000;

/** Signed-in frame: loads the admin once, then renders sidebar, topbar and the current page. */
export function ConsoleLayout() {
  const { t } = useI18n();
  const { data: admin, error, reload } = useApi<AdminUser>("auth/me");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pending = useApi<Page<Handoff>>(admin ? `handoffs${query({ status: "open", limit: 1 })}` : null, ALERT_REFRESH_MS);
  const failed = useApi<Page<KnowledgeDocument>>(admin ? `knowledge/documents${query({ status: "failed", limit: 1 })}` : null, ALERT_REFRESH_MS);

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!admin) return <LoadingState />;
  const pendingHandoffs = pending.data?.total ?? 0;

  return (
    <SessionProvider admin={admin}>
      <a href="#main" className="skip-link">
        {t("nav.skip")}
      </a>
      <div className="shell">
        <Sidebar
          capabilities={capabilitiesFor(admin.role)}
          pendingHandoffs={pendingHandoffs}
          open={sidebarOpen}
          onNavigate={() => setSidebarOpen(false)}
        />
        <div className="shell__main">
          <TopBar onMenu={() => setSidebarOpen((value) => !value)} pendingHandoffs={pendingHandoffs} failedDocuments={failed.data?.total ?? 0} />
          <main id="main" className="shell__content" tabIndex={-1}>
            <Outlet />
          </main>
        </div>
      </div>
    </SessionProvider>
  );
}
