/**
 * Smoke test: every route renders against a mocked admin API without hitting
 * the error boundary, and navigation follows the admin's role.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "./components/ui/Toast";
import { I18nProvider } from "./i18n/I18nProvider";
import { ThemeProvider } from "./lib/theme";
import { routes } from "./router";
import type { Role } from "./lib/types";

const NOW = "2026-09-29T08:00:00Z";
const page = (items: unknown[]) => ({ items, total: items.length, limit: 50, offset: 0 });
const document = {
  id: "doc-1",
  title: "Luật người lao động",
  source: "general",
  original_filename: "luat.pdf",
  file_type: "pdf",
  status: "ready",
  error: null,
  enabled: false,
  review_status: "pending",
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
  chunk_count: 1,
  metadata: { url: "https://x.test" },
  created_by: "owner@example.test",
  created_at: NOW,
  updated_at: NOW,
};
const settings = {
  fallback_mode: "deny",
  deny_message: "Không có thông tin",
  handoff_message: "Đã chuyển",
  guard_block_message: "Bị chặn",
  greeting_message: "Xin chào",
  thanks_message: "Không có gì",
  assistant_instructions: "",
  widget_title: "Trợ lý",
  widget_welcome_message: "Chào bạn",
  widget_primary_color: "#0B5FFF",
  widget_suggested_questions: ["Giờ làm việc?"],
  chat_model: "gpt-5-mini",
  light_model: "gpt-4.1-nano",
  semantic_weight: 0.7,
  retrieval_top_k: 4,
  max_context_chunks: 6,
};

function fixtures(role: Role): Record<string, unknown> {
  return {
    "auth/me": { id: "admin-1", email: "owner@example.test", role, disabled: false, created_at: NOW, last_login_at: NOW },
    handoffs: page([{ id: "h-1", conversation_id: "c-1", message_id: null, reason: "user_request", status: "open", note: null, signed_in: false, contact_email: null, contact_phone: null, has_contact: false, consent_at: null, details: null, assigned_to: null, answer: null, answered_at: null, emailed_at: null, due_at: NOW, closed_at: null, created_at: NOW, updated_at: NOW }]),
    "knowledge/documents": page([document]),
    "knowledge/documents/doc-1": { ...document, chunks: [{ id: "chunk-1", position: 0, content: "Điều 1. Phạm vi", metadata: { article: "Điều 1" }, edited: true, updated_at: NOW }] },
    "knowledge/access-tiers": ["anonymous", "user", "premium"],
    "knowledge/review/counts": { pending: 1, approved: 7, rejected: 0 },
    "knowledge/documents/doc-1/review": { ...document, review_status: "approved", reviewed_by: "owner@example.test", chunks: [] },
    "knowledge/sources": [{ id: 1, name: "general", description: "", priority: 1, enabled: true, document_count: 1 }],
    "usage/summary": {
      since: NOW,
      daily: [{ day: "2026-09-29", model: "gpt-5-mini", prompt_tokens: 100, completion_tokens: 20, calls: 1 }],
      by_purpose: [{ purpose: "answer", tokens: 120, calls: 1 }],
      outcomes: { answered: 3, denied: 1 },
      feedback: { positive: 2, negative: 1 },
      latency: { p50_ms: 900, p95_ms: 2100, conversations: 4 },
      totals: { prompt_tokens: 100, completion_tokens: 20, calls: 1, cost_micro_usd: 180 },
      by_tier: [{ tier: "anonymous", tokens: 120, cost_micro_usd: 180 }],
      month: { tokens: 120, cost_micro_usd: 180 },
    },
    system: {
      version: "1.0.0",
      uptime_seconds: 10,
      database: true,
      knowledge_index_version: 3,
      indexed_chunks: 12,
      indexed_sources: { general: 12 },
      llm_provider: "openai",
      llm_model: "gpt-5-mini",
      embedding_model: "paraphrase-multilingual-MiniLM-L12-v2",
      reranker_loaded: true,
      cache: { size: 2, hit_rate: 0.5 },
      fallback_mode: "deny",
      ingestion_queue: { pending: 0, in_progress: 0, oldest_pending_seconds: null },
    },
    conversations: page([{ id: "c-1", end_user_id: "visitor-1234", channel: "web", status: "active", message_count: 2, created_at: NOW, last_activity_at: NOW }]),
    "conversations/c-1": {
      id: "c-1",
      end_user_id: "visitor-1234",
      channel: "web",
      status: "active",
      message_count: 2,
      created_at: NOW,
      last_activity_at: NOW,
      messages: [
        { id: "m-1", role: "user", content: "Giờ làm việc?", outcome: null, citations: [], confidence: null, model: null, prompt_tokens: 0, completion_tokens: 0, latency_ms: null, cached: false, guard_reason: null, request_id: null, created_at: NOW, feedback: null },
        { id: "m-2", role: "assistant", content: "8 giờ.", outcome: "answered", citations: [{ document_id: "doc-1", chunk_id: "chunk-1", title: "Luật", source: "general", url: "https://x.test", score: 0.9 }], confidence: 0.8, model: "gpt-5-mini", prompt_tokens: 100, completion_tokens: 20, latency_ms: 900, cached: false, guard_reason: null, request_id: "r1", created_at: NOW, feedback: { rating: -1, comment: "thiếu" } },
      ],
    },
    feedback: page([{ id: "f-1", rating: -1, comment: "thiếu", created_at: NOW, message_id: "m-2", conversation_id: "c-1", question: "Giờ làm việc?", answer: "8 giờ.", outcome: "answered" }]),
    logs: [{ ts: NOW, level: "WARNING", logger: "api", message: "slow", request_id: "r1", exception: null }],
    settings,
    "settings/defaults": { ...settings, semantic_weight: 0.6 },
    users: [{ id: "admin-1", email: "owner@example.test", role: "owner", disabled: false, created_at: NOW, last_login_at: NOW }],
    "api-keys": [{ id: "k-1", name: "web", key_prefix: "ck_ab", scopes: ["chat"], created_at: NOW, last_used_at: null, revoked_at: null }],
    audit: page([{ id: "a-1", created_at: NOW, actor_id: "admin-1", actor_email: "owner@example.test", actor_role: "owner", method: "PATCH", path: "/api/v1/admin/settings", status_code: 200, request_id: "r1", client_ip: "10.0.0.1", request_body: { a: 1 }, response_body: { a: 1 } }]),
  };
}

/** What the widget server (`/api/chat/*`) and the admin's runtime config answer. */
const widgetConfig = { title: "Trợ lý", welcome_message: "Chào bạn", primary_color: "#0B5FFF", suggested_questions: ["Giờ làm việc?"] };
const streamedTurn = [
  ["meta", { conversation_id: "c-1", message_id: "m-2" }],
  ["delta", { text: "8 giờ." }],
  ["done", { outcome: "answered", text: "8 giờ.", citations: [{ document_id: "doc-1", chunk_id: "chunk-1", title: "Luật", source: "general", score: 0.9 }], confidence: 0.8, cached: false, handoff_id: null }],
].map(([name, payload]) => `event: ${String(name)}\ndata: ${JSON.stringify(payload)}\n\n`);

