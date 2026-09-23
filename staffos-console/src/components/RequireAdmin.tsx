/**
 * RequireAdmin — RoleGuard for the `/admin/*` route branch (M5).
 *
 * Display-layer gate: non-admin identities are bounced to the chat page.
 * The backend re-checks `require_perm(...)` on every admin endpoint, so
 * this component is about UX (no dead menu entries), never about security.
 */
import type React from "react";
import { Navigate } from "react-router-dom";
import { useAuthStore, selectIsAdmin } from "../stores/authStore";

export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const isAdmin = useAuthStore(selectIsAdmin);
  if (!isAdmin) {
    return <Navigate to="/chat" replace />;
  }
  return <>{children}</>;
}

/**
 * Wrap a page component with the admin guard so it can be registered in
 * the route registry as a plain ComponentType.
 */
export function withRequireAdmin<P extends object>(
  Component: React.ComponentType<P>,
): React.ComponentType<P> {
  return function AdminGuardedPage(props: P) {
    return (
      <RequireAdmin>
        <Component {...props} />
      </RequireAdmin>
    );
  };
}
