/**
 * navModel.ts — 导航模型（面包屑 / 标签页）的唯一真源，纯函数无 React 依赖。
 *
 * 背景：此前每个页面在 PageHeader 上硬编码 `parent="平台管理"` 这类面包屑前缀，
 * 与后端 rbac_menus 的菜单名各写一份（已出现 "管理" / "平台管理" 两种不一致），
 * 菜单改名后页面路径不会跟着变。本模块把「路径 → 祖先链 + 显示名」收敛为一次
 * 遍历菜单树得到的索引，侧栏、顶部面包屑、标签页三处共用同一份判定。
 *
 * 两条硬约束：
 * 1. 显示名一律来自菜单数据（内置 BUILTIN_MENU 或后端 rbac_menus 经
 *    dynamicMenuAdapter 转换后的中性 MenuItem），本模块不产出任何文案常量；
 * 2. 匹配规则必须与 Sidebar 的 activeId 保持一致（最长前缀优先），否则会出现
 *    「侧栏高亮 A、面包屑显示 B」的漂移。
 *
 * @author qingfeng
 */
import { matchPath } from "react-router-dom";
import { resolveItemPath, resolveLabel } from "./adapter";
import type { RouteRef } from "./adapter";
import type { MenuItem } from "../../plugins/registry/types";

/** 动态菜单适配器挂在 MenuItem 上的子节点字段（与 Sidebar 消费形状一致）。 */
type MenuNode = MenuItem & { __children?: MenuNode[] };

/** 一个可导航叶子菜单的导航信息。 */
export interface NavEntry {
  /** 叶子菜单解析出的真实路由 path（如 "/admin/users"）。 */
  path: string;
  /** 叶子菜单显示名（已按当前语言解析）。 */
  label: string;
  /** 祖先链显示名，自顶向下，不含自身（如 ["平台管理"]）。 */
  trail: string[];
  /** 菜单项 id，便于反查权限与做埋点。 */
  menuId: string;
  /** 菜单图标原样透传，由渲染层用 adapter.renderIcon 处理。 */
  icon?: MenuItem["icon"];
}

/** path → NavEntry 的只读索引。 */
export interface NavIndex {
  byPath: Map<string, NavEntry>;
}

const EMPTY_INDEX: NavIndex = { byPath: new Map() };

/** 菜单 label 只取纯文本形态；JSX 型 label（如带未读 Badge 的装饰）不参与导航文案。 */
function labelToText(label: MenuItem["label"]): string {
  const node = resolveLabel(label);
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  return "";
}

/**
 * 遍历菜单树构建导航索引。
 *
 * @param items 已经过 dynamicMenuAdapter / 内置注册表合并后的菜单树（可多段拼接）。
 * @param routes 路由快照，用于把内置菜单的 route id 解析成真实 path。
 */
export function buildNavIndex(items: MenuItem[], routes: RouteRef[]): NavIndex {
  const byPath = new Map<string, NavEntry>();

  const walk = (nodes: MenuNode[], trail: string[]) => {
    for (const item of nodes) {
      // 显式隐藏项与分隔线不参与导航；外链在新标签打开，同样不建面包屑/标签。
      if (item.visible?.() === false || item.divider || item.href) continue;

      const label = labelToText(item.label);
      const children = item.__children ?? [];

      if (item.isGroup || children.length > 0) {
        walk(children, label ? [...trail, label] : trail);
        continue;
      }

      const path = resolveItemPath(item.route, routes);
      if (!path) continue;
      // 先到先得：侧栏靠前的段（platform）优先于同名 path 的重复注册。
      if (byPath.has(path)) continue;
      byPath.set(path, {
        path,
        label: label || path,
        trail,
        menuId: item.id,
        icon: item.icon,
      });
    }
  };

  walk(items as MenuNode[], []);
  return { byPath };
}

/** 去掉 query / hash 与结尾斜杠，得到用于比较与做 key 的路径。 */
export function normalizePathname(pathname: string): string {
  const clean = (pathname || "/").split(/[?#]/, 1)[0].replace(/\/+$/, "");
  return clean || "/";
}

/**
 * 标签/滚动记忆用的归一化 key。
 *
 * collapseSegments 用于详情页：`/agents/a1/chat` 与 `/agents/a1/files` 属于同一个
 * 数字员工，截断到前 2 段后共用一个标签，避免员工内部子导航炸出成排标签。
 */
export function normalizeTabKey(
  pathname: string,
  collapseSegments?: number,
): string {
  const base = normalizePathname(pathname);
  if (!collapseSegments || collapseSegments <= 0) return base;
  const parts = base.split("/").filter(Boolean);
  if (parts.length <= collapseSegments) return base;
  return `/${parts.slice(0, collapseSegments).join("/")}`;
}

/**
 * 菜单叶子匹配：与 Sidebar.activeId 同规则（精确或子路径，最长 path 胜出）。
 */
export function matchNavEntry(
  index: NavIndex,
  pathname: string,
): NavEntry | undefined {
  const path = normalizePathname(pathname);
  let best: NavEntry | undefined;
  let bestLength = -1;
  index.byPath.forEach((entry) => {
    const hit = path === entry.path || path.startsWith(`${entry.path}/`);
    if (hit && entry.path.length > bestLength) {
      best = entry;
      bestLength = entry.path.length;
    }
  });
  return best;
}

/** 参与标签/面包屑解析所需的最小路由形状（与 registry ResolvedRoute 兼容）。 */
export interface RouteLike extends RouteRef {
  source?: string;
}

/**
 * 路由 specificity 分值：静态段权重高于参数段，全段数相等再给整匹配加分。
 * 语义与 os/osRouteMap.ts 保持一致，但 layouts 不反向依赖桌面壳模块。
 */
function routeMatchScore(pathname: string, routePath: string): number {
  const pathParts = pathname.split("/").filter(Boolean);
  const patternParts = routePath.split("/").filter(Boolean);
  let score = 0;

  if (patternParts.length === 0) return pathParts.length === 0 ? 1000 : -1;

  for (let index = 0; index < patternParts.length; index += 1) {
    const part = patternParts[index];
    if (part === "*") return score + 1;
    const current = pathParts[index];
    if (!current) return -1;
    if (part.startsWith(":")) {
      score += 2;
    } else if (part === current) {
      score += part.length + 4;
    } else {
      return -1;
    }
  }

  return pathParts.length === patternParts.length ? score + 1000 : score;
}

/**
 * 解析 pathname 最匹配的路由 id。
 *
 * 必须做 specificity 排序：注册表里 `/agents/:aid/*` 排在 `/agents/manage` 之前，
 * 按声明顺序取首个匹配会把「数字员工管理」误判成员工详情。
 */
export function matchRouteId(
  pathname: string,
  routes: RouteLike[],
): string | undefined {
  const path = normalizePathname(pathname);
  if (!routes.length) return undefined;
  // `/` 由 DefaultRedirect 处理，不参与路由归属判定。
  if (path === "/") return undefined;

  let bestId: string | undefined;
  let bestScore = -1;
  for (const route of routes) {
    if (!route.path || route.path === "/") continue;
    if (!matchPath({ path: route.path, end: false }, path)) continue;
    const score = routeMatchScore(path, route.path);
    if (score > bestScore) {
      bestScore = score;
      bestId = route.id;
    }
  }
  return bestId;
}

/** 空索引常量：供 hook 在菜单未就绪时返回稳定引用，避免下游 effect 反复触发。 */
export const EMPTY_NAV_INDEX = EMPTY_INDEX;
