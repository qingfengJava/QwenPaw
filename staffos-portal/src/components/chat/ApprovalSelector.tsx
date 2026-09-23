/**
 * ApprovalSelector — tool-execution approval level (STRICT/SMART/AUTO/OFF),
 * sent as request_context.approval_level on every chat turn. Mirrors the
 * backend composer's shield toggle ("默认权限").
 */
import { useEffect, useRef, useState } from "react";
import {
  APPROVAL_META,
  useChatPrefs,
  type ApprovalLevel,
} from "../../stores/chatPrefs";

const LEVELS: ApprovalLevel[] = ["STRICT", "SMART", "AUTO", "OFF"];

export default function ApprovalSelector() {
  const approvalLevel = useChatPrefs((s) => s.approvalLevel);
  const setApprovalLevel = useChatPrefs((s) => s.setApprovalLevel);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const meta = APPROVAL_META[approvalLevel];

  return (
    <div className="approval-selector" ref={rootRef}>
      <button
        type="button"
        className={`approval-trigger${open ? " open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title={`工具审批：${meta.label} — ${meta.description}`}
      >
        <i className="fa-solid fa-shield-halved" />
        <span>{meta.label}</span>
        <i className="fa-solid fa-chevron-down ms-caret" />
      </button>

      {open && (
        <div className="approval-panel">
          <div className="loop-panel-title">工具执行权限</div>
          {LEVELS.map((level) => {
            const info = APPROVAL_META[level];
            const isActive = level === approvalLevel;
            return (
              <button
                type="button"
                key={level}
                className={`agent-option${isActive ? " active" : ""}`}
                onClick={() => {
                  setApprovalLevel(level);
                  setOpen(false);
                }}
              >
                <span className="agent-option-copy">
                  <span className="agent-option-name">{info.label}</span>
                  <span className="agent-option-desc">{info.description}</span>
                </span>
                {isActive && <i className="fa-solid fa-check ms-check" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
