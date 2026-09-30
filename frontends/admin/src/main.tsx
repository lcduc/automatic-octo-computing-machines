import "@fontsource-variable/inter";
import "@fontsource-variable/outfit";
import "./styles/tokens.css";
import "./styles/components.css";
import "./styles/sidebar.css";
import "./styles/topbar.css";
import "./styles/chat.css";
import "./styles/chat-message.css";
import "./styles/widget-preview.css";
import "./styles/planned.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { ToastProvider } from "./components/ui/Toast";
import { I18nProvider } from "./i18n/I18nProvider";
import { setUnauthorizedHandler } from "./lib/api";
import { applyStoredTheme, ThemeProvider } from "./lib/theme";
import { routes } from "./router";

setUnauthorizedHandler(() => {
  if (window.location.pathname === "/login") return;
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  // A full navigation drops every cached screen of the expired session.
  window.location.assign(`/login?next=${next}`);
});

applyStoredTheme();
const router = createBrowserRouter(routes);
const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
);
