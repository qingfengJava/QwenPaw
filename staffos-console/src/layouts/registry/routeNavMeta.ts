/**
 * routeNavMeta.ts — 非菜单路由的标签页/面包屑声明。
 *
 * 菜单叶子（navModel 索引）能覆盖绝大多数页面，但仍有两类路径需要额外声明：
 * 1. 详情页（员工详情 / 专家详情 / 内嵌应用）：菜单里没有它们，标签名要能由页面
 *    在拿到实体数据后回填（dynamic: true），未回填前用 titleKey/titleFallback 兜底；
 * 2. 重定向路由（/chat/* → /agents/:aid/chat 等）：它们只渲染 <Navigate>，若被建成
 *    标签会留下一张一点就跳走的死标签，因此显式排除。
 *
 * 这里只描述「怎么导航」，不描述「叫什么业务文案」——文案仍走 i18n key 或菜单数据。
 *
 * @author qingfeng
 */
import { matchNavEntry, normalizePathname, normalizeTabKey } from "./navModel";
import type { NavEntry, NavIndex } from "./navModel";

/** 单条路由的导航行为声明。 */
export interface RouteNavMeta {
  /** registry 中的路由 id，如 "core.agent-detail"。 */
  routeId: string;
  /** i18n key（静态标题用）。 */
  titleKey?: string;
  /** i18n 未命中或语言包缺键时的兜底文案。 */
  titleFallback?: string;
  /** 标签名由页面运行时通过 usePageNavTitle 回填。 */
  dynamic?: boolean;
  /** 归一化到前 N 段：同一实体的所有子导航共用一张标签。 */
  collapseSegments?: number;
  /**
   * 面包屑父级所在的列表页 path（如 /agents）。
   * 父级名称仍从菜单索引取，不在这里写任何文案常量。
   */
  parentPath?: string;
}

/**
 * 需要标签但不挂在菜单树上的路由。
 * collapseSegments 取值见各路由的 path 形状。
 */
export const ROUTE_NAV_META: RouteNavMeta[] = [
  {
    routeId: "core.agent-detail",
    titleKey: "nav.employees",
    titleFallback: "Digital Employee",
    dynamic: true,
    collapseSegments: 2,
    parentPath: "/agents",
  },
  {
    routeId: "core.agents-manage-detail",
    titleKey: "nav.employees",
    titleFallback: "Digital Employee",
    dynamic: true,
    collapseSegments: 3,
    parentPath: "/agents/manage",
  },
  {
    routeId: "core.agents-manage-schedule-runs",
    titleKey: "staffdeck.sched.runs",
    titleFallback: "Schedule Runs",
    dynamic: true,
    // 真实 path 为 /agents/manage/:expertId/schedules/:jobId/runs（6 段），截到 5 段
    // 即「一个定时任务一张标签」；截到 4 段会让同一员工的所有任务挤成一张。
    collapseSegments: 5,
    parentPath: "/agents/manage",
  },
  {
    routeId: "core.app-center.embed",
    titleKey: "nav.apps",
    titleFallback: "App",
    dynamic: true,
    collapseSegments: 2,
  },
];

/**
 * 重定向 / 宿主型路由：永不建标签、不出面包屑。
 * 清单对应 builtinRoutes.tsx 中所有渲染 <Navigate> 的条目。
 */
export const NON_TABBABLE_ROUTE_IDS: ReadonlySet<string> = new Set([
  "core.root",
  "core.chat",
  "core.files",
  "core.sessions",
  "core.cron-jobs",
  "core.heartbeat",
  "core.skills",
  "core.tools",
  "core.mcp",
  "core.acp",
  "core.acp-alias",
  "core.checkpoints",
  "core.agent-config",
  "core.agent-stats",
  "core.admin-experts",
  "core.admin-expert-detail",
  "core.admin-expert-teams",
  "core.admin-workforce-runs",
]);

/** 按路由 id 取导航声明。 */
export function findRouteNavMeta(
  routeId: string | undefined,
): RouteNavMeta | undefined {
  if (!routeId) return undefined;
  return ROUTE_NAV_META.find((meta) => meta.routeId === routeId);
}

/** 该路由 id 是否被明确排除在标签体系之外。 */
export function isNonTabbableRoute(routeId: string | undefined): boolean {
  if (!routeId) return false;
  return NON_TABBABLE_ROUTE_IDS.has(routeId);
}

/** 一个路径的标签化解析结果。 */
export interface TabbableResolution {
  /** 标签 key（归一化后的 path）。 */
  key: string;
  kind: "menu" | "detail";
  /** 命中的菜单叶子（菜单型才有）。 */
  navEntry?: NavEntry;
  /** 命中的路由声明（详情型才有）。 */
  meta?: RouteNavMeta;
}

/**
 * 判定一个 pathname 是否应当成为标签，并给出归一化 key。
 *
 * 优先级（顺序不可颠倒）：
 * 1. 排除名单（重定向路由）→ 不建标签；
 * 2. 菜单叶子精确命中 → 菜单型标签；
 * 3. 路由声明命中 → 详情型标签（按 collapseSegments 归一，同一实体共用一张）；
 *    必须先于前缀匹配，否则 /agents/a1 会被 /agents 菜单叶子吞掉，每个员工都
 *    被标成「数字员工」并各开一张新标签；
 * 4. 菜单叶子前缀命中（菜单页的子路径）→ 复用该菜单名，key 取完整路径。
 */
export function resolveTabbable(
  pathname: string,
  routeId: string | undefined,
  navIndex: NavIndex,
): TabbableResolution | undefined {
  if (isNonTabbableRoute(routeId)) return undefined;

  const normalized = normalizePathname(pathname);
  const exactEntry = navIndex.byPath.get(normalized);
  if (exactEntry) {
    return { key: normalizeTabKey(pathname), kind: "menu", navEntry: exactEntry };
  }

  const meta = findRouteNavMeta(routeId);
  if (meta) {
    return {
      key: normalizeTabKey(pathname, meta.collapseSegments),
      kind: "detail",
      meta,
    };
  }

  const prefixEntry = matchNavEntry(navIndex, pathname);
  if (prefixEntry) {
    return { key: normalizeTabKey(pathname), kind: "menu", navEntry: prefixEntry };
  }

  return undefined;
}
