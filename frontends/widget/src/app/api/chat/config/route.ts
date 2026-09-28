/**
 * Widget bootstrap: issues the visitor cookie and returns the widget's look
 * (title, welcome text, colour, suggested questions) set in the admin web.
 */
import { backendFetch, errorResponse, relay } from "@/lib/server/backend";
import { isSameOrigin } from "@/lib/server/same-origin";
import { ensureVisitorId } from "@/lib/server/visitor";

export async function GET(request: Request): Promise<Response> {
  if (!isSameOrigin(request)) return errorResponse(403, "Cross-site request rejected");
  try {
    await ensureVisitorId();
    return relay(await backendFetch("/api/v1/widget/config", request, undefined));
  } catch (error) {
    console.error("widget config failed", error);
    return errorResponse(502, "Chat service unavailable");
  }
}
