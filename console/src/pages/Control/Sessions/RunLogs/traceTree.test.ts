/**
 * Tests for RunLogs/traceTree pure helpers: execution-chain tree
 * building (user/assistant/tool mapping, tool-output pairing),
 * duration computation, and payload truncation.
 */
import { describe, expect, it } from "vitest";
import {
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

function traceOf(events: Array<{ at: number; event: unknown }>): RunLogTrace {
  return {
    run_id: "run-1",
    created_at: 1000,
    completed_at: 1050,
    status: "success",
    meta: { query: "排查发货短信" },
    events: events as RunLogTrace["events"],
  };
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
  it("maps user → assistant → tool chain with pairing and durations", () => {
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
    expect(tree.title).toBe("root");
    expect(tree.durationMs).toBe(50000);
    expect(tree.detail.input).toBe("排查发货短信");

    // Four child nodes in order.
    expect(tree.children.map((node) => node.title)).toEqual([
      "user",
      "assistant",
      "assistant",
    ]);

    const [userNode, thinkingNode, replyNode] = tree.children;
    expect(userNode.detail.input).toBe("客户反馈没收到发货短信，排查一下");
    expect(userNode.durationMs).toBe(1000);

    // The tool-calling assistant exposes one paired tool child.
    expect(thinkingNode.children.map((child) => child.title)).toEqual([
      "knowledge_search",
    ]);
    const toolChild = thinkingNode.children[0];
    expect(toolChild.detail.input).toEqual({ q: "发货短信" });
    // Output pairs the following role=tool message text.
    expect(toolChild.detail.output).toBe("命中");

    // Plain assistant reply carries its text as output.
    expect(replyNode.detail.output).toBe("问题已定位");
    expect(replyNode.durationMs).toBeNull();
  });

  it("survives empty events and missing timestamps", () => {
    const tree = buildTraceTree(traceOf([]));
    expect(tree.children).toEqual([]);
    expect(tree.durationMs).toBe(50000);
  });
});
