/**
 * teamTabs.ts — 专家团工作台详情 Tab 键常量。
 *
 * 独立无依赖小模块：外壳（AgentWorkbenchLayout）与团队详情容器
 * （TeamWorkbenchDetail）共享同一 white-list，且外壳静态导入本文件
 * 不会把懒加载的详情组件链拉进 entry chunk。
 */

export const TEAM_TAB_KEYS = [
  "overview",
  "members",
  "workflow",
  "sessions",
  "ops",
] as const;

export type TeamTabKey = (typeof TEAM_TAB_KEYS)[number];

/** 路径首段是否为合法团队 Tab（未知路径回 overview）。 */
export function isTeamTabKey(value: string): value is TeamTabKey {
  return (TEAM_TAB_KEYS as readonly string[]).includes(value);
}
