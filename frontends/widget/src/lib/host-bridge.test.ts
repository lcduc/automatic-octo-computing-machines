import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HostBridge, secondsUntilExpiry, type HostMessage } from "./host-bridge";

const HOST = "https://www.client.vn";
const OTHER_ALLOWED = "https://client.vn";

function fakeParent() {
  return { postMessage: vi.fn() };
}

function deliver(data: unknown, origin: string, source: unknown) {
  const event = new MessageEvent("message", { data, origin });
  Object.defineProperty(event, "source", { value: source });
  window.dispatchEvent(event);
}

describe("HostBridge", () => {
  let parent: ReturnType<typeof fakeParent>;
  let received: HostMessage[];
  let stop: () => void;

  beforeEach(() => {
    parent = fakeParent();
    Object.defineProperty(window, "parent", { value: parent, configurable: true });
    received = [];
    stop = new HostBridge([HOST, OTHER_ALLOWED], (message) => received.push(message)).start();
  });

  afterEach(() => {
    stop();
    Object.defineProperty(window, "parent", { value: window, configurable: true });
  });

  it("announces itself to each allowed origin exactly, never to *", () => {
    expect(parent.postMessage.mock.calls).toEqual([
      [{ type: "chatbot:ready" }, HOST],
      [{ type: "chatbot:ready" }, OTHER_ALLOWED],
    ]);
  });

  it("accepts only well-formed messages from the parent at an allowed origin", () => {
    deliver({ type: "host:login", token: "t1" }, "https://evil.test", parent);
    deliver({ type: "host:login", token: "t2" }, HOST, {});
    deliver({ type: "host:login", token: 42 }, HOST, parent);
    deliver({ type: "host:login", token: "x".repeat(5000) }, HOST, parent);
    deliver({ type: "chatbot:ready" }, HOST, parent);
    expect(received).toEqual([]);

    deliver({ type: "host:login", token: "t3" }, HOST, parent);
    deliver({ type: "host:logout" }, HOST, parent);
    expect(received).toEqual([{ type: "host:login", token: "t3" }, { type: "host:logout" }]);
  });

  it("talks only to the origin that answered once the host has replied", () => {
    deliver({ type: "host:hello" }, OTHER_ALLOWED, parent);
    parent.postMessage.mockClear();
    new HostBridge([HOST, OTHER_ALLOWED], () => {}); // unrelated instance does not interfere
    deliver({ type: "host:hello" }, OTHER_ALLOWED, parent);
    expect(received.map((message) => message.type)).toEqual(["host:hello", "host:hello"]);
  });
});

describe("secondsUntilExpiry", () => {
  it("reads exp from the token payload and tolerates junk", () => {
    const payload = btoa(JSON.stringify({ exp: 1_000 })).replace(/=+$/, "");
    expect(secondsUntilExpiry(`h.${payload}.s`, 400_000)).toBe(600);
    expect(secondsUntilExpiry("not-a-jwt")).toBeNull();
  });
});
