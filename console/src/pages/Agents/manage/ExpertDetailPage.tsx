/**
 * Admin/ExpertDetail — 数字员工详情页（StaffDeck DashboardPage 移植，20260830）。
 *
 * 结构：Hero 档案卡（头像/姓名职称/在线胶囊/创建者/入职时间/工作风格/
 * 四计数条/生命周期按钮）→ UnderlineTabs：
 *   工作记录（StatCard 四联 + Day/Week/Month 时间线 + 成长记录）/
 *   定时任务（表格 + 暂停/恢复/立即执行/删除 + 新建）/
 *   记忆（分桶卡片 + 增删 + 清空）/
 *   能力资产（技能 + SOP/知识/工具挂载管理）/
 *   执行日志（定时执行留痕 + 反馈样本；会话回放属 P3 收件箱范围）。
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { SopFlowCanvas } from "@/components/sop/SopFlowCanvas";
import {
  ActivityTimeline,
  SopFlowPreview,
  StatCard,
  StatusPill,
  UnderlineTabs,
  expertStatusTone,
  expertStatusLabel,
} from "@/components/staffdeck";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  adminExpertsApi,
  expertCapabilityApi,
  evolutionApi,
  sopApi,
  type ApiKeyRecord,
  type CapabilityCounts,
  type EvolutionProposal,
  type MemoryRecord,
  type ResourceBinding,
  type ResourceType,
  type ScheduledTask,
  type SopRecord,
  type TaskRun,
  type WorkRecord,
} from "../../../api/modules/admin";
import type { ExpertRecord } from "../../../api/modules/admin";

type DetailTab = "work" | "scheduled" | "memories" | "resources" | "logs";

const KIND_LABELS: Record<string, { zh: string; tone: "green" | "red" | "blue" | "gray" }> = {
  profile: { zh: "画像", tone: "blue" },
  preference: { zh: "偏好", tone: "green" },
  fact: { zh: "事实", tone: "gray" },
};

export default function ExpertDetailPage() {
  const { expertId = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [expert, setExpert] = useState<ExpertRecord | null>(null);
  const [counts, setCounts] = useState<CapabilityCounts>({
    resources: 0,
    skills: 0,
    sops: 0,
    scheduled_tasks: 0,
  });
  const [tab, setTab] = useState<DetailTab>("work");
  const [keysOpen, setKeysOpen] = useState(false);

  const loadExpert = useCallback(async () => {
    try {
      const record = await adminExpertsApi.get(expertId);
      setExpert(record);
      const c = await expertCapabilityApi.capabilityCounts([expertId]);
      setCounts(
        c.counts?.[expertId] ?? {
          resources: 0,
          skills: 0,
          sops: 0,
          scheduled_tasks: 0,
        },
      );
    } catch (err) {
      message.error(String(err));
    }
  }, [expertId, message]);

  useEffect(() => {
    if (expertId) void loadExpert();
  }, [expertId, loadExpert]);

  const handlePublish = async () => {
    try {
      await adminExpertsApi.publish(expertId);
      message.success(t("admin.experts.published", "Expert published"));
      void loadExpert();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleArchive = async () => {
    try {
      await adminExpertsApi.archive(expertId);
      message.success(t("admin.experts.archived", "Expert archived"));
      void loadExpert();
    } catch (err) {
      message.error(String(err));
    }
  };

  if (!expert) {
    return (
      <div className="sd-page">
        <PageHeader
          parent={t("nav.agentsManage", "Manage Employees")}
          current={t("staffdeck.detail.title", "员工详情")}
        />
        <Empty description={t("staffdeck.detail.loading", "加载中…")} />
      </div>
    );
  }

  return (
    <div className="sd-page">
      <PageHeader
        parent={t("nav.agentsManage", "Manage Employees")}
        current={expert.name}
        extra={
          <Space>
            <Button onClick={() => navigate("/agents/manage")}>
              {t("staffdeck.detail.back", "返回列表")}
            </Button>
            <Button onClick={() => setKeysOpen(true)}>
              {t("staffdeck.keys.title", "API 密钥")}
            </Button>
            {expert.status !== "archived" ? (
              <Button type="primary" className="sd-btn-primary" onClick={handlePublish}>
                {expert.status === "published"
                  ? t("staffdeck.detail.republish", "重新发布")
                  : t("admin.experts.publish", "Publish")}
              </Button>
            ) : null}
            {expert.status === "published" ? (
              <Popconfirm
                title={t("staffdeck.detail.archiveConfirm", "归档该员工？")}
                onConfirm={handleArchive}
              >
                <Button danger>{t("admin.experts.archive", "Archive")}</Button>
              </Popconfirm>
            ) : null}
          </Space>
        }
      />

      {/* Hero 档案卡 */}
      <div
        className="sd-card"
        style={{ padding: "28px 32px", display: "flex", gap: 28, alignItems: "flex-start" }}
      >
        <div
          style={{
            width: 88,
            height: 88,
            borderRadius: "50%",
            background: "linear-gradient(145deg, #0f766e, #14b8a6)",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 34,
            fontWeight: 600,
            flexShrink: 0,
          }}
        >
          {(expert.name || "?").slice(0, 1)}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span style={{ fontSize: 24, fontWeight: 700, color: "var(--sd-ink)" }}>
              {expert.name}
            </span>
            {expert.title ? (
              <span style={{ fontSize: 14, color: "var(--sd-text-2)" }}>
                {expert.title}
              </span>
            ) : null}
            <StatusPill tone={expertStatusTone(expert.status)}>
              {expertStatusLabel(expert.status)}
            </StatusPill>
            {expert.badge ? (
              <StatusPill tone="amber" dot={false}>
                {expert.badge}
              </StatusPill>
            ) : null}
          </div>
          <div
            style={{
              marginTop: 8,
              fontSize: 13,
              color: "var(--sd-text-2)",
              display: "flex",
              gap: 18,
              flexWrap: "wrap",
            }}
          >
            {expert.department ? <span>{expert.department}</span> : null}
            {expert.owner_id ? (
              <span>
                {t("staffdeck.detail.creator", "创建者")}：{expert.owner_id}
              </span>
            ) : null}
            <span>
              {t("staffdeck.detail.hireDate", "入职时间")}：
              {(expert.hire_date || expert.created_at || "").slice(0, 10) || "—"}
            </span>
            <span>
              {t("staffdeck.detail.version", "版本")}：v{expert.version}
            </span>
          </div>
          <div style={{ marginTop: 10, fontSize: 13, color: "var(--sd-text-4)", lineHeight: "20px" }}>
            {expert.description || "\u00a0"}
          </div>
          {(expert.work_styles?.length || expert.work_modes?.length) ? (
            <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
              {[...(expert.work_styles ?? []), ...(expert.work_modes ?? [])].map((s) => (
                <StatusPill key={s} tone="plain" dot={false}>
                  {s}
                </StatusPill>
              ))}
            </div>
          ) : null}
          {/* 四计数条 */}
          <div
            style={{
              marginTop: 18,
              display: "grid",
              gridTemplateColumns: "repeat(4, minmax(0, 180px))",
              gap: 14,
            }}
          >
            {[
              { label: t("staffdeck.detail.countResources", "资料/能力"), value: counts.resources },
              { label: t("staffdeck.detail.countSkills", "技能"), value: counts.skills },
              { label: t("staffdeck.detail.countSops", "SOP"), value: counts.sops },
              {
                label: t("staffdeck.detail.countTasks", "定时任务"),
                value: counts.scheduled_tasks,
              },
            ].map((m) => (
              <div
                key={m.label}
                style={{
                  background: "var(--sd-surface)",
                  borderRadius: "var(--sd-radius-md)",
                  padding: "8px 18px",
                }}
              >
                <span style={{ fontSize: 20, fontWeight: 600, color: "var(--sd-ink)" }}>
                  {m.value}
                </span>
                <span className="sd-stat-label" style={{ marginLeft: 8 }}>
                  {m.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ marginTop: 24 }}>
        <UnderlineTabs
          items={[
            { key: "work", label: t("staffdeck.detail.tabWork", "工作记录") },
            { key: "scheduled", label: t("staffdeck.detail.tabScheduled", "定时任务") },
            { key: "memories", label: t("staffdeck.detail.tabMemories", "记忆") },
            { key: "resources", label: t("staffdeck.detail.tabResources", "能力资产") },
            { key: "logs", label: t("staffdeck.detail.tabLogs", "执行日志") },
          ]}
          value={tab}
          onChange={(k) => setTab(k as DetailTab)}
        />
      </div>

      <div style={{ marginTop: 20 }}>
        {tab === "work" ? <WorkRecordTab expertId={expertId} /> : null}
        {tab === "scheduled" ? <ScheduledTab expertId={expertId} onChanged={loadExpert} /> : null}
        {tab === "memories" ? <MemoriesTab expertId={expertId} /> : null}
        {tab === "resources" ? <ResourcesTab expert={expert} onChanged={loadExpert} /> : null}
        {tab === "logs" ? <LogsTab expertId={expertId} /> : null}
      </div>

      {/* API 密钥管理（P4 开放 API 凭证面） */}
      <ApiKeysModal
        expertId={expertId}
        open={keysOpen}
        onClose={() => setKeysOpen(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 工作记录
// ---------------------------------------------------------------------------

function WorkRecordTab({ expertId }: { expertId: string }) {
  const { t } = useTranslation();
  const [record, setRecord] = useState<WorkRecord | null>(null);
  const [proposals, setProposals] = useState<EvolutionProposal[]>([]);

  useEffect(() => {
    void (async () => {
      try {
        setRecord(await expertCapabilityApi.workRecord(expertId, 30));
        const res = await evolutionApi.list(expertId);
        setProposals(
          (res.proposals ?? []).filter(
            (p) => p.status === "published" || p.status === "rolled_back",
          ),
        );
      } catch (err) {
        console.error(err);
      }
    })();
  }, [expertId]);

  if (!record) {
    return <Empty description={t("staffdeck.detail.loading", "加载中…")} />;
  }

  const positive =
    record.positive_rate === null || record.positive_rate === undefined
      ? "—"
      : `${Math.round(record.positive_rate * 100)}%`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
        <StatCard value={record.total_tasks} label={t("staffdeck.work.tasks", "任务总数")} />
        <StatCard
          value={record.succeeded_tasks}
          label={t("staffdeck.work.succeeded", "成功任务")}
          tone="green"
        />
        <StatCard value={positive} label={t("staffdeck.work.positive", "好评率")} tone="green" />
        <StatCard
          value={record.feedback_down}
          label={t("staffdeck.work.negative", "差评数")}
          tone="red"
        />
      </div>

      <ActivityTimeline byDay={record.by_day} timeline={record.timeline} />

      {/* 成长记录（演进提案已发布/已回滚） */}
      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
          {t("staffdeck.work.growth", "成长记录")}
        </div>
        {proposals.length === 0 ? (
          <div style={{ marginTop: 10, fontSize: 13, color: "var(--sd-text-3)" }}>
            {t("staffdeck.work.growthEmpty", "暂无成长记录（反馈驱动的演进提案发布后展示在此）")}
          </div>
        ) : (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
            {proposals.map((p) => (
              <div
                key={p.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 14px",
                  border: "0.5px solid var(--sd-line)",
                  borderRadius: "var(--sd-radius-lg)",
                }}
              >
                <span style={{ fontSize: 12, color: "var(--sd-text-3)", width: 90 }}>
                  {(p.updated_at || "").slice(0, 10)}
                </span>
                <span style={{ flex: 1, fontSize: 13, color: "var(--sd-ink)" }}>{p.title}</span>
                <StatusPill tone={p.status === "published" ? "green" : "gray"}>
                  {p.status === "published"
                    ? t("staffdeck.evo.published", "已发布")
                    : t("staffdeck.evo.rolledBack", "已回滚")}
                </StatusPill>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 定时任务
// ---------------------------------------------------------------------------

function ScheduledTab({
  expertId,
  onChanged,
}: {
  expertId: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [creating, setCreating] = useState(false);
  const [runsOf, setRunsOf] = useState<ScheduledTask | null>(null);
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    try {
      const res = await expertCapabilityApi.listScheduledTasks(expertId);
      setTasks(res.tasks ?? []);
    } catch (err) {
      message.error(String(err));
    }
  }, [expertId, message]);

  useEffect(() => {
    void load();
  }, [load]);

  const action = async (fn: () => Promise<unknown>, okText: string) => {
    try {
      await fn();
      message.success(okText);
      void load();
      onChanged();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    const scheduleJson =
      values.schedule_type === "once"
        ? { run_at: values.run_at?.toISOString?.() ?? values.run_at }
        : { cron: values.cron };
    await action(async () => {
      await expertCapabilityApi.createScheduledTask(expertId, {
        name: values.name,
        description: values.description ?? "",
        task_prompt: values.task_prompt,
        schedule_type: values.schedule_type,
        schedule_json: scheduleJson,
        timezone: values.timezone || "Asia/Shanghai",
      });
      message.success(t("staffdeck.sched.created", "定时任务已创建"));
    }, "");
    setCreating(false);
    form.resetFields();
  };

  return (
    <div className="sd-card" style={{ padding: "20px 24px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 14,
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
          {t("staffdeck.sched.title", "定时任务")}
        </span>
        <Button className="sd-btn-primary" onClick={() => setCreating(true)}>
          {t("staffdeck.sched.create", "新建任务")}
        </Button>
      </div>
      <Table<ScheduledTask>
        rowKey="id"
        dataSource={tasks}
        pagination={false}
        locale={{ emptyText: t("staffdeck.sched.empty", "暂无定时任务") }}
        columns={[
          { title: t("staffdeck.sched.name", "名称"), dataIndex: "name" },
          {
            title: t("staffdeck.sched.schedule", "计划"),
            render: (_, task) =>
              task.schedule_type === "once"
                ? `${t("staffdeck.sched.once", "一次性")} ${task.schedule_json.run_at ?? ""}`
                : `cron: ${task.schedule_json.cron ?? ""}`,
          },
          { title: t("staffdeck.sched.timezone", "时区"), dataIndex: "timezone", width: 120 },
          {
            title: t("staffdeck.sched.status", "状态"),
            dataIndex: "status",
            width: 90,
            render: (s: string) => (
              <StatusPill
                tone={s === "active" ? "green" : s === "paused" ? "amber" : "gray"}
              >
                {s}
              </StatusPill>
            ),
          },
          {
            title: t("staffdeck.sched.last", "最近执行"),
            render: (_, task) => (
              <span style={{ fontSize: 12, color: "var(--sd-text-2)" }}>
                {(task.last_run_at ?? "").slice(0, 16).replace("T", " ") || "—"}
                {task.last_status ? ` · ${task.last_status}` : ""}
              </span>
            ),
          },
          {
            title: t("admin.experts.actions", "Actions"),
            width: 260,
            render: (_, task) => (
              <Space size={4} wrap>
                {task.status === "active" ? (
                  <Button
                    size="small"
                    onClick={() =>
                      void action(
                        () =>
                          expertCapabilityApi.pauseScheduledTask(
                            expertId,
                            task.id,
                          ),
                        t("staffdeck.sched.paused", "已暂停"),
                      )
                    }
                  >
                    {t("staffdeck.sched.pause", "暂停")}
                  </Button>
                ) : task.status === "paused" ? (
                  <Button
                    size="small"
                    onClick={() =>
                      void action(
                        () =>
                          expertCapabilityApi.resumeScheduledTask(
                            expertId,
                            task.id,
                          ),
                        t("staffdeck.sched.resumed", "已恢复"),
                      )
                    }
                  >
                    {t("staffdeck.sched.resume", "恢复")}
                  </Button>
                ) : null}
                <Button
                  size="small"
                  onClick={() =>
                    void action(
                      () =>
                        expertCapabilityApi.runScheduledTaskNow(
                          expertId,
                          task.id,
                        ),
                      t("staffdeck.sched.triggered", "已触发"),
                    )
                  }
                >
                  {t("staffdeck.sched.runNow", "立即执行")}
                </Button>
                <Button
                  size="small"
                  onClick={() => {
                    setRunsOf(task);
                    void expertCapabilityApi
                      .listTaskRuns(expertId, task.id)
                      .then((res) => setRuns(res.runs ?? []))
                      .catch((err) => message.error(String(err)));
                  }}
                >
                  {t("staffdeck.sched.runs", "执行记录")}
                </Button>
                <Popconfirm
                  title={t("staffdeck.sched.deleteConfirm", "删除该任务？")}
                  onConfirm={() =>
                    void action(
                      () =>
                        expertCapabilityApi.deleteScheduledTask(
                          expertId,
                          task.id,
                        ),
                      t("staffdeck.sched.deleted", "已删除"),
                    )
                  }
                >
                  <Button size="small" danger>
                    {t("common.delete", "Delete")}
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      {/* 新建弹窗 */}
      <Modal
        title={t("staffdeck.sched.create", "新建任务")}
        open={creating}
        onOk={handleCreate}
        onCancel={() => setCreating(false)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}
          initialValues={{ schedule_type: "cron", timezone: "Asia/Shanghai" }}
        >
          <Form.Item
            name="name"
            label={t("staffdeck.sched.name", "名称")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="task_prompt"
            label={t("staffdeck.sched.prompt", "执行指令（触发时投给该员工）")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Space size="middle" style={{ display: "flex" }}>
            <Form.Item
              name="schedule_type"
              label={t("staffdeck.sched.type", "类型")}
            >
              <Select
                style={{ width: 140 }}
                options={[
                  { value: "cron", label: t("staffdeck.sched.cron", "周期 cron") },
                  { value: "once", label: t("staffdeck.sched.once", "一次性") },
                ]}
              />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(a, b) => a.schedule_type !== b.schedule_type}>
              {({ getFieldValue }) =>
                getFieldValue("schedule_type") === "once" ? (
                  <Form.Item
                    name="run_at"
                    label={t("staffdeck.sched.runAt", "执行时间 (ISO8601)")}
                    rules={[{ required: true }]}
                  >
                    <Input placeholder="2026-09-01T09:00:00+08:00" style={{ width: 240 }} />
                  </Form.Item>
                ) : (
                  <Form.Item
                    name="cron"
                    label={t("staffdeck.sched.cronExpr", "cron 表达式（5 段）")}
                    rules={[{ required: true }]}
                  >
                    <Input placeholder="0 9 * * 1-5" style={{ width: 200 }} />
                  </Form.Item>
                )
              }
            </Form.Item>
            <Form.Item
              name="timezone"
              label={t("staffdeck.sched.timezone", "时区")}
            >
              <Input style={{ width: 160 }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* 执行记录弹窗 */}
      <Modal
        title={`${runsOf?.name ?? ""} · ${t("staffdeck.sched.runs", "执行记录")}`}
        open={runsOf !== null}
        onCancel={() => setRunsOf(null)}
        footer={null}
        width={680}
      >
        <Table<TaskRun>
          rowKey="id"
          dataSource={runs}
          pagination={false}
          size="small"
          locale={{ emptyText: t("staffdeck.sched.noRuns", "暂无执行记录") }}
          columns={[
            {
              title: t("staffdeck.sched.started", "开始"),
              dataIndex: "started_at",
              render: (v: string) => (v ?? "").slice(0, 19).replace("T", " "),
            },
            {
              title: t("staffdeck.sched.result", "结果"),
              dataIndex: "status",
              width: 90,
              render: (s: string) => (
                <StatusPill tone={s === "succeeded" ? "green" : s === "failed" ? "red" : "gray"}>
                  {s}
                </StatusPill>
              ),
            },
            {
              title: t("staffdeck.sched.summary", "结果摘要"),
              dataIndex: "result_summary",
              ellipsis: true,
            },
          ]}
        />
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 记忆
// ---------------------------------------------------------------------------

function MemoriesTab({ expertId }: { expertId: string }) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    try {
      const res = await expertCapabilityApi.listMemories(expertId);
      setMemories(res.memories ?? []);
    } catch (err) {
      message.error(String(err));
    }
  }, [expertId, message]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="sd-card" style={{ padding: "20px 24px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 14,
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
          {t("staffdeck.memory.title", "长期记忆（按用户分桶）")}
        </span>
        <Space>
          <Button className="sd-btn-primary" onClick={() => setCreating(true)}>
            {t("staffdeck.memory.add", "新增记忆")}
          </Button>
          <Popconfirm
            title={t("staffdeck.memory.clearConfirm", "清空全部记忆？")}
            onConfirm={() => {
              void expertCapabilityApi
                .clearMemories(expertId)
                .then(() => {
                  message.success(t("staffdeck.memory.cleared", "已清空"));
                  void load();
                })
                .catch((err) => message.error(String(err)));
            }}
          >
            <Button danger>{t("staffdeck.memory.clear", "清空")}</Button>
          </Popconfirm>
        </Space>
      </div>

      {memories.length === 0 ? (
        <Empty description={t("staffdeck.memory.empty", "暂无记忆")} />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
          {memories.map((m) => (
            <div
              key={m.id}
              style={{
                border: "0.5px solid var(--sd-line)",
                borderRadius: "var(--sd-radius-lg)",
                padding: "12px 16px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Tag color={m.kind === "preference" ? "green" : m.kind === "profile" ? "blue" : "default"}>
                  {KIND_LABELS[m.kind]?.zh ?? m.kind}
                </Tag>
                <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
                  {m.user_id || t("staffdeck.memory.org", "组织级")}
                </span>
                <span style={{ flex: 1 }} />
                <Popconfirm
                  title={t("staffdeck.memory.deleteConfirm", "删除该记忆？")}
                  onConfirm={() => {
                    void expertCapabilityApi
                      .deleteMemory(expertId, m.id)
                      .then(() => void load())
                      .catch((err) => message.error(String(err)));
                  }}
                >
                  <Button type="text" size="small" danger>
                    {t("common.delete", "Delete")}
                  </Button>
                </Popconfirm>
              </div>
              <div style={{ marginTop: 8, fontSize: 13, color: "var(--sd-ink)", lineHeight: "20px" }}>
                {m.content}
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal
        title={t("staffdeck.memory.add", "新增记忆")}
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={async () => {
          const values = await form.validateFields();
          try {
            await expertCapabilityApi.upsertMemory(expertId, {
              kind: values.kind,
              content: values.content,
              importance: values.importance ?? 0.5,
              dedup_key: values.dedup_key || "",
            });
            message.success(t("staffdeck.memory.saved", "已保存"));
            setCreating(false);
            form.resetFields();
            void load();
          } catch (err) {
            message.error(String(err));
          }
        }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}
          initialValues={{ kind: "fact", importance: 0.5 }}
        >
          <Form.Item name="kind" label={t("staffdeck.memory.kind", "分桶")}>
            <Select
              options={[
                { value: "profile", label: t("staffdeck.memory.profile", "用户画像") },
                { value: "preference", label: t("staffdeck.memory.preference", "偏好") },
                { value: "fact", label: t("staffdeck.memory.fact", "事实") },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="content"
            label={t("staffdeck.memory.content", "内容")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            name="dedup_key"
            label={t("staffdeck.memory.dedupKey", "去重键（同键覆盖，可选）")}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 能力资产（技能 + SOP/知识/工具挂载）
// ---------------------------------------------------------------------------

function ResourcesTab({
  expert,
  onChanged,
}: {
  expert: ExpertRecord;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [grouped, setGrouped] = useState<
    Record<string, ResourceBinding[]>
  >({});
  const [sops, setSops] = useState<SopRecord[]>([]);
  const [adding, setAdding] = useState<"sop" | "knowledge_base" | "tool" | null>(null);
  // SOP 只读流程图预览（查看抽屉）
  const [previewSopId, setPreviewSopId] = useState("");
  // SOP 画布编辑（缺口④：React Flow 编辑器全屏抽屉）
  const [editingSop, setEditingSop] = useState<SopRecord | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    try {
      const res = await expertCapabilityApi.listResources(expert.id);
      setGrouped(res.bindings ?? {});
      setSops(await sopApi.list());
    } catch (err) {
      message.error(String(err));
    }
  }, [expert.id, message]);

  useEffect(() => {
    void load();
  }, [load]);

  const replaceAll = async (
    next: Record<string, ResourceBinding[]>,
  ) => {
    const flat = Object.entries(next).flatMap(([type, rows]) =>
      rows.map((row) => ({ ...row, resource_type: type as ResourceType })),
    );
    await expertCapabilityApi.replaceResources(expert.id, flat);
    await load();
    onChanged();
  };

  const sections: Array<{ type: "sop" | "knowledge_base" | "tool"; label: string }> = [
    { type: "sop", label: t("staffdeck.res.sop", "SOP 流程资产") },
    { type: "knowledge_base", label: t("staffdeck.res.kb", "知识库") },
    { type: "tool", label: t("staffdeck.res.tool", "工具") },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* 技能（只读，权威在 expert_skills，发布时物化） */}
      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
          {t("staffdeck.res.skills", "技能")}
        </div>
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {(expert.skills ?? []).length === 0 ? (
            <span style={{ fontSize: 13, color: "var(--sd-text-3)" }}>
              {t("staffdeck.res.skillsEmpty", "未绑定技能（在专家编辑页管理技能绑定）")}
            </span>
          ) : (
            (expert.skills ?? []).map((s) => (
              <Tag key={s.skill_name}>{s.skill_name}</Tag>
            ))
          )}
        </div>
      </div>

      {sections.map((section) => {
        const rows = grouped[section.type] ?? [];
        return (
          <div key={section.type} className="sd-card" style={{ padding: "20px 24px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
                {section.label}
              </span>
              <Button size="small" onClick={() => setAdding(section.type)}>
                {t("staffdeck.res.add", "挂载")}
              </Button>
            </div>
            {rows.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--sd-text-3)" }}>
                {t("staffdeck.res.none", "未挂载")}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {rows.map((row) => {
                  const name =
                    (row.metadata?.name as string) || row.resource_id;
                  return (
                    <div
                      key={row.resource_id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        padding: "8px 14px",
                        border: "0.5px solid var(--sd-line)",
                        borderRadius: "var(--sd-radius-lg)",
                      }}
                    >
                      <span style={{ flex: 1, fontSize: 13, color: "var(--sd-ink)" }}>
                        {name}
                      </span>
                      <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
                        {row.resource_id}
                      </span>
                      {section.type === "sop" ? (
                        <>
                          <Button
                            size="small"
                            onClick={() => setPreviewSopId(row.resource_id)}
                          >
                            {t("staffdeck.res.view", "查看")}
                          </Button>
                          <Button
                            size="small"
                            type="primary"
                            ghost
                            onClick={() => {
                              const target = sops.find(
                                (s) => s.id === row.resource_id,
                              );
                              if (target) {
                                setEditingSop(target);
                              } else {
                                message.error(
                                  t(
                                    "staffdeck.res.sopMissing",
                                    "SOP 不存在或已删除",
                                  ),
                                );
                              }
                            }}
                          >
                            {t("staffdeck.res.edit", "编辑")}
                          </Button>
                        </>
                      ) : null}
                      <Popconfirm
                        title={t("staffdeck.res.removeConfirm", "卸载该能力？")}
                        onConfirm={() => {
                          const next = { ...grouped };
                          next[section.type] = rows.filter(
                            (r) => r.resource_id !== row.resource_id,
                          );
                          void replaceAll(next).catch((err) =>
                            message.error(String(err)),
                          );
                        }}
                      >
                        <Button size="small" danger>
                          {t("staffdeck.res.remove", "卸载")}
                        </Button>
                      </Popconfirm>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {/* 挂载弹窗 */}
      <Modal
        title={t("staffdeck.res.add", "挂载")}
        open={adding !== null}
        onCancel={() => setAdding(null)}
        onOk={async () => {
          const values = await form.validateFields();
          const type = adding;
          if (!type) return;
          const resourceId =
            type === "sop" ? values.sop_id : values.resource_id;
          if (!resourceId) return;
          const next = { ...grouped };
          const list = next[type] ?? [];
          if (list.some((r) => r.resource_id === resourceId)) {
            message.warning(t("staffdeck.res.exists", "该能力已挂载"));
            setAdding(null);
            return;
          }
          next[type] = [
            ...list,
            {
              resource_type: type,
              resource_id: resourceId,
              enabled: true,
              metadata:
                type === "sop"
                  ? {
                      name: sops.find((s) => s.id === resourceId)?.name,
                    }
                  : values.name
                    ? { name: values.name }
                    : {},
            },
          ];
          try {
            await replaceAll(next);
            setAdding(null);
            form.resetFields();
          } catch (err) {
            message.error(String(err));
          }
        }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          {adding === "sop" ? (
            <Form.Item
              name="sop_id"
              label={t("staffdeck.res.pickSop", "选择 SOP")}
              rules={[{ required: true }]}
            >
              <Select
                options={sops
                  .filter((s) => s.status === "published")
                  .map((s) => ({ value: s.id, label: `${s.name} (v${s.version})` }))}
                placeholder={t("staffdeck.res.pickSopHint", "仅已发布的 SOP 可挂载")}
              />
            </Form.Item>
          ) : (
            <>
              <Form.Item
                name="resource_id"
                label={t("staffdeck.res.resourceId", "资源 ID")}
                rules={[{ required: true }]}
              >
                <Input
                  placeholder={
                    adding === "knowledge_base"
                      ? t("staffdeck.res.kbHint", "知识库 ID")
                      : t("staffdeck.res.toolHint", "工具名（如 web_search）")
                  }
                />
              </Form.Item>
              <Form.Item name="name" label={t("staffdeck.res.displayName", "显示名（可选）")}>
                <Input />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>

      {/* SOP 只读流程图预览 */}
      <Drawer
        title={t("staffdeck.sop.preview", "SOP 流程预览")}
        open={previewSopId !== ""}
        onClose={() => setPreviewSopId("")}
        width={520}
        destroyOnHidden
      >
        {previewSopId ? <SopFlowPreview sopId={previewSopId} /> : null}
      </Drawer>

      {/* SOP 画布编辑器（缺口④：React Flow，编辑态全屏抽屉） */}
      <Drawer
        title={
          editingSop
            ? `${t("staffdeck.canvas.editorTitle", "SOP 画布编辑")} · ${editingSop.name} (v${editingSop.version})`
            : t("staffdeck.canvas.editorTitle", "SOP 画布编辑")
        }
        open={editingSop !== null}
        onClose={() => setEditingSop(null)}
        width="94vw"
        destroyOnHidden
        styles={{ body: { padding: 12, height: "calc(100% - 55px)" } }}
      >
        {editingSop ? (
          <SopFlowCanvas
            sop={editingSop}
            onSave={async (payload) => {
              try {
                const updated = await sopApi.update(editingSop.id, {
                  nodes: payload.nodes,
                  edges: payload.edges,
                  slots: payload.slots,
                });
                setEditingSop(updated);
                await load();
                message.success(
                  t("staffdeck.canvas.saved", "已保存"),
                );
              } catch (err) {
                message.error(String(err));
              }
            }}
          />
        ) : null}
      </Drawer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 执行日志（定时执行留痕 + 反馈样本；会话回放属 P3 收件箱范围）
// ---------------------------------------------------------------------------

function LogsTab({ expertId }: { expertId: string }) {
  const { t } = useTranslation();
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [feedback, setFeedback] = useState<Awaited<
    ReturnType<typeof expertCapabilityApi.feedbackSummary>
  > | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setFeedback(await expertCapabilityApi.feedbackSummary(expertId, 30));
      } catch (err) {
        console.error(err);
      }
      // 汇总该员工全部任务的执行留痕（任务数有限，可接受并发拉取）
      try {
        const res = await expertCapabilityApi.listScheduledTasks(expertId);
        const all = await Promise.all(
          (res.tasks ?? []).map((task) =>
            expertCapabilityApi
              .listTaskRuns(expertId, task.id)
              .then((r) => r.runs ?? []),
          ),
        );
        setRuns(
          all
            .flat()
            .sort((a, b) =>
              (b.started_at ?? "").localeCompare(a.started_at ?? ""),
            ),
        );
      } catch (err) {
        console.error(err);
      }
    })();
  }, [expertId]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
          {t("staffdeck.logs.feedback", "近期反馈")}
        </div>
        {feedback && feedback.recent && feedback.recent.length > 0 ? (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
            {feedback.recent.map((f) => (
              <div
                key={f.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "8px 14px",
                  border: "0.5px solid var(--sd-line)",
                  borderRadius: "var(--sd-radius-lg)",
                }}
              >
                <StatusPill tone={f.rating === "up" ? "green" : "red"}>
                  {f.rating === "up" ? "👍" : "👎"}
                </StatusPill>
                <span style={{ flex: 1, fontSize: 13, color: "var(--sd-ink)" }}>
                  {f.comment || f.message_id}
                </span>
                <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
                  {(f.created_at || "").slice(0, 16).replace("T", " ")}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ marginTop: 10, fontSize: 13, color: "var(--sd-text-3)" }}>
            {t("staffdeck.logs.noFeedback", "暂无反馈")}
          </div>
        )}
      </div>

      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
          {t("staffdeck.logs.runs", "定时执行留痕")}
        </div>
        <div style={{ marginTop: 12 }}>
          <Table<TaskRun>
            rowKey="id"
            dataSource={runs}
            pagination={{ pageSize: 8 }}
            size="small"
            locale={{ emptyText: t("staffdeck.sched.noRuns", "暂无执行记录") }}
            columns={[
              {
                title: t("staffdeck.sched.started", "开始"),
                dataIndex: "started_at",
                render: (v: string) => (v ?? "").slice(0, 19).replace("T", " "),
              },
              {
                title: t("staffdeck.sched.result", "结果"),
                dataIndex: "status",
                width: 90,
                render: (s: string) => (
                  <StatusPill tone={s === "succeeded" ? "green" : s === "failed" ? "red" : "gray"}>
                    {s}
                  </StatusPill>
                ),
              },
              {
                title: t("staffdeck.sched.summary", "结果摘要"),
                dataIndex: "result_summary",
                ellipsis: true,
              },
            ]}
          />
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// API 密钥管理（P4：签发/列表/吊销；明文仅签发时展示一次）
// ---------------------------------------------------------------------------

function ApiKeysModal({
  expertId,
  open,
  onClose,
}: {
  expertId: string;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [keys, setKeys] = useState<ApiKeyRecord[]>([]);
  const [name, setName] = useState("");
  const [plaintext, setPlaintext] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await expertCapabilityApi.listApiKeys(expertId);
      setKeys(res.keys ?? []);
    } catch (err) {
      message.error(String(err));
    }
  }, [expertId, message]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  return (
    <Modal
      title={t("staffdeck.keys.title", "API 密钥")}
      open={open}
      onCancel={onClose}
      footer={null}
      width={680}
      destroyOnHidden
    >
      {/* 签发区 */}
      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("staffdeck.keys.nameHint", "密钥备注（如：OA 系统集成）")}
          style={{ flex: 1 }}
        />
        <Button
          className="sd-btn-primary"
          onClick={async () => {
            try {
              const created = await expertCapabilityApi.issueApiKey(
                expertId,
                name,
              );
              setPlaintext(created.plaintext ?? "");
              setName("");
              void load();
            } catch (err) {
              message.error(String(err));
            }
          }}
        >
          {t("staffdeck.keys.issue", "签发密钥")}
        </Button>
      </div>

      {/* 明文一次性提示 */}
      {plaintext ? (
        <div
          style={{
            background: "var(--sd-amber-bg)",
            color: "var(--sd-amber)",
            borderRadius: "var(--sd-radius-lg)",
            padding: "10px 14px",
            fontSize: 13,
            marginBottom: 14,
          }}
        >
          <div>{t("staffdeck.keys.onceWarning", "请立即保存，明文仅显示这一次：")}</div>
          <code style={{ display: "block", marginTop: 6, wordBreak: "break-all" }}>
            {plaintext}
          </code>
        </div>
      ) : null}

      {/* 密钥列表 */}
      {keys.length === 0 ? (
        <Empty description={t("staffdeck.keys.empty", "尚未签发密钥")} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {keys.map((k) => (
            <div
              key={k.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "10px 14px",
                border: "0.5px solid var(--sd-line)",
                borderRadius: "var(--sd-radius-lg)",
              }}
            >
              <StatusPill tone={k.revoked_at ? "gray" : "green"}>
                {k.revoked_at
                  ? t("staffdeck.keys.revoked", "已吊销")
                  : t("staffdeck.keys.active", "有效")}
              </StatusPill>
              <span style={{ fontSize: 13, color: "var(--sd-ink)" }}>
                {k.name || k.key_prefix}
              </span>
              <code style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
                {k.key_prefix}…
              </code>
              <span style={{ flex: 1 }} />
              {!k.revoked_at ? (
                <Popconfirm
                  title={t("staffdeck.keys.revokeConfirm", "吊销该密钥？即时生效。")}
                  onConfirm={() => {
                    void expertCapabilityApi
                      .revokeApiKey(expertId, k.id)
                      .then(() => void load())
                      .catch((err) => message.error(String(err)));
                  }}
                >
                  <Button size="small" danger>
                    {t("staffdeck.keys.revoke", "吊销")}
                  </Button>
                </Popconfirm>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
