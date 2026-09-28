import type { ReactNode } from "react";
import { isRouteErrorResponse, Link, useRouteError, type RouteObject } from "react-router";
import { ConsoleLayout } from "./components/layout/ConsoleLayout";
import type { RouteHandle } from "./components/layout/TopBar";
import { Callout, EmptyState } from "./components/ui/primitives";
import { useI18n } from "./i18n/I18nProvider";
import { useSession } from "./lib/session";
import { AccessPage } from "./pages/AccessPage";
import { AuditPage } from "./pages/AuditPage";
import { ConversationPage } from "./pages/conversations/ConversationPage";
import { ConversationsPage } from "./pages/conversations/ConversationsPage";
import { FeedbackPage } from "./pages/FeedbackPage";
import { HandoffsPage } from "./pages/HandoffsPage";
import { DocumentPage } from "./pages/knowledge/DocumentPage";
import { KnowledgePage } from "./pages/knowledge/KnowledgePage";
import { LoginPage } from "./pages/LoginPage";
import { LogsPage } from "./pages/LogsPage";
import { OverviewPage } from "./pages/overview/OverviewPage";
import { SettingsPage } from "./pages/settings/SettingsPage";

/** Pages only owners may open (the backend refuses the calls for anyone else anyway). */
function OwnerOnly({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { isOwner } = useSession();
  return isOwner ? children : <Callout tone="warning">{t("errors.ownerOnly")}</Callout>;
}

function NotFound() {
  const { t } = useI18n();
  return <EmptyState title={t("errors.notFound")} action={<Link to="/">{t("errors.home")}</Link>} />;
}

function RouteError() {
  const { t } = useI18n();
  const error = useRouteError();
  const message = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : String(error);
  return <Callout tone="danger">{t("errors.page", { message })}</Callout>;
}

const handle = (crumb: RouteHandle["crumb"]): RouteHandle => ({ crumb });

/** The route table, used by the browser router (main.tsx) and the smoke tests. */
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: <ConsoleLayout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <OverviewPage />, handle: handle("nav.overview") },
      { path: "knowledge", element: <KnowledgePage />, handle: handle("nav.knowledge") },
      { path: "knowledge/:id", element: <DocumentPage />, handle: handle("nav.knowledge") },
      { path: "conversations", element: <ConversationsPage />, handle: handle("nav.conversations") },
      { path: "conversations/:id", element: <ConversationPage />, handle: handle("nav.conversations") },
      { path: "feedback", element: <FeedbackPage />, handle: handle("nav.feedback") },
      { path: "handoffs", element: <HandoffsPage />, handle: handle("nav.handoffs") },
      { path: "logs", element: <LogsPage />, handle: handle("nav.logs") },
      { path: "settings", element: <SettingsPage />, handle: handle("nav.settings") },
      { path: "access", element: <OwnerOnly><AccessPage /></OwnerOnly>, handle: handle("nav.access") },
      { path: "audit", element: <OwnerOnly><AuditPage /></OwnerOnly>, handle: handle("nav.audit") },
      { path: "*", element: <NotFound /> },
    ],
  },
];
