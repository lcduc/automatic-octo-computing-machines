/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** Backend the dev server forwards the admin API to (same origin, like production behind Caddy). */
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8500";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api/v1/admin": { target: BACKEND_URL, changeOrigin: false },
    },
  },
  build: { sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
