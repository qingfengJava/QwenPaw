/*
 * Chat — full parity with the backend chat page: model selector in the
 * header, streaming timeline with markdown / reasoning / tool cards, and
 * the complete composer (attachments, speech, slash commands, mode /
 * approval / agent selectors, char counter).
 *
 * The session list lives in the sidebar tree (SidebarChatTree via the
 * shared chats store); this page never auto-selects a chat. Without
 * `?chat=` it renders an empty-state placeholder guiding users to the
 * sidebar or a brand-new task.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import TimelineList from "../components/chat/TimelineList";
import ModelSelector from "../components/chat/ModelSelector";
import ChatComposer, {
  type PendingAttachment,
} from "../components/chat/ChatComposer";
import Modal from "../components/Modal";
import { KICKOFF_ATTACHMENTS_KEY } from "./Home";
import { chatApi, expertApi, workforceApi } from "../api/modules";
import type { ChatSpecView, ExpertTeam } from "../api/modules";
import { useAuthStore } from "../stores/auth";
import { useChatPrefs } from "../stores/chatPrefs";
import { useAllChats, useChatsStore } from "../stores/chats";
import { useToast } from "../components/Toast";
import { useChatStream } from "../chat/useChatStream";
import { subscribeRunEvents } from "../lib/feedStream";
import { RUN_TERMINAL_STATUSES } from "../lib/runStatus";
import {
  historyToTimeline,
  teamRunItem,
  type TurnUsage,
} from "../chat/protocol";

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

  const chatList = useAllChats();
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  /** Last cached snapshot for the active chat (usage persistence above). */
  const [storedUsage, setStoredUsage] = useState<TurnUsage | null>(null);
  const { items, streaming, send, stop, reset, patch } = useChatStream();
  const kickoffRef = useRef("");
  const kickoffAttachmentsRef = useRef<PendingAttachment[]>([]);
  const historyLoadedRef = useRef("");

  const activeChat = useMemo(
    () => chatList.find((c) => c.id === activeId) ?? null,
    [chatList, activeId],
  );

  // ---- 升级为专家团任务（聊天双态入口的手动通道） ----
  const [escalateOpen, setEscalateOpen] = useState(false);
  const [escalateTeams, setEscalateTeams] = useState<ExpertTeam[]>([]);
  const [escalateTeamId, setEscalateTeamId] = useState("");
  const [escalateBusy, setEscalateBusy] = useState(false);

  /**
   * 打开团队选择弹层。goal 直接取当前输入框文本（升级动作要求用户
   * 先写下任务目标——空目标只会换来澄清挂起，先在前端拦一道）。
   */
  const openEscalate = useCallback(() => {
    if (!input.trim()) {
      toast.info("请先在输入框写下任务目标，再升级为专家团任务");
      return;
    }
    setEscalateTeamId("");
    setEscalateOpen(true);
    expertApi
      .listTeams()
      .then((teams) => setEscalateTeams(teams))
      .catch(() => {
        setEscalateTeams([]);
        toast.error("加载专家团列表失败");
      });
  }, [input, toast]);

  /**
   * 确认升级：POST workforce runs（source_chat_id 关联当前会话）→
   * 时间线插入 team_run 占位卡片（SSE 驱动后续状态刷新）→ 清空输入。
   */
  const confirmEscalate = useCallback(async () => {
    const team = escalateTeams.find((t) => t.id === escalateTeamId);
    if (!team || !activeChat || escalateBusy) {
      return;
    }
    setEscalateBusy(true);
    try {
      const run = await workforceApi.create({
        team_id: team.id,
        goal: input.trim(),
        source_chat_id: activeChat.id,
      });
      setInput("");
      setEscalateOpen(false);
      patch((prev) => [
        ...prev,
        teamRunItem(run.id, team.name, run.status),
      ]);
      toast.success(`已升级为「${team.name}」专家团任务，可随时查看详情`);
    } catch (err) {
      toast.error(`升级失败：${String(err)}`);
    } finally {
      setEscalateBusy(false);
    }
  }, [escalateTeams, escalateTeamId, activeChat, escalateBusy, input, patch, toast]);

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
        window.setTimeout(() => void useChatsStore.getState().reload(), 0);
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
  }, [activeChat, kickoff, navigate, reset, send]);

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
      // Every creation path funnels through here (empty-state button,
      // context-ring 新对话, send-without-chat fallback), so consuming the
      // pending workspace pick HERE closes the loop for all of them — and
      // clears a stale pick before it can leak into a later creation.
      await useChatsStore.getState().applyPendingWorkspace(chat.id);
      await useChatsStore.getState().reload();
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

  // ---- team_run 卡片实时刷新：订阅未终态 run 的 SSE ----
  // 每条事件拉一次 run 详情并 patch 对应卡片的 status/summary（与
  // RunDetail 的"事件触发重载"同模式）；终态后集合收缩自动退订。以
  // join 后的字符串做 effect 依赖，流式打字期间不反复重建订阅。
  const activeRunKey = useMemo(() => {
    const ids = Array.from(
      new Set(
        items
          .filter((it) => it.kind === "team_run" && !RUN_TERMINAL_STATUSES.has(it.status))
          .map((it) => (it.kind === "team_run" ? it.runId : "")),
      ),
    ).filter(Boolean);
    return ids.join(",");
  }, [items]);

  useEffect(() => {
    if (!activeRunKey) {
      return;
    }
    const ids = activeRunKey.split(",");
    const handles = ids.map((runId) =>
      subscribeRunEvents(runId, {
        onEvent: () => {
          workforceApi
            .detail(runId)
            .then((run) => {
              patch((prev) =>
                prev.map((it) =>
                  it.kind === "team_run" && it.runId === runId
                    ? { ...it, status: run.status, summary: run.summary || it.summary }
                    : it,
                ),
              );
            })
            .catch(() => undefined);
        },
      }),
    );
    return () => handles.forEach((h) => h.close());
  }, [activeRunKey, patch]);

  const handleRegenerate = useCallback(() => {
    if (!activeChat || streaming) return;
    const lastUser = [...items].reverse().find((it) => it.kind === "user");
    if (lastUser && lastUser.kind === "user") {
      void send(lastUser.text, activeChat);
    }
  }, [activeChat, items, streaming, send]);

  // No chat selected: the sidebar owns task selection; guide the user
  // there instead of auto-jumping into an arbitrary latest session.
  if (!activeId) {
    return (
      <div className="view active">
        <div className="chat-empty-state">
          <div className="chat-empty-icon">
            <i className="fa-regular fa-comments" />
          </div>
          <h2>助理</h2>
          <p>从左侧选择任务继续对话，或开始一个新任务</p>
          <button
            type="button"
            className="btn-accent"
            onClick={() => void handleCreate()}
          >
            <i className="fa-solid fa-plus" />
            新建任务
          </button>
        </div>
      </div>
    );
  }

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
            chatId={activeChat?.id}
            workspaceDisabled={streaming}
            onEscalateTeam={openEscalate}
          />
        </div>
      </div>

      {/* 升级为专家团任务：团队选择弹层（手动双态入口） */}
      <Modal
        open={escalateOpen}
        title="升级为专家团任务"
        onClose={() => setEscalateOpen(false)}
        width={520}
        footer={
          <button
            type="button"
            className="btn-accent"
            disabled={!escalateTeamId || escalateBusy}
            onClick={() => void confirmEscalate()}
          >
            {escalateBusy ? "创建中…" : "创建并开始编排"}
          </button>
        }
      >
        <div style={{ fontSize: 13, color: "#64748b", marginBottom: 12 }}>
          任务目标将取当前输入框内容，升级后由专家团在后台按 DAG 计划拆解、
          逐节点执行与验收，进度实时回推到本会话卡片。
        </div>
        {escalateTeams.length === 0 && (
          <div className="blank-state">暂无可用专家团</div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {escalateTeams.map((team) => (
            <button
              key={team.id}
              type="button"
              className="list-row-card"
              style={{
                cursor: "pointer",
                textAlign: "left",
                width: "100%",
                fontFamily: "inherit",
                borderColor:
                  escalateTeamId === team.id ? "#2563eb" : undefined,
                borderWidth: escalateTeamId === team.id ? 2 : 1,
              }}
              onClick={() => setEscalateTeamId(team.id)}
            >
              <span className="list-row-main">
                <span className="card-icon" style={{ width: 36, height: 36, fontSize: 14 }}>
                  <i className="fa-solid fa-people-group" />
                </span>
                <span>
                  <span className="list-row-title">{team.name}</span>
                  <span className="list-row-desc">
                    {team.member_count} 名成员
                    {team.description ? ` · ${team.description}` : ""}
                  </span>
                </span>
              </span>
              {escalateTeamId === team.id && (
                <i className="fa-solid fa-circle-check" style={{ color: "#2563eb" }} />
              )}
            </button>
          ))}
        </div>
      </Modal>
    </div>
  );
}
