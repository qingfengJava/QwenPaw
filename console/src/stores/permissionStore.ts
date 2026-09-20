/**
 * permissionStore.ts — RBAC permission & dynamic menu state (M7 PG-RBAC).
 *
 * Manages the current user's permission codes and backend-provided menu tree.
 * Supports wildcard matching: `*` grants everything, `resource:*` grants all
 * actions under that resource.
 *
 * When authentication is disabled (AUTH_DISABLED_IDENTITY), all permissions are
 * auto-granted (`['*']`) so the UI stays fully accessible.
 */
import { create } from "zustand";
import { request } from "../api/request";
import {
  useAuthStore,
  AUTH_DISABLED_IDENTITY,
} from "./authStore";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

/** Menu item as returned by `GET /auth/menus` (mirrors backend MenuRecord). */
export interface MenuItem {
  id: string;
  parent_id: string | null;
  name: string;
  menu_type: "directory" | "menu" | "button";
  path: string;
  component: string;
  icon: string;
  perm_code: string;
  sort_order: number;
  is_visible: boolean;
  is_enabled: boolean;
  is_external: boolean;
  redirect: string;
  children?: MenuItem[];
}

interface PermissionState {
  // ── State ──────────────────────────────────────────────────────────────
  /** Flat list of permission codes held by the current user. */
  permissions: string[];
  /** Backend-provided menu tree for the current user. */
  menus: MenuItem[];
  /** True once loadAll() has completed (success or auth-disabled shortcut). */
  loaded: boolean;
  /** True while a fetch is in-flight. */
  loading: boolean;

  // ── Actions ────────────────────────────────────────────────────────────
  fetchPermissions: () => Promise<void>;
  fetchMenus: () => Promise<void>;
  /** Load permissions + menus in parallel. Short-circuits when auth disabled. */
  loadAll: () => Promise<void>;
  /** Reset to initial state (call on logout). */
  reset: () => void;

  // ── Selectors (as methods) ─────────────────────────────────────────────
  /** Check a single permission code. Supports `*` and `resource:*` wildcards. */
  hasPerm: (code: string) => boolean;
  /** True if user holds ANY of the given codes. */
  hasAnyPerm: (codes: string[]) => boolean;
  /** True if user holds ALL of the given codes. */
  hasAllPerms: (codes: string[]) => boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Detect whether the deployment runs with authentication disabled by checking
 * if authStore holds the AUTH_DISABLED_IDENTITY sentinel.
 */
function isAuthDisabled(): boolean {
  const auth = useAuthStore.getState();
  return (
    auth.loaded &&
    auth.username === AUTH_DISABLED_IDENTITY.username &&
    auth.role === AUTH_DISABLED_IDENTITY.role
  );
}

/**
 * Wildcard-aware permission match.
 * - `*` in held permissions → matches everything.
 * - `resource:*` → matches any code starting with `resource:`.
 * - Exact match otherwise.
 */
function matchPerm(held: string[], code: string): boolean {
  if (held.includes("*")) return true;
  if (held.includes(code)) return true;

  // Check wildcard patterns like "admin:*"
  const segments = code.split(":");
  for (let i = segments.length - 1; i >= 1; i--) {
    const pattern = segments.slice(0, i).join(":") + ":*";
    if (held.includes(pattern)) return true;
  }
  return false;
}

// ─────────────────────────────────────────────────────────────────────────────
// Store
// ─────────────────────────────────────────────────────────────────────────────

export const usePermissionStore = create<PermissionState>((set, get) => ({
  permissions: [],
  menus: [],
  loaded: false,
  loading: false,

  fetchPermissions: async () => {
    const perms = await request<string[]>("/auth/permissions");
    set({ permissions: Array.isArray(perms) ? perms : [] });
  },

  fetchMenus: async () => {
    const menus = await request<MenuItem[]>("/auth/menus");
    set({ menus: Array.isArray(menus) ? menus : [] });
  },

  loadAll: async () => {
    // Auth-disabled shortcut: grant permissions locally, but still fetch the
    // backend menu tree — /auth/menus returns the full tree when auth is
    // disabled (symmetric with the ["*"] grant), so dynamic menus work in
    // single-user deployments too. On failure keep [] so useDynamicMenus
    // falls back to the builtin menu.
    if (isAuthDisabled()) {
      set({ permissions: ["*"], menus: [], loaded: true, loading: false });
      try {
        await get().fetchMenus();
      } catch (error) {
        console.warn(
          "[permissionStore] Failed to fetch menus (auth disabled):",
          error,
        );
      }
      return;
    }

    set({ loading: true });
    try {
      await Promise.all([get().fetchPermissions(), get().fetchMenus()]);
      set({ loaded: true });
    } catch (error) {
      // Degrade gracefully: log but don't block the UI.
      console.warn("[permissionStore] Failed to load permissions/menus:", error);
      set({ loaded: true });
    } finally {
      set({ loading: false });
    }
  },

  reset: () => {
    set({ permissions: [], menus: [], loaded: false, loading: false });
  },

  hasPerm: (code: string) => {
    return matchPerm(get().permissions, code);
  },

  hasAnyPerm: (codes: string[]) => {
    if (codes.length === 0) return true;
    const { permissions } = get();
    return codes.some((c) => matchPerm(permissions, c));
  },

  hasAllPerms: (codes: string[]) => {
    if (codes.length === 0) return true;
    const { permissions } = get();
    return codes.every((c) => matchPerm(permissions, c));
  },
}));
