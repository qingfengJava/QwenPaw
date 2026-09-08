/**
 * RunLogs — competitor-style run-log list for the Sessions page.
 * Columns: status / environment / query preview / user / start time /
 * channel / trace id / session id / tokens / duration / version.
 * Mounted inside SessionsPage's Tabs (key="runs") and lazy-loaded.
 */
import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button, Input, Select, Table } from "@agentscope-ai/design";
import { DatePicker } from "antd";
import type { Dayjs } from "dayjs";
import { StatusPill } from "@/components/staffdeck";
import { useAgentStore } from "../../../../stores/agentStore";
import { ChannelIcon } from "../../Channels/components";
import type { RunLogItem } from "../../../../api/modules/runLogs";
import {
  useRunLogs,
  type RunEnvironmentFilter,
  type RunStatusFilter,
} from "./useRunLogs";
import { RunLogDetailDrawer, formatClock, formatDuration } from "./RunLogDetailDrawer";
import styles from "./runLogs.module.less";

const { RangePicker } = DatePicker;

/** 76b3e9a2f1c8… — short copyable trace id cell. */
function TraceIdCell({ runId }: { runId: string }) {
  const short = runId.length > 14 ? `${runId.slice(0, 14)}…` : runId;
  return (
    <button
      type="button"
      className={styles.traceId}
      title={runId}
      onClick={(event) => {
        event.stopPropagation();
        navigator.clipboard?.writeText(runId).catch(() => undefined);
      }}
    >
      {short}
    </button>
  );
}

