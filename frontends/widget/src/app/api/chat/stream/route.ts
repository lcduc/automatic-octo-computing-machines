/**
 * Streams an answer: forwards the visitor's message to the backend with this
 * frontend's API key and relays the Server-Sent Events unchanged.
 */
import { isSameOrigin } from "@/lib/server/same-origin";
import { backendFetch, errorResponse, relay } from "@/lib/server/backend";
import { ensureVisitorId } from "@/lib/server/visitor";

/** Largest accepted request body (a message is at most a few KB). */
const MAX_BODY_BYTES = 16 * 1024;

export async function POST(request: Request): Promise<Response> {
  if (!isSameOrigin(request)) return errorResponse(403, "Cross-site request rejected");
  const body = await request.text();
  if (body.length > MAX_BODY_BYTES) return errorResponse(413, "Message too long");
  try {
    const visitorId = await ensureVisitorId();
    const response = await backendFetch("/api/v1/chat/stream", request, visitorId, {
      method: "POST",
      body,
      headers: { "Content-Type": "application/json" },
    });
    return relay(response);
  } catch (error) {
    console.error("chat stream failed", error);
    return errorResponse(502, "Chat service unavailable");
  }
}
