/**
 * detailTabs — 员工域子 Tab 定义的唯一来源。
 *
 * 供两套详情壳复用：旧档案中心（AgentDetailLayout，/agents/:aid/*）与
 * 工作台（/studio/:aid）。独立成常量模块是为了切断「工作台 →
 * AgentDetailLayout」的静态依赖——否则懒加载的工作台会被 Rollup 并入
 * entry chunk（AgentDetailLayout 经 builtinRoutes 静态进首屏）。
 */
import type { DetailTab } from "./EmployeeProfileAside";

export const TABS: DetailTab[] = [
  { key: "overview", labelKey: "agentDetail.overview", fallback: "Overview", group: "basic" },
  { key: "activity", labelKey: "agentDetail.activity", fallback: "Activity", group: "basic" },
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
