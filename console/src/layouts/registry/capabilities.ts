import type { MenuItem } from "../../plugins/registry/types";

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

type MenuTreeItem = MenuItem & { __children?: MenuItem[] };

const NATIVE_WORKSPACE_MENU_IDS = new Set([
  "core.workspace",
  "core.acp",
  "core.agent-config",
  "core.agent-stats",
]);

export function filterMenuForAgentCapabilities(
  items: MenuItem[],
  capabilities: AgentMenuCapabilities | undefined,
): MenuItem[] {
  if (capabilities?.workspace_ui !== false) return items;
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
  const showAgentGroup = showSkills || showTools || showMcp;

  return items.flatMap((item) => {
    if (NATIVE_WORKSPACE_MENU_IDS.has(item.id)) return [];
    if (item.id === "core.agent-group" && !showAgentGroup) return [];
    if (item.id === "core.skills" && !showSkills) return [];
    if (item.id === "core.tools" && !showTools) return [];
    if (item.id === "core.mcp" && !showMcp) return [];

    const treeItem = item as MenuTreeItem;
    if (!treeItem.__children) return [item];
    return [
      {
        ...treeItem,
        __children: filterMenuForAgentCapabilities(
          treeItem.__children,
          capabilities,
        ),
      },
    ];
  });
}
