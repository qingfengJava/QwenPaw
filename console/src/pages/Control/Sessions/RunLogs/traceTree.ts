/**
 * Build the execution-chain tree from a run trace's flat session events.
 *
 * Competitor-style skeleton, mapped onto real data only (no fabricated
 * payloads):
 *
 *   运行总览 (total duration)
 *   ├─ 系统上下文 (0 ms)     — trace.meta (environment / channel / model…)
 *   ├─ 用户输入              — user messages
 *   ├─ 意图识别              — first assistant message (input = first user text)
 *   ├─ Agent 节点            — container for the mid-loop assistant messages
 *   │   ├─ LLM 思考          — assistant message
 *   │   │   └─ tool_name     — tool_use block, paired with the next tool msg
 *   │   └─ …
 *   └─ 逻辑结束              — trailing plain-text assistant reply
 *
 * Payloads stay RAW here; ``truncateDetail`` is applied lazily by the
 * detail page for the selected node only (cheap builds for big traces).
 * Pure functions only, so the pairing logic stays unit-testable.
 */
import type {
  RunLogSpan,
  RunLogTrace,
  RunLogTraceEvent,
} from "../../../../api/modules/runLogs";

export interface TraceNodeDetail {
  input?: unknown;
  output?: unknown;
}

export type TraceNodeKind =
  | "root"
  | "system"
  | "user"
  | "intent"
  | "agent"
  | "llm"
  | "toolCall"
  | "tool"
  | "end";

export interface TraceNode {
  key: string;
  kind: TraceNodeKind;
  /** Tool name for tool nodes; otherwise the kind key (i18n-mapped). */
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

/** Truncate oversized payloads before rendering them in the panel. */
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
  const meta = trace.meta ?? ({} as RunLogTrace["meta"]);
  const rootDuration =
    typeof trace.completed_at === "number" &&
    typeof trace.created_at === "number"
      ? Math.max(0, (trace.completed_at - trace.created_at) * 1000)
      : null;

  const root: TraceNode = {
    key: "root",
    kind: "root",
    title: "root",
    durationMs: rootDuration,
    detail: { input: meta?.query ?? undefined },
    children: [],
  };

  // 系统上下文：本次运行的真实元信息（环境/渠道/模型/会话等）。
  if (meta && Object.keys(meta).length > 0) {
    root.children.push({
      key: "node-system",
      kind: "system",
      title: "system",
      durationMs: 0,
      detail: { input: meta },
      children: [],
    });
  }

  let nodeSeq = 0;
  const makeNode = (
    kind: TraceNodeKind,
    detail: TraceNodeDetail,
    title?: string,
  ): TraceNode => {
    nodeSeq += 1;
    return {
      key: `node-${nodeSeq}`,
      kind,
      title: title ?? kind,
      durationMs: null,
      detail,
      children: [],
    };
  };

  // Pending tool children waiting for their output message.
  let openToolNodes: TraceNode[] = [];
  const loopChildren: TraceNode[] = [];
  let firstUserText: string | null = null;
  let intentSeen = false;
  let trailingTextNode: TraceNode | null = null;

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
      const text = textOf(msg);
      if (firstUserText === null) {
        firstUserText = text;
      }
      const node = makeNode("user", { input: text });
      node.durationMs = durationMs;
      root.children.push(node);
      return;
    }

    if (role === "assistant") {
      const blocks = blocksOf(msg);
      const toolBlocks = blocks.filter((block) =>
        isToolCallType(String(block.type || "")),
      );
      const output = textOf(msg);

      if (!intentSeen) {
        // 首条 assistant 响应 = 意图识别（输入即首条用户提问）；
        // 它触发的工具调用同样作为子节点配对展示。
        intentSeen = true;
        const node = makeNode("intent", {
          input: firstUserText ?? undefined,
          output,
        });
        node.durationMs = durationMs;
        node.children = toolBlocks.map((block) => {
          const rawInput = block.raw_input ?? block.input;
          return makeNode("tool", { input: rawInput }, toolNameOf(block, msg));
        });
        openToolNodes = node.children;
        root.children.push(node);
        return;
      }

      const node = makeNode("llm", { output });
      node.durationMs = durationMs;
      node.children = toolBlocks.map((block) => {
        const rawInput = block.raw_input ?? block.input;
        return makeNode("tool", { input: rawInput }, toolNameOf(block, msg));
      });
      openToolNodes = node.children;

      if (toolBlocks.length === 0 && index === events.length - 1) {
        // 末条纯文本回复暂存，收尾时作为「逻辑结束」挂到 root。
        trailingTextNode = node;
      } else {
        loopChildren.push(node);
      }
      return;
    }

    if (role === "tool") {
      const output = textOf(msg);
      // Pair in order with the assistant's unfilled tool children.
      const target = openToolNodes.find(
        (node) => node.detail.output === undefined,
      );
      if (target) {
        target.detail.output = output;
      }
    }
  });

  if (loopChildren.length > 0) {
    const agentNode = makeNode(
      "agent",
      {},
      String(meta?.agent_id || "") || "Agent",
    );
    const summed = loopChildren.reduce(
      (sum, child) => sum + (child.durationMs ?? 0),
      0,
    );
    agentNode.durationMs = summed > 0 ? summed : null;
    agentNode.children = loopChildren;
    root.children.push(agentNode);
  }

  if (trailingTextNode) {
    const endNode = trailingTextNode as TraceNode;
    endNode.kind = "end";
    endNode.title = "end";
    const lastAt = eventAt(events[events.length - 1] ?? ({} as RunLogTraceEvent));
    if (
      lastAt !== null &&
      typeof trace.completed_at === "number" &&
      trace.completed_at >= lastAt
    ) {
      endNode.durationMs = Math.round((trace.completed_at - lastAt) * 1000);
    }
    root.children.push(endNode);
  }

  return root;
}

