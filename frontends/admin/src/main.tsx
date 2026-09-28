import "@fontsource-variable/inter";
import "@fontsource-variable/outfit";
import "./styles/tokens.css";
import "./styles/components.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { ToastProvider } from "./components/ui/Toast";
import { I18nProvider } from "./i18n/I18nProvider";
import { setUnauthorizedHandler } from "./lib/api";
import { routes } from "./router";

setUnauthorizedHandler(() => {
  if (window.location.pathname === "/login") return;
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  // A full navigation drops every cached screen of the expired session.
  window.location.assign(`/login?next=${next}`);
});

const router = createBrowserRouter(routes);
const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <I18nProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </I18nProvider>
  </StrictMode>,
);
