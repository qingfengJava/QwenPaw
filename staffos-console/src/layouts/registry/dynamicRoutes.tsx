/**
 * dynamicRoutes.tsx — 由后端菜单动态生成页面路由（动态菜单驱动路由）。
 *
 * 菜单项的 `component` 字段（如 "Admin/Users"）经 `lazyImportWithRetry`
 * 解析为按页分包的懒加载组件；MainLayout 把这里产出的路由与内置
 * routeRegistry 合并（内置优先去重），实现"菜单里新增一项指向已存在页面
 * 即可生成新路由"，同时不破坏 chat/agent-detail/redirect 等功能路由。
 *
 * @author qingfeng
 */
import type { ComponentType } from "react";
import { Navigate } from "react-router-dom";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { usePermissionStore } from "../../stores/permissionStore";
import type { MenuItem } from "../../stores/permissionStore";

/** 动态路由条目（与 routeRegistry.snapshot 的 ResolvedRoute 渲染形状兼容）。 */
export interface DynamicRoute {
  id: string;
  path: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Component: ComponentType<any>;
}

/**
 * 给页面组件套一层按 perm_code 的展示级守卫（防御性；后端接口另有
 * require_perm 强制）。无 perm_code 时原样返回，不额外包裹。
 */
export function withPermGuard(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Component: ComponentType<any>,
  permCode: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): ComponentType<any> {
  if (!permCode) return Component;
  function PermGuarded(props: Record<string, unknown>) {
    const allowed = usePermissionStore((s) => s.hasPerm(permCode));
    if (!allowed) {
      return <Navigate to="/workbench" replace />;
    }
    return <Component {...props} />;
  }
  return PermGuarded;
}

/**
 * 遍历菜单树，为「页面型且有 path + component」的项生成懒加载路由。
 *
 * @param menus `/auth/menus` 返回的菜单树（roots，children 已嵌套）。
 */
export function buildDynamicRoutes(menus: MenuItem[]): DynamicRoute[] {
  const out: DynamicRoute[] = [];
  const walk = (nodes: MenuItem[]) => {
    for (const menu of nodes) {
      if (
        menu.menu_type === "menu" &&
        menu.path &&
        menu.component &&
        menu.is_visible !== false &&
        menu.is_enabled !== false
      ) {
        // 约定：component = 相对 pages 的路径串（"Admin/Users"）。
        const page = lazyImportWithRetry(`../../pages/${menu.component}`);
        out.push({
          id: `dyn:${menu.id}`,
          path: menu.path,
          Component: withPermGuard(page, menu.perm_code),
        });
      }
      if (menu.children?.length) walk(menu.children);
    }
  };
  walk(menus ?? []);
  return out;
}
