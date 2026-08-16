/**
 * ReasoningBlock — collapsible chain-of-thought step, console Accordion
 * (DeepThinking / inline) parity: the collapsed header renders as an outlined
 * pill (accordion-group-header-close), expanding wraps header + body in a
 * bordered card (accordion-group-open) whose text keeps a left guide line
 * (accordion-deep-thinking). The status icon sits in the chained step-icon
 * slot — spinner while generating, green check when finished — and a
 * "Thinking..." title gets the soft-light shimmer sweep while streaming.
 */
import { useEffect, useState } from "react";

interface ReasoningBlockProps {
  text: string;
  done: boolean;
  /** Step-chain flags — hide the upstream / downstream connector stub. */
  stepFirst?: boolean;
  stepLast?: boolean;
}

export default function ReasoningBlock({ text, done, stepFirst, stepLast }: ReasoningBlockProps) {
  const [open, setOpen] = useState(!done);

  // Console Thinking parity: auto-collapse when reasoning finishes
  // (defaultOpen: loading ? defaultOpen : false).
  useEffect(() => {
    if (done) setOpen(false);
  }, [done]);
  const classes = [
    "reasoning-block",
    open ? "open" : "",
    stepFirst ? "step-first" : "",
    stepLast ? "step-last" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes}>
      <button type="button" className="reasoning-header" onClick={() => setOpen((v) => !v)}>
        <span className="step-icon">
          {done ? (
            <i className="fa-solid fa-circle-check step-icon-success" />
          ) : (
            <i className="fa-solid fa-spinner fa-spin step-icon-loading" />
          )}
        </span>
        <span className={`reasoning-title${done ? "" : " reasoning-title-shimmer"}`}>
          Thinking
        </span>
        <i className={`fa-solid fa-chevron-${open ? "up" : "down"} step-caret`} />
      </button>
      {open && (
        <div className="reasoning-body">
          <div className="reasoning-body-text">{text}</div>
        </div>
      )}
    </div>
  );
}
