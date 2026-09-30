import { describe, expect, it } from "vitest";
import { applyStreamEvent, STREAM_ERROR, type DemoMessage } from "./chat-stream";

const pending: DemoMessage = { id: "local-1-reply", role: "assistant", text: "", createdAt: "2026-09-29T08:00:00Z", streaming: true, citations: [] };
const event = (name: string, payload: unknown) => ({ event: name, data: JSON.stringify(payload) });

describe("applyStreamEvent", () => {
  it("takes the server ids from meta, appends deltas and finishes with done", () => {
    const meta = applyStreamEvent(pending, event("meta", { conversation_id: "c-1", message_id: "m-2" }));
    expect(meta.conversationId).toBe("c-1");
    expect(meta.message.id).toBe("m-2");

    const first = applyStreamEvent(meta.message, event("delta", { text: "8 " }));
    const second = applyStreamEvent(first.message, event("delta", { text: "giờ" }));
    expect(second.message.text).toBe("8 giờ");

    const citation = { document_id: "d", chunk_id: "k", title: "Luật", source: "general", score: 0.9 };
    const done = applyStreamEvent(second.message, event("done", {
      outcome: "handoff", text: "", citations: [citation], confidence: 0.4, cached: false, handoff_id: "h-1", reply_expected_by: "2026-09-30T08:00:00Z",
    }));
    expect(done.message).toMatchObject({
      text: "8 giờ", outcome: "handoff", citations: [citation], confidence: 0.4, handoffId: "h-1", replyBy: "2026-09-30T08:00:00Z", streaming: false,
    });
  });

  it("uses the done text for canned replies that never streamed", () => {
    const done = applyStreamEvent(pending, event("done", { outcome: "denied", text: "Không có thông tin", citations: [] }));
    expect(done.message.text).toBe("Không có thông tin");
    expect(done.message.handoffId).toBeUndefined();
  });

  it("turns an error event into a finished error message", () => {
    expect(applyStreamEvent(pending, event("error", { message: "Quá tải" })).message).toMatchObject({ text: "Quá tải", outcome: "error", streaming: false });
    expect(applyStreamEvent(pending, event("error", {})).message.text).toBe(STREAM_ERROR);
  });
});
