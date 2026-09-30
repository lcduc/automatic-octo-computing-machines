import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useChat } from "./use-chat";

// Lets React's act() flush effects outside a test renderer.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const NO_HOST: string[] = [];
const SETTLE_ROUNDS = 20;

function Probe() {
  useChat(NO_HOST);
  return null;
}

describe("useChat", () => {
  let container: HTMLDivElement;
  let root: Root;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // A fresh config object per response, as a real fetch returns.
    fetchMock = vi.fn(async () => new Response(JSON.stringify({ title: "Hỏi đáp" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    container = document.createElement("div");
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("loads the widget config once, not again on every re-render", async () => {
    await act(async () => {
      root.render(createElement(Probe));
    });
    for (let round = 0; round < SETTLE_ROUNDS; round += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }
    const configCalls = fetchMock.mock.calls.filter(([url]) => url === "/api/chat/config");
    expect(configCalls).toHaveLength(1);
  });
});
