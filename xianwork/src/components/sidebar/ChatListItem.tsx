/**
 * ChatListItem — one chat row inside the sidebar tree.
 *
 * Highlights the active chat (bold via `.active`) with a relative
 * timestamp, opens the context menu on right-click AND on the hover
 * ellipsis button (competitor shot: `...` / archive / pin), and renders a
 * checkbox while batch mode is on (disabled for running chats).
 * Renaming swaps the title for an inline input committed on Enter/blur
 * — controlled through `renaming` so the context menu can trigger it.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ChatSpecView } from "../../api/modules";
import { relativeTime } from "../../lib/relativeTime";

/** Anchor for the shared anchored context menu (viewport coordinates). */
export interface MenuAnchor {
  x: number;
  y: number;
}

export interface ChatListItemProps {
  chat: ChatSpecView;
  active: boolean;
  batchMode: boolean;
  checked: boolean;
  /** Inline rename editor visibility (driven by the context menu). */
  renaming: boolean;
  onRenamingChange: (chatId: string, renaming: boolean) => void;
  onToggleCheck: (chatId: string, checked: boolean) => void;
  /** Right-click and hover-ellipsis both open the six-entry menu. */
  onOpenMenu: (chat: ChatSpecView, anchor: MenuAnchor) => void;
  onRenamed: (chatId: string, name: string) => void;
  /** Hover archive button (single chat, skips running server-side). */
  onArchive: (chat: ChatSpecView) => void;
  /** Hover pin button — toggles ChatSpec.pinned via PUT /chats/{id}. */
  onTogglePin: (chat: ChatSpecView) => void;
}

export default function ChatListItem({
  chat,
  active,
  batchMode,
  checked,
  renaming,
  onRenamingChange,
  onToggleCheck,
  onOpenMenu,
  onRenamed,
  onArchive,
  onTogglePin,
}: ChatListItemProps) {
  const navigate = useNavigate();
  const [draft, setDraft] = useState(chat.name || "");
  const inputRef = useRef<HTMLInputElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  const running = chat.status === "running";
  const pinned = !!chat.pinned;

  useEffect(() => {
    if (renaming) {
      setDraft(chat.name || "");
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [renaming, chat.name]);

  const commitRename = () => {
    const next = draft.trim();
    onRenamingChange(chat.id, false);
    if (next && next !== chat.name) {
      onRenamed(chat.id, next);
    }
  };

  const openMenuFromButton = () => {
    const rect = moreRef.current?.getBoundingClientRect();
    onOpenMenu(chat, {
      x: rect ? Math.max(8, rect.left - 180) : 0,
      y: rect ? rect.bottom + 4 : 0,
    });
  };

  return (
    <li className="sidebar-chat-item">
      <div
        className={`nav-item chat-row${active ? " active" : ""}`}
        onContextMenu={(e) => {
          if (!batchMode) {
            e.preventDefault();
            onOpenMenu(chat, { x: e.clientX, y: e.clientY });
          }
        }}
        onClick={() => {
          if (batchMode && !running) {
            onToggleCheck(chat.id, !checked);
            return;
          }
          navigate(`/chat?chat=${chat.id}`);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !batchMode && !renaming) {
            navigate(`/chat?chat=${chat.id}`);
          }
        }}
      >
        <div className="nav-item-left">
          {batchMode ? (
            <input
              type="checkbox"
              className="chat-check"
              checked={checked}
              disabled={running}
              title={running ? "回复中的任务不可选择" : undefined}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => onToggleCheck(chat.id, e.target.checked)}
              aria-label={`选择 ${chat.name || "任务"}`}
            />
          ) : renaming ? (
            <input
              ref={inputRef}
              className="chat-rename-input"
              value={draft}
              maxLength={60}
              onChange={(e) => setDraft(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onBlur={commitRename}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  commitRename();
                } else if (e.key === "Escape") {
                  onRenamingChange(chat.id, false);
                }
              }}
              aria-label="重命名任务"
            />
          ) : (
            <>
              {pinned && (
                <i
                  className="fa-solid fa-thumbtack chat-pinned-icon"
                  title="已置顶"
                />
              )}
              <span>{chat.name || "新任务"}</span>
            </>
          )}
          {running && !renaming && (
            <i
              className="fa-solid fa-spinner fa-spin chat-running-icon"
              title="回复中"
            />
          )}
        </div>
        {renaming ? null : batchMode ? (
          <div className="nav-item-right">
            {relativeTime(chat.updated_at)}
          </div>
        ) : (
          <>
            <div className="nav-item-right">
              {relativeTime(chat.updated_at)}
            </div>
            <div className="chat-item-actions">
              <button
                ref={moreRef}
                type="button"
                className="chat-item-action-btn"
                title="更多操作"
                aria-label={`更多操作 ${chat.name || "任务"}`}
                onClick={(e) => {
                  e.stopPropagation();
                  openMenuFromButton();
                }}
              >
                <i className="fa-solid fa-ellipsis" />
              </button>
              <button
                type="button"
                className="chat-item-action-btn"
                title="归档"
                aria-label={`归档 ${chat.name || "任务"}`}
                disabled={running}
                onClick={(e) => {
                  e.stopPropagation();
                  onArchive(chat);
                }}
              >
                <i className="fa-solid fa-box-archive" />
              </button>
              <button
                type="button"
                className={`chat-item-action-btn${pinned ? " pinned" : ""}`}
                title={pinned ? "取消置顶" : "置顶"}
                aria-label={`${pinned ? "取消置顶" : "置顶"} ${chat.name || "任务"}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onTogglePin(chat);
                }}
              >
                <i
                  className={`fa-${pinned ? "solid" : "regular"} fa-thumbtack`}
                />
              </button>
            </div>
          </>
        )}
      </div>
    </li>
  );
}
