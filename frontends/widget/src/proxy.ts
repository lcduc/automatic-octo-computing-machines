/**
 * Runs before every page/route: sets framing and security headers at runtime,
 * so the sites allowed to embed the widget are configurable without a rebuild.
 */
import { NextResponse, type NextRequest } from "next/server";

const HSTS = "max-age=31536000; includeSubDomains";

/** Space-separated origins allowed to embed the widget, e.g. "https://example.com". */
function widgetParents(): string {
  return (process.env.WIDGET_ALLOWED_PARENTS ?? "").split(/[\s,]+/).filter(Boolean).join(" ");
}

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const response = NextResponse.next();
  if (pathname === "/widget") {
    response.headers.set("Content-Security-Policy", `frame-ancestors 'self' ${widgetParents()}`.trim());
  } else {
    response.headers.set("Content-Security-Policy", "frame-ancestors 'none'");
    response.headers.set("X-Frame-Options", "DENY");
  }
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  if (process.env.NODE_ENV === "production") response.headers.set("Strict-Transport-Security", HSTS);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|embed.js).*)"],
};
