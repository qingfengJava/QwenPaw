/**
 * Chat wire protocol for the console SSE plane (POST /console/chat).
 *
 * Event shapes were captured live against the backend (sequence_number
 * ordering, `object` discriminators):
 *   1. { object: "response", status: created|in_progress|completed, output: Msg[], usage? }
 *   2. { object: "message",  id: "msg_*", type: message|reasoning|plugin_call|plugin_call_output,
 *        role, content: Block[], status: in_progress|completed, usage? }
 *   3. { object: "content",  type: text|data, delta: boolean, index, msg_id, text? ,
 *        data?: FunctionCall { call_id, name, arguments } | FunctionCallOutput { call_id, name, output } }
 *   4. { type: "turn_usage", usage: {...}, context_usage: {...} }
 *   5. { error: string }  — emitted by the router on stream failure
 *
 * History (GET /chats/{id}) returns `{ messages: Msg[], status }` where Msg
 * mirrors the message events above with fully materialized content blocks.
 */
/** History message shape (GET /chats/{id}) — same skeleton as message events. */
export interface ChatHistoryMessage {
  id?: string;
  type?: string;
  role?: string;
  status?: string;
  content?: WireContent[];
  usage?: { input_tokens?: number; output_tokens?: number } | null;
}

export type ToolStatus = "running" | "completed" | "error";

export interface TurnUsage {
  provider_id?: string;
  model_name?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  context_size?: number;
  estimated_tokens?: number;
  context_usage_ratio?: number;
}

export type TimelineItem =
  | { kind: "user"; key: string; text: string }
  | { kind: "reasoning"; key: string; text: string; done: boolean }
  | {
      kind: "assistant";
      key: string;
      text: string;
      done: boolean;
      usage?: { input_tokens?: number; output_tokens?: number } | null;
    }
  | {
      kind: "tool";
      key: string;
      callId: string;
      name: string;
      args: string;
      output: string;
      status: ToolStatus;
    }
  | { kind: "usage"; key: string; usage: TurnUsage }
  | { kind: "error"; key: string; text: string };

interface WireMessage {
  object?: string;
  id?: string;
  type?: string;
  role?: string;
  status?: string;
  content?: WireContent[];
  usage?: { input_tokens?: number; output_tokens?: number } | null;
}

interface WireContent {
  type?: string;
  delta?: boolean;
  index?: number;
  status?: string | null;
  msg_id?: string | null;
  text?: string;
  data?: {
    call_id?: string;
    name?: string;
    arguments?: string;
    output?: string;
  };
}

type WireEvent = WireMessage &
  WireContent & {
    error?: unknown;
    context_usage?: {
      estimated_tokens?: number;
      max_input_length?: number;
      context_usage_ratio?: number;
    };
  };

