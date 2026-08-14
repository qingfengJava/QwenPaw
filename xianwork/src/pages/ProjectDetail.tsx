/**
 * ProjectDetail — WorkBuddy project workspace:
 * - Tabs: 动态 Feed / 计划 (four-column kanban) / 任务 (list) / 资产
 * - Right panel: project configuration (指令 / 专家绑定 / 成员)
 * - Bottom input: streams the project-shared AI (`project:{pid}` owner,
 *   shared memory) via the XianWork chat proxy.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Input, Modal, Select, Tag, message } from "antd";
import {
  expertApi,
  projectApi,
  taskApi,
} from "../api/modules";
import type {
  Expert,
  ExpertTeam,
  FeedEvent,
  Project,
  ProjectMember,
  Task,
} from "../api/modules";
import { buildAgentRequest, streamChat } from "./Home";

const COLUMNS: { key: Task["status"]; label: string; dot: string }[] = [
  { key: "todo", label: "待开始", dot: "dot-gray" },
  { key: "doing", label: "进行中", dot: "dot-blue" },
  { key: "paused", label: "已暂停", dot: "dot-orange" },
  { key: "done", label: "已完成", dot: "dot-green" },
];

const KIND_LABEL: Record<string, string> = {
  project_created: "创建了项目",
  project_updated: "更新了项目",
  task_created: "创建了事项",
  task_status: "变更了事项状态",
  task_updated: "更新了事项",
  comment: "发布留言",
  ai_message: "向项目 AI 发起任务",
  ai_reply: "项目 AI 完成回复",
  member_joined: "加入了项目",
  member_left: "退出了项目",
};

export default function ProjectDetailPage() {
  const { projectId = "" } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [feed, setFeed] = useState<FeedEvent[]>([]);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [experts, setExperts] = useState<Expert[]>([]);
  const [teams, setTeams] = useState<ExpertTeam[]>([]);
  const [tab, setTab] = useState<"feed" | "board" | "tasks">("feed");
  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [newTask, setNewTask] = useState("");
  const [aiInput, setAiInput] = useState("");
  const [aiReply, setAiReply] = useState("");
  const [streaming, setStreaming] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, t, f, m, e, tm] = await Promise.all([
        projectApi.get(projectId),
        taskApi.list(projectId),
        projectApi.feed(projectId),
        projectApi.members(projectId),
        expertApi.list().catch(() => []),
        expertApi.listTeams().catch(() => []),
      ]);
      setProject(p);
      setTasks(t);
      setFeed(f);
      setMembers(m);
      setExperts(e);
      setTeams(tm);
    } catch (err) {
      message.error(`加载项目失败：${String(err)}`);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const bindingOptions = useMemo(
    () => [
      ...experts.map((e) => ({
        value: `expert:${e.id}`,
        label: `专家 · ${e.name}`,
      })),
      ...teams.map((t) => ({
        value: `expert_team:${t.id}`,
        label: `专家团 · ${t.name}`,
      })),
    ],
    [experts, teams],
  );

  const canEdit =
    project?.member_role === "owner" || project?.member_role === "editor";

  const handleComment = async () => {
    if (!comment.trim()) return;
    await projectApi.comment(projectId, comment.trim());
    setComment("");
    setCommentOpen(false);
    load();
  };

  const handleAddTask = async (_status: Task["status"]) => {
    if (!newTask.trim() || !canEdit) return;
    await taskApi.create(projectId, { title: newTask.trim() });
    setNewTask("");
    load();
  };

  const handleMove = async (task: Task, status: Task["status"]) => {
    if (!canEdit) return;
    // Optimistic move, then persist.
    setTasks((prev) =>
      prev.map((t) => (t.id === task.id ? { ...t, status } : t)),
    );
    try {
      await taskApi.update(projectId, task.id, { status });
      load();
    } catch (err) {
      message.error(String(err));
      load();
    }
  };

  const handleBind = async (value: string) => {
    const [kind, ref_id] = value.split(":");
    await projectApi.update(projectId, {
      ai_binding: { kind, ref_id } as Project["ai_binding"],
    });
    message.success("项目 AI 已绑定");
    load();
  };

  const sendToProjectAI = async () => {
    const text = aiInput.trim();
    if (!text || streaming) return;
    setAiInput("");
    setStreaming(true);
    setAiReply("");
    try {
      await streamChat(
        `/xian/projects/${projectId}/chat`,
        buildAgentRequest(text, "default"),
        (raw) => {
          try {
            const evt = JSON.parse(raw);
            const delta =
              evt?.choices?.[0]?.delta?.content ??
              evt?.delta ??
              evt?.content ??
              (typeof evt?.text === "string" ? evt.text : "");
            if (delta) {
              setAiReply((prev) => prev + delta);
            }
          } catch {
            /* keepalive */
          }
        },
      );
      load();
    } catch (err) {
      setAiReply(`（项目 AI 连接失败：${String(err)}）`);
    } finally {
      setStreaming(false);
    }
  };

  if (!project) {
    return <div className="xian-page">加载中…</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* top nav */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "12px 22px",
          borderBottom: "1px solid var(--border-light)",
        }}
      >
        <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          📁 项目 / <strong style={{ color: "var(--text-primary)" }}>{project.name}</strong>
        </div>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {project.member_role || "访客"}
        </span>
      </div>

      {/* tabs */}
      <div
        style={{
          display: "flex",
          gap: 4,
          padding: "0 22px",
          borderBottom: "1px solid var(--border-light)",
        }}
      >
        {(
          [
            ["feed", "动态"],
            ["board", "计划"],
            ["tasks", "任务"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            style={{
              padding: "13px 18px",
              border: "none",
              background: "transparent",
              cursor: "pointer",
              fontWeight: tab === key ? 600 : 500,
              color: tab === key ? "var(--text-primary)" : "var(--text-secondary)",
              borderBottom:
                tab === key ? "2px solid var(--text-primary)" : "2px solid transparent",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", flexGrow: 1, overflow: "hidden" }}>
        {/* main area */}
        <div
          style={{
            flexGrow: 1,
            display: "flex",
            flexDirection: "column",
            position: "relative",
            overflow: "hidden",
          }}
        >
          <div style={{ flexGrow: 1, overflowY: "auto", padding: 22 }}>
            {tab === "feed" && (
              <>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    marginBottom: 20,
                  }}
                >
                  <Button onClick={() => setCommentOpen(true)}>
                    ＋ 发布留言
                  </Button>
                  <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    实时动态（SSE）
                  </div>
                </div>
                {feed.map((event) => (
                  <div key={event.id} className="xian-feed-item">
                    <div className="xian-feed-avatar">
                      {event.actor === "local" ? "L" : event.actor[0]?.toUpperCase()}
                    </div>
                    <div style={{ flexGrow: 1 }}>
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          fontSize: 13,
                          marginBottom: 6,
                        }}
                      >
                        <span>
                          <strong>{event.actor}</strong>{" "}
                          <span style={{ color: "var(--text-secondary)" }}>
                            {KIND_LABEL[event.kind] ?? event.kind}
                          </span>
                        </span>
                        <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                          {event.created_at?.slice(0, 10)}
                        </span>
                      </div>
                      {event.kind === "comment" && (
                        <div className="xian-feed-box">
                          💬 {String(event.payload.text ?? "")}
                        </div>
                      )}
                      {event.kind !== "comment" && (
                        <div className="xian-feed-box">
                          ✅ {String(event.payload.title ?? event.kind)}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {feed.length === 0 && (
                  <div style={{ textAlign: "center", color: "var(--text-muted)", marginTop: 40 }}>
                    暂无动态
                  </div>
                )}
              </>
            )}

            {tab === "board" && (
              <div>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    marginBottom: 16,
                    alignItems: "center",
                  }}
                >
                  <Input
                    placeholder={canEdit ? "新任务标题，回车添加到「待开始」" : "需要编辑权限"}
                    value={newTask}
                    disabled={!canEdit}
                    onChange={(e) => setNewTask(e.target.value)}
                    onPressEnter={() => handleAddTask("todo")}
                    style={{ width: 360 }}
                  />
                </div>
                <div className="xian-kanban">
                  {COLUMNS.map((col) => {
                    const columnTasks = tasks.filter(
                      (t) => t.status === col.key,
                    );
                    return (
                      <div key={col.key} className="xian-kanban-col">
                        <div className="xian-kanban-head">
                          <span>
                            <span className={`status-dot ${col.dot}`} />
                            {col.label}
                          </span>
                          <span style={{ color: "var(--text-muted)" }}>
                            {columnTasks.length}
                          </span>
                        </div>
                        {columnTasks.map((task) => (
                          <div key={task.id} className="xian-task-card">
                            <div
                              className={`xian-task-title${task.status === "done" ? " done" : ""}`}
                            >
                              {task.title}
                            </div>
                            <div className="xian-task-meta">
                              <span>
                                👤 {task.assignee ?? "未指派"}
                              </span>
                              <span>
                                {task.status !== "done" && canEdit && (
                                  <Select
                                    size="small"
                                    variant="borderless"
                                    value={task.status}
                                    style={{ width: 92 }}
                                    onChange={(next) => handleMove(task, next)}
                                    options={COLUMNS.map((c) => ({
                                      value: c.key,
                                      label: c.label,
                                    }))}
                                  />
                                )}
                              </span>
                            </div>
                          </div>
                        ))}
                        {columnTasks.length === 0 && (
                          <div
                            style={{
                              textAlign: "center",
                              fontSize: 12,
                              color: "var(--text-muted)",
                              border: "1px dashed var(--border-medium)",
                              borderRadius: 8,
                              padding: "18px 0",
                            }}
                          >
                            暂无事项
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {tab === "tasks" && (
              <div>
                {tasks.map((task) => (
                  <div
                    key={task.id}
                    className="xian-task-card"
                    style={{ display: "flex", justifyContent: "space-between" }}
                  >
                    <span className={task.status === "done" ? "xian-task-title done" : ""}>
                      {task.title}
                    </span>
                    <Tag>
                      {COLUMNS.find((c) => c.key === task.status)?.label}
                    </Tag>
                  </div>
                ))}
                {tasks.length === 0 && (
                  <div style={{ color: "var(--text-muted)", textAlign: "center", marginTop: 40 }}>
                    暂无任务
                  </div>
                )}
              </div>
            )}
          </div>

          {/* bottom AI input (WorkBuddy style) */}
          {aiReply && (
            <div
              style={{
                margin: "0 22px 8px",
                padding: "10px 14px",
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: 10,
                fontSize: 13,
                maxHeight: 160,
                overflowY: "auto",
                whiteSpace: "pre-wrap",
              }}
            >
              🤖 {aiReply}{streaming ? "▍" : ""}
            </div>
          )}
          <div
            style={{
              padding: "0 22px 18px",
              display: "flex",
              justifyContent: "center",
            }}
          >
            <div className="xian-input-bar" style={{ maxWidth: 760 }}>
              <textarea
                placeholder="问问项目 AI…（项目共享上下文）"
                value={aiInput}
                onChange={(e) => setAiInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendToProjectAI();
                  }
                }}
              />
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                <button
                  type="button"
                  onClick={sendToProjectAI}
                  disabled={streaming || !aiInput.trim()}
                  style={{
                    width: 30,
                    height: 30,
                    borderRadius: "50%",
                    border: "none",
                    background: aiInput.trim() ? "#2b2d31" : "#d1d1d6",
                    color: "#fff",
                    cursor: aiInput.trim() ? "pointer" : "default",
                  }}
                >
                  ➤
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* right config panel */}
        <div className="xian-side-panel">
          <div style={{ fontWeight: 600, marginBottom: 16 }}>项目配置</div>

          <div className="xian-config-block">
            <div className="xian-config-title">指令</div>
            <div className="xian-config-desc">
              {project.description || "在项目设置中编辑项目指令（系统提示词）"}
            </div>
          </div>

          <div className="xian-config-block">
            <div className="xian-config-title">项目 AI（专家绑定）</div>
            <div className="xian-config-desc">
              绑定后底部输入框走该专家，并共享项目记忆
            </div>
            <Select
              style={{ width: "100%", marginTop: 8 }}
              placeholder="选择已发布专家 / 专家团"
              value={
                project.ai_binding?.ref_id
                  ? `${project.ai_binding.kind}:${project.ai_binding.ref_id}`
                  : undefined
              }
              disabled={!canEdit}
              onChange={handleBind}
              options={bindingOptions}
            />
          </div>

          <div className="xian-config-block">
            <div className="xian-config-title">连接器</div>
            <div className="xian-config-desc">
              连接外部服务，扩展 AI 能力（沿用管理端 MCP 配置）
            </div>
          </div>

          <div className="xian-config-block">
            <div className="xian-config-title">技能</div>
            <div className="xian-config-desc">
              项目 AI 可用的技能（沿用专家配置）
            </div>
          </div>

          <div className="xian-config-block">
            <div className="xian-config-title">成员（{members.length}）</div>
            <div className="xian-config-desc">
              {members.map((m) => `${m.username}(${m.role})`).join("、") || "—"}
            </div>
          </div>
        </div>
      </div>

      <Modal
        title="发布留言"
        open={commentOpen}
        onOk={handleComment}
        onCancel={() => setCommentOpen(false)}
        destroyOnHidden
      >
        <Input.TextArea
          rows={4}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="说点什么…"
        />
      </Modal>
    </div>
  );
}
