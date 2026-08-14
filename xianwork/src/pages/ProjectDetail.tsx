/**
 * ProjectDetail — prototype project-detail view (L1213-1534):
 * - Top nav: breadcrumb + 「邀请」btn-black (opens the invite drawer)
 * - Four tabs: 动态 (SSE feed + comments) / 计划 (four-column kanban with
 *   HTML5 drag & drop) / 任务 (list) / 资产 (shared chats)
 * - Fixed-bottom PromptInput streaming the project-shared AI
 *   (`project:{pid}` owner, shared memory)
 * - Right 320px config panel: 指令 / 连接器 / 专家 / 技能 / 自动化
 *
 * Data logic lives in hooks/useProjectDetail (moved verbatim + extended).
 */
import { useCallback, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import PromptInput from "../components/PromptInput";
import Modal from "../components/Modal";
import ConfigBlock from "../components/config/ConfigBlock";
import BoundItem from "../components/config/BoundItem";
import FeedItem from "../components/feed/FeedItem";
import type { FeedItemView } from "../components/feed/FeedItem";
import KanbanColumn from "../components/kanban/KanbanColumn";
import { COLUMN_META } from "../components/kanban/TaskCard";
import InviteModal from "../components/project/InviteModal";
import { useToast } from "../components/Toast";
import { useProjectDetail } from "../hooks/useProjectDetail";
import {
  automationApi,
  bindingApi,
  projectApi,
  taskApi,
} from "../api/modules";
import type { FeedEvent, Task } from "../api/modules";

const KIND_LABEL: Record<string, string> = {
  project_created: "创建了项目",
  project_updated: "更新了项目",
  task_created: "创建了事项并指派了你",
  task_status: "变更了事项状态",
  task_updated: "更新了事项",
  comment: "发布留言",
  ai_message: "向项目 AI 发起任务",
  ai_reply: "项目 AI 完成回复",
  member_joined: "加入了项目",
  member_left: "退出了项目",
  binding_added: "为项目添加了资源配置",
  binding_removed: "移除了项目资源",
  automation_created: "创建了项目自动化",
  automation_removed: "删除了项目自动化",
};

const TABS = [
  { key: "feed", label: "动态" },
  { key: "kanban", label: "计划" },
  { key: "tasks", label: "任务" },
  { key: "assets", label: "资产" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

function toFeedView(event: FeedEvent): FeedItemView {
  const isComment = event.kind === "comment";
  const payload = event.payload ?? {};
  return {
    id: event.id,
    actor: event.actor === "local" ? "本地用户" : event.actor,
    verb: KIND_LABEL[event.kind] ?? event.kind,
    target: isComment
      ? String(payload.text ?? "")
      : String(
          payload.title ??
            payload.name ??
            payload.ref_id ??
            (payload.text ? String(payload.text).slice(0, 80) : event.kind),
        ),
    boxIcon: isComment
      ? "fa-solid fa-comment"
      : event.kind.startsWith("automation")
        ? "fa-regular fa-clock"
        : event.kind.startsWith("binding")
          ? "fa-solid fa-plug"
          : "fa-regular fa-square-check",
    wrapText: isComment,
    createdAt: event.created_at,
  };
}

export default function ProjectDetailPage() {
  const toast = useToast();
  const notify = useCallback(
    (kind: "error" | "success" | "info", text: string) => {
      toast[kind](text);
    },
    [toast],
  );
  const [params, setParams] = useSearchParams();
  const routeParams = useParams();
  const projectId = routeParams.projectId ?? "";
  const {
    project,
    tasks,
    feed,
    members,
    experts,
    teams,
    bindings,
    automations,
    connectors,
    skills,
    chats,
    aiReply,
    streaming,
    canEdit,
    reload,
    handleMove,
    handleBind,
    sendToProjectAI,
  } = useProjectDetail(projectId, notify);

  const tab = (params.get("tab") as TabKey) || "feed";
  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [aiInput, setAiInput] = useState("");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [newTaskStatus, setNewTaskStatus] = useState<Task["status"]>("todo");
  const [automationOpen, setAutomationOpen] = useState(false);
  const [autoName, setAutoName] = useState("");
  const [autoSchedule, setAutoSchedule] = useState("0 9 * * *");
  const [autoPrompt, setAutoPrompt] = useState("");
  const [editingInstructions, setEditingInstructions] = useState(false);
  const [instructionsDraft, setInstructionsDraft] = useState("");

  const pid = projectId;
  const setTab = (key: TabKey) => setParams({ tab: key }, { replace: true });

  const feedViews = useMemo(() => feed.map(toFeedView), [feed]);

  const bindingOptions = useMemo(
    () => [
      ...experts.map((e) => ({ value: `expert:${e.id}`, label: `专家 · ${e.name}` })),
      ...teams.map((t) => ({
        value: `expert_team:${t.id}`,
        label: `专家团 · ${t.name}`,
      })),
    ],
    [experts, teams],
  );

  const boundConnectors = bindings.filter((b) => b.kind === "connector");
  const boundSkills = bindings.filter((b) => b.kind === "skill");

  if (!project) {
    return <div className="loading-state">加载中…</div>;
  }

  const handleComment = async () => {
    if (!comment.trim()) return;
    await projectApi.comment(pid, comment.trim());
    setComment("");
    setCommentOpen(false);
    reload();
  };

  const handleAddTask = async () => {
    if (!newTaskTitle.trim() || !canEdit) return;
    try {
      await taskApi.create(pid, { title: newTaskTitle.trim(), status: newTaskStatus });
      setNewTaskTitle("");
      setNewTaskOpen(false);
      reload();
    } catch (err) {
      notify("error", String(err));
    }
  };

  const handleSaveInstructions = async () => {
    try {
      await projectApi.update(pid, { instructions: instructionsDraft });
      setEditingInstructions(false);
      notify("success", "项目指令已保存");
      reload();
    } catch (err) {
      notify("error", String(err));
    }
  };

  const handleAddBinding = async (kind: "connector" | "skill", refId: string) => {
    try {
      await bindingApi.add(pid, { kind, ref_id: refId });
      notify("success", "已添加到项目");
      reload();
    } catch (err) {
      notify("error", String(err));
    }
  };

  const handleRemoveBinding = async (bindingId: string) => {
    try {
      await bindingApi.remove(pid, bindingId);
      reload();
    } catch (err) {
      notify("error", String(err));
    }
  };

  const handleCreateAutomation = async () => {
    if (!autoName.trim() || !autoSchedule.trim()) {
      notify("info", "请填写名称与执行时间");
      return;
    }
    try {
      await automationApi.create(pid, {
        name: autoName.trim(),
        schedule: autoSchedule.trim(),
        prompt: autoPrompt.trim(),
      });
      setAutoName("");
      setAutoPrompt("");
      setAutoSchedule("0 9 * * *");
      setAutomationOpen(false);
      notify("success", "自动化已创建");
      reload();
    } catch (err) {
      notify("error", String(err));
    }
  };

  return (
    <div className="view active">
      <div className="project-detail-layout">
        {/* top nav (prototype L1214-1221) */}
        <div className="detail-top-nav">
          <div className="breadcrumb">
            <i className="fa-regular fa-folder" />
            <span>项目 /</span>
            <strong>{project.name}</strong>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {project.member_role || "访客"}
            </span>
          </div>
          <button
            type="button"
            className="btn-black"
            onClick={() => setInviteOpen(true)}
          >
            邀请
          </button>
        </div>

        {/* tabs (prototype L1223-1228) */}
        <div className="detail-tabs-bar">
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`detail-tab${tab === item.key ? " active" : ""}`}
              onClick={() => setTab(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="detail-body">
          <div className="detail-main-area">
            {/* ---- 动态 tab (prototype L1234-1301) ---- */}
            {tab === "feed" && (
              <div className="feed-container">
                <div className="feed-header">
                  <button
                    type="button"
                    className="btn-black"
                    onClick={() => setCommentOpen(true)}
                  >
                    <i className="fa-solid fa-plus" /> 发布留言
                  </button>
                  <div className="filter-toggle">
                    <div className="filter-option active">与我相关</div>
                    <div className="filter-option">成员动态</div>
                  </div>
                </div>
                {feedViews.map((event) => (
                  <FeedItem key={event.id} event={event} />
                ))}
                {feedViews.length === 0 && (
                  <div className="blank-state">暂无动态，发布第一条留言吧</div>
                )}
                <div className="end-message">没有更多了</div>
              </div>
            )}

            {/* ---- 计划 tab (prototype L1304-1442) ---- */}
            {tab === "kanban" && (
              <div className="kanban-container">
                <div className="kanban-toolbar">
                  <div className="kanban-toolbar-left">
                    <div className="kanban-scope-pill">
                      <i className="fa-solid fa-table-list" /> 全部{" "}
                      <i
                        className="fa-solid fa-chevron-down"
                        style={{ fontSize: 10, marginLeft: 4 }}
                      />
                    </div>
                    {canEdit && (
                      <button
                        type="button"
                        className="toolbar-btn"
                        title="添加事项"
                        onClick={() => {
                          setNewTaskStatus("todo");
                          setNewTaskOpen(true);
                        }}
                      >
                        <i className="fa-solid fa-plus" />
                      </button>
                    )}
                  </div>
                  <div className="kanban-toolbar-right">
                    <i className="fa-solid fa-filter" title="筛选" />
                    <i className="fa-solid fa-magnifying-glass" title="搜索" />
                    <div className="kanban-toolbar-divider" />
                    <button
                      type="button"
                      className="btn-plain"
                      style={{ padding: "4px 12px", fontSize: 12 }}
                      onClick={() => {
                        setNewTaskStatus("todo");
                        setNewTaskOpen(true);
                      }}
                    >
                      添加
                    </button>
                  </div>
                </div>

                <div className="kanban-board">
                  {(Object.keys(COLUMN_META) as Task["status"][]).map(
                    (status) => (
                      <KanbanColumn
                        key={status}
                        status={status}
                        tasks={tasks.filter((t) => t.status === status)}
                        canEdit={canEdit}
                        onDropTask={(taskId, next) =>
                          void handleMove(taskId, next)
                        }
                        onAdd={(status2) => {
                          setNewTaskStatus(status2);
                          setNewTaskOpen(true);
                        }}
                      />
                    ),
                  )}
                </div>
              </div>
            )}

            {/* ---- 任务 tab ---- */}
            {tab === "tasks" && (
              <div className="feed-container">
                {tasks.map((task) => (
                  <div key={task.id} className="task-row">
                    <span
                      className={`task-row-title${task.status === "done" ? " task-completed" : ""}`}
                    >
                      {task.title}
                    </span>
                    <span className="task-status">
                      <div className={`status-dot ${COLUMN_META[task.status].dot}`} />
                      {COLUMN_META[task.status].label}
                      <span className="task-assignee-flag">
                        {task.assignee ?? "无"}
                      </span>
                    </span>
                  </div>
                ))}
                {tasks.length === 0 && (
                  <div className="blank-state">暂无任务</div>
                )}
              </div>
            )}

            {/* ---- 资产 tab ---- */}
            {tab === "assets" && (
              <div className="feed-container">
                <div className="asset-group-heading">
                  项目会话（{chats.length}）
                </div>
                {chats.map((chat) => (
                  <div key={chat.id} className="task-row" title={chat.id}>
                    <span className="task-row-title">
                      <i
                        className="fa-regular fa-message"
                        style={{ marginRight: 8, color: "#94a3b8" }}
                      />
                      {chat.name}
                    </span>
                    <span className="task-time">
                      {chat.updated_at?.slice(0, 16).replace("T", " ")}
                    </span>
                  </div>
                ))}
                {chats.length === 0 && (
                  <div className="blank-state">
                    项目 AI 会话与文件资产将沉淀在这里
                  </div>
                )}
              </div>
            )}

            {/* streaming reply preview above the fixed input */}
            {aiReply && (
              <div className="chat-stream-box">
                <i
                  className="fa-solid fa-robot"
                  style={{ color: "#94a3b8", marginRight: 6 }}
                />
                {aiReply}
                {streaming ? "▍" : ""}
              </div>
            )}

            {/* fixed bottom input (prototype L1445-1476) */}
            <div className="fixed-bottom-input">
              <PromptInput
                variant="detail"
                placeholder="今天帮你做些什么？ @ 引用资产文件、项目待办或调用技能"
                value={aiInput}
                onChange={setAiInput}
                onSend={(value) => {
                  setAiInput("");
                  void sendToProjectAI(value);
                }}
                busy={streaming}
                contextTags={[
                  { label: "本地任务" },
                  { icon: "fa-regular fa-folder", label: "选择工作空间" },
                  { icon: "fa-solid fa-shield-halved", label: "默认权限" },
                ]}
              />
            </div>
          </div>

          {/* right config panel (prototype L1480-1532) */}
          <div className="right-config-panel">
            <div className="panel-header">
              <span>项目配置</span>
              <i className="fa-solid fa-book-open" title="项目文档" />
            </div>

            {/* 指令 */}
            <ConfigBlock
              title="指令"
              onAdd={
                canEdit
                  ? () => {
                      setInstructionsDraft(project.instructions ?? "");
                      setEditingInstructions(true);
                    }
                  : undefined
              }
            >
              {editingInstructions ? (
                <div className="instruction-box">
                  <textarea
                    value={instructionsDraft}
                    onChange={(e) => setInstructionsDraft(e.target.value)}
                    placeholder="项目的 SOP 与系统指令，项目 AI 与成员都会遵循"
                  />
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <button
                      type="button"
                      className="btn-black"
                      style={{ padding: "4px 12px", fontSize: 12 }}
                      onClick={() => void handleSaveInstructions()}
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      className="btn-plain"
                      style={{ padding: "4px 12px", fontSize: 12 }}
                      onClick={() => setEditingInstructions(false)}
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : (
                <div className="instruction-box">
                  {project.instructions?.trim() ||
                    "✨ 欢迎来到 XianWork 项目！\n\n点击右上角 + 配置项目指令（SOP），项目 AI 将自动遵循。"}
                </div>
              )}
            </ConfigBlock>

            {/* 连接器 */}
            <ConfigBlock
              title="连接器"
              desc="连接外部服务，扩展 AI 能力"
              onAdd={canEdit ? () => handleAddBinding("connector", connectors[0]?.client_key ?? "") : undefined}
            >
              {boundConnectors.map((binding) => (
                <BoundItem
                  key={binding.id}
                  icon="fa-solid fa-plug"
                  name={
                    connectors.find((c) => c.client_key === binding.ref_id)
                      ?.display_name ?? binding.ref_id
                  }
                  sub={binding.enabled ? undefined : "已停用"}
                  onRemove={
                    canEdit
                      ? () => void handleRemoveBinding(binding.id)
                      : undefined
                  }
                />
              ))}
              {boundConnectors.length === 0 && (
                <div className="bound-empty">
                  {connectors.length > 0
                    ? "点击 + 绑定管理员配置的 MCP 连接器"
                    : "管理员尚未配置连接器"}
                </div>
              )}
              {canEdit && connectors.length > 0 && (
                <select
                  className="native-select"
                  style={{ width: "100%", marginTop: 8 }}
                  value=""
                  onChange={(e) => {
                    if (e.target.value) {
                      void handleAddBinding("connector", e.target.value);
                    }
                  }}
                >
                  <option value="">+ 选择连接器绑定…</option>
                  {connectors.map((connector) => (
                    <option key={connector.client_key} value={connector.client_key}>
                      {connector.display_name}
                      {connector.enabled ? "" : "（已停用）"}
                    </option>
                  ))}
                </select>
              )}
            </ConfigBlock>

            {/* 专家 */}
            <ConfigBlock
              title="专家"
              desc="配置项目专家，为成员提供更专业的服务"
            >
              <select
                className="native-select"
                style={{ width: "100%", marginTop: 8 }}
                value={
                  project.ai_binding?.ref_id
                    ? `${project.ai_binding.kind}:${project.ai_binding.ref_id}`
                    : ""
                }
                disabled={!canEdit}
                onChange={(e) => void handleBind(e.target.value)}
              >
                <option value="">默认助手</option>
                {bindingOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </ConfigBlock>

            {/* 技能 */}
            <ConfigBlock
              title="技能"
              desc="配置项目技能，让 AI 精准执行任务"
              onAdd={canEdit ? () => handleAddBinding("skill", skills[0]?.name ?? "") : undefined}
            >
              {boundSkills.map((binding) => (
                <BoundItem
                  key={binding.id}
                  icon="fa-solid fa-bolt"
                  name={binding.ref_id}
                  onRemove={
                    canEdit
                      ? () => void handleRemoveBinding(binding.id)
                      : undefined
                  }
                />
              ))}
              {boundSkills.length === 0 && (
                <div className="bound-empty">
                  {skills.length > 0 ? "点击 + 为项目启用技能" : "工作区暂无已安装技能"}
                </div>
              )}
              {canEdit && skills.length > 0 && (
                <select
                  className="native-select"
                  style={{ width: "100%", marginTop: 8 }}
                  value=""
                  onChange={(e) => {
                    if (e.target.value) {
                      void handleAddBinding("skill", e.target.value);
                    }
                  }}
                >
                  <option value="">+ 选择技能启用…</option>
                  {skills.map((skill) => (
                    <option key={skill.name} value={skill.name}>
                      {skill.name}
                    </option>
                  ))}
                </select>
              )}
            </ConfigBlock>

            {/* 自动化 (prototype L1522-1531) */}
            <ConfigBlock
              title={`自动化 ${automations.length}`}
              onAdd={canEdit ? () => setAutomationOpen(true) : undefined}
            >
              {automations.map((automation) => (
                <div key={automation.id} className="automation-item">
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 8,
                    }}
                  >
                    <div>
                      <div className="auto-title">{automation.name}</div>
                      <div className="auto-time">
                        {automation.schedule} ·{" "}
                        {automation.enabled ? "运行中" : "已暂停"}
                      </div>
                    </div>
                    {canEdit && (
                      <i
                        className="fa-solid fa-xmark"
                        style={{ color: "var(--text-muted)", cursor: "pointer" }}
                        title="删除自动化"
                        onClick={async () => {
                          try {
                            await automationApi.remove(pid, automation.id);
                            reload();
                          } catch (err) {
                            notify("error", String(err));
                          }
                        }}
                      />
                    )}
                  </div>
                </div>
              ))}
              {automations.length === 0 && (
                <div className="bound-empty">
                  定时让项目 AI 执行例行任务（如每日资讯总结）
                </div>
              )}
            </ConfigBlock>
          </div>
        </div>
      </div>

      {/* ---- dialogs ---- */}
      <Modal
        open={commentOpen}
        title="发布留言"
        onClose={() => setCommentOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="btn-plain"
              onClick={() => setCommentOpen(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="btn-black"
              onClick={() => void handleComment()}
            >
              发布
            </button>
          </>
        }
      >
        <div className="form-field">
          <textarea
            rows={4}
            placeholder="说点什么…"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>
      </Modal>

      <Modal
        open={newTaskOpen}
        title={`添加事项 · ${COLUMN_META[newTaskStatus].label}`}
        onClose={() => setNewTaskOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="btn-plain"
              onClick={() => setNewTaskOpen(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="btn-black"
              onClick={() => void handleAddTask()}
            >
              添加
            </button>
          </>
        }
      >
        <div className="form-field">
          <label>事项标题</label>
          <input
            placeholder="要做什么？"
            value={newTaskTitle}
            onChange={(e) => setNewTaskTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                void handleAddTask();
              }
            }}
          />
        </div>
        <div className="form-field">
          <label>所属列</label>
          <select
            className="native-select"
            style={{ width: "100%" }}
            value={newTaskStatus}
            onChange={(e) => setNewTaskStatus(e.target.value as Task["status"])}
          >
            {(Object.keys(COLUMN_META) as Task["status"][]).map((status) => (
              <option key={status} value={status}>
                {COLUMN_META[status].label}
              </option>
            ))}
          </select>
        </div>
      </Modal>

      <Modal
        open={automationOpen}
        title="新建自动化"
        onClose={() => setAutomationOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="btn-plain"
              onClick={() => setAutomationOpen(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="btn-black"
              onClick={() => void handleCreateAutomation()}
            >
              创建
            </button>
          </>
        }
      >
        <div className="form-field">
          <label>名称</label>
          <input
            placeholder="如：生成昨日 AI 重点资讯总结"
            value={autoName}
            onChange={(e) => setAutoName(e.target.value)}
          />
        </div>
        <div className="form-field">
          <label>执行时间（cron，默认北京时间）</label>
          <input
            placeholder="0 9 * * * 表示每天 09:00"
            value={autoSchedule}
            onChange={(e) => setAutoSchedule(e.target.value)}
          />
        </div>
        <div className="form-field">
          <label>提示词（发给项目 AI）</label>
          <textarea
            rows={3}
            placeholder="项目 AI 将按计划收到这段提示词并执行"
            value={autoPrompt}
            onChange={(e) => setAutoPrompt(e.target.value)}
          />
        </div>
      </Modal>

      <InviteModal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        projectId={pid}
        canManage={project.member_role === "owner"}
        members={members}
        onChanged={reload}
      />
    </div>
  );
}
