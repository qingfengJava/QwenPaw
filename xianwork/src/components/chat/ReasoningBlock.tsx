/**
 * ReasoningBlock — collapsible chain-of-thought panel. Collapsed by default
 * once complete (backend chat parity), auto-open look while streaming.
 */
import { useState } from "react";

interface ReasoningBlockProps {
  text: string;
  done: boolean;
}

export default function ReasoningBlock({ text, done }: ReasoningBlockProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`reasoning-block${open ? " open" : ""}`}>
      <button type="button" className="reasoning-header" onClick={() => setOpen((v) => !v)}>
        {done ? (
          <i className="fa-regular fa-lightbulb" />
        ) : (
          <i className="fa-solid fa-spinner fa-spin" />
        )}
        <span>{done ? "已深度思考" : "思考中…"}</span>
        <i className={`fa-solid fa-chevron-${open ? "up" : "down"} reasoning-caret`} />
      </button>
      {open && <div className="reasoning-body">{text}</div>}
    </div>
  );
}
