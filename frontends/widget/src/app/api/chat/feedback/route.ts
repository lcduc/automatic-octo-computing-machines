/**
 * Records the visitor's thumbs-up/down on an answer.
 */
import { isSameOrigin } from "@/lib/server/same-origin";
import { backendFetch, errorResponse, relay } from "@/lib/server/backend";
import { currentVisitorId } from "@/lib/server/visitor";

const MAX_BODY_BYTES = 4 * 1024;

export async function POST(request: Request): Promise<Response> {
  if (!isSameOrigin(request)) return errorResponse(403, "Cross-site request rejected");
  const visitorId = await currentVisitorId();
  if (!visitorId) return errorResponse(400, "Missing visitor session");
  const body = await request.text();
  if (body.length > MAX_BODY_BYTES) return errorResponse(413, "Feedback too long");
  try {
    return relay(
      await backendFetch("/api/v1/feedback", request, visitorId, {
        method: "POST",
        body,
        headers: { "Content-Type": "application/json" },
      }),
    );
  } catch (error) {
    console.error("feedback failed", error);
    return errorResponse(502, "Chat service unavailable");
  }
}
