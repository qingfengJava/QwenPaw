/**
 * useNavModel.ts — 侧栏 / 顶部面包屑 / 多标签页共用的导航判定。
 *
 * 原先「哪一段菜单属于哪个分组」「当前高亮哪个菜单项」只写在 Sidebar 内部，
 * 顶部导航条若再实现一遍，两套判定必然漂移（侧栏高亮 A、面包屑显示 B）。本 hook
 * 把这些计算上收为唯一实现，并额外产出按 path 索引的面包屑元数据 navIndex。
 *
 * 注意引用稳定性：动态模式下 settingsMenu 必须是模块级常量，不能每次渲染新建
 * `[]`，否则 Sidebar 依赖它的 openKeys effect 会在每次渲染后把展开组重置回弹。
 *
 * @author qingfeng
 */
import { useMemo } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMenuItems, useAllMenuItems, useRoutes } from "../plugins/registry/hooks";
import { buildNavIndex, matchNavEntry } from "../layouts/registry/navModel";
import { rbacMenusToRegistryItems } from "../layouts/registry/dynamicMenuAdapter";
import { useDynamicMenus } from "./useDynamicMenus";
import { useSidebarModeStore } from "../stores/sidebarModeStore";
import type { NavIndex } from "../layouts/registry/navModel";
import type { MenuItem } from "../plugins/registry/types";

/** 动态模式下 settings 段为空（全部菜单走单个 agentMenu 树）。 */
const EMPTY_MENU_ITEMS: MenuItem[] = [];

/** 简洁侧栏模式下仍然保留的菜单项 id。 */
const SIMPLE_MODE_WHITELIST = new Set([
  "core.workbench",
  "core.agents",
  "core.channels",
  "core.inbox",
  "core.marketplace",
  "core.models",
  "core.skill-pool",
]);

type MenuNode = MenuItem & { __children?: MenuNode[] };

/**
 * 简洁模式：把分组拍平，只保留白名单叶子（分组本身不出现在结果里）。
 */
function flattenForSimpleMode(items: MenuItem[]): MenuItem[] {
  const result: MenuItem[] = [];
  for (const rawItem of items) {
    const item = rawItem as MenuNode;
    if (item.__children && item.__children.length > 0) {
      item.__children.forEach((child) => {
        if (SIMPLE_MODE_WHITELIST.has(child.id)) result.push(child);
      });
      continue;
    }
    if (SIMPLE_MODE_WHITELIST.has(item.id)) result.push(item);
  }
  return result;
}

/** 导航模型快照，所有字段在同一渲染内自洽。 */
export interface NavModel {
  /** 注册表路由快照（内置 + 插件）。 */
  routes: ReturnType<typeof useRoutes>;
  /** 菜单是否来自后端 rbac_menus（false 表示内置注册表兜底）。 */
  isDynamic: boolean;
  /** 权限菜单是否已加载完成（未就绪时导航条只出骨架，避免面包屑闪空）。 */
  menusLoaded: boolean;
  /** 侧栏主段菜单（已按简洁模式与插件分组处理）。 */
  agentMenu: MenuItem[];
  /** 侧栏系统段菜单，动态模式下恒为空数组常量。 */
  settingsMenu: MenuItem[];
  /** path → 面包屑元数据索引。 */
  navIndex: NavIndex;
  /** 当前应高亮的菜单项 id（侧栏与面包屑共用）。 */
  activeId: string | undefined;
}

/** 侧栏 / 顶部导航条共用的导航判定 hook。 */
export function useNavModel(): NavModel {
  const { t } = useTranslation();
  const location = useLocation();
  const routes = useRoutes();
  const { mode: sidebarMode } = useSidebarModeStore();

  const rawPlatformMenu = useMenuItems("primary.platform");
  const rawLegacyAgentMenu = useMenuItems("primary.agentScoped");
  const rawSettingsMenu = useMenuItems("primary.settings");
  const allMenuItems = useAllMenuItems();
  const { menus: dynamicMenuTree, source: menuSource, loaded } =
    useDynamicMenus();
  const isDynamic = menuSource === "backend";

  // 内置平台段：简洁模式拍平，并把第三方插件注册的 agentScoped 项并成尾部分组。
  const builtinAgentMenu = useMemo(() => {
    const platformMenu =
      sidebarMode === "simple"
        ? flattenForSimpleMode(rawPlatformMenu)
        : rawPlatformMenu;
    const legacy = rawLegacyAgentMenu.filter((item) => !item.isGroup);
    if (legacy.length === 0) return platformMenu;
    const pluginGroup = {
      id: "platform.plugins-group",
      label: () => t("nav.plugins", "Plugins"),
      isGroup: true,
      order: 900,
      __children: legacy.map((item) => ({
        ...item,
        parentId: "platform.plugins-group",
      })),
    } as MenuItem;
    return [...platformMenu, pluginGroup];
  }, [rawPlatformMenu, rawLegacyAgentMenu, sidebarMode, t]);

  const builtinSettingsMenu = useMemo(
    () =>
      sidebarMode === "simple"
        ? flattenForSimpleMode(rawSettingsMenu)
        : rawSettingsMenu,
    [rawSettingsMenu, sidebarMode],
  );

  // 动态模式：后端树 → 中性 MenuItem，并合并第三方插件注册的非 core 菜单。
  const dynamicPrimaryMenu = useMemo<MenuItem[]>(() => {
    if (!isDynamic) return EMPTY_MENU_ITEMS;
    const items = rbacMenusToRegistryItems(dynamicMenuTree);
    const pluginItems = allMenuItems.filter(
      (i) =>
        !i.id.startsWith("core.") && !i.isGroup && i.visible?.() !== false,
    );
    return [...items, ...(pluginItems as MenuItem[])];
  }, [isDynamic, dynamicMenuTree, allMenuItems]);

  const agentMenu: MenuItem[] = isDynamic
    ? dynamicPrimaryMenu
    : builtinAgentMenu;
  const settingsMenu: MenuItem[] = isDynamic
    ? EMPTY_MENU_ITEMS
    : builtinSettingsMenu;

  // 面包屑索引：语言切换后菜单 label 会变，必须把当前翻译函数纳入依赖。
  const navIndex = useMemo(
    () => buildNavIndex([...agentMenu, ...settingsMenu], routes),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [agentMenu, settingsMenu, routes, t],
  );

  // 当前高亮菜单 id：与面包屑同源（navIndex 最长前缀匹配），动态/内置两种模式
  // 走同一条判定，杜绝「侧栏高亮 A、面包屑显示 B」的漂移。
  const activeId = useMemo<string | undefined>(
    () => matchNavEntry(navIndex, location.pathname)?.menuId,
    [navIndex, location.pathname],
  );

  return {
    routes,
    isDynamic,
    menusLoaded: loaded,
    agentMenu,
    settingsMenu,
    navIndex,
    activeId,
  };
}
