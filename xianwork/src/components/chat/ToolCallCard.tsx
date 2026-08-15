/**
 * ToolCallCard — console ToolCall Accordion parity: an "执行 {tool}" step
 * header styled exactly like the Thinking pill (collapsed = outlined pill,
 * expanded = bordered card). The run state lives in the chained step-icon
 * slot — spinner while running, green check on success, red cross on error —
 * and the Input / Output blocks render as bordered cards with grey bars
 * (operate-card-tool-call-block parity).
 */
import { useState } from "react";

function prettyJson(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

export interface ToolCallCardProps {
  name: string;
  args: string;
  output: string;
  status: "running" | "completed" | "error";
  /** Step-chain flags — hide the upstream / downstream connector stub. */
  stepFirst?: boolean;
  stepLast?: boolean;
}

export default function ToolCallCard({
  name,
  args,
  output,
  status,
  stepFirst,
  stepLast,
}: ToolCallCardProps) {
  const hasDetail = Boolean(args || output);
  const [open, setOpen] = useState(false);
  const classes = [
    "tool-card",
    open ? "open" : "",
    stepFirst ? "step-first" : "",
    stepLast ? "step-last" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes}>
      <button
        type="button"
        className="tool-card-header"
        onClick={() => hasDetail && setOpen((v) => !v)}
        disabled={!hasDetail}
      >
        <span className="step-icon">
          {status === "running" && <i className="fa-solid fa-spinner fa-spin step-icon-loading" />}
          {status === "completed" && <i className="fa-solid fa-circle-check step-icon-success" />}
          {status === "error" && <i className="fa-solid fa-circle-xmark step-icon-error" />}
        </span>
        <span className="tool-card-label">执行 {name}</span>
        {hasDetail && <i className={`fa-solid fa-chevron-${open ? "up" : "down"} step-caret`} />}
      </button>
      {open && (
        <div className="tool-card-detail">
          {args && (
            <div className="tool-card-block">
              <div className="tool-card-block-head">参数</div>
              <pre className="tool-card-pre">{prettyJson(args)}</pre>
            </div>
          )}
          {output && (
            <div className="tool-card-block">
              <div className="tool-card-block-head">结果</div>
              <pre className="tool-card-pre">{output}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
