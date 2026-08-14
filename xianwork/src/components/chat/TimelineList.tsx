/**
 * TimelineList — renders the chat timeline: user bubbles on the right,
 * assistant markdown full-width on the left, collapsible reasoning panels,
 * tool cards and per-turn usage footers. Auto-follows the stream only when
 * the user is already near the bottom (backend chat parity). Assistant
 * turns carry copy / regenerate actions like the console action group.
 */
import { useEffect, useRef, useState } from "react";
import type { TimelineItem, UserAttachment } from "../../chat/protocol";
import MarkdownView from "./MarkdownView";
import ReasoningBlock from "./ReasoningBlock";
import ToolCallCard from "./ToolCallCard";

function formatTokens(n?: number): string {
  if (!n || n <= 0) return "0";
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return String(n);
}

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

  // Follow the newest content while the user hasn't scrolled away.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [items, streaming]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  return (
    <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
      <div className="chat-timeline">
        {items.map((item) => {
          switch (item.kind) {
            case "user":
              return (
                <div key={item.key} className="chat-row user">
                  <div className="chat-bubble user">
                    {item.attachments && item.attachments.length > 0 && (
                      <AttachmentChips attachments={item.attachments} />
                    )}
                    {item.text}
                  </div>
                </div>
              );
            case "reasoning":
              return <ReasoningBlock key={item.key} text={item.text} done={item.done} />;
            case "tool":
              return (
                <ToolCallCard
                  key={item.key}
                  name={item.name}
                  args={item.args}
                  output={item.output}
                  status={item.status}
                />
              );
            case "assistant":
              return (
                <div key={item.key} className="chat-row assistant">
                  <div className="chat-avatar">
                    <i className="fa-solid fa-paw" />
                  </div>
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
                    {!streaming && onCopy && (
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
  );
}
