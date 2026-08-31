import { useEffect, useMemo } from "react";
import { Button, Dropdown, Tag } from "antd";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MessageCircle, ChevronDown, Pin } from "lucide-react";
import Chat from "@/pages/Chat";
import AgentOverviewTab from "@/pages/Agents/AgentOverviewTab";
import { lazyImportWithRetry } from "@/utils/lazyWithRetry";
import { useAgentStore } from "@/stores/agentStore";
import {
  filterTabsForAgentCapabilities,
  type AgentMenuCapabilities,
} from "@/layouts/registry/capabilities";
import { AgentStatusIndicator } from "@/components/AgentStatusIndicator";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import type { AgentSummary } from "@/api/types/agents";
import styles from "./detail.module.less";

// 员工域子页面全部复用现有页面组件（借壳策略：数据域由布局同步到
// selectedAgent，页面 hooks 零改动）。Chat 保持 eager 以保证首屏对话体验。
const SessionsPage = lazyImportWithRetry("../../pages/Control/Sessions");
const CronJobsPage = lazyImportWithRetry("../../pages/Control/CronJobs");
const FilesPage = lazyImportWithRetry("../../pages/Files");
const SkillsPage = lazyImportWithRetry("../../pages/Agent/Skills");
const ToolsPage = lazyImportWithRetry("../../pages/Agent/Tools");
const MCPPage = lazyImportWithRetry("../../pages/Agent/MCP");
const ACPPage = lazyImportWithRetry("../../pages/Agent/ACP");
const CheckpointsPage = lazyImportWithRetry("../../pages/Agent/Checkpoints");
const ChannelsPage = lazyImportWithRetry("../../pages/Control/Channels");
const AgentConfigPage = lazyImportWithRetry("../../pages/Agent/Config");
const AgentStatsPage = lazyImportWithRetry("../../pages/Settings/AgentStats");
const HeartbeatPage = lazyImportWithRetry("../../pages/Control/Heartbeat");

type TabGroup = "basic" | "capability" | "ops";

interface DetailTab {
  key: string;
  labelKey: string;
  fallback: string;
  group: TabGroup;
}

const TABS: DetailTab[] = [
  { key: "overview", labelKey: "agentDetail.overview", fallback: "Overview", group: "basic" },
  { key: "chat", labelKey: "agentDetail.chat", fallback: "Chat", group: "basic" },
  { key: "sessions", labelKey: "nav.sessions", fallback: "Sessions", group: "basic" },
  { key: "cron-jobs", labelKey: "nav.cronJobs", fallback: "Scheduled Tasks", group: "basic" },
  { key: "files", labelKey: "nav.files", fallback: "Files", group: "capability" },
  { key: "skills", labelKey: "nav.skills", fallback: "Skills", group: "capability" },
  { key: "tools", labelKey: "nav.tools", fallback: "Tools", group: "capability" },
  { key: "mcp", labelKey: "nav.mcp", fallback: "MCP", group: "capability" },
  { key: "acp", labelKey: "nav.acp", fallback: "ACP", group: "capability" },
  { key: "checkpoints", labelKey: "checkpoints.nav", fallback: "Checkpoints", group: "ops" },
  { key: "channels", labelKey: "agentDetail.channels", fallback: "Channel Bindings", group: "ops" },
  { key: "stats", labelKey: "nav.agentStats", fallback: "Usage Stats", group: "ops" },
  { key: "heartbeat", labelKey: "nav.heartbeat", fallback: "Heartbeat", group: "ops" },
  { key: "config", labelKey: "nav.agentConfig", fallback: "Configuration", group: "ops" },
];

const GROUP_LABEL_KEYS: [TabGroup, string][] = [
  ["basic", "agentDetail.groupBasic"],
  ["capability", "agentDetail.groupCapability"],
  ["ops", "agentDetail.groupOps"],
];

