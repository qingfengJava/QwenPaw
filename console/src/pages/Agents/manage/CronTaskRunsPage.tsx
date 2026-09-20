/**
 * CronTaskRunsPage — full-page execution-history list for one scheduled
 * task (interaction aligned with the sessions run-log UX): "执行记录"
 * navigates here instead of opening a dialog; clicking a row opens a
 * right-side detail drawer, whose "查看完整执行链" entry reuses the
 * run-log detail page (agent_runs span tree + session replay).
 * Routed at /agents/manage/:expertId/schedules/:jobId/runs.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button, Descriptions, Drawer, Table, Tag, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { PageHeader } from "@/components/PageHeader";
import { usePageNavTitle } from "@/hooks/usePageNavTitle";
import { StatusPill } from "@/components/staffdeck";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  expertCapabilityApi,
  type ScheduledTask,
  type TaskRun,
} from "../../../api/modules/admin/expertCapability";

/** run 状态 → StatusPill tone（与执行记录弹窗历史语义一致）。 */
const RUN_TONE: Record<string, "green" | "red" | "gray"> = {
  running: "gray",
  succeeded: "green",
  failed: "red",
};

/** run 状态 → 中文描述（枚举展示描述文本规范）。 */
const RUN_LABEL: Record<string, string> = {
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
};

/** 任务来源 → 中文描述（与定时任务列表"来源"列一致）。 */
const SOURCE_LABEL: Record<string, string> = {
  ui: "界面创建",
  chat: "对话创建",
  api: "接口创建",
};

const SOURCE_COLOR: Record<string, string> = {
  ui: "green",
  chat: "blue",
  api: "purple",
};

/** 任务状态 → StatusPill tone。 */
const TASK_TONE: Record<string, "green" | "amber" | "gray"> = {
  active: "green",
  paused: "amber",
  completed: "gray",
  archived: "gray",
};

const TASK_LABEL: Record<string, string> = {
  active: "已启用",
  paused: "已暂停",
  completed: "已完成",
  archived: "已归档",
};

function fmtTime(v?: string | null): string {
  return (v ?? "").slice(0, 19).replace("T", " ") || "—";
}

/** 调度描述：cron 表达式或一次性执行时间。 */
function scheduleText(task: ScheduledTask): string {
  const json = task.schedule_json ?? {};
  return String(
    task.schedule_type === "cron" ? json.cron ?? "—" : json.run_at ?? "—",
  );
}

/** 触发方式：scheduled_for 为空 = 手动 run-now（后端幂等锚约定）。 */
function isManualTrigger(run: TaskRun): boolean {
  return !run.scheduled_for;
}

