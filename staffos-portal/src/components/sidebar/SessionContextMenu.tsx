/**
 * SessionContextMenu — right-click menu for sidebar chat rows.
 *
 * Six entries (competitor parity): 批量操作 / 打开文件夹 / 重命名 /
 * 保存到工作空间 / 分享任务 / 删除任务 (danger). Built on the generic
 * `ContextMenu`, which the workspace folder row also reuses with its own
 * entry set (打开文件夹 / 重命名空间 / 删除空间).
 */
import type { ReactNode } from "react";
import { useEffect, useRef } from "react";

export interface ContextMenuEntry {
  key: string;
  label: string;
  icon: string;
  danger?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}

export interface ContextMenuProps {
  anchor: { x: number; y: number } | null;
  entries: ContextMenuEntry[];
  onClose: () => void;
}

/** Anchored menu; closes on outside mousedown / Escape / scroll. */
export function ContextMenu({ anchor, entries, onClose }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!anchor) {
      return;
    }
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onClose);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onClose);
    };
  }, [anchor, onClose]);

  if (!anchor) {
    return null;
  }
  // Keep the menu inside the viewport (menu is ~200x260px).
  const x = Math.min(anchor.x, window.innerWidth - 210);
  const y = Math.min(anchor.y, window.innerHeight - 280);

  return (
    <div
      ref={ref}
      className="context-menu"
      style={{ left: x, top: y }}
      role="menu"
    >
      {entries.map((entry) => (
        <button
          key={entry.key}
          type="button"
          className={`context-menu-item${entry.danger ? " danger" : ""}`}
          disabled={entry.disabled}
          onClick={() => {
            onClose();
            entry.onClick?.();
          }}
          role="menuitem"
        >
          <i className={entry.icon} />
          <span>{entry.label}</span>
        </button>
      ))}
    </div>
  );
}

export interface SessionContextMenuProps {
  anchor: { x: number; y: number } | null;
  chatName: string;
  onClose: () => void;
  onBatchMode: () => void;
  onOpenFolder: () => void;
  onRename: () => void;
  onSaveToWorkspace: () => void;
  onShare: () => void;
  onDelete: () => void;
}

export default function SessionContextMenu({
  anchor,
  chatName,
  onClose,
  onBatchMode,
  onOpenFolder,
  onRename,
  onSaveToWorkspace,
  onShare,
  onDelete,
}: SessionContextMenuProps): ReactNode {
  const entries: ContextMenuEntry[] = [
    {
      key: "batch",
      label: "批量操作",
      icon: "fa-regular fa-square-check",
      onClick: onBatchMode,
    },
    {
      key: "open-folder",
      label: "打开文件夹",
      icon: "fa-regular fa-folder-open",
      onClick: onOpenFolder,
    },
    {
      key: "rename",
      label: "重命名",
      icon: "fa-regular fa-pen-to-square",
      onClick: onRename,
    },
    {
      key: "save-to-workspace",
      label: "保存到工作空间",
      icon: "fa-solid fa-box-archive",
      onClick: onSaveToWorkspace,
    },
    {
      key: "share",
      label: "分享任务",
      icon: "fa-regular fa-share-from-square",
      onClick: onShare,
    },
    {
      key: "delete",
      label: "删除任务",
      icon: "fa-regular fa-trash-can",
      danger: true,
      onClick: onDelete,
    },
  ];
  return (
    <ContextMenu
      anchor={anchor}
      entries={entries}
      onClose={onClose}
      key={chatName}
    />
  );
}
