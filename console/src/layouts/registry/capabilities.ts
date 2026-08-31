// 说明：旧的平台菜单过滤入口 filterMenuForAgentCapabilities 已随平台 IA
// 重构移除（员工域菜单已从侧栏下线），能力过滤职责收敛到下方的
// filterTabsForAgentCapabilities（详情页 Tab）。

/** 员工详情页 Tab 的最小形状（只需 key）。 */
interface TabLike {
  key: string;
}

/**
 * 按员工 backend_capabilities 过滤详情页 Tab（平台 IA 阶段 4）。
 * 与菜单版规则一致：仅当 workspace_ui === false（非 qwenpaw 后端等）时启用；
 * 无工作区 UI 的员工隐藏文件/技能/工具/MCP/ACP/检查点/配置/统计。
 */
export function filterTabsForAgentCapabilities<T extends TabLike>(
  tabs: T[],
  capabilities: AgentMenuCapabilities | undefined,
): T[] {
  if (capabilities?.workspace_ui !== false) return tabs;
  const showSkills = Boolean(
    capabilities.native_skills_ui ||
      capabilities.qwenpaw_skills_projection ||
      capabilities.provider_skills_discovery,
  );
  const showTools = Boolean(capabilities.native_tools_ui);
  const showMcp = Boolean(
    capabilities.native_mcp_ui ||
      capabilities.qwenpaw_mcp_projection ||
      capabilities.provider_mcp_discovery,
  );

  return tabs.filter((tab) => {
    switch (tab.key) {
      case "skills":
        return showSkills;
      case "tools":
        return showTools;
      case "mcp":
        return showMcp;
      case "files":
      case "acp":
      case "checkpoints":
      case "config":
      case "stats":
        return false;
      default:
        return true;
    }
  });
}

export interface AgentMenuCapabilities {
  workspace_ui?: boolean;
  native_skills_ui?: boolean;
  native_tools_ui?: boolean;
  native_mcp_ui?: boolean;
  qwenpaw_skills_projection?: boolean;
  qwenpaw_mcp_projection?: boolean;
  provider_skills_discovery?: boolean;
  provider_mcp_discovery?: boolean;
}
