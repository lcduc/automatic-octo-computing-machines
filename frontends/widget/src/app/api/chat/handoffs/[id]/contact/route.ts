/**
 * Leaves the visitor's contact details on their own support ticket (HND-13).
 */
import { backendFetch, errorResponse, relay } from "@/lib/server/backend";
import { isSameOrigin } from "@/lib/server/same-origin";
import { currentVisitorId } from "@/lib/server/visitor";

const UUID_PATTERN = /^[0-9a-f-]{36}$/i;
const MAX_BODY_BYTES = 4 * 1024;

export async function POST(request: Request, ctx: RouteContext<"/api/chat/handoffs/[id]/contact">): Promise<Response> {
  if (!isSameOrigin(request)) return errorResponse(403, "Cross-site request rejected");
  const { id } = await ctx.params;
  if (!UUID_PATTERN.test(id)) return errorResponse(400, "Invalid request id");
  const visitorId = await currentVisitorId();
  if (!visitorId) return errorResponse(400, "Missing visitor session");
  const body = await request.text();
  if (body.length > MAX_BODY_BYTES) return errorResponse(413, "Too long");
  try {
    return relay(
      await backendFetch(`/api/v1/handoffs/${id}/contact`, request, visitorId, {
        method: "POST",
        body,
        headers: { "Content-Type": "application/json" },
      }),
    );
  } catch (error) {
    console.error("handoff contact failed", error);
    return errorResponse(502, "Chat service unavailable");
  }
}
