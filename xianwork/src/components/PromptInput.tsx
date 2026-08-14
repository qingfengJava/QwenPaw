/**
 * PromptInput — the prototype's three-part input-wrapper, React-ified
 * (prototype L343-477 + JS L1582-1596):
 *
 *   ┌ textarea.main-input (auto-grow) ─────────────┐
 *   │ input-toolbar: [+] … [Auto ▾][mic][send ●]   │
 *   │ input-footer:  context-tags row               │
 *   └───────────────────────────────────────────────┘
 *
 * `variant="home"`   → the centred Home launcher card
 * `variant="detail"` → fixed-bottom bar in ProjectDetail/Chat (compact)
 */
import { useRef, useState } from "react";

export interface ContextTag {
  icon?: string;
  label: string;
  onClick?: () => void;
}

export interface PromptInputProps {
  variant?: "home" | "detail";
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  onSend: (value: string) => void;
  disabled?: boolean;
  busy?: boolean;
  contextTags?: ContextTag[];
}

export default function PromptInput({
  variant = "home",
  placeholder,
  value,
  onChange,
  onSend,
  disabled = false,
  busy = false,
  contextTags = [],
}: PromptInputProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [focused, setFocused] = useState(false);

  const hasText = value.trim().length > 0;

  const handleInput = (next: string) => {
    onChange(next);
    // Prototype auto-resize behaviour (L1583-1587).
    const el = ref.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight}px`;
    }
  };

  const handleSend = () => {
    if (!hasText || disabled || busy) {
      return;
    }
    onSend(value.trim());
  };

  return (
    <div className="input-wrapper" data-variant={variant}>
      <textarea
        ref={ref}
        className="main-input"
        style={variant === "detail" ? { minHeight: 24, height: 24 } : undefined}
        placeholder={placeholder}
        value={value}
        disabled={disabled || busy}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChange={(e) => handleInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
          }
        }}
      />

      <div className="input-toolbar">
        <div className="toolbar-left">
          <button
            type="button"
            className="toolbar-btn"
            aria-label="添加附件"
            title="添加附件"
          >
            <i
              className="fa-solid fa-plus"
              style={{ fontSize: variant === "detail" ? 18 : 20 }}
            />
          </button>
        </div>
        <div className="toolbar-right">
          <div className="auto-dropdown" title="选择执行模式">
            <i className="fa-solid fa-robot" /> Auto{" "}
            <i className="fa-solid fa-chevron-down" style={{ fontSize: 10 }} />
          </div>
          <button
            type="button"
            className="toolbar-btn"
            aria-label="语音输入"
            title="语音输入"
          >
            <i className="fa-solid fa-microphone" style={{ fontSize: 15 }} />
          </button>
          <button
            type="button"
            className={`send-btn-circle${hasText || busy ? " active" : ""}`}
            onClick={handleSend}
            disabled={disabled || busy}
            aria-label="发送"
            title={busy ? "生成中…" : "发送"}
            style={{
              cursor: hasText && !busy && !disabled ? "pointer" : "default",
            }}
          >
            {busy ? (
              <i className="fa-solid fa-spinner fa-spin" style={{ fontSize: 12 }} />
            ) : (
              <i
                className="fa-solid fa-paper-plane"
                style={{ fontSize: 12, marginLeft: -2 }}
              />
            )}
          </button>
        </div>
      </div>

      {contextTags.length > 0 && (
        <div
          className="input-footer"
          style={
            variant === "detail" ? { marginTop: 12, paddingTop: 8 } : undefined
          }
        >
          {contextTags.map((tag) => (
            <div
              key={tag.label}
              className="context-tag"
              onClick={tag.onClick}
              title={focused ? undefined : tag.label}
            >
              {tag.icon && <i className={tag.icon} />}
              <span>{tag.label}</span>
              <i className="fa-solid fa-chevron-down" style={{ fontSize: 10 }} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