export default function RunLogsPage() {
  const { t } = useTranslation();
  // 详情页/工作台内时 :aid 显式指定数据域；独立挂载时回退 selectedAgent（借壳）。
  const { aid } = useParams<{ aid: string }>();
  const { selectedAgent } = useAgentStore();
  const effectiveAgent = aid ?? selectedAgent;
  const {
    items,
    total,
    loading,
    error,
    query,
    patchQuery,
    setPage,
    refresh,
  } = useRunLogs(effectiveAgent);
  const [detailRun, setDetailRun] = useState<RunLogItem | null>(null);

  const statusLabel = (status: string) => {
    if (status === "success") {
      return t("runLogs.status.success", "成功");
    }
    if (status === "failed") {
      return t("runLogs.status.failed", "失败");
    }
    return t("runLogs.status.running", "运行中");
  };

  const statusTone = (status: string) => {
    if (status === "success") {
      return "green" as const;
    }
    if (status === "failed") {
      return "red" as const;
    }
    return "blue" as const;
  };

  const columns = useMemo(
    () => [
      {
        title: t("runLogs.column.status", "状态"),
        dataIndex: "status",
        key: "status",
        width: 90,
        render: (status: string) => (
          <StatusPill tone={statusTone(status)}>{statusLabel(status)}</StatusPill>
        ),
      },
      {
        title: t("runLogs.column.environment", "环境"),
        dataIndex: "environment",
        key: "environment",
        width: 80,
        render: (env: string) => (
          <span className={styles.envTag}>
            {env === "debug"
              ? t("runLogs.env.debug", "调试")
              : t("runLogs.env.online", "线上")}
          </span>
        ),
      },
      {
        title: t("runLogs.column.query", "对话内容"),
        dataIndex: "query_preview",
        key: "query_preview",
        width: 260,
        ellipsis: true,
        render: (text: string) => text || "—",
      },
      {
        title: t("runLogs.column.user", "用户"),
        dataIndex: "user_id",
        key: "user_id",
        width: 120,
        ellipsis: true,
        render: (text: string) => text || "—",
      },
      {
        title: t("runLogs.column.startedAt", "开始时间"),
        dataIndex: "started_at",
        key: "started_at",
        width: 170,
        render: (value: number) => formatClock(value),
      },
      {
        title: t("runLogs.column.channel", "渠道"),
        dataIndex: "channel",
        key: "channel",
        width: 130,
        render: (channel: string) =>
          channel ? (
            <span className={styles.channelCell}>
              <ChannelIcon channelKey={channel} size={16} />
              <span>{channel}</span>
            </span>
          ) : (
            "—"
          ),
      },
      {
        title: "Trace ID",
        dataIndex: "run_id",
        key: "run_id",
        width: 150,
        render: (runId: string) => <TraceIdCell runId={runId} />,
      },
      {
        title: t("runLogs.column.sessionId", "会话 ID"),
        dataIndex: "session_id",
        key: "session_id",
        width: 150,
        ellipsis: true,
        render: (text: string) => (
          <span title={text} className={styles.sessionId}>
            {text || "—"}
          </span>
        ),
      },
      {
        title: t("runLogs.column.tokens", "额度"),
        dataIndex: "total_tokens",
        key: "total_tokens",
        width: 90,
        render: (value: number) =>
          typeof value === "number" && value > 0 ? value : "—",
      },
      {
        title: t("runLogs.column.duration", "耗时"),
        dataIndex: "duration_ms",
        key: "duration_ms",
        width: 100,
        render: (value: number | null) => formatDuration(value),
      },
      {
        title: t("runLogs.column.version", "版本"),
        dataIndex: "version",
        key: "version",
        width: 90,
        render: (text: string) => text || "—",
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t],
  );

  return (
    <div className={styles.runLogsPage}>
      <div className={styles.retentionHint}>
        {t(
          "runLogs.retentionHint",
          "运行日志仅保留近 30 天，如需更长周期请及时备份",
        )}
      </div>

      <div className={styles.filterBar}>
        <Input
          allowClear
          className={styles.searchInput}
          placeholder={t("runLogs.searchPlaceholder", "通过对话内容或 Trace ID 搜索")}
          value={query.keyword}
          onChange={(event) => patchQuery({ keyword: event.target.value })}
        />
        <Select
          allowClear
          className={styles.statusSelect}
          placeholder={t("runLogs.column.status", "状态")}
          value={query.status || undefined}
          onChange={(value) =>
            patchQuery({ status: (value ?? "") as RunStatusFilter })
          }
          options={[
            { value: "success", label: t("runLogs.status.success", "成功") },
            { value: "failed", label: t("runLogs.status.failed", "失败") },
            { value: "running", label: t("runLogs.status.running", "运行中") },
          ]}
        />
        <Select
          allowClear
          className={styles.envSelect}
          placeholder={t("runLogs.column.environment", "环境")}
          value={query.environment || undefined}
          onChange={(value) =>
            patchQuery({ environment: (value ?? "") as RunEnvironmentFilter })
          }
          options={[
            { value: "online", label: t("runLogs.env.online", "线上") },
            { value: "debug", label: t("runLogs.env.debug", "调试") },
          ]}
        />
        <RangePicker
          className={styles.rangePicker}
          onChange={(dates: [Dayjs | null, Dayjs | null] | null) => {
            if (dates && dates[0] && dates[1]) {
              patchQuery({
                start: dates[0].startOf("day").unix(),
                end: dates[1].endOf("day").unix(),
              });
            } else {
              patchQuery({ start: null, end: null });
            }
          }}
        />
        <Button onClick={() => refresh()}>{t("common.refresh", "刷新")}</Button>
      </div>

      {error && <div className={styles.loadError}>{error}</div>}

      <Table
        columns={columns}
        dataSource={items}
        loading={loading}
        rowKey="run_id"
        size="middle"
        onRow={(record) => ({
          className: styles.clickableRow,
          onClick: () => setDetailRun(record),
        })}
        pagination={{
          current: query.page,
          pageSize: query.pageSize,
          total,
          showSizeChanger: false,
          showTotal: (count) =>
            t("runLogs.totalCount", "共 {{count}} 条", { count }),
          onChange: (page, pageSize) => setPage(page, pageSize),
        }}
      />

      <RunLogDetailDrawer
        open={detailRun !== null}
        run={detailRun}
        onClose={() => setDetailRun(null)}
      />
    </div>
  );
}
