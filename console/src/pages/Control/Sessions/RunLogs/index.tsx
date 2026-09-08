/**
 * RunLogs — competitor-style run-log list for the Sessions page.
 * Toolbar mirrors the competitor: retention hint, search / status /
 * environment / date-range (default last 7 days) filters plus reset,
 * column-settings and refresh icon buttons. Clicking a row (or its id)
 * navigates to the full detail page at runs/:runId.
 */
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Input, Select, Table, Tag } from "@agentscope-ai/design";
import { Checkbox, DatePicker, Popover } from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import {
  CircleCheck,
  CircleX,
  LoaderCircle,
  RotateCcw,
  Settings2,
} from "lucide-react";
import { useAgentStore } from "../../../../stores/agentStore";
import { useExpertAvatarUri } from "../../../../hooks/useExpertAvatarUri";
import { CHANNEL_COLORS } from "../../../../constants/channel";
import type { RunLogItem } from "../../../../api/modules/runLogs";
import {
  useRunLogs,
  type RunEnvironmentFilter,
  type RunStatusFilter,
} from "./useRunLogs";
import { formatClock, formatDuration } from "./format";
import styles from "./runLogs.module.less";

const { RangePicker } = DatePicker;

/** Green ✓ / red ✗ / blue spinner, competitor-style status column. */
function StatusIcon({ status }: { status: string }) {
  if (status === "success") {
    return (
      <span
        className={`${styles.statusIcon} ${styles.statusIconSuccess}`}
        title={status}
      >
        <CircleCheck size={16} />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        className={`${styles.statusIcon} ${styles.statusIconFailed}`}
        title={status}
      >
        <CircleX size={16} />
      </span>
    );
  }
  return (
    <span
      className={`${styles.statusIcon} ${styles.statusIconRunning}`}
      title={status}
    >
      <LoaderCircle size={16} className={styles.statusSpin} />
    </span>
  );
}

/** DiceBear avatar for the chatting user (stable seed = user_id). */
function RunUserAvatar({ userId }: { userId: string }) {
  const avatar = useExpertAvatarUri(null, userId);
  if (avatar) {
    return <img className={styles.userAvatar} src={avatar} alt="" />;
  }
  return (
    <span className={styles.userAvatarFallback}>
      {(userId || "?").slice(0, 1).toUpperCase()}
    </span>
  );
}

