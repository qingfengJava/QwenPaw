/**
 * HasPerm.tsx — Button-level permission guard component (M7 PG-RBAC).
 *
 * Usage:
 *   <HasPerm code="admin:users:create"><Button>Create</Button></HasPerm>
 *   <HasPerm codes={["admin:users:edit", "admin:users:delete"]} mode="all">...</HasPerm>
 *
 * Also exports a `usePermission` hook for imperative checks.
 */
import React from "react";
import { usePermissionStore } from "../stores/permissionStore";

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export interface HasPermProps {
  /** Single permission code, e.g. "admin:users:create". */
  code?: string;
  /** Multiple permission codes; combined with `mode`. */
  codes?: string[];
  /** Match mode: "any" (default) = at least one; "all" = every one. */
  mode?: "any" | "all";
  /** Rendered when permission check fails. Defaults to null (nothing). */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Declarative permission guard. Renders `children` when the current user
 * holds the required permission(s); otherwise renders `fallback`.
 */
export const HasPerm: React.FC<HasPermProps> = ({
  code,
  codes,
  mode = "any",
  fallback = null,
  children,
}) => {
  const hasPerm = usePermissionStore((s) => s.hasPerm);
  const hasAnyPerm = usePermissionStore((s) => s.hasAnyPerm);
  const hasAllPerms = usePermissionStore((s) => s.hasAllPerms);
  // Subscribe to permissions array so the component re-renders on change.
  const permissions = usePermissionStore((s) => s.permissions);

  // Determine the effective code list.
  const effectiveCodes: string[] = codes ?? (code ? [code] : []);

  // No codes specified → always render children.
  if (effectiveCodes.length === 0) {
    return <>{children}</>;
  }

  let allowed: boolean;
  if (effectiveCodes.length === 1) {
    allowed = hasPerm(effectiveCodes[0]);
  } else if (mode === "all") {
    allowed = hasAllPerms(effectiveCodes);
  } else {
    allowed = hasAnyPerm(effectiveCodes);
  }

  // Reference permissions to suppress unused-variable lint; the subscription
  // is what triggers re-render when permissions change.
  void permissions;

  return allowed ? <>{children}</> : <>{fallback}</>;
};

export default HasPerm;

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Imperative permission-check hook.
 *
 * ```tsx
 * const { hasPerm } = usePermission();
 * if (hasPerm("admin:users:create")) { ... }
 * ```
 */
export const usePermission = () => {
  const hasPerm = usePermissionStore((s) => s.hasPerm);
  const hasAnyPerm = usePermissionStore((s) => s.hasAnyPerm);
  const hasAllPerms = usePermissionStore((s) => s.hasAllPerms);
  return { hasPerm, hasAnyPerm, hasAllPerms };
};
