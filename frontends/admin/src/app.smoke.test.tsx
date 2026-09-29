/**
 * Smoke test: every route renders against a mocked admin API without hitting
 * the error boundary, and navigation follows the admin's role.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "./components/ui/Toast";
import { I18nProvider } from "./i18n/I18nProvider";
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
  chunk_count: 1,
  metadata: { url: "https://x.test" },
  chunking: { strategy: "legal_article", split_at: "article" },
  can_rechunk: true,
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
  similarity_threshold: 0.3,
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
    "knowledge/sources": [{ id: 1, name: "general", description: "", priority: 1, enabled: true, document_count: 1 }],
    "knowledge/chunking/strategies": [{ name: "auto", description: "", params_schema: { properties: { strategy: { const: "auto" } } } }],
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
    "settings/defaults": { ...settings, similarity_threshold: 0.25 },
    users: [{ id: "admin-1", email: "owner@example.test", role: "owner", disabled: false, created_at: NOW, last_login_at: NOW }],
    "api-keys": [{ id: "k-1", name: "web", key_prefix: "ck_ab", scopes: ["chat"], created_at: NOW, last_used_at: null, revoked_at: null }],
    audit: page([{ id: "a-1", created_at: NOW, actor_id: "admin-1", actor_email: "owner@example.test", actor_role: "owner", method: "PATCH", path: "/api/v1/admin/settings", status_code: 200, request_id: "r1", client_ip: "10.0.0.1", request_body: { a: 1 }, response_body: { a: 1 } }]),
  };
}

function installFetch(role: Role) {
  const data = fixtures(role);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
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
    <I18nProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </I18nProvider>,
  );
}

beforeEach(() => installFetch("owner"));
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
    ["/settings?tab=models", "Cấu hình"],
    ["/settings?tab=widget", "Cấu hình"],
    ["/access", "Tài khoản & khoá API"],
    ["/audit", "Nhật ký thao tác"],
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

describe("navigation follows the role", () => {
  it("hides owner pages from a support agent", async () => {
    installFetch("support_agent");
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: /Điều hướng/ }).catch(() => screen.getByRole("complementary"));
    expect(within(nav).getByText("Chuyển nhân viên")).toBeTruthy();
    expect(within(nav).queryByText("Nhật ký thao tác")).toBeNull();
    expect(within(nav).queryByText("Tài khoản & khoá API")).toBeNull();
  });

  it("refuses owner pages opened directly by a viewer", async () => {
    installFetch("viewer");
    renderAt("/audit");
    expect(await screen.findByText("Chỉ chủ sở hữu mới xem được trang này.")).toBeTruthy();
  });
});
