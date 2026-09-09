/**
 * EmployeeProfileAside.tsx — 员工档案栏（详情页左栏）。
 *
 * 结构：灰带头像（渐变首字符）→ 名称/状态 → 描述 → 元信息（后端/模型/
 * 工作区）→ 迷你统计三格 → 去对话/AI 调优 → 分组竖排导航（可折叠）→
 * 切换员工。数据域零逻辑：agent/aid 由 Layout 提供，本组件只做呈现。
 */
import { useMemo, useState } from "react";
import { Button, Dropdown, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import {
  ChevronDown,
  ChevronRight,
  MessageCircle,
  Pin,
  Sparkles,
} from "lucide-react";
import { StatusPill } from "@/components/staffdeck";
import ExpertAvatar from "@/components/ExpertAvatar";
import ModelSelector from "@/pages/Chat/ModelSelector";
import { avatarGradient } from "@/utils/avatarGradient";
import { isExpertAgentId } from "@/api/modules/xianFeedback";
import { useExpertIcons } from "@/hooks/useExpertIcons";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import type { AgentSummary } from "@/api/types/agents";
import { useBriefStats } from "./useBriefStats";
import styles from "./detail.module.less";

export type TabGroup = "basic" | "capability" | "ops";

export interface DetailTab {
  key: string;
  labelKey: string;
  fallback: string;
  group: TabGroup;
}

export interface GroupLabel {
  group: TabGroup;
  labelKey: string;
}

interface EmployeeProfileAsideProps {
  agent: AgentSummary | undefined;
  aid: string;
  visibleTabs: DetailTab[];
  visibleGroups: GroupLabel[];
  activeTab: string;
  agents: AgentSummary[];
  onTabClick: (key: string) => void;
  onGoChat: () => void;
  onAiTune: (prompt: string) => void;
  onSwitchAgent: (targetId: string) => void;
}

export default function EmployeeProfileAside({
  agent,
  aid,
  visibleTabs,
  visibleGroups,
  activeTab,
  agents,
  onTabClick,
  onGoChat,
  onAiTune,
  onSwitchAgent,
}: EmployeeProfileAsideProps) {
  const { t } = useTranslation();
  const { stats, loading: statsLoading } = useBriefStats(aid);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const displayName = agent
    ? getAgentDisplayName(agent, t)
    : aid;

  // 数字员工形象：expert_ 前缀 agent 才有；普通 agent 回退渐变首字符
  const expertId = isExpertAgentId(aid);
  const expertIcon = useExpertIcons()[expertId];

  const backendBadge = useMemo(() => {
    if (!agent?.backend) return "—";
    return agent.backend === "qwenpaw"
      ? `QwenPaw · ${t("agent.backend.nativeBadge", "Native")}`
      : agent.backend;
  }, [agent, t]);

  const toggleGroup = (group: string) => {
    setCollapsed((prev) => ({ ...prev, [group]: !prev[group] }));
  };

  return (
    <aside className={styles.profileAside}>
      <div className={styles.profileCard}>
        <div className={styles.profileBody}>
          {/* 档案头一行：头像 + 名称与运行状态同行 */}
          <div className={styles.profileHeaderRow}>
            {expertId ? (
              <ExpertAvatar
                icon={expertIcon}
                expertId={expertId}
                name={displayName}
                size={48}
                className={styles.profileAvatar}
              />
            ) : (
              <div
                className={styles.profileAvatar}
                style={{ background: avatarGradient(aid + displayName) }}
              >
                {(displayName || "?").slice(0, 1)}
              </div>
            )}
            <div className={styles.profileNameRow}>
              <span className={styles.profileName} title={displayName}>
                {displayName}
              </span>
              {(agent?.id === "default" || agent?.pinned) && (
                <Pin size={13} className={styles.pinIcon} />
              )}
              <StatusPill tone={agent?.enabled ? "green" : "gray"}>
                {agent?.enabled
                  ? t("agent.status.running", "Running")
                  : t("agent.status.disabled", "Disabled")}
              </StatusPill>
            </div>
          </div>

          {/* 描述（两行截断） */}
          <p className={styles.profileDesc}>
            {agent?.description || "\u00a0"}
          </p>

          {/* 元信息：后端 / 模型 / 工作区 */}
          <dl className={styles.profileMeta}>
            <div className={styles.metaRow}>
              <dt>{t("agentDetail.backend", "Backend")}</dt>
              <dd>{backendBadge}</dd>
            </div>
            <div className={styles.metaRow}>
              <dt>{t("agentDetail.model", "Model")}</dt>
              <dd>
                {/* 默认模型：复用聊天页 ModelSelector，数据域随 selectedAgent */}
                <ModelSelector />
              </dd>
            </div>
            {agent?.workspace_dir ? (
              <div className={styles.metaRow}>
                <dt>{t("agent.workspace", "Workspace")}</dt>
                <dd>
                  <Tooltip title={agent.workspace_dir}>
                    <span className={styles.metaWs}>{agent.workspace_dir}</span>
                  </Tooltip>
                </dd>
              </div>
            ) : null}
          </dl>

          {/* 迷你统计三格：今日对话 / 累计对话 / 好评率 */}
          <div className={styles.miniStats}>
            <div className={styles.miniStatCell}>
              <div className={styles.miniStatValue}>
                {statsLoading && !stats ? "…" : stats?.today_chats ?? "—"}
              </div>
              <div className={styles.miniStatLabel}>
                {t("agentDetail.statTodayChats", "Today's chats")}
              </div>
            </div>
            <div className={styles.miniStatCell}>
              <div className={styles.miniStatValue}>
                {statsLoading && !stats ? "…" : stats?.total_chats ?? "—"}
              </div>
              <div className={styles.miniStatLabel}>
                {t("agentDetail.statTotalChats", "Total chats")}
              </div>
            </div>
            <div className={styles.miniStatCell}>
              {/* 好评率：后端 feedback 查询接口就绪后接入，暂显示占位 */}
              <div className={styles.miniStatValue}>—</div>
              <div className={styles.miniStatLabel}>
                {t("agentDetail.statGoodRate", "Positive rate")}
              </div>
            </div>
          </div>

          {/* 主操作：去对话 / AI 调优（并排一行） */}
          <div className={styles.profileActions}>
            <Button
              type="primary"
              className={styles.actionBtn}
              icon={<MessageCircle size={14} />}
              onClick={onGoChat}
            >
              {t("agentDetail.goChat", "Chat")}
            </Button>
            <Button
              className={styles.actionBtn}
              icon={<Sparkles size={14} />}
              onClick={() =>
                onAiTune(
                  t(
                    "agentDetail.aiTuneDefault",
                    "Help me optimize this digital employee: refine the profile and suggest suitable skills and tools.",
                  ),
                )
              }
            >
              {t("agentDetail.aiTune", "AI Tuning")}
            </Button>
          </div>

          {/* 分组竖排导航 */}
          <nav className={styles.asideNav}>
            {visibleGroups.map(({ group, labelKey }) => {
              const groupTabs = visibleTabs.filter(
                (tab) => tab.group === group,
              );
              const isCollapsed = collapsed[group] ?? false;
              const groupActive = groupTabs.some(
                (tab) => tab.key === activeTab,
              );
              return (
                <div className={styles.asideNavGroup} key={group}>
                  <button
                    type="button"
                    className={styles.asideNavGroupHeader}
                    onClick={() => toggleGroup(group)}
                  >
                    {isCollapsed ? (
                      <ChevronRight size={13} />
                    ) : (
                      <ChevronDown size={13} />
                    )}
                    <span
                      className={
                        groupActive ? styles.asideNavGroupLabelActive : undefined
                      }
                    >
                      {t(labelKey)}
                    </span>
                  </button>
                  {!isCollapsed && (
                    <div className={styles.asideNavItems}>
                      {groupTabs.map((tab) => (
                        <button
                          key={tab.key}
                          type="button"
                          className={`${styles.asideNavItem} ${
                            activeTab === tab.key ? styles.asideNavItemActive : ""
                          }`}
                          onClick={() => onTabClick(tab.key)}
                        >
                          {t(tab.labelKey, tab.fallback)}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>

          {/* 切换员工 */}
          <div className={styles.switchWrap}>
            <Dropdown
              trigger={["click"]}
              menu={{
                items: agents
                  .filter((item) => item.enabled)
                  .map((item: AgentSummary) => ({
                    key: item.id,
                    label: getAgentDisplayName(item, t),
                  })),
                onClick: ({ key }) => onSwitchAgent(String(key)),
              }}
            >
              <Button block icon={<ChevronDown size={13} />}>
                {t("agentDetail.switchAgent", "Switch employee")}
              </Button>
            </Dropdown>
          </div>
        </div>
      </div>
    </aside>
  );
}
