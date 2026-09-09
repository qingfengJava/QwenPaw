/**
 * Tests for RunLogs/traceTree buildSpanTree: span-driven tree assembly
 * (system/agent/end skeleton, tool spans under their owning llm span,
 * backend durations used verbatim) and legacy fallback behavior.
 */
import { describe, expect, it } from "vitest";
import { buildSpanTree } from "./traceTree";
import type { RunLogSpan, RunLogTrace } from "../../../../api/modules/runLogs";

function span(
  span_id: string,
  kind: RunLogSpan["kind"],
  extra: Partial<RunLogSpan> = {},
): RunLogSpan {
  return {
    span_id,
    parent_span_id: null,
    kind,
    name: null,
    started_at: 1000,
    ended_at: 1001,
    duration_ms: 1000,
    input: undefined,
    output: undefined,
    status: "success",
    ...extra,
  };
}

function traceOf(spans: RunLogSpan[]): RunLogTrace {
  return {
    run_id: "run-1",
    created_at: 1000,
    completed_at: 1002,
    status: "success",
    meta: { query: "介绍能力", agent_id: "expert_builtin_qa_guard" },
    events: [],
    spans,
  } as RunLogTrace;
}

describe("buildSpanTree", () => {
  it("assembles the competitor-style skeleton with backend durations", () => {
    const tree = buildSpanTree(
      traceOf([
        span("s1", "system", { duration_ms: 0 }),
        span("s2", "llm", {
          name: "qwen-max",
          started_at: 1000.1,
          duration_ms: 15490,
          input: { message_count: 3 },
          output: { blocks: [{ type: "tool_call", name: "bash" }] },
          tokens: 763,
        }),
        span("s3", "tool", {
          name: "bash",
          parent_span_id: "s2",
          started_at: 1000.2,
          duration_ms: 2880,
          input: { command: "ls" },
          output: { content: ["a.txt"] },
        }),
        span("s4", "reply", { duration_ms: 825, output: "完成" }),
      ]),
    );

    expect(tree.durationMs).toBe(2000);
    expect(tree.children.map((node) => node.kind)).toEqual([
      "system",
      "agent",
      "end",
    ]);
    const agent = tree.children[1];
    expect(agent.children.map((node) => node.kind)).toEqual(["llm"]);
    const llm = agent.children[0];
    expect(llm.durationMs).toBe(15490);
    expect(llm.children.map((child) => child.title)).toEqual(["bash"]);
    expect(llm.children[0].detail.input).toEqual({ command: "ls" });
    expect(tree.children[2].detail.output).toBe("完成");
  });

  it("hoists tool spans without an llm parent under the agent container", () => {
    const tree = buildSpanTree(
      traceOf([
        span("s1", "tool", { name: "orphan_tool", duration_ms: 5 }),
        span("s2", "llm", { name: "qwen-max", duration_ms: 10 }),
      ]),
    );
    const agent = tree.children[1];
    expect(agent.children.map((node) => node.kind)).toEqual(["tool", "llm"]);
  });

  it("orders out-of-order spans by started_at", () => {
    const tree = buildSpanTree(
      traceOf([
        span("late", "llm", { started_at: 1001.5, duration_ms: 1 }),
        span("early", "llm", { started_at: 1000.5, duration_ms: 2 }),
      ]),
    );
    const agent = tree.children[1];
    expect(agent.children[0].durationMs).toBe(2);
    expect(agent.children[1].durationMs).toBe(1);
  });

  it("survives an empty span list with the meta node only", () => {
    const tree = buildSpanTree(traceOf([]));
    expect(tree.children.map((node) => node.kind)).toEqual(["system"]);
  });
});
