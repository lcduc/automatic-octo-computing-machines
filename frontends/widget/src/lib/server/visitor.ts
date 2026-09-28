/**
 * Anonymous visitor identity for the chat widget.
 *
 * Each browser gets a random id in a signed, HttpOnly cookie. The backend
 * uses it for per-visitor rate limits and to scope conversation history;
 * it carries no personal data.
 */
import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { secureCookies, visitorCookieSecret } from "./config";

export const VISITOR_COOKIE = "chat_vid";
/** Visitor ids live one year; clearing cookies simply starts a new visitor. */
const VISITOR_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

function sign(id: string): string {
  return createHmac("sha256", visitorCookieSecret()).update(id).digest("base64url");
}

/** Verify a cookie value and return the visitor id, or null if tampered/malformed. */
export function verifyVisitorCookie(value: string | undefined): string | null {
  if (!value) return null;
  const [id, signature] = value.split(".");
  if (!id || !signature) return null;
  const expected = Buffer.from(sign(id));
  const actual = Buffer.from(signature);
  return expected.length === actual.length && timingSafeEqual(expected, actual) ? id : null;
}

/** The current visitor id from the request cookies, or null. */
export async function currentVisitorId(): Promise<string | null> {
  return verifyVisitorCookie((await cookies()).get(VISITOR_COOKIE)?.value);
}

/**
 * Return the visitor id, issuing a new signed cookie when missing.
 * Must be called from a Route Handler (cookies can only be set there).
 */
export async function ensureVisitorId(): Promise<string> {
  const existing = await currentVisitorId();
  if (existing) return existing;
  const id = crypto.randomUUID();
  const secure = secureCookies();
  (await cookies()).set(VISITOR_COOKIE, `${id}.${sign(id)}`, {
    httpOnly: true,
    secure,
    // The widget runs in an iframe on another site: cross-site cookies need
    // SameSite=None + Secure, and Partitioned keeps them working as browsers
    // phase out third-party cookies (CHIPS).
    sameSite: secure ? "none" : "lax",
    partitioned: secure,
    path: "/",
    maxAge: VISITOR_MAX_AGE_SECONDS,
  });
  return id;
}
