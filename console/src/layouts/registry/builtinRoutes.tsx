/**
 * builtinRoutes.ts — host's built-in routes as data.
 *
 * Importing self-registers all builtins into routeRegistry. MainLayout's
 * `useRoutes()` snapshot returns them. Plugin routes are registered via
 * `QwenPaw.route.add(...)` into the same registry and treated uniformly.
 *
 * Lazy components use `lazyImportWithRetry` inline; the eager Chat page is
 * passed as ComponentType directly. The `/` redirect is a
 * named route with a tiny DefaultRedirect component so routeRegistry has a
 * single uniform shape.
 *
 * Naming convention mirrors builtinMenu: `core.<key>`.
 */
import { Suspense } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { routeRegistry } from "../../plugins/registry/store";
import { withRequireAdmin } from "../../components/RequireAdmin";
import { useAgentStore } from "../../stores/agentStore";
import AgentDetailLayout from "../../pages/Agents/AgentDetailLayout";
import type { Route } from "../../plugins/registry/types";

// Lazy pages (platform-level only — agent-scoped pages are mounted inside
// AgentDetailLayout's sub-routes; their old top-level URLs are redirects now)
const WorkbenchPage = lazyImportWithRetry(
  "../../pages/Workbench/index.tsx",
);
const InboxPage = lazyImportWithRetry("../../pages/Inbox");
const SkillPoolPage = lazyImportWithRetry("../../pages/Settings/SkillPool");
const ModelsPage = lazyImportWithRetry("../../pages/Settings/Models");
const EnvironmentsPage = lazyImportWithRetry(
  "../../pages/Settings/Environments",
);
const OffloadPolicyPage = lazyImportWithRetry(
  "../../pages/Settings/OffloadPolicy",
);
const SecurityPage = lazyImportWithRetry("../../pages/Settings/Security");
const TokenUsagePage = lazyImportWithRetry("../../pages/Settings/TokenUsage");
const VoiceTranscriptionPage = lazyImportWithRetry(
  "../../pages/Settings/VoiceTranscription",
);
const AgentsPage = lazyImportWithRetry(
  "../../pages/Agents/AgentsGalleryPage.tsx",
);
const DebugPage = lazyImportWithRetry("../../pages/Settings/Debug");
const BackupsPage = lazyImportWithRetry("../../pages/Settings/Backups");
const PluginManagerPage = lazyImportWithRetry(
  "../../pages/Settings/PluginManager",
);
const AppCenterPage = lazyImportWithRetry("../../pages/AppCenter");

// Admin pages (M5): flat .tsx files, wrapped in the RoleGuard at registration.
const AdminUsersPage = lazyImportWithRetry("../../pages/Admin/Users.tsx");
const AdminRolesPage = lazyImportWithRetry("../../pages/Admin/Roles.tsx");
const AdminTeamsPage = lazyImportWithRetry("../../pages/Admin/Teams.tsx");
const AdminAgentGrantsPage = lazyImportWithRetry(
  "../../pages/Admin/AgentGrants.tsx",
);
const AdminModelGrantsPage = lazyImportWithRetry(
  "../../pages/Admin/ModelGrants.tsx",
);
const AdminQuotasPage = lazyImportWithRetry("../../pages/Admin/Quotas.tsx");
const AdminAuditPage = lazyImportWithRetry("../../pages/Admin/Audit.tsx");
const AdminKnowledgePage = lazyImportWithRetry(
  "../../pages/Admin/Knowledge.tsx",
);
const AdminOrganizationPage = lazyImportWithRetry(
  "../../pages/Admin/Organization.tsx",
);
const AdminExpertsPage = lazyImportWithRetry(
  "../../pages/Admin/Experts.tsx",
);
const AdminExpertDetailPage = lazyImportWithRetry(
  "../../pages/Admin/ExpertDetail.tsx",
);
const AdminPendingPage = lazyImportWithRetry(
  "../../pages/Admin/Pending.tsx",
);
const AdminExpertTeamsPage = lazyImportWithRetry(
  "../../pages/Admin/ExpertTeams.tsx",
);
const AdminWorkforceRunsPage = lazyImportWithRetry(
  "../../pages/Admin/WorkforceRuns.tsx",
);

/** "/" lands on the platform workbench. */
function DefaultRedirect() {
  return <Navigate to="/workbench" replace />;
}

/**
 * Old agent-scoped top-level URLs → /agents/:aid/<sub>.
 * `aid` comes from the remembered selectedAgent so deep links keep working;
 * the sub-path beyond the first segment (e.g. /chat/<sessionId>) is preserved.
 */
function createAgentScopedRedirect(subPath: string) {
  return function AgentScopedRedirect() {
    const location = useLocation();
    const aid = useAgentStore.getState().selectedAgent || "default";
    const rest = location.pathname.split("/").slice(2).join("/");
    const target = `/agents/${aid}/${subPath}${rest ? `/${rest}` : ""}${location.search}`;
    return <Navigate to={target} replace />;
  };
}

/** Synonym for /acp. Kept for plugins / external links that reference uppercase. */
function ACPRedirect() {
  return <Navigate to="/acp" replace />;
}