/** 由当前路径推导激活 Tab（"overview" 为 index）。 */
function activeTabFromPathname(pathname: string, aid: string): string {
  const prefix = `/agents/${aid}`;
  const rest = pathname.startsWith(prefix)
    ? pathname.slice(prefix.length).replace(/^\//, "")
    : "";
  const first = rest.split("/")[0];
  if (!first || first === "") return "overview";
  return TABS.some((tab) => tab.key === first) ? first : "overview";
}

export default function AgentDetailLayout() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { aid } = useParams<{ aid: string }>();
  const { agents } = useAgentStore();
  const currentAgent = useMemo(
    () => agents.find((agent) => agent.id === aid),
    [agents, aid],
  );

  // 与旧侧栏规则一致：非 qwenpaw 后端强制无工作区 UI，用于过滤工作区类 Tab。
  const backendCapabilities = useMemo<AgentMenuCapabilities | undefined>(() => {
    if (!currentAgent) return undefined;
    return {
      ...currentAgent.backend_capabilities,
      workspace_ui:
        currentAgent.backend === "qwenpaw"
          ? currentAgent.backend_capabilities?.workspace_ui ?? true
          : false,
    };
  }, [currentAgent]);

  // Tab 能力过滤：无工作区能力的员工隐藏文件/技能/工具等工作区类 Tab。
  const visibleTabs = useMemo(
    () => filterTabsForAgentCapabilities(TABS, backendCapabilities),
    [backendCapabilities],
  );
  const visibleGroups = useMemo(
    () =>
      GROUP_LABEL_KEYS.filter(([, labelKey]) =>
        visibleTabs.some((tab) => tab.group === labelKeyGroup(labelKey)),
      ),
    [visibleTabs],
  );

  // 借壳同步：URL :aid 是数据域唯一事实来源，单向同步到 selectedAgent。
  // 相同 aid 短路，避免 menuRegistry.refresh() 风暴。
  useEffect(() => {
    if (!aid) return;
    const state = useAgentStore.getState();
    if (state.selectedAgent === aid) return;
    state.setSelectedAgent(aid);
  }, [aid]);

  // 无效 / 已删员工：回列表页（agents 尚未加载完成时不误判）。
  useEffect(() => {
    if (agents.length === 0 || !aid) return;
    if (agents.some((agent) => agent.id === aid)) return;
    navigate("/agents", { replace: true });
  }, [agents, aid, navigate]);

  const activeTab = activeTabFromPathname(location.pathname, aid ?? "");

  const handleTabClick = (key: string) => {
    if (!aid) return;
    navigate(key === "overview" ? `/agents/${aid}` : `/agents/${aid}/${key}`);
  };

  const handleSwitchAgent = (targetId: string) => {
    if (!targetId || targetId === aid) return;
    navigate(
      activeTab === "overview"
        ? `/agents/${targetId}`
        : `/agents/${targetId}/${activeTab}`,
    );
  };

  if (!aid) return null;
  // agents 加载完成且找不到该员工时，上面的 effect 会跳回列表页。
  if (agents.length > 0 && !currentAgent) return null;


  return (
    <div className={styles.detailPage}>
      <header className={styles.detailHeader}>
        <div className={styles.headerMain}>
          {currentAgent ? (
            <>
              <AgentStatusIndicator
                status={currentAgent.startup_status}
                enabled={currentAgent.enabled}
              />
              <span className={styles.agentName}>
                {getAgentDisplayName(currentAgent, t)}
              </span>
              {(currentAgent.id === "default" || currentAgent.pinned) && (
                <Pin size={14} className={styles.pinIcon} />
              )}
              <Tag
                className={styles.enabledTag}
                color={currentAgent.enabled ? "success" : "default"}
              >
                {currentAgent.enabled
                  ? t("agent.status.running", "Running")
                  : t("agent.status.disabled", "Disabled")}
              </Tag>
            </>
          ) : (
            <span className={styles.agentName}>{aid}</span>
          )}
        </div>
        {currentAgent?.description ? (
          <div className={styles.agentDescription}>{currentAgent.description}</div>
        ) : null}
        <div className={styles.headerActions}>
          <Button
            type="primary"
            icon={<MessageCircle size={15} />}
            onClick={() => handleTabClick("chat")}
          >
            {t("agentDetail.goChat", "Chat")}
          </Button>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: agents
                .filter((agent) => agent.enabled)
                .map((agent: AgentSummary) => ({
                  key: agent.id,
                  label: getAgentDisplayName(agent, t),
                })),
              onClick: ({ key }) => handleSwitchAgent(String(key)),
            }}
          >
            <Button icon={<ChevronDown size={14} />}>
              {t("agentDetail.switchAgent", "Switch employee")}
            </Button>
          </Dropdown>
        </div>
      </header>

      <nav className={styles.tabBar}>
        {visibleGroups.map(([group, labelKey]) => (
          <div className={styles.tabGroup} key={group}>
            <span className={styles.tabGroupLabel}>
              {t(labelKey)}
            </span>
            <div className={styles.tabGroupItems}>
              {visibleTabs.filter((tab) => tab.group === group).map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  className={`${styles.tabItem} ${
                    activeTab === tab.key ? styles.tabItemActive : ""
                  }`}
                  onClick={() => handleTabClick(tab.key)}
                >
                  {t(tab.labelKey, tab.fallback)}
                </button>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className={styles.detailBody}>
        <Routes>
          <Route index element={<AgentOverviewTab agent={currentAgent} aid={aid} />} />
          <Route path="overview" element={<AgentOverviewTab agent={currentAgent} aid={aid} />} />
          <Route path="chat/*" element={<Chat />} />
          <Route path="sessions" element={<SessionsPage />} />
          <Route path="cron-jobs" element={<CronJobsPage />} />
          <Route path="files" element={<FilesPage />} />
          <Route path="skills" element={<SkillsPage />} />
          <Route path="tools" element={<ToolsPage />} />
          <Route path="mcp" element={<MCPPage />} />
          <Route path="acp" element={<ACPPage />} />
          <Route path="checkpoints" element={<CheckpointsPage />} />
          <Route path="channels" element={<ChannelsPage />} />
          <Route path="config" element={<AgentConfigPage />} />
          <Route path="stats" element={<AgentStatsPage />} />
          <Route path="heartbeat" element={<HeartbeatPage />} />
          <Route path="*" element={<Navigate to="overview" replace />} />
        </Routes>
      </div>
    </div>
  );
}

/**
 * labelKey → group 的反查（GROUP_LABEL_KEYS 是 [group, labelKey] 对）。
 */
function labelKeyGroup(labelKey: string): TabGroup {
  const hit = GROUP_LABEL_KEYS.find(([, key]) => key === labelKey);
  return hit ? hit[0] : "basic";
}
