/**
 * CSRF guard for the widget's state-changing routes (chat, feedback).
 *
 * A browser always sends `Origin` on cross-origin POSTs, so a request is
 * accepted only when that origin is this site. Requests without `Origin`
 * (same-origin navigations, server-to-server) are rejected when the browser
 * marks them as cross-site.
 */
export function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return request.headers.get("sec-fetch-site") !== "cross-site";
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  try {
    return Boolean(host) && new URL(origin).host === host;
  } catch {
    return false;
  }
}
