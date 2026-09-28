import { afterEach, describe, expect, it, vi } from "vitest";
import { adminApi, ApiError, describeError, query, setUnauthorizedHandler } from "./api";

function mockFetch(status: number, body: unknown) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(body === null ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(() => {});
});

describe("adminApi", () => {
  it("sends the CSRF header on writes only, with same-origin credentials", async () => {
    const fetchMock = mockFetch(200, { ok: true });
    await adminApi("settings");
    await adminApi("settings", { method: "PATCH", body: { greeting_message: "Xin chào" } });

    const [readUrl, readInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [, writeInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(readUrl).toBe("/api/v1/admin/settings");
    expect(readInit.credentials).toBe("same-origin");
    expect(readInit.headers).not.toHaveProperty("X-Admin-Request");
    expect(writeInit.headers).toMatchObject({ "X-Admin-Request": "1", "Content-Type": "application/json" });
    expect(writeInit.body).toBe('{"greeting_message":"Xin chào"}');
  });

  it("reports the backend message and calls the expired-session handler on 401", async () => {
    const onUnauthorized = vi.fn<() => void>();
    setUnauthorizedHandler(onUnauthorized);
    mockFetch(401, { detail: "Not signed in" });

    await expect(adminApi("auth/me")).rejects.toEqual(new ApiError(401, "Not signed in"));
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("does not treat a failed sign-in as an expired session", async () => {
    const onUnauthorized = vi.fn<() => void>();
    setUnauthorizedHandler(onUnauthorized);
    mockFetch(401, { detail: "Incorrect e-mail or password" });

    await expect(adminApi("auth/login", { method: "POST", body: {}, allowUnauthorized: true })).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});

describe("describeError", () => {
  it("joins FastAPI validation errors with their field", () => {
    const body = { detail: [{ loc: ["body", "chunking", "max_chars"], msg: "must be ≥ 200" }, { msg: "bad" }] };
    expect(describeError(body, 422)).toBe("chunking.max_chars: must be ≥ 200; bad");
    expect(describeError(null, 500)).toBe("HTTP 500");
  });
});

describe("query", () => {
  it("skips empty values", () => {
    expect(query({ source: "", status: "ready", limit: 25, since: undefined })).toBe("?status=ready&limit=25");
    expect(query({})).toBe("");
  });
});