let seq = 0;
const nextKey = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${(seq++).toString(36)}`;

/** Concatenate all text blocks of a message into one string. */
function messageText(msg: WireMessage): string {
  return (msg.content ?? [])
    .filter((block) => block.type === "text" && typeof block.text === "string")
    .map((block) => block.text as string)
    .join("");
}

function messageUsage(msg: WireMessage) {
  return msg.usage ?? null;
}

/**
 * Merge one SSE payload into the timeline (pure — returns the new array).
 * Unknown / keepalive payloads are ignored gracefully.
 */
export function applyEvent(items: TimelineItem[], payload: unknown): TimelineItem[] {
  let evt: WireEvent;
  try {
    evt = typeof payload === "string" ? (JSON.parse(payload) as WireEvent) : (payload as WireEvent);
  } catch {
    return items;
  }
  if (!evt || typeof evt !== "object") {
    return items;
  }

  // Router-level failure event.
  if (typeof evt.error === "string" && evt.error) {
    return [...items, { kind: "error", key: nextKey("err"), text: evt.error }];
  }

  // Per-turn usage footer (model + context window ratio).
  if ((evt as { type?: string }).type === "turn_usage" && evt.usage) {
    const usage: TurnUsage = {
      ...(evt.usage as TurnUsage),
      ...(evt.context_usage ?? {}),
    };
    const last = items[items.length - 1];
    if (last && last.kind === "usage") {
      const copy = items.slice(0, -1);
      return [...copy, { ...last, usage }];
    }
    return [...items, { kind: "usage", key: nextKey("usage"), usage }];
  }

  if (evt.object === "message" && evt.id && evt.type) {
    // User messages are appended locally on send; skip server echoes.
    if (evt.role === "user") {
      return items;
    }
    const idx = items.findIndex((it) => (it.kind === "reasoning" || it.kind === "assistant") && it.key === evt.id);
    if (evt.type === "reasoning") {
      if (idx >= 0) {
        const copy = items.slice();
        const prev = copy[idx] as Extract<TimelineItem, { kind: "reasoning" }>;
        copy[idx] = {
          ...prev,
          text: evt.content?.length ? messageText(evt) : prev.text,
          done: evt.status === "completed",
        };
        return copy;
      }
      return [
        ...items,
        { kind: "reasoning", key: evt.id, text: messageText(evt), done: evt.status === "completed" },
      ];
    }
    if (evt.type === "message") {
      if (idx >= 0) {
        const copy = items.slice();
        const prev = copy[idx] as Extract<TimelineItem, { kind: "assistant" }>;
        copy[idx] = {
          ...prev,
          text: evt.content?.length ? messageText(evt) : prev.text,
          done: evt.status === "completed",
          usage: messageUsage(evt) ?? prev.usage ?? null,
        };
        return copy;
      }
      return [
        ...items,
        {
          kind: "assistant",
          key: evt.id,
          text: messageText(evt),
          done: evt.status === "completed",
          usage: messageUsage(evt),
        },
      ];
    }
    // plugin_call / plugin_call_output message shells carry their payload in
    // data contents handled below; the completed shell closes the tool card.
    if (evt.type === "plugin_call_output" && evt.status === "completed" && evt.content?.length) {
      return evt.content.reduce(mergeDataContent, items);
    }
    if (evt.type === "plugin_call" && evt.status === "completed" && evt.content?.length) {
      return evt.content.reduce(mergeDataContent, items);
    }
    return items;
  }

  if (evt.object === "content") {
    if (evt.type === "text" && typeof evt.text === "string") {
      const msgId = evt.msg_id ?? "";
      const idx = items.findIndex(
        (it) => (it.kind === "reasoning" || it.kind === "assistant") && it.key === msgId,
      );
      if (idx < 0) {
        return items;
      }
      const copy = items.slice();
      const prev = copy[idx] as Extract<TimelineItem, { kind: "reasoning" | "assistant" }>;
      copy[idx] = {
        ...prev,
        text: evt.delta ? prev.text + evt.text : evt.text,
      };
      return copy;
    }
    if (evt.type === "data" && evt.data) {
      return mergeDataContent(items, evt);
    }
    return items;
  }

  if (evt.object === "response" && evt.status === "completed") {
    // Close every still-running tool card when the turn finishes.
    let mutated = false;
    const copy = items.map((it) => {
      if (it.kind === "tool" && it.status === "running") {
        mutated = true;
        return { ...it, status: "completed" as ToolStatus };
      }
      return it;
    });
    return mutated ? copy : items;
  }

  return items;
}

/** Merge a `data` content block (FunctionCall or FunctionCallOutput). */
function mergeDataContent(items: TimelineItem[], evt: WireContent): TimelineItem[] {
  const data = evt.data;
  if (!data || !data.call_id) {
    return items;
  }

  // FunctionCall: register / update the tool card arguments.
  if (typeof data.arguments === "string") {
    const idx = items.findIndex((it) => it.kind === "tool" && it.callId === data.call_id);
    if (idx >= 0) {
      const copy = items.slice();
      const prev = copy[idx] as Extract<TimelineItem, { kind: "tool" }>;
      copy[idx] = {
        ...prev,
        name: data.name || prev.name,
        args: evt.delta ? prev.args + data.arguments : data.arguments,
        status: evt.status === "completed" ? "completed" : prev.status,
      };
      return copy;
    }
    return [
      ...items,
      {
        kind: "tool",
        key: `tool_${data.call_id}`,
        callId: data.call_id,
        name: data.name || "tool",
        args: data.arguments,
        output: "",
        status: evt.status === "completed" ? "completed" : "running",
      },
    ];
  }

  // FunctionCallOutput: attach the output text to the matching card.
  const idx = items.findIndex((it) => it.kind === "tool" && it.callId === data.call_id);
  if (idx >= 0) {
    const copy = items.slice();
    const prev = copy[idx] as Extract<TimelineItem, { kind: "tool" }>;
    const output = typeof data.output === "string" ? data.output : JSON.stringify(data.output ?? "");
    copy[idx] = {
      ...prev,
      name: data.name || prev.name,
      output: evt.delta ? prev.output + output : output,
      status: evt.status === "completed" ? "completed" : prev.status,
    };
    return copy;
  }

  // Output without a prior call card (history replay edge) — synthesize one.
  const output = typeof data.output === "string" ? data.output : JSON.stringify(data.output ?? "");
  return [
    ...items,
    {
      kind: "tool",
      key: `tool_${data.call_id}`,
      callId: data.call_id,
      name: data.name || "tool",
      args: "",
      output,
      status: "completed",
    },
  ];
}

/** Build a user timeline entry (used on send). */
export function userItem(text: string): TimelineItem {
  return { kind: "user", key: nextKey("u"), text };
}

/**
 * Convert chat history (GET /chats/{id}) into the timeline model.
 * plugin_call + plugin_call_output pairs are joined into one tool card by
 * call_id, preserving the call's original position in the sequence.
 */
export function historyToTimeline(history: { messages?: unknown[] } | null | undefined): TimelineItem[] {
  const messages = (history?.messages ?? []) as WireMessage[];
  const items: TimelineItem[] = [];
  const toolIndex = new Map<string, number>();

  for (const msg of messages) {
    if (!msg || typeof msg !== "object") {
      continue;
    }
    if (msg.type === "message" && msg.role === "user") {
      items.push({ kind: "user", key: msg.id || nextKey("hu"), text: messageText(msg) });
      continue;
    }
    if (msg.type === "reasoning") {
      items.push({
        kind: "reasoning",
        key: msg.id || nextKey("hr"),
        text: messageText(msg),
        done: msg.status === "completed",
      });
      continue;
    }
    if (msg.type === "message" && msg.role === "assistant") {
      items.push({
        kind: "assistant",
        key: msg.id || nextKey("ha"),
        text: messageText(msg),
        done: msg.status === "completed",
        usage: messageUsage(msg),
      });
      continue;
    }
    if (msg.type === "plugin_call" || msg.type === "plugin_call_output") {
      for (const block of msg.content ?? []) {
        const data = block.data;
        if (!data || !data.call_id) {
          continue;
        }
        const existing = toolIndex.get(data.call_id);
        if (msg.type === "plugin_call" && typeof data.arguments === "string") {
          if (existing === undefined) {
            toolIndex.set(data.call_id, items.length);
            items.push({
              kind: "tool",
              key: `tool_${data.call_id}`,
              callId: data.call_id,
              name: data.name || "tool",
              args: data.arguments,
              output: "",
              status: msg.status === "completed" ? "completed" : "running",
            });
          } else {
            const it = items[existing] as Extract<TimelineItem, { kind: "tool" }>;
            items[existing] = { ...it, args: data.arguments, name: data.name || it.name };
          }
        } else if (msg.type === "plugin_call_output") {
          const output = typeof data.output === "string" ? data.output : JSON.stringify(data.output ?? "");
          if (existing === undefined) {
            toolIndex.set(data.call_id, items.length);
            items.push({
              kind: "tool",
              key: `tool_${data.call_id}`,
              callId: data.call_id,
              name: data.name || "tool",
              args: "",
              output,
              status: "completed",
            });
          } else {
            const it = items[existing] as Extract<TimelineItem, { kind: "tool" }>;
            items[existing] = { ...it, output, name: data.name || it.name, status: "completed" };
          }
        }
      }
    }
  }
  return items;
}
