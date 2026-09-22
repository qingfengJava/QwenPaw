/**
 * TeamOpsTab — 运维（团队详情页 Tab）。
 *
 * 团队运行记录只读视图：状态、目标、返工/重规划次数与时间线。
 * 数据来自 /admin/workforce/runs（team_id 过滤，一次拉取 limit 上限），
 * 状态色映射与文案走 i18n；接口失败（无权限等）降级为提示 + 重试按钮，
 * 不阻断会话 Tab。点击行跳转至运行日志详情（经外壳 MemoryRouter 路径）。
 */
import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import { adminWorkforceApi } from "../../../../api/modules/admin/workforce";
import type {
  AdminRunStatus,
  AdminTeamRun,
} from "../../../../api/modules/admin/workforce";

/** 拉取条数上限（列表页样本，详情趋势看运行记录页）。 */
const RUN_LIMIT = 50;

/** 状态 → Tag 色（与 AdminRunStatus 状态机对齐，未知态用 default）。 */
const STATUS_COLOR: Partial<Record<AdminRunStatus, string>> = {
  done: "green",
  failed: "red",
  escalated: "orange",
  running: "blue",
  planning: "cyan",
  verifying: "cyan",
  repairing: "gold",
  awaiting_confirm: "purple",
  aggregating: "cyan",
  canceled: "default",
  interrupted: "default",
};

export interface TeamOpsTabProps {
  teamId: string;
  /** 外壳 navigate 函数（团队详情容器传入）。 */
  onNavigate?: (path: string) => void;
}

export default function TeamOpsTab({ teamId, onNavigate }: TeamOpsTabProps) {
  const { t } = useTranslation();
  const [runs, setRuns] = useState<AdminTeamRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchRuns = useCallback(() => {
    setLoading(true);
    setError("");
    adminWorkforceApi
      .listRuns({ team_id: teamId, limit: RUN_LIMIT })
      .then((rows) => {
        setRuns(rows);
      })
      .catch((err) => {
        setError(String(err));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [teamId]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // 点击行跳转至运行日志详情（路径经外壳 MemoryRouter 解析）。
  const handleRowClick = useCallback(
    (record: AdminTeamRun) => {
      if (!onNavigate) return;
      onNavigate(`/studio/team_${teamId}/sessions/runs/${record.id}`);
    },
    [onNavigate, teamId],
  );

  if (error) {
    return (
      <Alert
        type="warning"
        showIcon
        message={t("workbench.team.opsLoadFailed", "运行记录加载失败")}
        description={error}
        action={
          <Button size="small" onClick={fetchRuns}>
            {t("common.retry", "重试")}
          </Button>
        }
      />
    );
  }

  const columns: ColumnsType<AdminTeamRun> = [
    {
      title: t("workbench.team.colStatus", "状态"),
      dataIndex: "status",
      width: 110,
      align: "center",
      render: (status: AdminRunStatus) => (
        <Tag color={STATUS_COLOR[status] ?? "default"}>{status}</Tag>
      ),
    },
    {
      title: t("workbench.team.colGoal", "任务目标"),
      dataIndex: "goal",
      ellipsis: true,
      render: (goal: string) => goal || "—",
    },
    {
      title: t("workbench.team.colRepairs", "返工/重规划"),
      key: "repair",
      width: 120,
      align: "center",
      render: (_, row) => `${row.repair_count} / ${row.replan_count}`,
    },
    {
      title: t("workbench.team.colCreated", "发起时间"),
      dataIndex: "created_at",
      width: 170,
      align: "center",
      render: (v: string | null) =>
        v ? new Date(v).toLocaleString("zh-CN") : "—",
    },
    {
      title: t("workbench.team.colUpdated", "最近更新"),
      dataIndex: "updated_at",
      width: 170,
      align: "center",
      render: (v: string | null) =>
        v ? new Date(v).toLocaleString("zh-CN") : "—",
    },
  ];

  return (
    <div>
      <Typography.Text
        type="secondary"
        style={{ fontSize: 12, display: "block", marginBottom: 8 }}
      >
        {t(
          "workbench.team.opsHint",
          "最近可见运行（点击行可查看运行详情）",
        )}
      </Typography.Text>
      <Table<AdminTeamRun>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={runs}
        pagination={false}
        columns={columns}
        onRow={(record) => ({
          onClick: () => handleRowClick(record),
          style: { cursor: onNavigate ? "pointer" : "default" },
        })}
        locale={{
          emptyText: t("workbench.team.opsEmpty", "该团队暂无运行记录"),
        }}
      />
    </div>
  );
}
