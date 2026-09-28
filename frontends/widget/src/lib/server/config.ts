/**
 * Server-only settings read from the environment at request time.
 * Never import this module from a client component.
 */

/** Base URL of the FastAPI backend (reachable from this server only). */
export function backendUrl(): string {
  return (process.env.BACKEND_URL ?? "http://127.0.0.1:8500").replace(/\/$/, "");
}

/** API key (chat scope) issued in the admin web (Tài khoản & khoá API) for this frontend. */
export function chatbotApiKey(): string {
  const key = process.env.CHATBOT_API_KEY;
  if (!key) throw new Error("CHATBOT_API_KEY is not configured");
  return key;
}

/** HMAC secret signing the anonymous visitor cookie. */
export function visitorCookieSecret(): string {
  const secret = process.env.VISITOR_COOKIE_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error("VISITOR_COOKIE_SECRET must be set to at least 32 characters");
  }
  return secret;
}

/** Whether cookies must be marked Secure (always true outside local development). */
export function secureCookies(): boolean {
  return process.env.NODE_ENV === "production";
}
