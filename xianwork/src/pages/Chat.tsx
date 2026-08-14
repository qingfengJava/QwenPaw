/**
 * Chat — full parity with the backend chat page: session drawer (console
 * channel scope), model selector in the header, streaming timeline with
 * markdown / reasoning / tool cards, and the complete composer (attachments,
 * speech, slash commands, mode / approval / agent selectors, char counter).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import Modal from "../components/Modal";
import SessionDrawer from "../components/chat/SessionDrawer";
import TimelineList from "../components/chat/TimelineList";
import ModelSelector from "../components/chat/ModelSelector";
import ChatComposer, {
  type PendingAttachment,
} from "../components/chat/ChatComposer";
import { KICKOFF_ATTACHMENTS_KEY } from "./Home";
import { chatApi } from "../api/modules";
import type { ChatSpecView } from "../api/modules";
import { useAuthStore } from "../stores/auth";
import { useChatPrefs } from "../stores/chatPrefs";
import { useToast } from "../components/Toast";
import { useChatStream } from "../chat/useChatStream";
import { historyToTimeline } from "../chat/protocol";

export default function ChatPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const activeId = params.get("chat") ?? "";
  const kickoff = params.get("kickoff") ?? "";
  const username = useAuthStore((s) => s.username);
  const selectedAgent = useChatPrefs((s) => s.selectedAgent);
  const toast = useToast();

  const [chats, setChats] = useState<ChatSpecView[]>([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [pendingDelete, setPendingDelete] = useState<ChatSpecView | null>(null);
  const { items, streaming, send, stop, reset } = useChatStream();
  const kickoffRef = useRef("");
  const kickoffAttachmentsRef = useRef<PendingAttachment[]>([]);
  const historyLoadedRef = useRef("");

  const activeChat = useMemo(
    () => chats.find((c) => c.id === activeId) ?? null,
    [chats, activeId],
  );

  const loadChats = useCallback(async () => {
    try {
      setChats(await chatApi.list(username));
    } catch {
      setChats([]);
    }
  }, [username]);

  // Initial list load; auto-select the most recent chat when none is active.
  useEffect(() => {
    void loadChats().then(() => {
      // Populated after the state settles in the next render tick.
    });
  }, [loadChats]);

  useEffect(() => {
    if (!activeId && chats.length > 0) {
      const latest = [...chats].sort(
        (a, b) =>
          (new Date(b.updated_at ?? 0).getTime() || 0) -
          (new Date(a.updated_at ?? 0).getTime() || 0),
      )[0];
      navigate(`/chat?chat=${latest.id}`, { replace: true });
    }
  }, [activeId, chats, navigate]);

  // Load history when switching chats (once per chat id). Kickoff sending
  // is chained AFTER the history reset — a parallel send used to race the
  // reset, which wiped the timeline mid-stream and aborted the fetch.
  useEffect(() => {
    if (!activeChat || historyLoadedRef.current === activeChat.id) {
      return;
    }
    historyLoadedRef.current = activeChat.id;
    kickoffRef.current = kickoff;
    // Home hands attachments over through sessionStorage; consume once.
    let kickoffAttachments: PendingAttachment[] = [];
    try {
      const raw = sessionStorage.getItem(KICKOFF_ATTACHMENTS_KEY);
      if (raw) {
        kickoffAttachments = JSON.parse(raw) as PendingAttachment[];
        sessionStorage.removeItem(KICKOFF_ATTACHMENTS_KEY);
      }
    } catch {
      sessionStorage.removeItem(KICKOFF_ATTACHMENTS_KEY);
    }
    kickoffAttachmentsRef.current = kickoffAttachments;
    void chatApi
      .history(activeChat.id)
      .then((h) => {
        reset(historyToTimeline(h));
        window.setTimeout(() => void loadChats(), 0);
        const text = kickoffRef.current;
        if (text || kickoffAttachmentsRef.current.length > 0) {
          kickoffRef.current = "";
          void send(
            text,
            activeChat,
            kickoffAttachmentsRef.current.length > 0
              ? kickoffAttachmentsRef.current
              : undefined,
          );
          kickoffAttachmentsRef.current = [];
        }
      })
      .catch(() => {
        reset([]);
        const text = kickoffRef.current;
        if (text || kickoffAttachmentsRef.current.length > 0) {
          kickoffRef.current = "";
          void send(
            text,
            activeChat,
            kickoffAttachmentsRef.current.length > 0
              ? kickoffAttachmentsRef.current
              : undefined,
          );
          kickoffAttachmentsRef.current = [];
        }
      });
    if (kickoff) {
      navigate(`/chat?chat=${activeChat.id}`, { replace: true });
    }
  }, [activeChat, kickoff, navigate, reset, loadChats, send]);

  const handleCreate = async () => {
    try {
      const chat = await chatApi.create("新对话", username);
      await loadChats();
      navigate(`/chat?chat=${chat.id}`);
    } catch {
      toast.error("创建会话失败");
    }
  };

  const handleSelect = (chat: ChatSpecView) => {
    if (chat.id !== activeId) {
      navigate(`/chat?chat=${chat.id}`);
    }
  };

  const handleRename = async (chat: ChatSpecView, name: string) => {
    try {
      await chatApi.rename(chat.id, name);
      setChats((prev) => prev.map((c) => (c.id === chat.id ? { ...c, name } : c)));
    } catch {
      toast.error("重命名失败");
    }
  };

  const handleTogglePin = async (chat: ChatSpecView) => {
    try {
      await chatApi.togglePin(chat.id, !chat.pinned);
      setChats((prev) => prev.map((c) => (c.id === chat.id ? { ...c, pinned: !c.pinned } : c)));
    } catch {
      toast.error("操作失败");
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete) {
      return;
    }
    const target = pendingDelete;
    setPendingDelete(null);
    try {
      await chatApi.remove(target.id);
      const rest = chats.filter((c) => c.id !== target.id);
      setChats(rest);
      if (target.id === activeId) {
        reset([]);
        historyLoadedRef.current = "";
        if (rest.length > 0) {
          navigate(`/chat?chat=${rest[0].id}`);
        } else {
          navigate("/chat");
        }
      }
      toast.success("会话已删除");
    } catch {
      toast.error("删除失败");
    }
  };

  const handleSend = (value: string, pending: PendingAttachment[]) => {
    const doSend = (target: ChatSpecView) => {
      setInput("");
      setAttachments([]);
      void send(value, target, pending);
    };
    if (!activeChat) {
      void handleCreate().then(() => {
        // Next render wires the new chat; queue the text into kickoff.
        kickoffRef.current = value;
      });
      return;
    }
    doSend(activeChat);
  };

  // Regenerate: replay the last user question after its assistant turn.
  const lastAssistantKey = useMemo(() => {
    for (let i = items.length - 1; i >= 0; i--) {
      if (items[i].kind === "assistant") return items[i].key;
    }
    return undefined;
  }, [items]);

  const handleRegenerate = useCallback(() => {
    if (!activeChat || streaming) return;
    const lastUser = [...items].reverse().find((it) => it.kind === "user");
    if (lastUser && lastUser.kind === "user") {
      void send(lastUser.text, activeChat);
    }
  }, [activeChat, items, streaming, send]);

  // Latest context ratio feeds the composer ring (0 when no turn yet).
  const contextRatio = useMemo(() => {
    for (let i = items.length - 1; i >= 0; i--) {
      const it = items[i];
      if (it.kind === "usage" && it.usage.context_usage_ratio != null) {
        return it.usage.context_usage_ratio;
      }
    }
    return 0;
  }, [items]);

  return (
    <div className="view active" style={{ flexDirection: "row" }}>
      <SessionDrawer
        chats={chats}
        activeId={activeId}
        onSelect={handleSelect}
        onCreate={() => void handleCreate()}
        onRename={(chat, name) => void handleRename(chat, name)}
        onTogglePin={(chat) => void handleTogglePin(chat)}
        onDelete={(chat) => setPendingDelete(chat)}
      />

      <div className="chat-main">
        <div className="chat-main-header">
          <div className="chat-main-title">
            {activeChat?.name || "新对话"}
            {streaming && (
              <span className="chat-main-live">
                <i className="fa-solid fa-spinner fa-spin" /> 回复中
              </span>
            )}
          </div>
          <ModelSelector agentId={selectedAgent} />
        </div>

        <TimelineList
          items={items}
          streaming={streaming}
          onCopy={(text) => {
            void navigator.clipboard.writeText(text).then(() =>
              toast.success("已复制"),
            );
          }}
          onRegenerate={() => handleRegenerate()}
          regenerateKey={lastAssistantKey}
        />

        <div className="fixed-bottom-input">
          <ChatComposer
            value={input}
            onChange={setInput}
            onSend={handleSend}
            onStop={activeChat ? () => void stop(activeChat) : undefined}
            busy={streaming}
            disabled={!activeChat}
            contextRatio={contextRatio}
            attachments={attachments}
            onAttachmentsChange={setAttachments}
          />
        </div>
      </div>

      <Modal
        open={pendingDelete !== null}
        title="删除会话"
        onClose={() => setPendingDelete(null)}
      >
        <div className="modal-body-text">
          确定删除会话「{pendingDelete?.name}」吗？聊天记录将无法恢复。
        </div>
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={() => setPendingDelete(null)}>
            取消
          </button>
          <button type="button" className="btn-danger" onClick={() => void handleDelete()}>
            删除
          </button>
        </div>
      </Modal>
    </div>
  );
}
