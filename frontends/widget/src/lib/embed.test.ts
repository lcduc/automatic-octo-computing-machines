import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";

const CHAT_ORIGIN = "https://chat.client.vn";
// The loader is a static file served from public/; tests run from the widget root.
const LOADER = readFileSync(join(process.cwd(), "public", "embed.js"), "utf8");

type ChatbotApi = { login(): void; logout(): void; configure(options: object): void };

function fromIframe(iframe: HTMLIFrameElement, data: unknown, origin = CHAT_ORIGIN) {
  const event = new MessageEvent("message", { data, origin });
  Object.defineProperty(event, "source", { value: iframe.contentWindow });
  window.dispatchEvent(event);
}

async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("embed.js on the host page", () => {
  let iframe: HTMLIFrameElement;
  let toIframe: ReturnType<typeof vi.fn>;
  const getToken = vi.fn(async () => "host-token-1");
  const onLoginRequest = vi.fn();

  beforeAll(() => {
    (window as unknown as { ChatbotConfig: object }).ChatbotConfig = { getToken, onLoginRequest };
    Object.defineProperty(document, "currentScript", {
      configurable: true,
      value: { src: `${CHAT_ORIGIN}/embed.js`, dataset: {} },
    });
    window.matchMedia = vi.fn(() => ({ matches: false, addEventListener: () => {} })) as never;
    new Function(LOADER)();
    (document.querySelector("[data-chatbot-embed] button") as HTMLButtonElement).click();
    iframe = document.querySelector("[data-chatbot-embed] iframe") as HTMLIFrameElement;
    toIframe = vi.fn();
    Object.defineProperty(iframe.contentWindow, "postMessage", { value: toIframe });
  });

  it("loads the chat from its own origin", () => {
    expect(iframe.src).toBe(`${CHAT_ORIGIN}/widget`);
  });

  it("answers the widget's handshake and token requests with the host token, to the chat origin only", async () => {
    fromIframe(iframe, { type: "chatbot:ready" });
    fromIframe(iframe, { type: "chatbot:request_token" });
    await flush();
    expect(toIframe.mock.calls).toEqual([
      [{ type: "host:login", token: "host-token-1" }, CHAT_ORIGIN],
      [{ type: "host:token_refresh", token: "host-token-1" }, CHAT_ORIGIN],
    ]);
  });

  it("ignores messages that do not come from the chat iframe at the chat origin", async () => {
    toIframe.mockClear();
    fromIframe(iframe, { type: "chatbot:ready" }, "https://evil.test");
    const forged = new MessageEvent("message", { data: { type: "chatbot:login_request" }, origin: CHAT_ORIGIN });
    window.dispatchEvent(forged);
    await flush();
    expect(toIframe).not.toHaveBeenCalled();
    expect(onLoginRequest).not.toHaveBeenCalled();
  });

  it("relays login requests to the host and host logout to the chat", async () => {
    fromIframe(iframe, { type: "chatbot:login_request" });
    expect(onLoginRequest).toHaveBeenCalledOnce();
    toIframe.mockClear();
    (window as unknown as { Chatbot: ChatbotApi }).Chatbot.logout();
    expect(toIframe.mock.calls).toEqual([[{ type: "host:logout" }, CHAT_ORIGIN]]);
  });
});
