import { useEffect, useLayoutEffect, useMemo } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import Chat from "@/pages/Chat";
import AgentOverviewTab from "@/pages/Agents/AgentOverviewTab";
import AgentActivityTab from "@/pages/Agents/AgentActivityTab";
import EmployeeProfileAside from "@/pages/Agents/EmployeeProfileAside";
import type {
  GroupLabel,
} from "@/pages/Agents/EmployeeProfileAside";
import { TABS } from "@/pages/Agents/detailTabs";
import { stashAiTunePrompt } from "@/pages/Agents/aiTunePrefill";
import { lazyImportWithRetry } from "@/utils/lazyWithRetry";
import { useAgentStore } from "@/stores/agentStore";
import {
  filterTabsForAgentCapabilities,
  type AgentMenuCapabilities,
} from "@/layouts/registry/capabilities";
import styles from "./detail.module.less";

// 员工域子页面全部复用现有页面组件（借壳策略：数据域由布局同步到
// selectedAgent，页面 hooks 零改动）。Chat 保持 eager 以保证首屏对话体验。
const SessionsPage = lazyImportWithRetry("../../pages/Control/Sessions");
const RunLogDetailPage = lazyImportWithRetry(
  "../../pages/Control/Sessions/RunLogs/RunLogDetailPage",
);
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

// 导航不含 chat：对话入口由档案栏「去对话」主按钮承担，避免双入口。
// 路由 /agents/:aid/chat 仍保留（按钮跳转 + AI 调优落点），
// 位于对话页时左栏导航不高亮任何项。
// Tab 定义唯一来源在 detailTabs.ts（与工作台共享）。

const GROUP_LABEL_KEYS: GroupLabel[] = [
  { group: "basic", labelKey: "agentDetail.groupBasic" },
  { group: "capability", labelKey: "agentDetail.groupCapability" },
  { group: "ops", labelKey: "agentDetail.groupOps" },
];

/** 由当前路径推导激活 Tab（"overview" 为 index；chat 不在导航中，返回自身以保持无高亮）。 */
function activeTabFromPathname(pathname: string, aid: string): string {
  const prefix = `/agents/${aid}`;
  const rest = pathname.startsWith(prefix)
    ? pathname.slice(prefix.length).replace(/^\//, "")
    : "";
  const first = rest.split("/")[0];
  if (!first || first === "") return "overview";
  if (first === "chat") return "chat";
  return TABS.some((tab) => tab.key === first) ? first : "overview";
}

export default function AgentDetailLayout() {
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
      GROUP_LABEL_KEYS.filter((group) =>
        visibleTabs.some((tab) => tab.group === group.group),
      ),
    [visibleTabs],
  );

  // 借壳同步：URL :aid 是数据域唯一事实来源，单向同步到 selectedAgent。
  // 相同 aid 短路，避免 menuRegistry.refresh() 风暴。
  // 用 useLayoutEffect：子组件 Chat 的 passive effect（首次拉会话列表）先
  // 于父级 useEffect 执行，layout 阶段同步可避免首帧请求头携带上一个员工。
  useLayoutEffect(() => {
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

  // 「AI 调优」：stash 预填指令后进入对话 Tab，由 Chat 挂载时消费。
  const handleAiTune = (prompt: string) => {
    if (!aid) return;
    stashAiTunePrompt(prompt);
    navigate(`/agents/${aid}/chat`);
  };

  if (!aid) return null;
  // agents 加载完成且找不到该员工时，上面的 effect 会跳回列表页。
  if (agents.length > 0 && !currentAgent) return null;

  return (
    <div className={styles.detailPage}>
      <EmployeeProfileAside
        agent={currentAgent}
        aid={aid}
        visibleTabs={visibleTabs}
        visibleGroups={visibleGroups}
        activeTab={activeTab}
        agents={agents}
        onTabClick={handleTabClick}
        onGoChat={() => handleTabClick("chat")}
        onAiTune={handleAiTune}
        onSwitchAgent={handleSwitchAgent}
      />

      <div className={styles.detailBody}>
        <Routes>
          <Route
            index
            element={
              <AgentOverviewTab
                agent={currentAgent}
                aid={aid}
                showHeader={false}
                onAiTune={handleAiTune}
              />
            }
          />
          <Route path="overview" element={
            <AgentOverviewTab
              agent={currentAgent}
              aid={aid}
              showHeader={false}
              onAiTune={handleAiTune}
            />
          } />
          <Route path="chat/*" element={<Chat />} />
          <Route path="activity" element={<AgentActivityTab aid={aid} />} />
          <Route path="sessions" element={<SessionsPage />} />
          <Route
            path="sessions/runs/:runId"
            element={<RunLogDetailPage />}
          />
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
