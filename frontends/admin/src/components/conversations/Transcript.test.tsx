import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../../i18n/I18nProvider";
import type { AdminMessage } from "../../lib/types";
import { Transcript } from "./Transcript";

vi.mock("./TraceDetails", () => ({ TraceDetails: () => <div data-testid="trace" /> }));

const message = (overrides: Partial<AdminMessage>): AdminMessage => ({
  id: "m1",
  role: "assistant",
  content: "hello",
  outcome: "answered",
  citations: [],
  confidence: null,
  model: null,
  prompt_tokens: 0,
  completion_tokens: 0,
  latency_ms: null,
  cached: false,
  guard_reason: null,
  answered_by: null,
  request_id: null,
  created_at: "2026-10-07T04:24:00Z",
  feedback: null,
  ...overrides,
});

const renderTranscript = (messages: AdminMessage[]) =>
  render(
    <I18nProvider>
      <Transcript messages={messages} />
    </I18nProvider>,
  );

afterEach(cleanup);

describe("Transcript", () => {
  it("shows the trace of a bot answer", () => {
    renderTranscript([message({})]);
    expect(screen.getByTestId("trace")).toBeTruthy();
  });

  it("shows who wrote a staff reply and no trace, which a human reply never has", () => {
    renderTranscript([message({ outcome: "agent_reply", answered_by: "agent@example.test" })]);
    expect(screen.queryByTestId("trace")).toBeNull();
    expect(screen.getByText(/agent@example\.test/)).toBeTruthy();
  });
});
