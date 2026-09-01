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
const ChannelsPlatformPage = lazyImportWithRetry(
  "../../pages/Control/Channels/ChannelsPlatformPage.tsx",
);
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
const AgentsManagePage = lazyImportWithRetry(
  "../../pages/Agents/manage/ExpertsManagePage.tsx",
);
const AgentExpertDetailPage = lazyImportWithRetry(
  "../../pages/Agents/manage/ExpertDetailPage.tsx",
);
const AgentsTeamsPage = lazyImportWithRetry(
  "../../pages/Agents/manage/TeamsPage.tsx",
);
const AgentsRunsPage = lazyImportWithRetry(
  "../../pages/Agents/manage/RunsPage.tsx",
);
const AdminPendingPage = lazyImportWithRetry(
  "../../pages/Admin/Pending.tsx",
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

/**
 * Legacy /admin/experts* expert URLs → /agents/* (C1 merge: an expert IS a
 * digital employee). Query strings are preserved so backend-generated links
 * (pending.py: ?tab=work / ?runId=…) and bookmarks keep working. Guards live
 * on the target routes — a redirect itself must not bounce inside OS windows.
 */
function AdminExpertsRedirect() {
  const location = useLocation();
  return <Navigate to={`/agents/manage${location.search}`} replace />;
}
function AdminExpertDetailRedirect() {
  const location = useLocation();
  const rest = location.pathname.replace(/^\/admin\/experts/, "");
  return <Navigate to={`/agents/manage${rest}${location.search}`} replace />;
}
function AdminExpertTeamsRedirect() {
  const location = useLocation();
  return <Navigate to={`/agents/teams${location.search}`} replace />;
}
function AdminWorkforceRunsRedirect() {
  const location = useLocation();
  return <Navigate to={`/agents/runs${location.search}`} replace />;
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
  // 平台级渠道接入：全量渠道按员工分组聚合（阶段5平台化）。
  // 旧的 /channels 深链直达平台视图，从卡片再进入具体员工的绑定管理。
  { id: "core.channels", path: "/channels", component: ChannelsPlatformPage },
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
  // ── Digital-employee management (C1 merge): admin-only, under /agents. ──
  {
    id: "core.agents-manage",
    path: "/agents/manage",
    component: withRequireAdmin(AgentsManagePage),
  },
  {
    id: "core.agents-manage-detail",
    path: "/agents/manage/:expertId",
    component: withRequireAdmin(AgentExpertDetailPage),
  },
  {
    id: "core.agents-teams",
    path: "/agents/teams",
    component: withRequireAdmin(AgentsTeamsPage),
  },
  {
    id: "core.agents-runs",
    path: "/agents/runs",
    component: withRequireAdmin(AgentsRunsPage),
  },
  // Legacy /admin/* expert URLs → /agents/* (see redirect components above).
  {
    id: "core.admin-experts",
    path: "/admin/experts",
    component: AdminExpertsRedirect,
  },
  {
    id: "core.admin-expert-detail",
    path: "/admin/experts/:expertId",
    component: AdminExpertDetailRedirect,
  },
  {
    id: "core.admin-pending",
    path: "/admin/pending",
    component: withRequireAdmin(AdminPendingPage),
  },
  {
    id: "core.admin-expert-teams",
    path: "/admin/expert-teams",
    component: AdminExpertTeamsRedirect,
  },
  {
    id: "core.admin-workforce-runs",
    path: "/admin/workforce-runs",
    component: AdminWorkforceRunsRedirect,
  },
];

routeRegistry.addBuiltin(BUILTIN_ROUTES);

// Suspense imported above is used by lazyImportWithRetry consumers; ref keeps
// TS from tree-shaking the import in older bundler configs.
void Suspense;
