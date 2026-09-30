import { describe, expect, it } from "vitest";
import { shouldNotify } from "../../lib/use-desktop-notifications";
import { parseWidgetOrigin } from "./use-widget-origin";
import { embedSnippet } from "./WidgetPreviewPage";

describe("widget origin", () => {
  it("keeps only the origin of an http(s) URL", () => {
    expect(parseWidgetOrigin("https://chat.client.vn/widget?x=1")).toBe("https://chat.client.vn");
    expect(parseWidgetOrigin(" http://localhost:3000 ")).toBe("http://localhost:3000");
  });

  it("rejects empty values and other schemes", () => {
    for (const value of ["", "   ", null, 42, "javascript:alert(1)", "data:text/html,x", "chat.client.vn"]) {
      expect(parseWidgetOrigin(value)).toBeNull();
    }
  });

  it("builds the same embed snippet embed.js documents", () => {
    expect(embedSnippet("https://chat.client.vn", "#0B5FFF", "Hỏi đáp")).toContain('src="https://chat.client.vn/embed.js" defer');
    expect(embedSnippet("https://chat.client.vn", "#0B5FFF", "Hỏi đáp")).toContain('data-color="#0B5FFF"');
  });
});

describe("desktop notifications", () => {
  it("fire only when the count grows after the first load", () => {
    expect(shouldNotify(null, 3)).toBe(false);
    expect(shouldNotify(3, 3)).toBe(false);
    expect(shouldNotify(3, 2)).toBe(false);
    expect(shouldNotify(2, 3)).toBe(true);
  });
});
