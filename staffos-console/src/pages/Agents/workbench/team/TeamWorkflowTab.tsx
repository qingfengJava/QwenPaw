/**
 * TeamWorkflowTab — 协作流程（团队详情页 Tab，只读展示）。
 *
 * 配置侧（管理后台 TeamDetailPage）负责编辑，此处只读呈现：标准链
 * / 快速链波次预览（复用 WavePreview）、RunPolicy 熔断边界、计划备
 * 注与编排开关状态。i18n 键与配置侧共用（admin.teamDetail.policy*），
 * 保证同一概念全端同一文案。
 */
import { Button, Descriptions, Tag, Typography } from "antd";
import { Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { addRouterBasename } from "@/utils/navigationMode";
import WavePreview from "../../manage/WavePreview";
import type { ExpertTeamRecord, TeamMetadata } from "../../../../api/modules/admin";
import styles from "./teamDetail.module.less";

/** RunPolicy 数值字段（与 TeamPolicyForm/后端 contracts.RunPolicy 一致）。 */
const POLICY_FIELD_LABEL_KEYS: Record<string, string> = {
  max_repair_per_node: "admin.teamDetail.policyMaxRepair",
  max_replan: "admin.teamDetail.policyMaxReplan",
  max_total_seconds: "admin.teamDetail.policyMaxSeconds",
  max_total_tokens: "admin.teamDetail.policyMaxTokens",
  parallelism: "admin.teamDetail.policyParallelism",
};

export interface TeamWorkflowTabProps {
  team: ExpertTeamRecord;
  teamId: string;
  canManage: boolean;
  /** 元数据（提供有效默认值，前端不硬编码 true/false 或默认限额）。 */
  metadata: TeamMetadata | null;
}

export default function TeamWorkflowTab({
  team,
  teamId,
  canManage,
  metadata,
}: TeamWorkflowTabProps) {
  const { t } = useTranslation();
  const orch = team.orchestration ?? {};
  const policy = (orch.policy ?? {}) as Record<string, number>;
  const nodes = Array.isArray(orch.nodes) ? (orch.nodes as unknown[]) : [];
  const fastNodes = Array.isArray(orch.fast_nodes)
    ? (orch.fast_nodes as unknown[])
    : [];
  // 有效配置：runtime_enabled 缺省 true（后端统一提供，前端不硬编码）
  const defaultRuntime = metadata?.default_runtime_enabled ?? true;
  const runtimeEnabled =
    typeof orch.runtime_enabled === "boolean"
      ? orch.runtime_enabled
      : defaultRuntime;
  const planNote = typeof orch.plan_note === "string" ? orch.plan_note : "";

  const goToConfig = () => {
    window.location.assign(
      addRouterBasename(window.location.pathname, `/agents/teams/${teamId}`),
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div className={styles.sectionTitle}>
          {t("workbench.team.workflowTitle", "协作流程")}
          <Tag color={runtimeEnabled ? "geekblue" : "default"}>
            {runtimeEnabled
              ? t("workbench.team.orchOn", "运行时编排")
              : t("workbench.team.orchOff", "基础模式")}
          </Tag>
        </div>
        <Typography.Paragraph
          type="secondary"
          style={{ fontSize: 12, marginTop: 10 }}
        >
          {t(
            "admin.teamDetail.workflowHint",
            "协作流程决定成员如何接力：预置 DAG 模板时规划器按模板派发（模板优先）；留空则由中央大脑（主理人）按需求单次规划。多个节点写相同 deps 即并行执行。",
          )}
        </Typography.Paragraph>
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 13, color: "var(--sd-ink)", marginBottom: 8 }}>
            {t("workbench.team.standardChain", "标准链")}
          </div>
          <WavePreview
            nodesJson={nodes.length ? JSON.stringify(nodes) : ""}
            emptyHint={t(
              "workbench.team.noNodes",
              "尚未预置节点模板（由中央大脑按需求规划）",
            )}
          />
        </div>
        {fastNodes.length > 0 ? (
          <div style={{ marginTop: 16 }}>
            <div
              style={{ fontSize: 13, color: "var(--sd-ink)", marginBottom: 8 }}
            >
              {t("workbench.team.fastChain", "快速链（小需求精简流程）")}
            </div>
            <WavePreview nodesJson={JSON.stringify(fastNodes)} />
          </div>
        ) : null}
        {planNote ? (
          <Typography.Paragraph
            style={{ marginTop: 14, fontSize: 13, marginBottom: 0 }}
          >
            {t("workbench.team.planNote", "编排意图")}：{planNote}
          </Typography.Paragraph>
        ) : null}
      </div>

      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div className={styles.sectionTitle}>
          {t("workbench.team.policyTitle", "运行边界（RunPolicy）")}
        </div>
        <Typography.Paragraph
          type="secondary"
          style={{ fontSize: 12, marginTop: 10 }}
        >
          {t(
            "admin.teamDetail.policyHint",
            "Harness 治理策略是该团队每次运行的熔断上限：返工/重规划次数、时限与 token 预算超限即熔断升级人工；并行度限制同时派发的成员数。默认值来自平台元数据。",
          )}
        </Typography.Paragraph>
        <Descriptions size="small" column={2} style={{ marginTop: 8 }}>
          {(() => {
            // 有效配置：从 metadata.limits 取默认值（后端唯一来源，前端不硬编码）
            const limits = (metadata?.limits ?? {}) as Record<string, number>;
            return Object.entries(POLICY_FIELD_LABEL_KEYS).map(([field, key]) => {
              const limitKey = `default_${field}`;
              const defaultVal = limits[limitKey];
              const value = policy[field] ?? defaultVal;
              return (
                <Descriptions.Item
                  key={field}
                  label={t(key, field)}
                >
                  {value !== undefined && value !== null ? value : "—"}
                </Descriptions.Item>
              );
            });
          })()}
        </Descriptions>
      </div>

      {canManage ? (
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Button icon={<Settings2 size={14} />} onClick={goToConfig}>
            {t("workbench.team.goConfigEdit", "前往配置工作台调整")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
