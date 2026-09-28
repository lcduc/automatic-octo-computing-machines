import { describe, expect, it } from "vitest";
import { capabilitiesFor } from "./permissions";
import { fromRows, toRows } from "./metadata";

describe("capabilitiesFor mirrors api/dependencies.py", () => {
  it.each([
    ["owner", { canWrite: true, canHandoff: true, isOwner: true }],
    ["editor", { canWrite: true, canHandoff: true, isOwner: false }],
    ["support_agent", { canWrite: false, canHandoff: true, isOwner: false }],
    ["viewer", { canWrite: false, canHandoff: false, isOwner: false }],
  ] as const)("%s", (role, expected) => {
    expect(capabilitiesFor(role)).toEqual(expected);
  });
});

describe("metadata rows", () => {
  it("round-trip every value type", () => {
    const metadata = { url: "https://x.test", page: 3, official: true, tags: ["a", "b"] };
    expect(fromRows(toRows(metadata))).toEqual({ metadata });
  });

  it("report the first invalid row like the backend would", () => {
    expect(fromRows([{ key: "1bad", value: "x", type: "text" }]).error?.key).toBe("metadata.invalidKey");
    expect(fromRows([{ key: "page", value: "three", type: "number" }]).error?.key).toBe("metadata.notNumber");
    expect(fromRows([{ key: "a", value: "1", type: "text" }, { key: "a", value: "2", type: "text" }]).error?.key).toBe("metadata.duplicateKey");
    expect(fromRows([{ key: "", value: "", type: "text" }])).toEqual({ metadata: {} });
  });
});