/**
 * Build the tree directly from backend-captured spans (PG runs).
 *
 * Structure mirrors the competitor detail page — real steps, real
 * durations, no semantic guessing:
 *
 *   运行总览 (total duration)
 *   ├─ 系统上下文           — system span
 *   ├─ Agent 容器           — all llm/tool spans, start-ordered
 *   │   ├─ LLM 思考        — llm span (title = model name -> i18n kind)
 *   │   │   └─ tool_name   — tool span (parent = owning llm span)
 *   │   └─ …
 *   └─ 逻辑结束              — reply span
 */
export function buildSpanTree(trace: RunLogTrace): TraceNode {
  const spans = trace.spans || [];
  const meta = trace.meta ?? ({} as RunLogTrace["meta"]);
  const rootDuration =
    typeof trace.completed_at === "number" &&
    typeof trace.created_at === "number"
      ? Math.max(0, (trace.completed_at - trace.created_at) * 1000)
      : null;

  const root: TraceNode = {
    key: "root",
    kind: "root",
    title: "root",
    durationMs: rootDuration,
    detail: { input: meta?.query ?? undefined },
    children: [],
  };

  if (meta && Object.keys(meta).length > 0) {
    root.children.push({
      key: "node-system",
      kind: "system",
      title: "system",
      durationMs: 0,
      detail: { input: meta },
      children: [],
    });
  }

  let nodeSeq = 0;
  const makeNode = (
    kind: TraceNodeKind,
    span: RunLogSpan,
  ): TraceNode => {
    nodeSeq += 1;
    return {
      key: `node-${nodeSeq}`,
      kind,
      // Tool nodes show their name; llm nodes carry the model name but
      // fall back to the kind title (titleMap lookup misses -> kind).
      title: span.name || kind,
      durationMs:
        typeof span.duration_ms === "number" ? span.duration_ms : null,
      detail: { input: span.input, output: span.output },
      children: [],
    };
  };

  const byId = new Map<string, TraceNode>();
  const ordered = [...spans].sort((a, b) => {
    const at = (s: RunLogSpan) =>
      typeof s.started_at === "number" ? s.started_at : 0;
    return at(a) - at(b);
  });

  const loopChildren: TraceNode[] = [];
  let replyNode: TraceNode | null = null;
  for (const span of ordered) {
    if (span.kind === "system") {
      continue; // already represented by the meta node above
    }
    if (span.kind === "reply") {
      replyNode = makeNode("end", span);
      replyNode.title = "end";
      continue;
    }
    const node = makeNode(span.kind === "tool" ? "tool" : "llm", span);
    byId.set(span.span_id, node);
    const parentSpanId = span.parent_span_id
      ? byId.get(span.parent_span_id)
      : undefined;
    if (span.kind === "tool" && parentSpanId) {
      parentSpanId.children.push(node);
    } else {
      loopChildren.push(node);
    }
  }

  if (loopChildren.length > 0) {
    const agentNode: TraceNode = {
      key: "node-agent",
      kind: "agent",
      // Prefer the human-readable agent name captured by the backend;
      // fall back to the raw agent id.
      title:
        String(meta?.display_name || "") ||
        String(meta?.agent_id || "") ||
        "Agent",
      durationMs:
        loopChildren.reduce(
          (sum, child) => sum + (child.durationMs ?? 0),
          0,
        ) || null,
      detail: {},
      children: loopChildren,
    };
    root.children.push(agentNode);
  }

  if (replyNode) {
    root.children.push(replyNode);
  }

  return root;
}
