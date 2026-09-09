/**
 * AgentWorkbenchLayout — 数字员工工作台（/studio/:aid，独立浏览器标签页）。
 *
 * 布局对标 Coze 编辑器：顶栏（身份 + 调试开关 + 发布）+ 左侧固定聊天
 * 面板 + 右侧信息 Tab（档案 / 能力 / 会话 / 运维 / 版本）。
 *
 * Router 结构（Desktop OS 同款）：app 在 /studio 路径下不再提供外层
 * Router（见 App.tsx 的 isStudioPath 分支），本组件自挂 MemoryRouter
 * 沙箱并承接两类顶层路径——
 *   - /studio/:aid/*：工作台本体；
 *   - /chat/*：Chat 切换会话时的硬导航落点（utils/sessionRoute），
     会话切换由此留在沙箱内，右侧信息区回退到档案页。
 * 地址栏始终停留在入口 URL（MemoryRouter 不写地址栏），刷新后从
 * sessionStorage 恢复上次会话。
 *
 * 借壳策略延续（与 AgentDetailLayout 一致）：aid 是数据域唯一事实来源，
 * 单向同步到 selectedAgent，右侧子页面组件零改动复用；调试模式打开时
 * selectedAgent 切到草稿实例 expert_{id}__draft，聊天/能力/会话全域跟随
 * 草稿，线上 expert_{id} 与前端业务完全不受影响。
 *
 * expert 托管判定：preview/status 探测成功（404 → 非托管，隐藏
 * 调试/发布/版本），无需依赖 id 前缀约定。
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import type { ComponentType } from "react";
import {
  MemoryRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { Button, Switch, Tooltip } from "antd";
import { House, Rocket } from "lucide-react";
import { useTranslation } from "react-i18next";
import { StatusPill, UnderlineTabs } from "@/components/staffdeck";
import AgentOverviewTab from "@/pages/Agents/AgentOverviewTab";
import AgentActivityTab from "@/pages/Agents/AgentActivityTab";
import { TABS } from "@/pages/Agents/detailTabs";
import { stashAiTunePrompt } from "@/pages/Agents/aiTunePrefill";
import { lazyImportWithRetry } from "@/utils/lazyWithRetry";
import {
  addRouterBasename,
  getAppRelativeLocation,
} from "@/utils/navigationMode";
import { useAgentStore } from "@/stores/agentStore";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  adminExpertsApi,
  type ExpertPreviewStatus,
} from "../../../api/modules/admin";
import WorkbenchChatPanel, {
  loadChatCollapsed,
  loadChatWidth,
} from "./WorkbenchChatPanel";
import WorkbenchVersionsTab from "./WorkbenchVersionsTab";
import styles from "./workbench.module.less";

// 右栏子页面全部复用现有页面组件（借壳策略：数据域由布局同步到
// selectedAgent，页面 hooks 零改动）。
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

/** 顶层 Tab → 分组键映射（能力 / 运维各为一个二级分组 Tab）。 */
const CAPABILITY_KEYS = ["files", "skills", "tools", "mcp", "acp", "cron-jobs"];
const OPS_KEYS = ["channels", "config", "checkpoints", "stats", "heartbeat"];

/** 全部子页面组件索引（key 与 TABS 对齐）。 */
const PAGE_COMPONENTS: Record<string, ComponentType> = {
  sessions: SessionsPage,
  "cron-jobs": CronJobsPage,
  files: FilesPage,
  skills: SkillsPage,
  tools: ToolsPage,
  mcp: MCPPage,
  acp: ACPPage,
  checkpoints: CheckpointsPage,
  channels: ChannelsPage,
  config: AgentConfigPage,
  stats: AgentStatsPage,
  heartbeat: HeartbeatPage,
};

