/**
 * Restores the visitor's own conversation after a page reload.
 */
import { backendFetch, errorResponse, relay } from "@/lib/server/backend";
import { isSameOrigin } from "@/lib/server/same-origin";
import { currentVisitorId } from "@/lib/server/visitor";

const UUID_PATTERN = /^[0-9a-f-]{36}$/i;

export async function GET(request: Request, ctx: RouteContext<"/api/chat/conversations/[id]">): Promise<Response> {
  if (!isSameOrigin(request)) return errorResponse(403, "Cross-site request rejected");
  const { id } = await ctx.params;
  if (!UUID_PATTERN.test(id)) return errorResponse(400, "Invalid conversation id");
  const visitorId = await currentVisitorId();
  if (!visitorId) return errorResponse(404, "Conversation not found");
  try {
    return relay(await backendFetch(`/api/v1/conversations/${id}`, request, visitorId));
  } catch (error) {
    console.error("conversation restore failed", error);
    return errorResponse(502, "Chat service unavailable");
  }
}
