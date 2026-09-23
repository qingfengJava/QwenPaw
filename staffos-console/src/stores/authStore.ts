import { create } from "zustand";

/**
 * authStore — the caller's identity as reported by `GET /auth/verify` (M5).
 *
 * Powers role-based menu/route filtering in the console. This is a
 * display-layer concern only: every admin endpoint re-checks permissions
 * server-side (`require_perm`), so a forged local state cannot escalate.
 */

/** RBAC role name held by platform administrators (mirrors rbac/models.py). */
export const RBAC_ROLE_PLATFORM_ADMIN = "platform_admin";

/** M1 flat role held by administrators (mirrors users/models.py). */
export const FLAT_ROLE_ADMIN = "admin";

export interface AuthIdentity {
  username: string;
  /** M1 flat role: "admin" | "employee" | "" (unknown / lookup failed). */
  role: string;
  /** M4 RBAC role names (e.g. "platform_admin", "team_lead"). */
  roles: string[];
}

interface AuthState extends AuthIdentity {
  /** True once AuthGuard finished the initial verify round-trip. */
  loaded: boolean;
  setIdentity: (identity: AuthIdentity) => void;
  clear: () => void;
}

const ANONYMOUS: AuthIdentity = { username: "", role: "", roles: [] };

/**
 * Identity recorded when authentication is disabled server-side: the
 * deployment is single-user, so every menu stays visible (pre-M5 behaviour).
 */
export const AUTH_DISABLED_IDENTITY: AuthIdentity = {
  username: "",
  role: FLAT_ROLE_ADMIN,
  roles: [RBAC_ROLE_PLATFORM_ADMIN],
};

/** Display-layer admin check; usable as a zustand selector. */
export function selectIsAdmin(s: AuthIdentity): boolean {
  return s.role === FLAT_ROLE_ADMIN || s.roles.includes(RBAC_ROLE_PLATFORM_ADMIN);
}

/** Standalone check for non-React call sites (menu `visible` callbacks). */
export function isAdminIdentity(identity: AuthIdentity): boolean {
  return selectIsAdmin(identity);
}

export const useAuthStore = create<AuthState>((set) => ({
  ...ANONYMOUS,
  loaded: false,

  setIdentity: (identity) =>
    set({
      username: identity.username,
      role: identity.role,
      roles: identity.roles,
      loaded: true,
    }),

  clear: () => set({ ...ANONYMOUS, loaded: false }),
}));