/** 由路径推导顶层 Tab 与二级 Tab。 */
function parseWorkbenchPath(pathname: string, aid: string): {
  top: string;
  sub: string | null;
} {
  const rest = pathname.replace(`/studio/${aid}`, "").replace(/^\//, "");
  const [first, second] = rest.split("/");
  if (first === "capability" || first === "ops") {
    return {
      top: first,
      sub: second && PAGE_COMPONENTS[second] ? second : null,
    };
  }
  if (
    first &&
    ["overview", "sessions", "activity", "versions"].includes(first)
  ) {
    return { top: first, sub: null };
  }
  return { top: "overview", sub: null };
}

/**
 * 沙箱外壳：app 在 /studio 路径下不再提供外层 Router，这里自挂
 * MemoryRouter（不写地址栏）。/chat/* 顶层路由承接 Chat 切换会话的
 * 硬导航，使其留在工作台内；未知路径回退到当前员工的档案页。
 */
export default function AgentWorkbenchLayout() {
  const initialPath = getAppRelativeLocation(window.location);
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/studio/:aid/*" element={<AgentWorkbenchShell />} />
        <Route path="/chat/*" element={<AgentWorkbenchShell chatRoute />} />
        <Route path="*" element={<CatchAllNavigate />} />
      </Routes>
    </MemoryRouter>
  );
}

/** 未知路径兜底：回当前选中员工的档案页（沙箱内导航，不出工作台）。 */
function CatchAllNavigate() {
  const aid = useAgentStore((s) => s.selectedAgent) || "default";
  return <Navigate to={`/studio/${aid}`} replace />;
}

function AgentWorkbenchShell({ chatRoute = false }: { chatRoute?: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams<{ aid: string }>();
  // /chat/* 顶层路由无 :aid 参数：回退到 selectedAgent（与聊天面板一致）。
  const fallbackAid = useAgentStore((s) => s.selectedAgent);
  const aid = params.aid || fallbackAid || "";
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { agents } = useAgentStore();
  const currentAgent = useMemo(
    () => agents.find((agent) => agent.id === aid),
    [agents, aid],
  );

  // ── expert 托管探测（preview/status 404 = 原生 agent）──
  const [previewState, setPreviewState] = useState<
    "loading" | "expert" | "native"
  >("loading");
  const [preview, setPreview] = useState<ExpertPreviewStatus | null>(null);
  const [debugOn, setDebugOn] = useState(false);
  const [debugBusy, setDebugBusy] = useState(false);
  const [publishing, setPublishing] = useState(false);
  // AI 调优：stash 预填指令后重挂 Chat（Chat 挂载时一次性消费 stash）。
  const [chatKey, setChatKey] = useState(0);
  const [chatWidth, setChatWidth] = useState(() => loadChatWidth());
  const [chatCollapsed, setChatCollapsed] = useState(() => loadChatCollapsed());

  const expertId =
    aid.startsWith("expert_") && !aid.includes("__draft")
      ? aid.slice("expert_".length)
      : null;

  const refreshPreview = useCallback(async () => {
    if (!expertId) return;
    try {
      const status = await adminExpertsApi.previewStatus(expertId);
      setPreview(status);
      setPreviewState("expert");
    } catch {
      // 404（原生 agent）或无权限（非管理员）：隐藏全部托管能力。
      setPreview(null);
      setPreviewState("native");
    }
  }, [expertId]);

  useEffect(() => {
    setPreviewState("loading");
    setPreview(null);
    setDebugOn(false);
    void refreshPreview();
  }, [refreshPreview]);

  // ── 借壳同步：调试态切草稿实例，常态切线上 aid ──
  const targetAgent = debugOn && preview ? preview.agent_id : aid;
  // 必须用 useLayoutEffect：子组件 Chat 的 passive effect（首次拉会话列表）
  // 先于父组件 useEffect 执行，若在此时才同步 selectedAgent，请求头会
  // 带着上一个员工（storage 兑底值）拿到别人的会话记录。layout 阶段
  // 同步可保证在所有 passive effect 之前完成数据域切换。
  useLayoutEffect(() => {
    if (!aid) return;
    const state = useAgentStore.getState();
    if (state.selectedAgent === targetAgent) return;
    state.setSelectedAgent(targetAgent);
  }, [aid, targetAgent]);

  // 无效 / 已删员工：回列表页（agents 尚未加载完成时不误判）。
  // 沙箱内无真实路由，用硬导航离开工作台回控制台。
  useEffect(() => {
    if (agents.length === 0 || !aid) return;
    if (agents.some((agent) => agent.id === aid)) return;
    window.location.replace(
      addRouterBasename(window.location.pathname, "/agents"),
    );
  }, [agents, aid]);

  const { top, sub } = parseWorkbenchPath(location.pathname, aid);

  // 顶层 Tab 恒等跳转（/studio/:aid 顶层路由由 Routes 承接）。
  const handleTopTab = (key: string) => {
    navigate(
      key === "overview"
        ? `/studio/${aid}`
        : `/studio/${aid}/${key}`,
    );
  };

  const handleAiTune = (prompt: string) => {
    stashAiTunePrompt(prompt);
    setChatKey((k) => k + 1);
  };

  // ── 调试开关：ON 物化草稿实例并切数据域；OFF 回线上并销毁实例 ──
  const handleDebugToggle = async (next: boolean) => {
    if (!expertId || !preview) return;
    setDebugBusy(true);
    try {
      if (next) {
        const started = await adminExpertsApi.previewStart(expertId);
        useAgentStore.getState().setSelectedAgent(started.agent_id);
        setDebugOn(true);
        await useAgentStore.getState().refreshAgents();
      } else {
        // 先离开草稿域再销毁，避免 selectedAgent 指向已卸载实例。
        useAgentStore.getState().setSelectedAgent(aid);
        setDebugOn(false);
        await adminExpertsApi.previewStop(expertId);
        await useAgentStore.getState().refreshAgents();
      }
      void refreshPreview();
    } catch (err) {
      message.error(String(err));
    } finally {
      setDebugBusy(false);
    }
  };

  const handlePublish = async () => {
    if (!expertId) return;
    setPublishing(true);
    try {
      await adminExpertsApi.publish(expertId);
      message.success(t("workbench.publishSuccess", "已发布，线上已更新"));
      // 发布联动销毁草稿实例：调试态回线上视角。
      if (debugOn) {
        useAgentStore.getState().setSelectedAgent(aid);
        setDebugOn(false);
        await useAgentStore.getState().refreshAgents();
      }
      void refreshPreview();
    } catch (err) {
      message.error(String(err));
    } finally {
      setPublishing(false);
    }
  };

  const handleVersionsChanged = () => {
    void refreshPreview();
  };

  if (!aid) return null;

  const isExpert = previewState === "expert";

  // 顶部状态徽标：expert 语义（已发布版本/未发布变更/草稿），原生退回运行态。
  const statusPill = isExpert && preview ? (
    preview.published_version === null ? (
      <StatusPill tone="blue">{t("workbench.statusDraft", "草稿")}</StatusPill>
    ) : preview.has_unpublished_changes ? (
      <StatusPill tone="amber">
        {t("workbench.statusHasChanges", "有未发布变更")}
      </StatusPill>
    ) : (
      <StatusPill tone="green">
        {t("workbench.statusPublished", "已发布 v{{v}}", {
          v: preview.published_version,
        })}
      </StatusPill>
    )
  ) : currentAgent ? (
    currentAgent.enabled ? (
      <StatusPill tone="green">{t("workbench.statusRunning", "运行中")}</StatusPill>
    ) : (
      <StatusPill tone="gray">{t("workbench.statusDisabled", "已停用")}</StatusPill>
    )
  ) : null;

  return (
    <div className={styles.workbench}>
      {/* ── 顶栏 ── */}
      <header className={styles.topBar}>
        <button
          type="button"
          className={styles.homeBtn}
          title={t("workbench.backToConsole", "返回控制台")}
          onClick={() =>
            // 沙箱内无真实路由：硬导航回控制台（新标签页语义下
            // 等价于在当前标签打开控制台首页）。
            window.location.assign(
              addRouterBasename(window.location.pathname, "/workbench"),
            )
          }
        >
          <House size={17} />
        </button>
        <span className={styles.crumb}>
          {t("nav.agents", "数字员工")}
        </span>
        <span className={styles.agentName}>{currentAgent?.name ?? aid}</span>
        {statusPill}
        <span className={styles.topSpacer} />
        {isExpert && preview ? (
          <Tooltip
            title={t(
              "workbench.debugHint",
              "调试模式：会话跑在独立草稿实例上，线上业务不受影响",
            )}
          >
            <span className={styles.debugSwitch}>
              {t("workbench.debug", "调试")}
              <Switch
                size="small"
                checked={debugOn}
                loading={debugBusy}
                onChange={handleDebugToggle}
              />
            </span>
          </Tooltip>
        ) : null}
        {isExpert ? (
          <Button
            type="primary"
            className={`sd-btn-primary ${styles.publishBtn}`}
            icon={<Rocket size={14} />}
            loading={publishing}
            onClick={handlePublish}
          >
            {t("workbench.publish", "发布")}
          </Button>
        ) : null}
      </header>

      {/* ── 主体：左聊天 + 右信息 ── */}
      <div className={styles.workbenchBody}>
        <WorkbenchChatPanel
          width={chatWidth}
          collapsed={chatCollapsed}
          debugOn={debugOn}
          chatKey={chatKey}
          hideHeaderModelSelector
          onWidthChange={setChatWidth}
          onCollapsedChange={setChatCollapsed}
        />

        <section className={styles.detailPane}>
          <div className={styles.tabBar}>
            <UnderlineTabs
              value={top}
              onChange={handleTopTab}
              items={[
                {
                  key: "overview",
                  label: t("workbench.tabProfile", "档案"),
                },
                {
                  key: "capability",
                  label: t("workbench.tabCapability", "能力"),
                },
                {
                  key: "sessions",
                  label: t("workbench.tabSessions", "会话"),
                },
                {
                  key: "activity",
                  label: t("workbench.tabActivity", "动态"),
                },
                { key: "ops", label: t("workbench.tabOps", "运维") },
                ...(isExpert
                  ? [
                      {
                        key: "versions",
                        label: t("workbench.tabVersions", "版本"),
                      },
                    ]
                  : []),
              ]}
            />
          </div>

          <div className={styles.tabContent}>
            {chatRoute ? (
              // /chat/* 会话路由：右侧回退档案页（会话状态看左栏聊天）。
              <AgentOverviewTab
                agent={currentAgent}
                aid={aid}
                onAiTune={handleAiTune}
              />
            ) : (
              <Routes>
              <Route
                index
                element={
                  <AgentOverviewTab
                    agent={currentAgent}
                    aid={aid}
                    onAiTune={handleAiTune}
                  />
                }
              />
              <Route
                path="overview"
                element={
                  <AgentOverviewTab
                    agent={currentAgent}
                    aid={aid}
                    onAiTune={handleAiTune}
                  />
                }
              />
              <Route path="sessions" element={<SessionsPage />} />
              <Route
                path="sessions/runs/:runId"
                element={<RunLogDetailPage />}
              />
              <Route path="activity" element={<AgentActivityTab aid={aid} />} />
              <Route
                path="capability"
                element={<GroupPane group="capability" sub={null} aid={aid} />}
              />
              <Route
                path="capability/:tab"
                element={<GroupPane group="capability" sub={sub} aid={aid} />}
              />
              <Route
                path="ops"
                element={<GroupPane group="ops" sub={null} aid={aid} />}
              />
              <Route
                path="ops/:tab"
                element={<GroupPane group="ops" sub={sub} aid={aid} />}
              />
              {isExpert && expertId ? (
                <Route
                  path="versions"
                  element={
                    <WorkbenchVersionsTab
                      expertId={expertId}
                      preview={preview}
                      onChanged={handleVersionsChanged}
                    />
                  }
                />
              ) : null}
              <Route
                path="*"
                element={<Navigate to="overview" replace />}
              />
              </Routes>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

/**
 * GroupPane — 能力 / 运维二级分组：横排二级 Tab + 复用的借壳页面。
 * 缺省落在该组第一个可见 Tab（保持 URL 简洁，不做隐式重定向）。
 */
function GroupPane({
  group,
  sub,
  aid,
}: {
  group: "capability" | "ops";
  sub: string | null;
  aid: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const keys = group === "capability" ? CAPABILITY_KEYS : OPS_KEYS;
  const items = keys
    .map((key) => {
      const tab = TABS.find((item) => item.key === key);
      if (!tab) return null;
      return {
        key,
        label: t(tab.labelKey, tab.fallback),
      };
    })
    .filter((item): item is { key: string; label: string } => item !== null);

  const active = sub && keys.includes(sub) ? sub : items[0]?.key;
  const ActivePage = active ? PAGE_COMPONENTS[active] : undefined;

  return (
    <div>
      <div className={styles.subTabBar}>
        <UnderlineTabs
          value={active ?? ""}
          onChange={(key) => navigate(`/studio/${aid}/${group}/${key}`)}
          items={items}
        />
      </div>
      {ActivePage ? <ActivePage /> : null}
    </div>
  );
}
