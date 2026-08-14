/**
 * SessionDrawer — left rail listing console-channel chats: search, new chat,
 * pinned section, inline rename (double click), pin toggle and delete.
 * Same data scope as the backend session drawer (channel=console per user).
 */
import { useMemo, useState } from "react";
import type { ChatSpecView } from "../../api/modules";

function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour} 小时前`;
  const day = Math.floor(hour / 24);
  if (day < 7) return `${day} 天前`;
  return new Date(t).toLocaleDateString("zh-CN");
}

interface SessionDrawerProps {
  chats: ChatSpecView[];
  activeId: string;
  onSelect: (chat: ChatSpecView) => void;
  onCreate: () => void;
  onRename: (chat: ChatSpecView, name: string) => void;
  onTogglePin: (chat: ChatSpecView) => void;
  onDelete: (chat: ChatSpecView) => void;
}

export default function SessionDrawer({
  chats,
  activeId,
  onSelect,
  onCreate,
  onRename,
  onTogglePin,
  onDelete,
}: SessionDrawerProps) {
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState("");
  const [draft, setDraft] = useState("");

  const { pinned, recent } = useMemo(() => {
    const filtered = chats.filter((c) => (c.name ?? "").toLowerCase().includes(query.toLowerCase()));
    const sorted = [...filtered].sort((a, b) => {
      const ta = new Date(a.updated_at ?? 0).getTime() || 0;
      const tb = new Date(b.updated_at ?? 0).getTime() || 0;
      return tb - ta;
    });
    return {
      pinned: sorted.filter((c) => c.pinned),
      recent: sorted.filter((c) => !c.pinned),
    };
  }, [chats, query]);

  const commitRename = (chat: ChatSpecView) => {
    const value = draft.trim();
    setEditingId("");
    if (value && value !== chat.name) {
      onRename(chat, value);
    }
  };

  const row = (chat: ChatSpecView) => {
    const active = chat.id === activeId;
    const editing = editingId === chat.id;
    return (
      <div
        key={chat.id}
        className={`chat-session-row${active ? " active" : ""}`}
        onClick={() => !editing && onSelect(chat)}
        onDoubleClick={() => {
          setEditingId(chat.id);
          setDraft(chat.name ?? "");
        }}
        title="双击重命名"
      >
        {editing ? (
          <input
            className="chat-session-rename"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => commitRename(chat)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                commitRename(chat);
              }
              if (e.key === "Escape") {
                setEditingId("");
              }
            }}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <>
            <div className="chat-session-main">
              <div className="chat-session-name">{chat.name || "未命名会话"}</div>
              <div className="chat-session-time">{relativeTime(chat.updated_at)}</div>
            </div>
            {chat.status === "running" && <span className="chat-session-live" />}
            <div className="chat-session-actions" onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                title={chat.pinned ? "取消置顶" : "置顶"}
                onClick={() => onTogglePin(chat)}
              >
                <i className={`fa-${chat.pinned ? "solid" : "regular"} fa-thumbtack`} />
              </button>
              <button type="button" title="删除会话" className="danger" onClick={() => onDelete(chat)}>
                <i className="fa-regular fa-trash-can" />
              </button>
            </div>
          </>
        )}
      </div>
    );
  };

  return (
    <div className="chat-session-drawer">
      <div className="chat-session-top">
        <button type="button" className="chat-new-btn" onClick={onCreate}>
          <i className="fa-solid fa-plus" /> 新对话
        </button>
        <div className="chat-session-search">
          <i className="fa-solid fa-magnifying-glass" />
          <input
            value={query}
            placeholder="搜索会话"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>
      <div className="chat-session-list">
        {pinned.length > 0 && (
          <>
            <div className="chat-session-group">置顶</div>
            {pinned.map(row)}
          </>
        )}
        {recent.length > 0 && (
          <>
            <div className="chat-session-group">最近</div>
            {recent.map(row)}
          </>
        )}
        {pinned.length === 0 && recent.length === 0 && (
          <div className="chat-session-empty">
            {query ? "没有匹配的会话" : "还没有对话，点击上方新建"}
          </div>
        )}
      </div>
    </div>
  );
}
