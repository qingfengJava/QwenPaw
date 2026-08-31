import { Button, Card, Descriptions, Space, Tag } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MessageCircle, FolderOpen, Clock } from "lucide-react";
import { AgentStatusIndicator } from "@/components/AgentStatusIndicator";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import type { AgentSummary } from "@/api/types/agents";
import styles from "./detail.module.less";

interface AgentOverviewTabProps {
  /** agents 尚未加载完成时为 undefined，此时仅渲染 aid。 */
  agent: AgentSummary | undefined;
  aid: string;
}

/**
 * 员工概览 Tab：档案信息卡 + 快捷入口。
 *
 * 指标说明：今日会话/好评率等指标依赖按员工聚合的后端接口
 * （chats 表无 agent 维度字段、feedback 仅有写入接口），为避免
 * 展示失真数据，本期先提供档案与资源入口，聚合接口到位后补齐
 * 指标卡（详见平台 IA 计划阶段 4 / P2 优化项）。
 */
export default function AgentOverviewTab({ agent, aid }: AgentOverviewTabProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const open = (tab: string) => navigate(`/agents/${aid}/${tab}`);

  return (
    <div className={styles.overviewWrap}>
      <Card className={styles.overviewCard} size="small">
        <div className={styles.overviewHead}>
          <AgentStatusIndicator
            status={agent?.startup_status}
            enabled={agent?.enabled}
          />
          <span className={styles.overviewName}>
            {agent ? getAgentDisplayName(agent, t) : aid}
          </span>
          {agent?.backend && (
            <Tag>
              {agent.backend === "qwenpaw"
                ? `QwenPaw · ${t("agent.backend.nativeBadge", "Native")}`
                : agent.backend}
            </Tag>
          )}
        </div>
        <Descriptions
          className={styles.overviewDescriptions}
          column={1}
          size="small"
          items={[
            { key: "id", label: t("agent.id", "ID"), children: aid },
            {
              key: "desc",
              label: t("agent.description", "Description"),
              children: agent?.description || "-",
            },
            ...(agent?.active_model
              ? [
                  {
                    key: "model",
                    label: t("agent.modelColumn", "Model"),
                    children: `${agent.active_model.provider_id} / ${agent.active_model.model}`,
                  },
                ]
              : []),
            ...(agent?.workspace_dir
              ? [
                  {
                    key: "ws",
                    label: t("agent.workspace", "Workspace"),
                    children: agent.workspace_dir,
                  },
                ]
              : []),
          ]}
        />
        <Space className={styles.overviewActions} wrap>
          <Button
            type="primary"
            icon={<MessageCircle size={14} />}
            onClick={() => open("chat")}
          >
            {t("agentDetail.goChat", "Chat")}
          </Button>
          <Button icon={<FolderOpen size={14} />} onClick={() => open("files")}>
            {t("nav.files", "Files")}
          </Button>
          <Button icon={<Clock size={14} />} onClick={() => open("cron-jobs")}>
            {t("nav.cronJobs", "Scheduled Tasks")}
          </Button>
        </Space>
      </Card>
    </div>
  );
}
