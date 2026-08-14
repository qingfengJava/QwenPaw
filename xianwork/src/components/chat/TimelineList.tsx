/**
 * TimelineList — renders the chat timeline: user bubbles on the right,
 * assistant markdown full-width on the left, collapsible reasoning panels,
 * tool cards and per-turn usage footers. Auto-follows the stream only when
 * the user is already near the bottom (backend chat parity).
 */
import { useEffect, useRef } from "react";
import type { TimelineItem } from "../../chat/protocol";
import MarkdownView from "./MarkdownView";
import ReasoningBlock from "./ReasoningBlock";
import ToolCallCard from "./ToolCallCard";

function formatTokens(n?: number): string {
  if (!n || n <= 0) return "0";
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return String(n);
}

function UsageFooter({ usage }: { usage: NonNullable<Extract<TimelineItem, { kind: "usage" }>["usage"]> }) {
  const ratio = usage.context_usage_ratio ?? 0;
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
}

export default function TimelineList({ items, streaming }: TimelineListProps) {
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
                  <div className="chat-bubble user">{item.text}</div>
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
