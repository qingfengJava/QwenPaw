/**
 * Admin/WorkforceRuns — tenant-wide workforce team-run operations view:
 * aggregate stat cards (volume / outcomes / repair & escalation rates /
 * token cost) plus the full run list with status filters. Read-only —
 * intervention lives in XianWork's run detail page.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Col,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { adminWorkforceApi } from "../../../api/modules/admin";
import type { AdminRunStats, AdminTeamRun } from "../../../api/modules/admin";
import styles from "@/pages/Admin/admin.module.less";

/** run 状态 → Tag 颜色（与 xianwork RunDetail 语义一致）。 */
const STATUS_COLORS: Record<string, string> = {
  planning: "default",
  awaiting_confirm: "orange",
  running: "processing",
  verifying: "processing",
  repairing: "orange",
  aggregating: "purple",
  done: "success",
  failed: "error",
  escalated: "error",
  canceled: "default",
  interrupted: "warning",
};

const STATUS_OPTIONS = Object.keys(STATUS_COLORS).map((value) => ({
  value,
  label: value,
}));

function formatTokens(n: number): string {
  if (!n || n <= 0) return "0";
  if (n >= 10_000_000) return `${(n / 10_000_000).toFixed(1)}千万`;
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)}万`;
  return String(n);
}

function WorkforceRunsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [runs, setRuns] = useState<AdminTeamRun[]>([]);
  const [stats, setStats] = useState<AdminRunStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [runList, stat] = await Promise.all([
        adminWorkforceApi.listRuns({ status: statusFilter, limit: 200 }),
        adminWorkforceApi.stats().catch(() => null),
      ]);
      setRuns(runList);
      setStats(stat);
    } catch (err) {
      message.error(
        t("admin.workforce.loadFailed", "Failed to load team runs"),
      );
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [message, statusFilter, t]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.employees", "Digital Employees")}
        current={t("nav.agentRuns", "Run History")}
      />

      {stats && (
        <Row gutter={12} style={{ marginBottom: 16 }}>
          <Col span={3}>
            <Card size="small">
              <Statistic
                title={t("admin.workforce.total", "Total runs")}
                value={stats.total_runs}
              />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic
                title={t("admin.workforce.active", "Active")}
                value={stats.active}
                valueStyle={{ color: "#1677ff" }}
              />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic
                title={t("admin.workforce.done", "Done")}
                value={stats.done}
                valueStyle={{ color: "#52c41a" }}
              />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic
                title={t("admin.workforce.escalated", "Escalated")}
                value={stats.escalated}
                valueStyle={{ color: "#cf1322" }}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title={t("admin.workforce.repairRate", "Repair rate")}
                value={(stats.repair_rate * 100).toFixed(1)}
                suffix="%"
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title={t("admin.workforce.escalationRate", "Escalation rate")}
                value={(stats.escalation_rate * 100).toFixed(1)}
                suffix="%"
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title={t("admin.workforce.tokens", "Token cost")}
                value={formatTokens(stats.tokens_total)}
              />
            </Card>
          </Col>
        </Row>
      )}

      <Space style={{ marginBottom: 12 }}>
        <Select
          allowClear
          placeholder={t("admin.workforce.statusFilter", "Filter by status")}
          style={{ width: 200 }}
          options={STATUS_OPTIONS}
          value={statusFilter}
          onChange={(value) => setStatusFilter(value)}
        />
      </Space>

      <Table<AdminTeamRun>
        rowKey="id"
        loading={loading}
        dataSource={runs}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          {
            title: t("admin.workforce.runId", "Run"),
            dataIndex: "id",
            width: 200,
            render: (id: string) => (
              <Typography.Text copyable style={{ fontSize: 12 }}>
                {id}
              </Typography.Text>
            ),
          },
          {
            title: t("admin.workforce.goal", "Goal"),
            dataIndex: "goal",
            ellipsis: true,
            render: (goal: string, run) => (
              <Tooltip
                title={run.escalation_reason || run.error || goal}
                placement="topLeft"
              >
                {goal}
              </Tooltip>
            ),
          },
          {
            title: t("admin.workforce.initiator", "Initiator"),
            dataIndex: "initiator_id",
            width: 120,
            ellipsis: true,
          },
          {
            title: t("admin.workforce.status", "Status"),
            dataIndex: "status",
            width: 130,
            render: (status: string) => (
              <Tag color={STATUS_COLORS[status] ?? "default"}>{status}</Tag>
            ),
          },
          {
            title: t("admin.workforce.repairs", "Repairs / Replans"),
            key: "counts",
            width: 140,
            render: (_, run) => `${run.repair_count} / ${run.replan_count}`,
          },
          {
            title: t("admin.workforce.createdAt", "Created"),
            dataIndex: "created_at",
            width: 170,
            render: (at: string | null) =>
              (at ?? "").slice(0, 19).replace("T", " ") || "—",
          },
        ]}
      />
    </div>
  );
}

export default WorkforceRunsPage;
