/**
 * Build the execution-chain tree from a run trace's flat session events.
 *
 * Mapping (competitor-style run detail):
 *   运行总览 (total duration)
 *   ├─ 用户输入            — user message
 *   ├─ LLM 思考 10.2s      — assistant message (Output panel = full content)
 *   │   └─ tool_name       — tool_use block, paired with the next tool msg
 *   └─ …
 *
 * Pure functions only, so the pairing logic stays unit-testable.
 */
import type {
  RunLogTrace,
  RunLogTraceEvent,
} from "../../../../api/modules/runLogs";

export interface TraceNodeDetail {
  input?: unknown;
  output?: unknown;
}

export interface TraceNode {
  key: string;
  title: string;
  /** Wall time to the next event, in ms; null when unknown. */
  durationMs: number | null;
  detail: TraceNodeDetail;
  children: TraceNode[];
}

type Msg = Record<string, unknown>;
type Block = Record<string, unknown>;

const isToolCallType = (type: string): boolean =>
  type === "tool_use" || type === "tool_call";

function blocksOf(msg: Msg): Block[] {
  const content = msg.content;
  if (!Array.isArray(content)) {
    return [];
  }
  return content.filter(
    (block): block is Block => !!block && typeof block === "object",
  );
}

function textOfBlock(block: Block): string {
  if (typeof block.text === "string") {
    return block.text;
  }
  if (typeof block.thinking === "string") {
    return block.thinking;
  }
  // tool_result blocks carry their payload in ``output[].text``
  // (same shape as Inbox traceUtils).
  const output = block.output;
  if (Array.isArray(output)) {
    const chunks = output
      .map(
        (item) =>
          typeof item === "object" &&
          item !== null &&
          typeof (item as Block).text === "string"
            ? ((item as Block).text as string)
            : "",
      )
      .filter(Boolean);
    if (chunks.length) {
      return chunks.join("\n");
    }
  }
  return "";
}

/** Human-readable text across string or block-array content. */
function textOf(msg: Msg): string {
  if (typeof msg.content === "string") {
    return msg.content;
  }
  return blocksOf(msg)
    .map(textOfBlock)
    .filter(Boolean)
    .join("\n");
}

function toolNameOf(block: Block, msg: Msg): string {
  if (typeof block.name === "string" && block.name) {
    return block.name;
  }
  if (typeof msg.tool_name === "string" && msg.tool_name) {
    return msg.tool_name;
  }
  if (typeof block.tool_name === "string" && block.tool_name) {
    return block.tool_name;
  }
  return "tool";
}

function eventAt(event: RunLogTraceEvent): number | null {
  return typeof event.at === "number" ? event.at : null;
}

/** Truncate oversized JSON payloads before rendering them in the panel. */
export function truncateDetail(value: unknown, maxChars = 16000): unknown {
  if (typeof value === "string") {
    return value.length > maxChars ? `${value.slice(0, maxChars)}…` : value;
  }
  try {
    const serialized = JSON.stringify(value);
    if (serialized && serialized.length > maxChars) {
      return {
        __truncated__: true,
        preview: `${serialized.slice(0, maxChars)}…`,
      };
    }
  } catch {
    return String(value);
  }
  return value;
}

/**
 * Assemble the trace tree. Tool outputs (role=tool messages carrying
 * ``tool_result``) pair back to the most recent unfilled tool child.
 */
export function buildTraceTree(trace: RunLogTrace): TraceNode {
  const events = trace.events || [];
  const rootDuration =
    typeof trace.completed_at === "number" &&
    typeof trace.created_at === "number"
      ? Math.max(0, (trace.completed_at - trace.created_at) * 1000)
      : null;

  const root: TraceNode = {
    key: "root",
    title: "root",
    durationMs: rootDuration,
    detail: { input: trace.meta?.query ?? undefined },
    children: [],
  };

  // Pending tool children waiting for their output message.
  let openToolNodes: TraceNode[] = [];
  let nodeSeq = 0;

  const makeNode = (
    title: string,
    detail: TraceNodeDetail,
    children: TraceNode[] = [],
  ): TraceNode => {
    nodeSeq += 1;
    return {
      key: `node-${nodeSeq}`,
      title,
      durationMs: null,
      detail,
      children,
    };
  };

  events.forEach((event: RunLogTraceEvent, index: number) => {
    const msg = (event.event || {}) as Msg;
    const role = String(msg.role || "");
    const at = eventAt(event);
    const nextAt = eventAt(events[index + 1] ?? ({} as RunLogTraceEvent));
    const durationMs =
      at !== null && nextAt !== null
        ? Math.max(0, Math.round((nextAt - at) * 1000))
        : null;

    if (role === "user") {
      const node = makeNode("user", { input: truncateDetail(textOf(msg)) });
      node.durationMs = durationMs;
      root.children.push(node);
      return;
    }

    if (role === "assistant") {
      const blocks = blocksOf(msg);
      const toolBlocks = blocks.filter((block) =>
        isToolCallType(String(block.type || "")),
      );
      const node = makeNode("assistant", {
        output: truncateDetail(textOf(msg)),
      });
      node.durationMs = durationMs;
      node.children = toolBlocks.map((block) => {
        const rawInput = block.raw_input ?? block.input;
        return makeNode(toolNameOf(block, msg), {
          input: truncateDetail(rawInput),
        });
      });
      openToolNodes = node.children;
      root.children.push(node);
      return;
    }

    if (role === "tool") {
      const output = truncateDetail(textOf(msg));
      // Pair in order with the assistant's unfilled tool children.
      const target = openToolNodes.find(
        (node) => node.detail.output === undefined,
      );
      if (target) {
        target.detail.output = output;
      }
    }
  });

  return root;
}