export const BUILTIN_ROUTES: Route[] = [
  { id: "core.root", path: "/", component: DefaultRedirect },
  {
    id: "core.workbench",
    path: "/workbench",
    component: WorkbenchPage,
  },
  { id: "core.chat", path: "/chat/*", component: createAgentScopedRedirect("chat") },
  { id: "core.files", path: "/files", component: createAgentScopedRedirect("files") },
  { id: "core.channels", path: "/channels", component: createAgentScopedRedirect("channels") },
  { id: "core.sessions", path: "/sessions", component: createAgentScopedRedirect("sessions") },
  { id: "core.inbox", path: "/inbox", component: InboxPage },
  { id: "core.cron-jobs", path: "/cron-jobs", component: createAgentScopedRedirect("cron-jobs") },
  { id: "core.heartbeat", path: "/heartbeat", component: createAgentScopedRedirect("heartbeat") },
  { id: "core.skills", path: "/skills", component: createAgentScopedRedirect("skills") },
  { id: "core.skill-pool", path: "/skill-pool", component: SkillPoolPage },
  { id: "core.tools", path: "/tools", component: createAgentScopedRedirect("tools") },
  { id: "core.mcp", path: "/mcp", component: createAgentScopedRedirect("mcp") },
  { id: "core.acp", path: "/acp", component: createAgentScopedRedirect("acp") },
  { id: "core.acp-alias", path: "/ACP", component: ACPRedirect },
  { id: "core.checkpoints", path: "/checkpoints", component: createAgentScopedRedirect("checkpoints") },
  { id: "core.agents", path: "/agents", component: AgentsPage },
  {
    id: "core.agent-detail",
    path: "/agents/:aid/*",
    component: AgentDetailLayout,
  },
  { id: "core.models", path: "/models", component: ModelsPage },
  {
    id: "core.environments",
    path: "/environments",
    component: EnvironmentsPage,
  },
  {
    id: "core.offload-policy",
    path: "/offload-policy",
    component: OffloadPolicyPage,
  },
  {
    id: "core.agent-config",
    path: "/agent-config",
    component: createAgentScopedRedirect("config"),
  },
  { id: "core.security", path: "/security", component: SecurityPage },
  { id: "core.token-usage", path: "/token-usage", component: TokenUsagePage },
  { id: "core.agent-stats", path: "/agent-stats", component: createAgentScopedRedirect("stats") },
  {
    id: "core.voice-transcription",
    path: "/voice-transcription",
    component: VoiceTranscriptionPage,
  },
  { id: "core.debug", path: "/debug", component: DebugPage },
  { id: "core.backups", path: "/backups", component: BackupsPage },
  {
    id: "core.plugin-manager",
    path: "/plugin-manager",
    component: PluginManagerPage,
  },
  { id: "core.app-center", path: "/apps", component: AppCenterPage },
  // Deep-link / refresh target: `/apps/<id>` also lands on the App Center,
  // which opens the app inline (with the “← App Center” bar) from the URL.
  {
    id: "core.app-center.embed",
    path: "/apps/:appId",
    component: AppCenterPage,
  },

  // ── /admin/* branch (M5): RoleGuard bounces non-admin identities. ──────
  {
    id: "core.admin-users",
    path: "/admin/users",
    component: withRequireAdmin(AdminUsersPage),
  },
  {
    id: "core.admin-roles",
    path: "/admin/roles",
    component: withRequireAdmin(AdminRolesPage),
  },
  {
    id: "core.admin-teams",
    path: "/admin/teams",
    component: withRequireAdmin(AdminTeamsPage),
  },
  {
    id: "core.admin-agent-grants",
    path: "/admin/agent-grants",
    component: withRequireAdmin(AdminAgentGrantsPage),
  },
  {
    id: "core.admin-model-grants",
    path: "/admin/model-grants",
    component: withRequireAdmin(AdminModelGrantsPage),
  },
  {
    id: "core.admin-quotas",
    path: "/admin/quotas",
    component: withRequireAdmin(AdminQuotasPage),
  },
  {
    id: "core.admin-audit",
    path: "/admin/audit",
    component: withRequireAdmin(AdminAuditPage),
  },
  {
    id: "core.admin-knowledge",
    path: "/admin/knowledge",
    component: withRequireAdmin(AdminKnowledgePage),
  },
  {
    id: "core.admin-organization",
    path: "/admin/organization",
    component: withRequireAdmin(AdminOrganizationPage),
  },
  {
    id: "core.admin-experts",
    path: "/admin/experts",
    component: withRequireAdmin(AdminExpertsPage),
  },
  {
    id: "core.admin-expert-detail",
    path: "/admin/experts/:expertId",
    component: withRequireAdmin(AdminExpertDetailPage),
  },
  {
    id: "core.admin-pending",
    path: "/admin/pending",
    component: withRequireAdmin(AdminPendingPage),
  },
  {
    id: "core.admin-expert-teams",
    path: "/admin/expert-teams",
    component: withRequireAdmin(AdminExpertTeamsPage),
  },
  {
    id: "core.admin-workforce-runs",
    path: "/admin/workforce-runs",
    component: withRequireAdmin(AdminWorkforceRunsPage),
  },
];

routeRegistry.addBuiltin(BUILTIN_ROUTES);

// Suspense imported above is used by lazyImportWithRetry consumers; ref keeps
// TS from tree-shaking the import in older bundler configs.
void Suspense;
