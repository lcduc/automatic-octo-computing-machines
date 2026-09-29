"use client";

/**
 * The signed-in host user as seen by the widget: the host token, held in
 * memory only (never a cookie or storage), refreshed before it expires.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { HostBridge, secondsUntilExpiry, type HostMessage } from "@/lib/host-bridge";

/** Ask for a new token this long before the current one expires. */
const REFRESH_MARGIN_SECONDS = 60;
/** Never schedule refreshes more often than this. */
const MIN_REFRESH_DELAY_SECONDS = 5;
/** How long to wait for the host page to answer a token request. */
const TOKEN_REPLY_TIMEOUT_MS = 5000;
/** How long to wait for the host page's first message before loading history anonymously. */
const FIRST_CONTACT_TIMEOUT_MS = 1500;

export interface HostSession {
  /** The current host token, or null for an anonymous visitor. */
  token: string | null;
  /** True once the host page answered (or it had its chance to): history can be loaded. */
  ready: boolean;
  /** Ask the host page for a fresh token; resolves with it, or null when signed out / no answer. */
  refresh(): Promise<string | null>;
  /** Ask the host page to show its sign-in (for answers that need a logged-in user). */
  requestLogin(): void;
  /** Ask the host page to close the chat panel. */
  close(): void;
}

/**
 * @param allowedOrigins - Origins allowed to frame the widget.
 * @param onLogout - Called when the host signs the user out (clear private history).
 */
export function useHostSession(allowedOrigins: string[], onLogout: () => void): HostSession {
  const [token, setToken] = useState<string | null>(null);
  const [contacted, setContacted] = useState(false);
  // Not framed (or no host configured): there is no host page to wait for.
  const standalone = !HostBridge.embedded() || allowedOrigins.length === 0;
  const bridge = useRef<HostBridge | null>(null);
  const waiting = useRef<Array<(token: string | null) => void>>([]);
  const logout = useRef(onLogout);

  useEffect(() => {
    logout.current = onLogout;
  }, [onLogout]);

  const settle = useCallback((value: string | null) => {
    for (const resolve of waiting.current.splice(0)) resolve(value);
  }, []);

  useEffect(() => {
    if (standalone) return;
    const handle = (message: HostMessage) => {
      setContacted(true);
      if (message.type === "host:login" || message.type === "host:token_refresh") {
        setToken(message.token);
        settle(message.token);
        if (message.token === null) logout.current();
      } else if (message.type === "host:logout") {
        setToken(null);
        settle(null);
        logout.current();
      } else {
        settle(null);
      }
    };
    const instance = new HostBridge(allowedOrigins, handle);
    bridge.current = instance;
    const stop = instance.start();
    const fallback = window.setTimeout(() => setContacted(true), FIRST_CONTACT_TIMEOUT_MS);
    return () => {
      stop();
      window.clearTimeout(fallback);
      bridge.current = null;
    };
  }, [allowedOrigins, settle, standalone]);

  // Refresh shortly before expiry, so a signed-in visitor never sees an expired session.
  useEffect(() => {
    if (!token) return;
    const remaining = secondsUntilExpiry(token);
    if (remaining === null) return;
    const delay = Math.max(MIN_REFRESH_DELAY_SECONDS, remaining - REFRESH_MARGIN_SECONDS) * 1000;
    const timer = window.setTimeout(() => bridge.current?.post("chatbot:request_token"), delay);
    return () => window.clearTimeout(timer);
  }, [token]);

  const refresh = useCallback((): Promise<string | null> => {
    if (!bridge.current) return Promise.resolve(null);
    return new Promise((resolve) => {
      const timer = window.setTimeout(() => {
        waiting.current = waiting.current.filter((item) => item !== done);
        resolve(null);
      }, TOKEN_REPLY_TIMEOUT_MS);
      const done = (value: string | null) => {
        window.clearTimeout(timer);
        resolve(value);
      };
      waiting.current.push(done);
      bridge.current?.post("chatbot:request_token");
    });
  }, []);

  const requestLogin = useCallback(() => bridge.current?.post("chatbot:login_request"), []);
  const close = useCallback(() => bridge.current?.post("chatbot:close"), []);

  return { token, ready: standalone || contacted, refresh, requestLogin, close };
}
