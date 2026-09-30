/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** Backend the dev server forwards the admin API to (same origin, like production behind Caddy). */
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8500";
/** Chat widget server; its /api/chat routes serve the demo chat, same origin like production. */
const WIDGET_URL = process.env.WIDGET_URL ?? "http://127.0.0.1:3000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api/v1/admin": { target: BACKEND_URL, changeOrigin: false },
      // Host stays the admin's, so the widget server's same-origin check accepts the demo chat.
      "/api/chat": { target: WIDGET_URL, changeOrigin: false },
    },
  },
  build: { sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
