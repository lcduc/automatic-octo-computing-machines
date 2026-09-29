/**
 * postMessage channel between the widget iframe and embed.js on the host page.
 *
 * Every message is sent with an exact `targetOrigin` and every received
 * message must come from `window.parent` at one of the allowed host origins
 * (WIDGET_ALLOWED_PARENTS). Until the host has answered, the widget does not
 * know which allowed origin framed it, so its first `chatbot:ready` is posted
 * once per allowed origin: the browser only delivers the one that matches.
 *
 * Messages from the host: `host:hello` (no signed-in user), `host:login` and
 * `host:token_refresh` (a new host token, or null), `host:logout`.
 * Messages to the host: `chatbot:ready`, `chatbot:request_token`,
 * `chatbot:login_request`, `chatbot:close`.
 */

export type HostMessage =
  | { type: "host:hello" }
  | { type: "host:login"; token: string | null }
  | { type: "host:token_refresh"; token: string | null }
  | { type: "host:logout" };

type WidgetMessageType = "chatbot:ready" | "chatbot:request_token" | "chatbot:login_request" | "chatbot:close";

const HOST_MESSAGE_TYPES = new Set(["host:hello", "host:login", "host:token_refresh", "host:logout"]);
/** Longest accepted token (a JWT of a few claims is far shorter). */
const MAX_TOKEN_LENGTH = 4096;

function parseHostMessage(data: unknown): HostMessage | null {
  if (!data || typeof data !== "object") return null;
  const { type, token } = data as { type?: unknown; token?: unknown };
  if (typeof type !== "string" || !HOST_MESSAGE_TYPES.has(type)) return null;
  if (type === "host:login" || type === "host:token_refresh") {
    const valid = token === null || (typeof token === "string" && token.length > 0 && token.length <= MAX_TOKEN_LENGTH);
    return valid ? ({ type, token } as HostMessage) : null;
  }
  return { type } as HostMessage;
}

export class HostBridge {
  private parentOrigin: string | null = null;
  private readonly listener = (event: MessageEvent) => this.receive(event);

  /**
   * @param allowedOrigins - Origins allowed to frame the widget.
   * @param onMessage - Called for every valid message from the host page.
   */
  constructor(
    private readonly allowedOrigins: string[],
    private readonly onMessage: (message: HostMessage) => void,
  ) {}

  /** True when the widget runs inside a frame (the only case with a host page to talk to). */
  static embedded(): boolean {
    return typeof window !== "undefined" && window.parent !== window;
  }

  /** Start listening and announce the widget; returns a cleanup function. */
  start(): () => void {
    window.addEventListener("message", this.listener);
    this.post("chatbot:ready");
    return () => window.removeEventListener("message", this.listener);
  }

  /** Send a message to the host page with an exact target origin (never `*`). */
  post(type: WidgetMessageType): void {
    if (!HostBridge.embedded()) return;
    const targets = this.parentOrigin ? [this.parentOrigin] : this.allowedOrigins;
    for (const origin of targets) window.parent.postMessage({ type }, origin);
  }

  private receive(event: MessageEvent): void {
    if (event.source !== window.parent || !this.allowedOrigins.includes(event.origin)) return;
    const message = parseHostMessage(event.data);
    if (!message) return;
    this.parentOrigin = event.origin;
    this.onMessage(message);
  }
}

/** Seconds until a JWT's `exp` (only to schedule a refresh; the server verifies the token). */
export function secondsUntilExpiry(token: string, now: number = Date.now()): number | null {
  try {
    const payload = token.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp === "number" ? exp - now / 1000 : null;
  } catch {
    return null;
  }
}
