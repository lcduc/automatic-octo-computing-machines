import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { I18nProvider } from "../../i18n/I18nProvider";
import type { ChunkingSpec, ChunkingStrategyInfo } from "../../lib/types";
import { defaultSpec, StrategyPicker } from "./StrategyPicker";

/** Shapes as Pydantic emits them for api/schemas/chunking.py. */
const STRATEGIES: ChunkingStrategyInfo[] = [
  { name: "auto", description: "", params_schema: { properties: { strategy: { const: "auto", default: "auto" } } } },
  {
    name: "legal_article",
    description: "",
    params_schema: {
      properties: {
        strategy: { const: "legal_article" },
        split_at: { enum: ["chapter", "section", "article", "clause"], type: "string", default: "article" },
        max_chars: { type: "integer", minimum: 200, maximum: 20000, default: 3000 },
        breadcrumb: { type: "boolean", default: true },
      },
    },
  },
];

function Harness({ onSpec }: { onSpec: (spec: ChunkingSpec) => void }) {
  const [spec, setSpec] = useState<ChunkingSpec>({ strategy: "auto" });
  return (
    <StrategyPicker
      strategies={STRATEGIES}
      value={spec}
      onChange={(next) => {
        setSpec(next);
        onSpec(next);
      }}
    />
  );
}

describe("StrategyPicker", () => {
  beforeEach(() => window.localStorage.setItem("admin.language", "vi")); // the queries below read Vietnamese labels

  it("builds defaults from the schema and edits typed parameters", () => {
    const specs: ChunkingSpec[] = [];
    render(
      <I18nProvider>
        <Harness onSpec={(spec) => specs.push(spec)} />
      </I18nProvider>,
    );

    fireEvent.change(screen.getByRole("combobox", { name: /Kiểu chia đoạn/ }), { target: { value: "legal_article" } });
    expect(specs.at(-1)).toEqual({ strategy: "legal_article", split_at: "article", max_chars: 3000, breadcrumb: true });

    fireEvent.change(screen.getByRole("combobox", { name: "Chia theo" }), { target: { value: "clause" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Số ký tự tối đa/ }), { target: { value: "1500" } });
    fireEvent.click(screen.getByRole("checkbox"));
    expect(specs.at(-1)).toEqual({ strategy: "legal_article", split_at: "clause", max_chars: 1500, breadcrumb: false });
  });

  it("omits parameters without a default", () => {
    expect(defaultSpec(STRATEGIES[0]!)).toEqual({ strategy: "auto" });
  });
});