function sse(frames: string[]): Response {
  const body = new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(new TextEncoder().encode(frame));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });

function installFetch(role: Role) {
  const data = fixtures(role);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      if (input === "/runtime-config.json") return json({ widgetOrigin: "http://localhost:3000" });
      if (input === "/api/chat/config") return json(widgetConfig);
      if (input === "/api/chat/stream") return sse(streamedTurn);
      const path = input.replace("/api/v1/admin/", "").split("?")[0] ?? "";
      if (path === "usage/live") return new Response(new ReadableStream({ start: (c) => c.close() }), { status: 200 });
      if (!(path in data)) return new Response(JSON.stringify({ detail: `no fixture for ${path}` }), { status: 404 });
      return new Response(JSON.stringify(data[path]), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <ThemeProvider>
      <I18nProvider>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.setItem("admin.language", "vi"); // the assertions below read Vietnamese copy
  installFetch("owner");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("every page renders", () => {
  it.each([
    ["/", "Tổng quan"],
    ["/knowledge", "Kho tri thức"],
    ["/knowledge?tab=sources", "Kho tri thức"],
    ["/knowledge/doc-1", "Luật người lao động"],
    ["/conversations", "Hội thoại"],
    ["/conversations/c-1", "Hội thoại của visitor-1234"],
    ["/feedback", "Đánh giá"],
    ["/handoffs", "Chuyển nhân viên"],
    ["/logs", "Nhật ký hệ thống"],
    ["/settings", "Cấu hình"],
    ["/settings?tab=widget", "Cấu hình"],
    ["/access", "Tài khoản & khoá API"],
    ["/audit", "Nhật ký thao tác"],
    ["/chat", "Thử trò chuyện"],
    ["/widget", "Xem trước khung chat"],
  ])("%s", async (path, heading) => {
    renderAt(path);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeTruthy();
    expect(screen.queryByText(/Trang gặp lỗi/)).toBeNull();
  });

  it("shows held-back documents, edited chunks and article labels", async () => {
    renderAt("/knowledge/doc-1");
    expect(await screen.findByText(/chưa dùng nó để trả lời/)).toBeTruthy();
    expect(screen.getByText("Đã sửa tay")).toBeTruthy();
    expect(screen.getByText("article: Điều 1")).toBeTruthy();
  });
});

describe("access page", () => {
  it("creates an account from a dialog instead of an inline form", async () => {
    renderAt("/access");
    fireEvent.click(await screen.findByRole("button", { name: "Thêm tài khoản" }));
    const dialog = await screen.findByRole("dialog");

    fireEvent.change(within(dialog).getByLabelText("E-mail"), { target: { value: "new@example.test" } });
    fireEvent.change(within(dialog).getByLabelText("Mật khẩu ban đầu"), { target: { value: "long-enough-password" } });
    fireEvent.submit(within(dialog).getByLabelText("E-mail").closest("form") as HTMLFormElement);

    expect(await screen.findByText("Đã tạo tài khoản new@example.test.")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    const init = vi.mocked(fetch).mock.calls.find(([, options]) => options?.method === "POST")?.[1];
    expect(JSON.parse(String(init?.body))).toEqual({ email: "new@example.test", password: "long-enough-password", role: "viewer" });
  });
});

describe("demo chat", () => {
  it("streams an answer with its outcome, citation and trace link", async () => {
    renderAt("/chat");
    const input = await screen.findByRole("textbox", { name: "Câu hỏi" });
    fireEvent.change(input, { target: { value: "Giờ làm việc?" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    expect(await screen.findByText("8 giờ.")).toBeTruthy();
    expect(await screen.findByText("Đã trả lời")).toBeTruthy();
    expect(screen.getByText("Luật")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Xem truy vết" }).getAttribute("href")).toBe("/conversations/c-1");
    const init = vi.mocked(fetch).mock.calls.find(([url]) => url === "/api/chat/stream")?.[1];
    expect(JSON.parse(String(init?.body))).toEqual({ message: "Giờ làm việc?" });
  });

  it("frames the real widget from the runtime origin", async () => {
    renderAt("/widget");
    const frame = await screen.findByTitle("Trợ lý");
    expect(frame.getAttribute("src")).toBe("http://localhost:3000/widget");
  });
});

describe("document review", () => {
  it("shows the review counts and lets an owner approve a pending document", async () => {
    renderAt("/knowledge");
    expect(await screen.findByText("7")).toBeTruthy();
    fireEvent.click(await screen.findByText("Luật người lao động"));
    fireEvent.click(await screen.findByRole("button", { name: "Duyệt" }));

    expect(await screen.findByText("Đã duyệt “Luật người lao động”.")).toBeTruthy();
    const call = vi.mocked(fetch).mock.calls.find(([url]) => url === "/api/v1/admin/knowledge/documents/doc-1/review");
    expect(call?.[1]?.method).toBe("POST");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ approve: true, note: null });
  });

  it("asks for an optional reason before rejecting", async () => {
    renderAt("/knowledge/doc-1");
    fireEvent.click(await screen.findByRole("button", { name: "Từ chối" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Lý do (không bắt buộc)"), { target: { value: "Đã lỗi thời" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Từ chối" }));

    await screen.findByText("Đã từ chối “Luật người lao động”.");
    const call = vi.mocked(fetch).mock.calls.find(([url]) => url === "/api/v1/admin/knowledge/documents/doc-1/review");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ approve: false, note: "Đã lỗi thời" });
  });

  it("shows a viewer the waiting document but no way to decide", async () => {
    installFetch("viewer");
    renderAt("/knowledge/doc-1");
    expect(await screen.findByText("Chờ duyệt")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Duyệt" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Từ chối" })).toBeNull();
  });
});

describe("access: view as", () => {
  it("previews a role's permissions read-only", async () => {
    renderAt("/access");
    const button = (await screen.findAllByRole("button", { name: /^Xem với vai trò này/ }))[0] as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Quyền hạn")).toBeTruthy();
    expect(within(dialog).getByText("Các trang trên thanh bên")).toBeTruthy();
  });
});

describe("navigation follows the role", () => {
  it("keeps owner tabs in the menu for a support agent but locks them", async () => {
    installFetch("support_agent");
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: /Điều hướng/ }).catch(() => screen.getByRole("complementary"));
    expect(within(nav).getByText("Chuyển nhân viên")).toBeTruthy();
    for (const label of ["Nhật ký thao tác", "Cấu hình", "Tài khoản & khoá API"]) {
      expect(within(nav).getByText(label).closest("a")?.className).toContain("nav-item--locked");
    }
    expect(within(nav).getByText("Chuyển nhân viên").closest("a")?.className).not.toContain("nav-item--locked");
  });

  it("refuses owner pages opened directly by a viewer", async () => {
    installFetch("viewer");
    renderAt("/audit");
    expect(await screen.findByText("Chỉ chủ sở hữu mới xem được trang này.")).toBeTruthy();
  });

  it("opens a locked tab to a disabled screen when a support agent clicks it", async () => {
    installFetch("support_agent");
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: /Điều hướng/ }).catch(() => screen.getByRole("complementary"));
    fireEvent.click(within(nav).getByText("Cấu hình"));
    expect(await screen.findByText("Chỉ chủ sở hữu mới xem được trang này.")).toBeTruthy();
  });
});
