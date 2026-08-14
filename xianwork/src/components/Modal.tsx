/**
 * Minimal antd-free Modal — overlay + box + ESC close + click-outside.
 * Vocabulary: .modal-overlay/.modal-box/.modal-header/.modal-body/.modal-footer
 * (see styles/global.css).
 */
import { useEffect } from "react";

export interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  footer?: React.ReactNode;
  width?: number;
  children: React.ReactNode;
}

export default function Modal({
  open,
  title,
  onClose,
  footer,
  width = 480,
  children,
}: ModalProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="modal-box" style={width !== 480 ? { width } : undefined}>
        <div className="modal-header">
          <span>{title}</span>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="关闭"
          >
            <i className="fa-solid fa-xmark" />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}
