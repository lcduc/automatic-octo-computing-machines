import { describe, expect, it } from "vitest";
import { parseFrame, readSse } from "./sse";

describe("SSE reader", () => {
  it("parses frames, joins multi-line data and skips keep-alive pings", async () => {
    const chunks = ["event: turn\ndata: {\"a\":", "1}\n\n: ping\n\n", "data: line1\ndata: line2\r\n\r\n"];
    const body = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
        controller.close();
      },
    });
    const events = [];
    for await (const event of readSse(new Response(body))) events.push(event);

    expect(events).toEqual([
      { event: "turn", data: '{"a":1}' },
      { event: "message", data: "line1\nline2" },
    ]);
  });

  it("returns null for a comment-only frame", () => {
    expect(parseFrame(": ping")).toBeNull();
  });
});
