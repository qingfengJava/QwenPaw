/**
 * TimelineList — renders the chat timeline: user bubbles on the right with an
 * HH:MM:SS footer, assistant turns opened by a xianwork identity head followed
 * by collapsible Thinking / tool step lists and full-width markdown, plus
 * per-turn usage footers. Auto-follows the stream only when the user is
 * already near the bottom (backend chat parity) and carries the right-side
 * user-message navigator (console UserMessageAnchors parity).
 */
import { useEffect, useRef, useState } from "react";
import type { TimelineItem, UserAttachment } from "../../chat/protocol";
import MarkdownView from "./MarkdownView";
import ReasoningBlock from "./ReasoningBlock";
import ToolCallCard from "./ToolCallCard";
import UserMessageNav, { anchorDomId } from "./UserMessageNav";

/** Console formatMessageTime parity — HH:MM:SS, seconds normalised to ms. */
function formatMessageTime(ts?: number): string {
  if (!ts) return "";
  const date = new Date(ts < 1e12 ? ts * 1000 : ts);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatTokens(n?: number): string {
  if (!n || n <= 0) return "0";
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return String(n);
}

/** Item kinds that open a new assistant turn (identity head rendered above). */
const TURN_HEAD_KINDS = new Set(["reasoning", "tool", "assistant"]);
/** Item kinds that close the previous turn — a head after them starts a new one. */
const TURN_TAIL_KINDS = new Set(["user", "error", "usage"]);
/** Collapsible agent-run steps — chained by the console connector line. */
const STEP_KINDS = new Set(["reasoning", "tool"]);

function AttachmentChips({ attachments }: { attachments: UserAttachment[] }) {
  return (
    <div className="user-attachments">
      {attachments.map((a) =>
        a.type.startsWith("image/") ? (
          <img
            key={a.url + a.name}
            className="user-attachment-image"
            src={a.url.startsWith("http") ? a.url : `/api/files/preview/${a.url.replace(/^\/+/, "")}`}
            alt={a.name}
          />
        ) : (
          <span key={a.url + a.name} className="user-attachment-file">
            <i className="fa-solid fa-file-lines" /> {a.name}
          </span>
        ),
      )}
    </div>
  );
}

function AgentHead() {
  return (
    <div className="chat-agent-head">
      <div className="chat-avatar">
        <i className="fa-solid fa-paw" />
      </div>
      <span className="chat-agent-name">xianwork</span>
    </div>
  );
}

function AssistantActions({
  text,
  onCopy,
  onRegenerate,
}: {
  text: string;
  onCopy: (text: string) => void;
  onRegenerate?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="assistant-actions">
      <button
        type="button"
        title="复制"
        onClick={() => {
          onCopy(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        }}
      >
        <i className={`fa-${copied ? "solid fa-check" : "regular fa-copy"}`} />
        {copied ? "已复制" : "复制"}
      </button>
      {onRegenerate && (
        <button type="button" title="重新生成" onClick={onRegenerate}>
          <i className="fa-solid fa-rotate-right" /> 重新生成
        </button>
      )}
    </div>
  );
}

function UsageFooter({ usage }: { usage: NonNullable<Extract<TimelineItem, { kind: "usage" }>["usage"]> }) {
  // Backend ratios can exceed 1 when estimated tokens overshoot the window;
  // clamp the display like the console ring does.
  const ratio = Math.min(1, Math.max(0, usage.context_usage_ratio ?? 0));
  return (
    <div className="usage-footer">
      <span>
        <i className="fa-solid fa-microchip" /> {usage.model_name ?? "—"}
      </span>
      <span>
        <i className="fa-solid fa-arrow-right-arrow-left" /> 输入 {formatTokens(usage.prompt_tokens)} · 输出{" "}
        {formatTokens(usage.completion_tokens)}
      </span>
      <span>
        <i className="fa-solid fa-gauge-high" /> 上下文 {(ratio * 100).toFixed(0)}%
      </span>
    </div>
  );
}

interface TimelineListProps {
  items: TimelineItem[];
  streaming: boolean;
  onCopy?: (text: string) => void;
  /** Provided only for the last assistant turn (regenerate support). */
  onRegenerate?: () => void;
  /** Key of the assistant item that supports regeneration. */
  regenerateKey?: string;
}

export default function TimelineList({
  items,
  streaming,
  onCopy,
  onRegenerate,
  regenerateKey,
}: TimelineListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const lastCountRef = useRef(0);
  const [showJump, setShowJump] = useState(false);

  // Follow the newest content while the user hasn't scrolled away. A newly
  // appended user turn (a send) or a timeline reset (chat switch) always
  // snaps to the bottom — the console reverse list keeps the newest bubble
  // in view by construction, a forward list must do it on append.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const grew = items.length > lastCountRef.current;
    const reset = items.length < lastCountRef.current;
    lastCountRef.current = items.length;
    const last = items[items.length - 1];
    const isSend = grew && last?.kind === "user";
    if (isSend || reset || stickRef.current) {
      stickRef.current = true;
      el.scrollTop = el.scrollHeight;
      setShowJump(false);
    }
  }, [items, streaming]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stickRef.current = nearBottom;
    setShowJump(
      !nearBottom && el.scrollHeight > el.clientHeight + 120,
    );
  };

  const jumpToLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = true;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setShowJump(false);
  };

  return (
    <div className="chat-scroll-wrap">
      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="chat-timeline">
        {items.map((item, index) => {
          // An assistant turn opens with a xianwork identity head; reasoning,
          // tool calls and the final message of one turn all live under it.
          const startsTurn =
            TURN_HEAD_KINDS.has(item.kind) &&
            (index === 0 || TURN_TAIL_KINDS.has(items[index - 1].kind));
          const head = startsTurn ? <AgentHead key={`head_${item.key}`} /> : null;
          // Step-chain flags: hide the connector stub above the first step of
          // a run and below the last one (console accordion icon-line parity).
          const stepFirst =
            STEP_KINDS.has(item.kind) &&
            (index === 0 || !STEP_KINDS.has(items[index - 1].kind));
          const stepLast =
            STEP_KINDS.has(item.kind) &&
            (index === items.length - 1 || !STEP_KINDS.has(items[index + 1].kind));
          switch (item.kind) {
            case "user":
              return (
                <div
                  key={item.key}
                  id={anchorDomId(item.key)}
                  data-user-msg
                  className="chat-row user"
                >
                  <div className="user-col">
                    <div className="chat-bubble user">
                      {item.attachments && item.attachments.length > 0 && (
                        <AttachmentChips attachments={item.attachments} />
                      )}
                      {item.text}
                    </div>
                    {(item.at || onCopy) && (
                      <div className="user-msg-meta">
                        {item.at && <span className="user-msg-time">{formatMessageTime(item.at)}</span>}
                        {onCopy && (
                          <button
                            type="button"
                            className="user-msg-copy"
                            title="复制"
                            onClick={() => onCopy(item.text)}
                          >
                            <i className="fa-regular fa-copy" />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            case "reasoning":
              return (
                <div key={item.key} className="chat-step-row">
                  {head}
                  <ReasoningBlock
                    text={item.text}
                    done={item.done}
                    stepFirst={stepFirst}
                    stepLast={stepLast}
                  />
                </div>
              );
            case "tool":
              return (
                <div key={item.key} className="chat-step-row">
                  {head}
                  <ToolCallCard
                    name={item.name}
                    args={item.args}
                    output={item.output}
                    status={item.status}
                    stepFirst={stepFirst}
                    stepLast={stepLast}
                  />
                </div>
              );
            case "assistant":
              return (
                <div key={item.key}>
                  {head}
                  <div className="chat-row assistant">
                    <div className="chat-assistant-body">
                      {item.text ? (
                        <MarkdownView text={item.text} />
                      ) : streaming ? (
                        <span className="chat-cursor">▍</span>
                      ) : null}
                      {streaming && item.text && <span className="chat-cursor">▍</span>}
                      {item.usage && (
                        <div className="usage-footer">
                          <span>
                            <i className="fa-solid fa-arrow-right-arrow-left" /> {formatTokens(item.usage.input_tokens)} /{" "}
                            {formatTokens(item.usage.output_tokens)} tokens
                          </span>
                        </div>
                      )}
                      {!streaming && (
                        <div className="assistant-foot">
                          {onCopy && (
                            <AssistantActions
                              text={item.text}
                              onCopy={onCopy}
                              onRegenerate={
                                onRegenerate && regenerateKey === item.key
                                  ? onRegenerate
                                  : undefined
                              }
                            />
                          )}
                          {item.at && (
                            <span className="assistant-time">{formatMessageTime(item.at)}</span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            case "usage":
              return <UsageFooter key={item.key} usage={item.usage} />;
            case "error":
              return (
                <div key={item.key} className="chat-error-banner">
                  <i className="fa-solid fa-triangle-exclamation" /> {item.text}
                </div>
              );
            default:
              return null;
          }
        })}
        </div>
      </div>

      <UserMessageNav scrollRef={scrollRef} items={items} />

      {showJump && (
        <button
          type="button"
          className="chat-jump-latest"
          onClick={jumpToLatest}
          aria-label="回到最新消息"
        >
          <i className="fa-solid fa-arrow-down" />
          {streaming ? "查看最新回复" : "回到最新"}
        </button>
      )}
    </div>
  );
}
