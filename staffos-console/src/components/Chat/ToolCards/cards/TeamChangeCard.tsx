/**
 * TeamChangeCard — AI 团队配置变更确认卡片。
 *
 * 渲染 ``team_prepare_change`` / ``team_prepare_publish`` 工具结果：
 * - 差异卡（字段级 old → new）
 * - 校验结果（ok / issues 列表）
 * - 确认 / 拒绝按钮（仅 pending 态可操作）
 * - 终态回执（applied / rejected / expired / conflict / failed）
 *
 * 用户点击确认后调用 HTTP 确认端点，服务端执行 CAS 写入；
 * 拒绝同理。操作完成后卡片就地更新为回执态。
 *
 * @author qingfeng
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  RocketOutlined,
  StopOutlined,
  ClockCircleOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { Button, Tag } from "antd";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { adminExpertTeamsApi } from "@/api/modules/admin/expertTeams";
import type {
  ChangeRequestStatus,
  ChangeRequestStatusMeta,
} from "@/api/modules/admin/expertTeams";

export interface TeamChangeCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

/** 工具结果 JSON 解析后的结构化数据。 */
interface ParsedResult {
  request_id: string;
  team_id: string;
  kind: "save_draft" | "publish";
  diff?: Record<string, { old: unknown; new: unknown }>;
  validation?: { ok: boolean; issues: string[] };
  base_revision?: number;
  current_version?: number;
  draft_revision?: number;
  member_count?: number;
  expires_at?: string;
  status?: string;
  message?: string;
}

/**
 * 状态文案与颜色：唯一来源是后端 metadata（change_request_statuses）；
 * metadata 未加载/失败时回退到 i18n key + 默认文案（不硬编码最终
 * 展示文案，仅作降级孪底）。
 */
const STATUS_FALLBACK_LABEL: Record<ChangeRequestStatus, string> = {
  pending: "待确认",
  applying: "执行中",
  applied: "已生效",
  rejected: "已拒绝",
  expired: "已过期",
  conflict: "冲突",
  failed: "失败",
};

/** metadata 未加载时的颜色降级（UI 展示语义，允许前端保留）。 */
const STATUS_FALLBACK_COLOR: Record<ChangeRequestStatus, string> = {
  pending: "blue",
  applying: "processing",
  applied: "success",
  rejected: "default",
  expired: "warning",
  conflict: "error",
  failed: "error",
};

/** module 级 metadata 缓存（同会话多卡片只拉一次）。 */
let statusMetaCache: ChangeRequestStatusMeta[] | null = null;

async function fetchStatusMeta(): Promise<ChangeRequestStatusMeta[]> {
  if (statusMetaCache) return statusMetaCache;
  try {
    const meta = await adminExpertTeamsApi.metadata();
    statusMetaCache = meta.change_request_statuses ?? [];
  } catch {
    statusMetaCache = [];
  }
  return statusMetaCache;
}

function parseResult(content: ToolCallContent): ParsedResult | null {
  const raw = content.result;
  if (!raw) return null;
  const text = typeof raw === "string" ? raw : JSON.stringify(raw);
  try {
    return JSON.parse(text) as ParsedResult;
  } catch {
    return null;
  }
}

