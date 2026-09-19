/**
 * dynamicMenuAdapter.ts — 后端 rbac_menus 树 → 中性 MenuItem 树。
 *
 * 让「菜单管理」(rbac_menus) 成为左侧导航唯一数据源：把后端返回的菜单树
 * （permissionStore.MenuItem）转换成 Sidebar 现有渲染管线（toAntdItems /
 * flattenMenu / findParentGroupId / deriveOpenKeys）能直接消费的中性
 * MenuItem（plugins/registry/types），从而零改动复用折叠/手风琴/simple/
 * 选中高亮逻辑。
 *
 * 映射规则：
 *   - menu_type=directory → isGroup 分组；menu → 可点击叶子（route=真实 path）；
 *     button → 权限点，不进导航（过滤）。
 *   - is_visible=false 或 is_enabled=false → 过滤（不进导航）。
 *   - is_external=true → href=redirect||path（新标签打开）。
 *   - icon 字符串 → 组件（resolveMenuIcon，未命中兜底）。
 *   - label：name 命中已知 i18n key 才翻译，否则原样显示（多语言平滑兼容）。
 *
 * @author qingfeng
 */
import i18next from "i18next";
import type { MenuItem as RegistryMenuItem } from "../../plugins/registry/types";
import type { MenuItem as RbacMenuItem } from "../../stores/permissionStore";
import { resolveMenuIcon } from "./iconRegistry";

/** 中性 MenuItem + 渲染管线使用的 ad-hoc 子节点字段。 */
export type DynamicMenuItem = RegistryMenuItem & {
  __children?: DynamicMenuItem[];
};

/**
 * 解析菜单显示名：若 name 是已知的 i18n key（含点号且翻译结果不同于 key
 * 本身）则走 i18next，否则按管理员配置的原文显示。这样后端存中文名或存
 * "nav.workbench" 都能正确显示。
 */
export function resolveMenuLabel(name: string): string {
  if (!name) return "";
  if (name.includes(".")) {
    const translated = i18next.t(name);
    // i18next 未命中时原样返回 key，此时判定为普通文本。
    if (translated && translated !== name) return translated;
  }
  return name;
}

/** 是否应作为可点击叶子参与导航（页面型且启用可见）。 */
function isNavigableLeaf(menu: RbacMenuItem): boolean {
  return (
    menu.menu_type === "menu" &&
    menu.is_visible !== false &&
    menu.is_enabled !== false
  );
}

/**
 * 递归把后端菜单树转换为中性 MenuItem 树。button 型与不可见/禁用项被剔除。
 *
 * @param menus 后端 `/auth/menus` 返回的树（roots，children 已嵌套）。
 * @returns 供 Sidebar 渲染的中性 MenuItem 顶层数组。
 */
export function rbacMenusToRegistryItems(
  menus: RbacMenuItem[],
): DynamicMenuItem[] {
  const walk = (nodes: RbacMenuItem[]): DynamicMenuItem[] => {
    const out: DynamicMenuItem[] = [];
    for (const menu of nodes) {
      // button 型仅作权限树叶子，绝不进导航。
      if (menu.menu_type === "button") continue;
      // 目录/页面均需可见且启用。
      if (menu.is_visible === false || menu.is_enabled === false) continue;

      const children = menu.children?.length ? walk(menu.children) : [];

      const item: DynamicMenuItem = {
        id: menu.id,
        order: menu.sort_order ?? 0,
        label: () => resolveMenuLabel(menu.name),
        icon: resolveMenuIcon(menu.icon),
      };

      if (menu.menu_type === "directory") {
        item.isGroup = true;
      } else if (isNavigableLeaf(menu)) {
        if (menu.is_external) {
          item.href = menu.redirect || menu.path;
        } else if (menu.path) {
          // 动态项 route 直接存真实 path（Sidebar 点击/扁平化按 path 解析）。
          item.route = menu.path;
        }
      }

      if (children.length > 0) {
        item.__children = children;
      }

      // 空分组（无子节点）与不可点击的叶子（无 route/href）均丢弃，
      // 避免侧栏出现空目录或死条目。
      const hasChildren = children.length > 0;
      if (item.isGroup && !hasChildren) continue;
      if (!item.isGroup && !item.route && !item.href) continue;
      out.push(item);
    }
    return out;
  };

  return walk(menus ?? []);
}