function durationText(run: TaskRun): string {
  if (!run.started_at || !run.finished_at) {
    return "—";
  }
  const ms =
    new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
  if (!Number.isFinite(ms) || ms < 0) {
    return "—";
  }
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} 秒` : `${ms} ms`;
}

function CronTaskRunsPage() {
  const { expertId = "", jobId = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [task, setTask] = useState<ScheduledTask | null>(null);
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedRun, setSelectedRun] = useState<TaskRun | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 任务头信息与执行列表并发拉取；任务可能已被删除（仅展示记录）
      const [taskRes, runRes] = await Promise.all([
        expertCapabilityApi
          .listScheduledTasks(expertId)
          .catch(() => ({ tasks: [] })),
        expertCapabilityApi.listTaskRuns(expertId, jobId),
      ]);
      setTask(
        (taskRes.tasks ?? []).find((item) => item.id === jobId) ?? null,
      );
      setRuns(
        (runRes.runs ?? []).sort((a, b) =>
          (b.started_at ?? "").localeCompare(a.started_at ?? ""),
        ),
      );
    } catch (err) {
      message.error(String(err));
    } finally {
      setLoading(false);
    }
  }, [expertId, jobId, message]);

  useEffect(() => {
    void load();
  }, [load]);

  // 顶部标签与面包屑显示任务名（菜单里查不到，由页面回填）。
  usePageNavTitle(task?.name ?? jobId);

  const triggerLabel = useCallback(
    (run: TaskRun) =>
      isManualTrigger(run)
        ? t("staffdeck.sched.triggerManual", "手动触发")
        : t("staffdeck.sched.triggerScheduled", "定时触发"),
    [t],
  );

  // 详情层复用运行日志页（agent_runs/spans 会话日志权威结构）：
  // 左执行链树 + 右 Input/Output 面板
  const runDetailPath = (runId: string) =>
    `/agents/expert_${encodeURIComponent(expertId)}/sessions/runs/`
    + encodeURIComponent(runId);

  return (
    <div style={{ padding: "0 4px" }}>
      <PageHeader
        current={`${task?.name ?? jobId} · ${t("staffdeck.sched.runs", "执行记录")}`}
        afterBreadcrumb={
          /* 面包屑已上移到顶部导航条，这里只保留「返回员工详情」这个动作入口。 */
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={() =>
              navigate(`/agents/manage/${encodeURIComponent(expertId)}`)
            }
          >
            {t("staffdeck.detail.back", "返回列表")}
          </Button>
        }
        extra={
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => void load()}
          >
            {t("common.refresh", "刷新")}
          </Button>
        }
      />

      {/* 任务信息卡（来源任务可能已删除 → 降级只显示 ID） */}
      <div className="sd-card" style={{ padding: "16px 24px", marginBottom: 16 }}>
        {task ? (
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: "var(--sd-ink)" }}>
              {task.name}
            </span>
            <StatusPill tone={TASK_TONE[task.status] ?? "gray"}>
              {TASK_LABEL[task.status] ?? task.status}
            </StatusPill>
            {task.source ? (
              <Tag color={SOURCE_COLOR[task.source] ?? "default"}>
                {SOURCE_LABEL[task.source] ?? task.source}
              </Tag>
            ) : null}
            <span style={{ fontSize: 13, color: "var(--sd-text-2)" }}>
              {task.schedule_type === "cron"
                ? t("staffdeck.sched.cron", "周期 cron")
                : t("staffdeck.sched.once", "一次性")}
              {" · "}
              {scheduleText(task)}
              {" · "}
              {task.timezone}
            </span>
            <Typography.Text
              copyable
              type="secondary"
              style={{ fontSize: 12 }}
            >
              {task.id}
            </Typography.Text>
          </div>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {t("staffdeck.sched.taskGone", "任务信息不可用（可能已删除），仅展示历史执行记录")}
          </Typography.Text>
        )}
      </div>

      <div className="sd-card" style={{ padding: "16px 24px" }}>
        <Table<TaskRun>
          rowKey="id"
          loading={loading}
          dataSource={runs}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          size="small"
          locale={{ emptyText: t("staffdeck.sched.noRuns", "暂无执行记录") }}
          onRow={(run) => ({
            // 点击行打开右侧详情抽屉（对齐会话日志交互）
            onClick: () => setSelectedRun(run),
            style: { cursor: "pointer" },
          })}
          columns={[
            {
              title: t("staffdeck.sched.trigger", "触发方式"),
              key: "trigger",
              width: 110,
              align: "center",
              render: (_, run) => triggerLabel(run),
            },
            {
              title: t("staffdeck.sched.started", "开始"),
              dataIndex: "started_at",
              width: 170,
              align: "center",
              render: (v: string) => fmtTime(v),
            },
            {
              title: t("staffdeck.sched.duration", "耗时"),
              key: "duration",
              width: 100,
              align: "center",
              render: (_, run) => durationText(run),
            },
            {
              title: t("staffdeck.sched.result", "结果"),
              dataIndex: "status",
              width: 90,
              align: "center",
              render: (s: string) => (
                <StatusPill tone={RUN_TONE[s] ?? "gray"}>
                  {RUN_LABEL[s] ?? s}
                </StatusPill>
              ),
            },
            {
              title: t("staffdeck.sched.summary", "结果摘要"),
              dataIndex: "result_summary",
              ellipsis: true,
              render: (v: string) => v || "—",
            },
            {
              title: t("staffdeck.sched.actions", "操作"),
              key: "actions",
              width: 90,
              align: "center",
              render: (_, run) => (
                <Button
                  size="small"
                  type="link"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedRun(run);
                  }}
                >
                  {t("staffdeck.sched.detail", "详情")}
                </Button>
              ),
            },
          ]}
        />
      </div>

      {/* 右侧详情抽屉（点击记录展开；不弹框） */}
      <Drawer
        title={
          selectedRun
            ? `${fmtTime(selectedRun.started_at)} · ${triggerLabel(selectedRun)}`
            : ""
        }
        open={selectedRun !== null}
        onClose={() => setSelectedRun(null)}
        width={480}
        destroyOnHidden
      >
        {selectedRun ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label={t("staffdeck.sched.result", "结果")}>
                <StatusPill tone={RUN_TONE[selectedRun.status] ?? "gray"}>
                  {RUN_LABEL[selectedRun.status] ?? selectedRun.status}
                </StatusPill>
              </Descriptions.Item>
              <Descriptions.Item label={t("staffdeck.sched.trigger", "触发方式")}>
                {triggerLabel(selectedRun)}
              </Descriptions.Item>
              <Descriptions.Item label={t("staffdeck.sched.started", "开始")}>
                {fmtTime(selectedRun.started_at)}
              </Descriptions.Item>
              <Descriptions.Item label={t("staffdeck.sched.finished", "结束")}>
                {fmtTime(selectedRun.finished_at)}
              </Descriptions.Item>
              <Descriptions.Item label={t("staffdeck.sched.duration", "耗时")}>
                {durationText(selectedRun)}
              </Descriptions.Item>
              {selectedRun.scheduled_for ? (
                <Descriptions.Item
                  label={t("staffdeck.sched.scheduledFor", "计划触发点")}
                >
                  {fmtTime(selectedRun.scheduled_for)}
                </Descriptions.Item>
              ) : null}
              {selectedRun.session_id ? (
                <Descriptions.Item label={t("staffdeck.sched.session", "会话 ID")}>
                  <Typography.Text copyable style={{ fontSize: 12 }}>
                    {selectedRun.session_id}
                  </Typography.Text>
                </Descriptions.Item>
              ) : null}
              {selectedRun.run_id ? (
                <Descriptions.Item label={t("staffdeck.sched.runId", "运行 ID")}>
                  <Typography.Text copyable style={{ fontSize: 12 }}>
                    {selectedRun.run_id}
                  </Typography.Text>
                </Descriptions.Item>
              ) : null}
            </Descriptions>

            <div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: "var(--sd-ink)" }}>
                {t("staffdeck.sched.summary", "结果摘要")}
              </div>
              <div
                style={{
                  background: "var(--sd-bg, #fafafa)",
                  border: "0.5px solid var(--sd-line)",
                  borderRadius: "var(--sd-radius-lg)",
                  padding: "10px 14px",
                  fontSize: 13,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  color: "var(--sd-ink)",
                }}
              >
                {selectedRun.result_summary || "—"}
              </div>
            </div>

            {selectedRun.error ? (
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: "var(--sd-ink)" }}>
                  {t("staffdeck.sched.error", "错误信息")}
                </div>
                <div
                  style={{
                    background: "var(--sd-red-bg, #fff1f0)",
                    borderRadius: "var(--sd-radius-lg)",
                    padding: "10px 14px",
                    fontSize: 13,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    color: "#cf1322",
                  }}
                >
                  {selectedRun.error}
                </div>
              </div>
            ) : null}

            {selectedRun.run_id ? (
              <Button
                type="primary"
                onClick={() => navigate(runDetailPath(selectedRun.run_id!))}
              >
                {t("staffdeck.sched.viewChain", "查看完整执行链")}
              </Button>
            ) : (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t(
                  "staffdeck.sched.noChain",
                  "该记录无关联运行（非 agent 任务或历史数据），无法查看执行链",
                )}
              </Typography.Text>
            )}
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}

export default CronTaskRunsPage;