export default function RunLogsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
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
    reset,
    refresh,
  } = useRunLogs(effectiveAgent);
  // Column visibility (competitor's column-settings popover).
  const [visibleKeys, setVisibleKeys] = useState<string[]>([]);

  const allColumns = useMemo(
    () => [
      {
        key: "status",
        title: t("runLogs.column.status", "状态"),
        dataIndex: "status",
        width: 64,
        render: (status: string) => <StatusIcon status={status} />,
      },
      {
        key: "environment",
        title: t("runLogs.column.environment", "环境"),
        dataIndex: "environment",
        width: 76,
        render: (env: string) => (
          <span
            className={`${styles.envTag} ${
              env === "debug" ? styles.envTagDebug : styles.envTagOnline
            }`}
          >
            {env === "debug"
              ? t("runLogs.env.debug", "调试")
              : t("runLogs.env.online", "线上")}
          </span>
        ),
      },
      {
        key: "query_preview",
        title: t("runLogs.column.query", "对话内容"),
        dataIndex: "query_preview",
        width: 240,
        ellipsis: true,
        render: (text: string) => (
          <span title={text}>{text || "—"}</span>
        ),
      },
      {
        key: "user_id",
        title: t("runLogs.column.user", "用户"),
        dataIndex: "user_id",
        width: 140,
        ellipsis: true,
        render: (text: string) =>
          text ? (
            <span className={styles.userCell} title={text}>
              <RunUserAvatar userId={text} />
              <span className={styles.userName}>{text}</span>
            </span>
          ) : (
            "—"
          ),
      },
      {
        key: "started_at",
        title: t("runLogs.column.startedAt", "开始时间"),
        dataIndex: "started_at",
        width: 160,
        render: (value: number) => formatClock(value),
      },
      {
        key: "channel",
        title: t("runLogs.column.channel", "渠道"),
        dataIndex: "channel",
        width: 130,
        render: (channel: string) =>
          channel ? (
            <Tag color={CHANNEL_COLORS[channel] || "default"}>{channel}</Tag>
          ) : (
            "—"
          ),
      },
      {
        key: "run_id",
        title: "Trace ID",
        dataIndex: "run_id",
        width: 150,
        render: (runId: string) => (
          <span
            className={styles.sessionId}
            title={runId}
            onClick={(event) => {
              event.stopPropagation();
              navigate(`runs/${runId}`);
            }}
            role="link"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                navigate(`runs/${runId}`);
              }
            }}
          >
            {runId.length > 14 ? `${runId.slice(0, 14)}…` : runId}
          </span>
        ),
      },
      {
        key: "session_id",
        title: t("runLogs.column.sessionId", "会话 ID"),
        dataIndex: "session_id",
        width: 150,
        ellipsis: true,
        render: (text: string) => (
          <span title={text} className={styles.sessionId}>
            {text || "—"}
          </span>
        ),
      },
      {
        key: "total_tokens",
        title: t("runLogs.column.tokens", "额度"),
        dataIndex: "total_tokens",
        width: 90,
        render: (value: number) =>
          typeof value === "number" && value > 0 ? value : "—",
      },
      {
        key: "duration_ms",
        title: t("runLogs.column.duration", "耗时"),
        dataIndex: "duration_ms",
        width: 100,
        render: (value: number | null) => formatDuration(value),
      },
      {
        key: "version",
        title: t("runLogs.column.version", "版本"),
        dataIndex: "version",
        width: 110,
        ellipsis: true,
        render: (_text: string, record: RunLogItem) => {
          // Prefer the model name; fall back to agent/app version labels.
          const label =
            record.model || record.version || record.app_version || "—";
          const tip = [record.model, record.version]
            .filter(Boolean)
            .join(" · ");
          return (
            <span title={tip || undefined} className={styles.sessionId}>
              {label}
            </span>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, navigate],
  );

  const columns = useMemo(
    () => allColumns.filter((column) => visibleKeys.includes(column.key)),
    [allColumns, visibleKeys],
  );

  const rangeValue =
    query.start && query.end
      ? ([dayjs.unix(query.start), dayjs.unix(query.end)] as [
          Dayjs,
          Dayjs,
        ])
      : null;

  return (
    <div className={styles.runLogsPage}>
      <div className={styles.retentionHint}>
        {t(
          "runLogs.retentionHint",
          "运行日志仅存储智能体近 30 天的运行日志，如需更长周期请及时备份",
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
          value={rangeValue}
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
        <span className={styles.filterActions}>
          <button
            type="button"
            className={styles.filterIconBtn}
            title={t("runLogs.filter.reset", "重置筛选")}
            onClick={reset}
          >
            <RotateCcw size={14} />
          </button>
          <Popover
            trigger="click"
            placement="bottomRight"
            content={
              <div className={styles.columnMenu}>
                {allColumns.map((column) => (
                  <label key={column.key} className={styles.columnMenuItem}>
                    <Checkbox
                      checked={visibleKeys.includes(column.key)}
                      onChange={(event) =>
                        setVisibleKeys((prev) =>
                          event.target.checked
                            ? [...prev, column.key]
                            : prev.filter((key) => key !== column.key),
                        )
                      }
                    >
                      {column.title as string}
                    </Checkbox>
                  </label>
                ))}
              </div>
            }
          >
            <button
              type="button"
              className={styles.filterIconBtn}
              title={t("runLogs.filter.columns", "列设置")}
            >
              <Settings2 size={14} />
            </button>
          </Popover>
          <button
            type="button"
            className={styles.filterIconBtn}
            title={t("common.refresh", "刷新")}
            onClick={() => refresh()}
          >
            <RotateCcw size={14} />
          </button>
        </span>
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
          onClick: () => navigate(`runs/${record.run_id}`),
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
    </div>
  );
}
