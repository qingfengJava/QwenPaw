/**
 * tabLabel.ts — 把标签归属解析成「显示名 + 面包屑祖先链」。
 *
 * 与 resolveTabbable 分开，是为了让「建标签」这条热路径不必每次翻译文案，
 * 同时把取名优先级集中在一处可单测的纯函数里：
 *   菜单名 > 详情页回填的实体名 > 路由声明的 i18n 兜底 > 路径本身。
 *
 * @author qingfeng
 */
import { getPageTitle } from "./pageTitleRegistry";
import type { NavIndex, NavEntry } from "./navModel";
import type { RouteNavMeta, TabbableResolution } from "./routeNavMeta";

/** 渲染层需要的标签描述。 */
export interface TabDescription {
  key: string;
  label: string;
  /** 面包屑祖先链（不含自身）。 */
  trail: string[];
  /** 菜单图标（详情型通常为空）。 */
  icon?: NavEntry["icon"];
}

/** 文案翻译函数（与 react-i18next 的 t 兼容的最小签名）。 */
export type NavTranslate = (key: string, defaultValue?: string) => string;

function metaTitle(meta: RouteNavMeta, translate: NavTranslate): string {
  if (meta.titleKey) return translate(meta.titleKey, meta.titleFallback) || "";
  return meta.titleFallback ?? "";
}

/** 详情型的父级名称：按声明的列表页 path 回查菜单，绝不在此写死文案。 */
function parentTrailOfMeta(
  meta: RouteNavMeta,
  navIndex: NavIndex,
): string[] {
  if (!meta.parentPath) return [];
  const parent = navIndex.byPath.get(meta.parentPath);
  if (!parent) return [];
  return [...parent.trail, parent.label];
}

/**
 * 解析一张标签的显示名与面包屑。
 *
 * @param resolution resolveTabbable 的结果（undefined 时返回 undefined）。
 * @param navIndex 菜单索引，用于详情型回查父级名称。
 * @param translate 翻译函数。
 */
export function describeTab(
  resolution: TabbableResolution | undefined,
  navIndex: NavIndex,
  translate: NavTranslate,
): TabDescription | undefined {
  if (!resolution) return undefined;
  const { key, kind, navEntry, meta } = resolution;

  if (kind === "menu" && navEntry) {
    return {
      key,
      label: navEntry.label,
      trail: navEntry.trail,
      icon: navEntry.icon,
    };
  }

  const dynamicTitle = getPageTitle(key);
  const fallbackTitle = meta ? metaTitle(meta, translate) : "";
  return {
    key,
    label: dynamicTitle || fallbackTitle || key,
    trail: meta ? parentTrailOfMeta(meta, navIndex) : [],
    icon: undefined,
  };
}
