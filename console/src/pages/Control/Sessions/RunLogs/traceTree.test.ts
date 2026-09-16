/**
 * Tests for RunLogs/traceTree pure helpers: execution-chain skeleton
 * building (system/intent/agent/end phases, tool-output pairing),
 * duration computation, and payload truncation.
 */
import { describe, expect, it } from "vitest";
import {
  buildSpanTree,
  buildTraceTree,
  truncateDetail,
} from "./traceTree";
import type { RunLogTrace } from "../../../../api/modules/runLogs";

function msg(
  role: string,
  content: unknown,
  extra: Record<string, unknown> = {},
) {
  return { role, content, ...extra };
}

function traceOf(
  events: Array<{ at: number; event: unknown }>,
  meta: Record<string, unknown> = { query: "排查发货短信" },
): RunLogTrace {
  return {
    run_id: "run-1",
    created_at: 1000,
    completed_at: 1050,
    status: "success",
    meta,
    events: events as RunLogTrace["events"],
  } as RunLogTrace;
}

describe("truncateDetail", () => {
  it("passes through short strings", () => {
    expect(truncateDetail("short")).toBe("short");
  });

  it("truncates long strings with ellipsis", () => {
    const out = truncateDetail("x".repeat(20000), 100) as string;
    expect(out.length).toBe(101);
    expect(out.endsWith("…")).toBe(true);
  });

  it("marks oversized objects as truncated previews", () => {
    const out = truncateDetail({ big: "y".repeat(20000) }, 50) as Record<
      string,
      unknown
    >;
    expect(out.__truncated__).toBe(true);
  });
});

describe("buildTraceTree", () => {
  it("maps the competitor skeleton with pairing and durations", () => {
    const tree = buildTraceTree(
      traceOf([
        {
          at: 1001,
          event: msg("user", "客户反馈没收到发货短信，排查一下"),
        },
        {
          at: 1002,
          event: msg("assistant", [
            { type: "thinking", thinking: "先查知识库" },
            {
              type: "tool_use",
              name: "knowledge_search",
              input: { q: "发货短信" },
            },
          ]),
        },
        {
          at: 1003,
          event: msg("tool", [
            { type: "tool_result", output: [{ type: "text", text: "命中" }] },
          ]),
        },
        { at: 1004, event: msg("assistant", "问题已定位") },
      ]),
    );

    // Root: run overview with total duration (50s → 50000ms).
    expect(tree.kind).toBe("root");
    expect(tree.durationMs).toBe(50000);
    expect(tree.detail.input).toBe("排查发货短信");

    // Skeleton: system context → user → intent → end (no mid-loop
    // assistant between the intent step and the trailing reply, so no
    // agent container is synthesized).
    expect(tree.children.map((node) => node.kind)).toEqual([
      "system",
      "user",
      "intent",
      "end",
    ]);

    const [, userNode, intentNode, endNode] = tree.children;
    expect(userNode.detail.input).toBe("客户反馈没收到发货短信，排查一下");

    // Intent = first assistant reply, fed with the first user text,
    // and its tool call pairs the following role=tool message.
    expect(intentNode.detail.input).toBe("客户反馈没收到发货短信，排查一下");
    expect(intentNode.detail.output).toBe("先查知识库");
    expect(intentNode.children.map((child) => child.title)).toEqual([
      "knowledge_search",
    ]);
    const toolChild = intentNode.children[0];
    expect(toolChild.kind).toBe("tool");
    expect(toolChild.detail.input).toEqual({ q: "发货短信" });
    expect(toolChild.detail.output).toBe("命中");

    // Trailing plain-text assistant becomes the end node, timed from
    // the last event to completed_at (1050 - 1004 = 46s → 46000ms).
    expect(endNode.kind).toBe("end");
    expect(endNode.detail.output).toBe("问题已定位");
    expect(endNode.durationMs).toBe(46000);
  });

  it("wraps mid-loop assistant steps in an agent container", () => {
    const tree = buildTraceTree(
      traceOf([
        { at: 1001, event: msg("user", "查一下") },
        {
          at: 1002,
          event: msg("assistant", [
            { type: "tool_use", name: "knowledge_search", input: {} },
          ]),
        },
        { at: 1003, event: msg("tool", []) },
        {
          at: 1004,
          event: msg("assistant", [
            { type: "tool_use", name: "bash", input: {} },
          ]),
        },
        { at: 1005, event: msg("tool", []) },
        { at: 1006, event: msg("assistant", "完成了") },
      ]),
    );

    expect(tree.children.map((node) => node.kind)).toEqual([
      "system",
      "user",
      "intent",
      "agent",
      "end",
    ]);
    const agentNode = tree.children[3];
    expect(agentNode.title).toBe("Agent");
    // Intent consumed the first assistant; only the middle loop lands here.
    expect(agentNode.children.map((child) => child.kind)).toEqual(["llm"]);
    expect(agentNode.children[0].children[0].title).toBe("bash");
    expect(tree.children[4].detail.output).toBe("完成了");
  });

  it("survives empty events and keeps payloads untruncated", () => {
    const tree = buildTraceTree(traceOf([], {}));
    // No meta keys → no system node; payload truncation is lazy now.
    expect(tree.children).toEqual([]);
    expect(tree.durationMs).toBe(50000);
  });

  it("omits the agent container for single-shot replies", () => {
    const tree = buildTraceTree(
      traceOf([
        { at: 1001, event: msg("user", "你好") },
        { at: 1002, event: msg("assistant", "你好呀") },
      ]),
    );
    expect(tree.children.map((node) => node.kind)).toEqual([
      "system",
      "user",
      "intent",
    ]);
  });
});

describe("buildSpanTree", () => {
  function spanOf(
    spanId: string,
    kind: string,
    extra: Record<string, unknown> = {},
  ) {
    return {
      span_id: spanId,
      kind,
      name: null,
      parent_span_id: null,
      started_at: 1000,
      duration_ms: 10,
      input: null,
      output: null,
      ...extra,
    };
  }

  function spanTrace(spans: unknown[]): RunLogTrace {
    return {
      run_id: "run-1",
      created_at: 1000,
      completed_at: 1050,
      status: "success",
      meta: { query: "出报告和方案" },
      spans,
    } as unknown as RunLogTrace;
  }

  it("renders verify spans as their own node kind", () => {
    const tree = buildSpanTree(
      spanTrace([
        spanOf("s1", "llm", { name: "qwen3-max" }),
        spanOf("s2", "verify", {
          name: "independent_verify",
          output: { verdict: "FAIL", issues: ["缺定价"] },
        }),
      ]),
    );
    const agent = tree.children[tree.children.length - 1];
    expect(agent?.kind).toBe("agent");
    expect(agent?.children.map((node) => node.kind)).toEqual([
      "llm",
      "verify",
    ]);
    // verify 节点标题回退到 span.name，由前端 i18n 映射为「独立验收」
    expect(agent?.children[1]?.title).toBe("independent_verify");
  });

  it("keeps unknown span kinds on the llm node", () => {
    const tree = buildSpanTree(spanTrace([spanOf("s1", "future_kind")]));
    const agent = tree.children[tree.children.length - 1];
    expect(agent?.children[0]?.kind).toBe("llm");
  });
});
