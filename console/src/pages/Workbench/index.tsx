import { useEffect, useMemo, useState } from "react";
import { Card } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  Bot,
  Globe,
  Inbox,
  LayoutGrid,
  Plus,
  Sparkles,
} from "lucide-react";
import { api } from "@/api";
import { useAgentStore } from "@/stores/agentStore";
import { AgentStatusIndicator } from "@/components/AgentStatusIndicator";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import { PageHeader } from "@/components/PageHeader";
import styles from "./workbench.module.less";

const QUICK_LINKS = [
  { path: "/channels", labelKey: "nav.channels", fallback: "Channels", Icon: Globe },
  { path: "/models", labelKey: "nav.models", fallback: "Models", Icon: Bot },
  { path: "/skill-pool", labelKey: "nav.skillPool", fallback: "Skill Pool", Icon: Sparkles },
  { path: "/apps", labelKey: "nav.apps", fallback: "Apps", Icon: LayoutGrid },
] as const;

/** 平台工作台：数字员工总览 + 收件箱摘要 + 快捷入口（平台 IA 阶段 4）。 */
export default function WorkbenchPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { agents, refreshAgents } = useAgentStore();
  const [hasUnreadInbox, setHasUnreadInbox] = useState(false);

  // 工作台是常见落地页，store 可能还没有员工缓存，挂载时拉一次
  // （refreshAgents 内建 promise 去重，与其它页并发调用安全）
  useEffect(() => {
    refreshAgents();
  }, [refreshAgents]);

  // 收件箱未读摘要（轮询逻辑归 Inbox 页与 Sidebar 徽标，这里只做一次性快照）
  useEffect(() => {
    let cancelled = false;
    api
      .getInboxEvents({ unread_only: true, limit: 1 })
      .then((res) => {
        if (!cancelled) setHasUnreadInbox((res?.events?.length || 0) > 0);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // 已启用的员工排前面，其余按原有顺序
  const sortedAgents = useMemo(() => {
    const enabled = agents.filter((agent) => agent.enabled);
    const disabled = agents.filter((agent) => !agent.enabled);
    return [...enabled, ...disabled];
  }, [agents]);

  return (
    <div className={styles.workbench}>
      <PageHeader current={t("nav.workbench", "Workbench")} />

      <Card
        className={`${styles.inboxCard} ${hasUnreadInbox ? styles.inboxCardUnread : ""}`}
        size="small"
        onClick={() => navigate("/inbox")}
      >
        <div className={styles.inboxRow}>
          <Inbox size={18} />
          <span className={styles.inboxText}>
            {hasUnreadInbox
              ? t("workbench.inboxUnread", "You have unread inbox messages")
              : t("workbench.inboxClear", "Inbox is all caught up")}
          </span>
          <ArrowRight size={15} className={styles.inboxArrow} />
        </div>
      </Card>

      <div className={styles.sectionTitle}>
        {t("nav.employees", "Digital Employees")}
      </div>
      <div className={styles.agentGrid}>
        {sortedAgents.map((agent) => (
          <Card
            key={agent.id}
            size="small"
            className={`${styles.agentCard} ${
              agent.enabled ? "" : styles.agentCardDisabled
            }`}
            onClick={() => navigate(`/agents/${agent.id}`)}
          >
            <div className={styles.agentCardHead}>
              <AgentStatusIndicator
                status={agent.startup_status}
                enabled={agent.enabled}
              />
              <span className={styles.agentCardName}>
                {getAgentDisplayName(agent, t)}
              </span>
              <ArrowRight size={14} className={styles.agentCardArrow} />
            </div>
            {agent.description ? (
              <div className={styles.agentCardDesc}>{agent.description}</div>
            ) : null}
          </Card>
        ))}
        <Card
          size="small"
          className={`${styles.agentCard} ${styles.agentCardCreate}`}
          onClick={() => navigate("/agents")}
        >
          <div className={styles.agentCardHead}>
            <Plus size={16} />
            <span className={styles.agentCardName}>
              {t("agent.create", "Create agent")}
            </span>
          </div>
          <div className={styles.agentCardDesc}>
            {t("workbench.createHint", "Onboard a new digital employee")}
          </div>
        </Card>
      </div>

      <div className={styles.sectionTitle}>
        {t("workbench.quickLinks", "Quick links")}
      </div>
      <div className={styles.quickGrid}>
        {QUICK_LINKS.map(({ path, labelKey, fallback, Icon }) => (
          <Card
            key={path}
            size="small"
            className={styles.quickCard}
            onClick={() => navigate(path)}
          >
            <Icon size={16} />
            <span>{t(labelKey, fallback)}</span>
          </Card>
        ))}
      </div>
    </div>
  );
}
