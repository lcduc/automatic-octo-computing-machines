/**
 * Client for the admin API, served from the same origin (`/api/v1/admin`).
 *
 * The session is an HttpOnly cookie set by the backend at sign-in, so no token
 * ever reaches JavaScript. Writes carry `X-Admin-Request: 1`, which the backend
 * requires for cookie-authenticated changes (a cross-site form cannot send it).
 */

export const ADMIN_API_BASE = "/api/v1/admin";
const CSRF_HEADER = "X-Admin-Request";
const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler = () => {};

/** Register what happens when the session has expired (the app redirects to sign-in). */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  onUnauthorized = handler;
}

/** Turn a FastAPI error body (string or validation list) into one readable line. */
export function describeError(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            const location = "loc" in item && Array.isArray(item.loc) ? `${item.loc.slice(1).join(".")}: ` : "";
            return `${location}${String((item as { msg: unknown }).msg)}`;
          }
          return String(item);
        })
        .join("; ");
    }
  }
  return `HTTP ${status}`;
}

export interface RequestOptions {
  method?: string;
  /** Plain values are sent as JSON, FormData as multipart. */
  body?: unknown;
  signal?: AbortSignal;
  /** Do not treat 401 as an expired session (the sign-in call itself). */
  allowUnauthorized?: boolean;
}

function buildInit(options: RequestOptions): RequestInit {
  const method = (options.method ?? "GET").toUpperCase();
  const isForm = options.body instanceof FormData;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (WRITE_METHODS.has(method)) headers[CSRF_HEADER] = "1";
  if (options.body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  return {
    method,
    headers,
    credentials: "same-origin",
    signal: options.signal,
    body: options.body === undefined ? undefined : isForm ? (options.body as FormData) : JSON.stringify(options.body),
  };
}

/**
 * Call an admin endpoint and return its JSON body.
 *
 * @param path - Path under `/api/v1/admin/`, e.g. `knowledge/documents?limit=20`.
 * @throws ApiError with the backend's message for any non-2xx response.
 */
export async function adminApi<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${ADMIN_API_BASE}/${path}`, buildInit(options));
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (response.status === 401 && !options.allowUnauthorized) {
    onUnauthorized();
  }
  if (!response.ok) {
    const error = new ApiError(response.status, describeError(body, response.status));
    const retryAfter = response.headers.get("Retry-After");
    if (retryAfter) error.message += ` (${retryAfter}s)`;
    throw error;
  }
  return body as T;
}

/** Open a streaming (SSE) admin endpoint; the caller reads the body. */
export async function adminStream(path: string, signal: AbortSignal): Promise<Response> {
  const response = await fetch(`${ADMIN_API_BASE}/${path}`, { ...buildInit({ signal }), headers: { Accept: "text/event-stream" } });
  if (response.status === 401) onUnauthorized();
  if (!response.ok) throw new ApiError(response.status, `HTTP ${response.status}`);
  return response;
}

/** Build a query string from defined, non-empty values. */
export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
