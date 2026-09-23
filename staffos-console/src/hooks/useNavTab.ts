/**
 * useNavTab.ts — 把「当前 pathname」解析成「当前标签」的共享 hook。
 *
 * MainLayout（建标签）、NavTabsBar（渲染标签与面包屑）、usePageNavTitle（详情页
 * 回填标题）三处必须用同一个解析器，否则会出现「建标签用一套 key、渲染用另一套」
 * 导致标签点不亮、面包屑查不到名字的问题。
 *
 * @author qingfeng
 */
import { useCallback } from "react";
import { useNavModel } from "./useNavModel";
import { matchRouteId } from "../layouts/registry/navModel";
import { resolveTabbable } from "../layouts/registry/routeNavMeta";
import type { TabbableResolution } from "../layouts/registry/routeNavMeta";
import type { NavIndex } from "../layouts/registry/navModel";

/** 标签解析器：输入 pathname，输出该路径的标签归属信息（不可标签化则 undefined）。 */
export type TabbableResolver = (pathname: string) => TabbableResolution | undefined;

/** 共享的标签解析器（内部持有 navIndex 与路由快照）。 */
export function useTabbableResolver(): {
  resolve: TabbableResolver;
  navIndex: NavIndex;
  routes: ReturnType<typeof useNavModel>["routes"];
  menusLoaded: boolean;
} {
  const { navIndex, routes, menusLoaded } = useNavModel();

  const resolve = useCallback<TabbableResolver>(
    (pathname) => resolveTabbable(pathname, matchRouteId(pathname, routes), navIndex),
    [navIndex, routes],
  );

  return { resolve, navIndex, routes, menusLoaded };
}
