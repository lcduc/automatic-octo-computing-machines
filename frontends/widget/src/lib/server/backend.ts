/**
 * Server-side calls to the FastAPI backend.
 *
 * The browser never talks to the backend directly: these helpers attach this
 * server's generated service token and the visitor id, forward the visitor IP
 * (as set by the TLS proxy) and a request id for log correlation.
 */
import { backendUrl, bffServiceToken } from "./config";

/** Headers forwarded from the incoming request to the backend. */
function forwardedHeaders(incoming: Request): Record<string, string> {
  const headers: Record<string, string> = {
    "X-Request-ID": crypto.randomUUID().replace(/-/g, ""),
  };
  const forwardedFor = incoming.headers.get("x-forwarded-for");
  if (forwardedFor) headers["X-Forwarded-For"] = forwardedFor;
  return headers;
}

/**
 * Call the public chat API.
 *
 * @param path - Path under the backend root, e.g. `/api/v1/chat/stream`.
 * @param incoming - The request being handled (for forwarded headers).
 * @param visitorId - The anonymous visitor, when the endpoint needs one.
 * @param init - Method, body and extra headers.
 */
export async function backendFetch(
  path: string,
  incoming: Request,
  visitorId: string | undefined,
  init: { method?: string; body?: BodyInit | null; headers?: Record<string, string> } = {},
): Promise<Response> {
  const credentials: Record<string, string> = { "X-Service-Token": bffServiceToken() };
  if (visitorId) credentials["X-End-User-Id"] = visitorId;
  return fetch(`${backendUrl()}${path}`, {
    method: init.method ?? "GET",
    body: init.body ?? null,
    headers: { ...forwardedHeaders(incoming), ...credentials, ...(init.headers ?? {}) },
    cache: "no-store",
  });
}

/** Headers of a backend response worth passing through to the browser. */
const PASS_THROUGH_HEADERS = ["content-type", "retry-after", "x-request-id", "cache-control"];

/**
 * Relay a backend response (including SSE streams) to the browser unchanged
 * apart from dropping hop-specific headers.
 */
export function relay(response: Response): Response {
  const headers = new Headers();
  for (const name of PASS_THROUGH_HEADERS) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (headers.get("content-type")?.startsWith("text/event-stream")) {
    headers.set("Cache-Control", "no-cache, no-transform");
    headers.set("X-Accel-Buffering", "no");
  }
  return new Response(response.body, { status: response.status, headers });
}

/** A JSON error response in the same shape the backend uses. */
export function errorResponse(status: number, detail: string): Response {
  return Response.json({ detail }, { status });
}
