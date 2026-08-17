/**
 * WorkspaceGroup — one workspace folder row with independently
 * expandable/collapsible nested chats (each row is a ChatListItem).
 * Right-click opens the workspace menu (打开文件夹 / 重命名空间 / 删除空间).
 */
import { useEffect, useRef, useState } from "react";
import type { ChatSpecView, WorkspaceView } from "../../api/modules";
import ChatListItem from "./ChatListItem";
import type { MenuAnchor } from "./ChatListItem";

export interface WorkspaceGroupProps {
  workspace: WorkspaceView;
  activeChatId: string;
  batchMode: boolean;
  checkedIds: Set<string>;
  renamingChatId: string | null;
  /** Controlled folder-row rename editor (opened via workspace context menu). */
  renamingWorkspace: boolean;
  collapsed: boolean;
  onToggleCollapse: (workspaceId: string) => void;
  onToggleCheck: (chatId: string, checked: boolean) => void;
  onChatOpenMenu: (chat: ChatSpecView, anchor: MenuAnchor) => void;
  onChatArchive: (chat: ChatSpecView) => void;
  onChatTogglePin: (chat: ChatSpecView) => void;
  /** Hover + shortcut on the folder row: create a new chat pre-bound
   *  to this workspace (the forward-creation loop). */
  onNewChat: (workspace: WorkspaceView) => void;
  onWorkspaceContextMenu: (e: React.MouseEvent, workspace: WorkspaceView) => void;
  onRenamingChange: (chatId: string, renaming: boolean) => void;
  onRenamed: (chatId: string, name: string) => void;
  onWorkspaceRenamingChange: (workspaceId: string, editing: boolean) => void;
  onWorkspaceRenamed: (workspaceId: string, name: string) => void;
}

export default function WorkspaceGroup({
  workspace,
  activeChatId,
  batchMode,
  checkedIds,
  renamingChatId,
  renamingWorkspace,
  collapsed,
  onToggleCollapse,
  onToggleCheck,
  onChatOpenMenu,
  onChatArchive,
  onChatTogglePin,
  onNewChat,
  onWorkspaceContextMenu,
  onRenamingChange,
  onRenamed,
  onWorkspaceRenamingChange,
  onWorkspaceRenamed,
}: WorkspaceGroupProps) {
  const chats = workspace.chats ?? [];
  const [draft, setDraft] = useState(workspace.name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (renamingWorkspace) {
      setDraft(workspace.name);
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [renamingWorkspace, workspace.name]);

  return (
    <li className="sidebar-workspace-group">
      <div
        className={`nav-item workspace-row${!collapsed ? " expanded" : ""}`}
        onContextMenu={(e) => onWorkspaceContextMenu(e, workspace)}
        onClick={() => !renamingWorkspace && onToggleCollapse(workspace.id)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !renamingWorkspace) {
            onToggleCollapse(workspace.id);
          }
        }}
        title={workspace.dir_path}
      >
        <div className="nav-item-left">
          <i className="fa-regular fa-folder workspace-folder-icon" />
          {renamingWorkspace ? (
            <input
              ref={inputRef}
              className="chat-rename-input"
              value={draft}
              maxLength={60}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={() => {
                onWorkspaceRenamingChange(workspace.id, false);
                const next = draft.trim();
                if (next && next !== workspace.name) {
                  onWorkspaceRenamed(workspace.id, next);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  inputRef.current?.blur();
                } else if (e.key === "Escape") {
                  onWorkspaceRenamingChange(workspace.id, false);
                }
              }}
              aria-label="重命名空间"
            />
          ) : (
            <span className="workspace-name">{workspace.name}</span>
          )}
          {/* Count hugs the folder name (not the row tail) so the right
           * side is a pure action group: [+][▾] — mirroring the section
           * headers above for a consistent visual rhythm. */}
          {!renamingWorkspace && (
            <span className="workspace-count">{chats.length}</span>
          )}
        </div>
        <div className="nav-item-right">
          <button
            type="button"
            className="ws-new-chat-btn"
            title="在此空间新建任务"
            aria-label={`在 ${workspace.name} 新建任务`}
            onClick={(e) => {
              e.stopPropagation();
              onNewChat(workspace);
            }}
          >
            <i className="fa-solid fa-plus" />
          </button>
          {/* Tail chevron: pinned last so the expand-state indicator
           * never shifts when the hover + button fades in. */}
          <i
            className={`fa-solid fa-chevron-${collapsed ? "right" : "down"} workspace-chevron`}
          />
        </div>
      </div>
      {!collapsed && (
        <ul className="workspace-chat-list">
          {chats.map((chat) => (
            <ChatListItem
              key={chat.id}
              chat={chat}
              active={chat.id === activeChatId}
              batchMode={batchMode}
              checked={checkedIds.has(chat.id)}
              renaming={renamingChatId === chat.id}
              onRenamingChange={onRenamingChange}
              onToggleCheck={onToggleCheck}
              onOpenMenu={onChatOpenMenu}
              onArchive={onChatArchive}
              onTogglePin={onChatTogglePin}
              onRenamed={onRenamed}
            />
          ))}
          {chats.length === 0 && (
            <li className="workspace-empty">暂无绑定任务</li>
          )}
        </ul>
      )}
    </li>
  );
}