const TeamChangeCard: React.FC<TeamChangeCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const parsed = useMemo(() => parseResult(content), [content]);

  // 后端 metadata 的提案状态文案/颜色（唯一来源；加载后覆盖降级值）
  const [statusMeta, setStatusMeta] = useState<ChangeRequestStatusMeta[]>([]);
  useEffect(() => {
    let cancelled = false;
    fetchStatusMeta().then((meta) => {
      if (!cancelled) setStatusMeta(meta);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const metaByValue = useMemo(
    () => new Map(statusMeta.map((m) => [m.value, m])),
    [statusMeta],
  );
  const statusLabel = useCallback(
    (s: ChangeRequestStatus) =>
      metaByValue.get(s)?.label ??
      t(`teamChange.status.${s}`, STATUS_FALLBACK_LABEL[s]),
    [metaByValue, t],
  );
  const statusColor = useCallback(
    (s: ChangeRequestStatus) =>
      metaByValue.get(s)?.color ?? STATUS_FALLBACK_COLOR[s],
    [metaByValue],
  );

  // 本地操作状态：初始从工具结果读取，操作后更新
  const [localStatus, setLocalStatus] = useState<ChangeRequestStatus>(
    (parsed?.status as ChangeRequestStatus) || "pending",
  );
  const [operating, setOperating] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);

  const isPending = localStatus === "pending";
  const isPublish = parsed?.kind === "publish";

  const cardTitle = useMemo(() => {
    if (isPublish) {
      return t("teamChange.publishTitle", "团队发布确认");
    }
    return t("teamChange.changeTitle", "团队配置变更");
  }, [isPublish, t]);

  // 通知 useTeamDetail 刷新分区数据（跨组件通信，走 window 自定义事件）。
  const notifyConfigChanged = useCallback(() => {
    if (!parsed) return;
    window.dispatchEvent(
      new CustomEvent("qwenpaw:team-config-changed", {
        detail: { teamId: parsed.team_id },
      }),
    );
  }, [parsed]);

  const handleConfirm = useCallback(async () => {
    if (!parsed || operating) return;
    setOperating(true);
    setOperationError(null);
    try {
      const result = await adminExpertTeamsApi.confirmChangeRequest(
        parsed.team_id,
        parsed.request_id,
      );
      setLocalStatus(result.status);
      // 确认成功后通知右侧详情面板刷新
      notifyConfigChanged();
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : t("teamChange.confirmFailed", "确认操作失败");
      setOperationError(msg);
    } finally {
      setOperating(false);
    }
  }, [parsed, operating, t, notifyConfigChanged]);

  const handleReject = useCallback(async () => {
    if (!parsed || operating) return;
    setOperating(true);
    setOperationError(null);
    try {
      const result = await adminExpertTeamsApi.rejectChangeRequest(
        parsed.team_id,
        parsed.request_id,
      );
      setLocalStatus(result.status);
      // 拒绝后同样通知刷新（状态从 pending → rejected）
      notifyConfigChanged();
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : t("teamChange.rejectFailed", "拒绝操作失败");
      setOperationError(msg);
    } finally {
      setOperating(false);
    }
  }, [parsed, operating, t, notifyConfigChanged]);

  // 工具还在执行中或无解析结果 → 用通用壳展示
  if (content.status === "calling" || !parsed) {
    return (
      <ToolCardShell
        content={content}
        isStreaming={isStreaming}
        icon={isPublish ? <RocketOutlined /> : <EditOutlined />}
        title={cardTitle}
      />
    );
  }

  // 终态回执图标
  const statusIcon = (() => {
    switch (localStatus) {
      case "applied":
        return <CheckCircleOutlined style={{ color: "#52c41a" }} />;
      case "rejected":
        return <CloseCircleOutlined style={{ color: "#8c8c8c" }} />;
      case "expired":
        return <ClockCircleOutlined style={{ color: "#faad14" }} />;
      case "conflict":
      case "failed":
        return <WarningOutlined style={{ color: "#ff4d4f" }} />;
      default:
        return null;
    }
  })();

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={isPublish ? <RocketOutlined /> : <EditOutlined />}
      title={cardTitle}
      defaultExpanded={isPending}
      badges={
        <Tag color={statusColor(localStatus)}>
          {statusLabel(localStatus)}
        </Tag>
      }
    >
      <div style={{ padding: "8px 0" }}>
        {/* 差异卡（仅 save_draft 有） */}
        {parsed.diff && Object.keys(parsed.diff).length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div
              style={{
                fontSize: 12,
                color: "#8c8c8c",
                marginBottom: 4,
                fontWeight: 500,
              }}
            >
              {t("teamChange.diffLabel", "变更内容")}
            </div>
            {Object.entries(parsed.diff).map(([field, change]) => (
              <div
                key={field}
                style={{
                  fontSize: 12,
                  padding: "4px 8px",
                  background: "#fafafa",
                  borderRadius: 4,
                  marginBottom: 4,
                  borderLeft: "3px solid #1677ff",
                }}
              >
                <span style={{ fontWeight: 500 }}>{field}</span>
                <span style={{ color: "#ff4d4f", marginLeft: 8 }}>
                  -{String(change.old ?? "∅")}
                </span>
                <span style={{ color: "#52c41a", marginLeft: 8 }}>
                  +{String(change.new ?? "∅")}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* 发布摘要（仅 publish 有） */}
        {isPublish && (
          <div style={{ marginBottom: 12, fontSize: 12, color: "#595959" }}>
            <div>
              {t("teamChange.currentVersion", "当前版本")}:{" "}
              <strong>v{parsed.current_version ?? 0}</strong>
            </div>
            <div>
              {t("teamChange.draftRevision", "草稿修订")}:{" "}
              <strong>#{parsed.draft_revision ?? 0}</strong>
            </div>
            {parsed.member_count != null && (
              <div>
                {t("teamChange.memberCount", "成员数")}:{" "}
                <strong>{parsed.member_count}</strong>
              </div>
            )}
          </div>
        )}

        {/* 校验结果 */}
        {parsed.validation && (
          <div style={{ marginBottom: 12 }}>
            {parsed.validation.ok ? (
              <Tag color="success" icon={<CheckCircleOutlined />}>
                {t("teamChange.validationOk", "校验通过")}
              </Tag>
            ) : (
              <div>
                <Tag color="warning" icon={<ExclamationCircleOutlined />}>
                  {t("teamChange.validationIssues", "校验问题")}
                </Tag>
                <ul
                  style={{
                    margin: "4px 0 0",
                    padding: "0 0 0 16px",
                    fontSize: 12,
                    color: "#ff4d4f",
                  }}
                >
                  {parsed.validation.issues.map((issue, idx) => (
                    <li key={idx}>{issue}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* 操作按钮（仅 pending 态） */}
        {isPending && (
          <div
            style={{
              display: "flex",
              gap: 8,
              marginTop: 8,
              alignItems: "center",
            }}
          >
            <Button
              type="primary"
              size="small"
              icon={<CheckCircleOutlined />}
              loading={operating}
              onClick={handleConfirm}
            >
              {isPublish
                ? t("teamChange.confirmPublish", "确认发布")
                : t("teamChange.confirmSave", "保存草稿")}
            </Button>
            <Button
              size="small"
              icon={<StopOutlined />}
              loading={operating}
              onClick={handleReject}
            >
              {t("teamChange.reject", "拒绝")}
            </Button>
          </div>
        )}

        {/* 终态回执 */}
        {!isPending && statusIcon && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: 12,
              color: "#595959",
              marginTop: 8,
              padding: "6px 8px",
              background: "#fafafa",
              borderRadius: 4,
            }}
          >
            {statusIcon}
            <span>
              {statusLabel(localStatus)}
              {localStatus === "applied" &&
                ` · ${t("teamChange.appliedHint", "配置已写入草稿")}`}
              {localStatus === "rejected" &&
                ` · ${t("teamChange.rejectedHint", "变更已取消")}`}
              {localStatus === "expired" &&
                ` · ${t("teamChange.expiredHint", "提案已超时过期")}`}
              {(localStatus === "conflict" || localStatus === "failed") &&
                ` · ${t("teamChange.failedHint", "请重新发起变更")}`}
            </span>
          </div>
        )}

        {/* 操作错误提示 */}
        {operationError && (
          <div
            style={{
              marginTop: 8,
              padding: "4px 8px",
              background: "#fff2f0",
              border: "1px solid #ffccc7",
              borderRadius: 4,
              fontSize: 12,
              color: "#ff4d4f",
            }}
          >
            {operationError}
          </div>
        )}

        {/* 消息（工具返回的原始提示） */}
        {parsed.message && isPending && (
          <div
            style={{
              marginTop: 8,
              fontSize: 12,
              color: "#8c8c8c",
              whiteSpace: "pre-wrap",
            }}
          >
            {parsed.message}
          </div>
        )}
      </div>
    </ToolCardShell>
  );
};

export default TeamChangeCard;
