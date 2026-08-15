/*
 * Chat — full parity with the backend chat page: model selector in the
 * header, streaming timeline with markdown / reasoning / tool cards, and
 * the complete composer (attachments, speech, slash commands, mode /
 * approval / agent selectors, char counter). The session list lives in
 * the sidebar task menu (MainLayout), not inside this page.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
import { historyToTimeline, type TurnUsage } from "../chat/protocol";

// --- Context-ring usage persistence ---------------------------------------
// The console restores its turn-usage snapshot from history message metadata
// (extractLatestSnapshotFromCards) and seeds a zeroed one on "/new", so its
// ring never vanishes. The xian wire protocol carries context usage only in
// the live turn_usage SSE event — history has none — so the last snapshot of
// each chat is cached locally and reseeded when the chat reloads.
const usageStorageKey = (user: string, chatId: string) =>
  `xianwork_turn_usage_${user}_${chatId}`;

function readStoredUsage(user: string, chatId: string): TurnUsage | null {
  if (!user || !chatId) return null;
  try {
    const raw = localStorage.getItem(usageStorageKey(user, chatId));
    return raw ? (JSON.parse(raw) as TurnUsage) : null;
  } catch {
    return null;
  }
}

function writeStoredUsage(user: string, chatId: string, usage: TurnUsage) {
  if (!user || !chatId) return;
  try {
    localStorage.setItem(usageStorageKey(user, chatId), JSON.stringify(usage));
  } catch {
    /* quota / privacy mode — the ring just loses persistence */
  }
}

/** Console handleNewCommand fallback window (max_input_length default). */
const DEFAULT_CONTEXT_SIZE = 131072;

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
  /** Last cached snapshot for the active chat (usage persistence above). */
  const [storedUsage, setStoredUsage] = useState<TurnUsage | null>(null);
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

  // Latest turn usage from the live timeline (null before the first reply
  // of this mount — the cached snapshot covers that gap below).
  const lastUsage = useMemo<TurnUsage | null>(() => {
    for (let i = items.length - 1; i >= 0; i--) {
      const it = items[i];
      if (it.kind === "usage") {
        return it.usage;
      }
    }
    return null;
  }, [items]);

  // Reseed the ring from the per-chat cache when switching sessions: the
  // live timeline only carries usage until its first reply arrives.
  useEffect(() => {
    setStoredUsage(readStoredUsage(username, activeId));
  }, [username, activeId]);

  // Cache every live snapshot so the ring survives reloads (write-through).
  useEffect(() => {
    if (lastUsage && activeChat) {
      writeStoredUsage(username, activeChat.id, lastUsage);
    }
  }, [username, activeChat, lastUsage]);

  const handleCreate = async () => {
    try {
      const chat = await chatApi.create("新对话", username);
      // Console handleNewCommand parity: seed a zeroed snapshot so the ring
      // stays visible (0%) on the fresh session instead of vanishing.
      const contextSize =
        lastUsage?.context_size ??
        storedUsage?.context_size ??
        DEFAULT_CONTEXT_SIZE;
      writeStoredUsage(username, chat.id, {
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
        estimated_tokens: 0,
        context_size: contextSize,
        context_usage_ratio: 0,
      });
      await loadChats();
      navigate(`/chat?chat=${chat.id}`);
    } catch {
      toast.error("创建会话失败");
    }
  };

  // Console parity: the context-ring "压缩" entry submits the /compact
  // system command over the same /console/chat SSE plane; the backend
  // summarizes and shrinks the running context of this session.
  const handleCompact = useCallback(() => {
    if (!activeChat || streaming) {
      return;
    }
    void send("/compact", activeChat);
  }, [activeChat, streaming, send]);

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

  return (
    <div className="view active">
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

        {/* Console parity: the sender docks in the layout flow below the
         * scroller (flex-shrink: 0) — never absolute — so it can no longer
         * be pushed off-screen by a long timeline or a tall composer. */}
        <div className="chat-input-dock">
          <ChatComposer
            value={input}
            onChange={setInput}
            onSend={handleSend}
            onStop={activeChat ? () => void stop(activeChat) : undefined}
            busy={streaming}
            disabled={!activeChat}
            usage={lastUsage ?? storedUsage}
            onCompact={handleCompact}
            onNewChat={() => void handleCreate()}
            attachments={attachments}
            onAttachmentsChange={setAttachments}
          />
        </div>
      </div>
    </div>
  );
}
