/**
 * useDynamicMenus.ts — Dynamic menu hook (M7 PG-RBAC).
 *
 * Prioritizes backend-provided menu data from permissionStore; falls back to
 * the hardcoded BUILTIN_MENU when the backend hasn't supplied menus (e.g.
 * auth disabled, API not yet available, or empty response).
 *
 * Consumers (Sidebar, route builders) can check `source` to determine whether
 * the menus are dynamic (backend) or static (builtin fallback).
 */
import { useMemo } from "react";
import { usePermissionStore, type MenuItem } from "../stores/permissionStore";
import { BUILTIN_MENU } from "../layouts/registry/builtinMenu";
import type { MenuItem as BuiltinMenuItem } from "../plugins/registry/types";

export interface DynamicMenusResult {
  /** Backend menu tree (empty when using builtin fallback). */
  menus: MenuItem[];
  /** The builtin menu entries (always available for fallback rendering). */
  builtinMenus: BuiltinMenuItem[];
  /** Which source is active: "backend" or "builtin". */
  source: "backend" | "builtin";
  /** Whether the permission store has finished loading. */
  loaded: boolean;
}

/**
 * Dynamic menu hook.
 *
 * - If backend menus are loaded and non-empty → `source === "backend"`, `menus`
 *   contains the tree from the API.
 * - Otherwise → `source === "builtin"`, `builtinMenus` provides the static
 *   BUILTIN_MENU entries for the existing sidebar renderer.
 */
export function useDynamicMenus(): DynamicMenusResult {
  const menus = usePermissionStore((s) => s.menus);
  const loaded = usePermissionStore((s) => s.loaded);

  return useMemo(() => {
    if (loaded && menus.length > 0) {
      return {
        menus,
        builtinMenus: BUILTIN_MENU,
        source: "backend" as const,
        loaded,
      };
    }
    return {
      menus: [] as MenuItem[],
      builtinMenus: BUILTIN_MENU,
      source: "builtin" as const,
      loaded,
    };
  }, [menus, loaded]);
}
