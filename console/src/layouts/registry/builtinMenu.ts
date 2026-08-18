/**
 * builtinMenu.ts — host's built-in sidebar menu entries as data.
 *
 * Importing this module self-registers all builtins into menuRegistry, so the
 * Sidebar's `useMenuItems()` snapshot returns them on first render. Plugins
 * register via `QwenPaw.menu.add(...)` which lands in the same registry, so
 * Sidebar treats core + plugin items uniformly.
 *
 * ── Naming convention ──────────────────────────────────────────────────────
 *  Group ids: `core.<name>-group` (e.g. core.control-group)
 *  Item ids:  `core.<key>`        (e.g. core.workspace)
 *  Plugin items use their own prefix (e.g. cloudpaw.a2a) — no clash possible.
 *
 * ── Sticky chat button carve-out ───────────────────────────────────────────
 *  `core.chat` is NOT in this data. The sticky chat button lives outside the
 *  antd <Menu> (rendered next to AgentSelector with bespoke styling); see
 *  Sidebar.tsx. We don't model it as menu data because it has zero antd-Menu
 *  semantics in common with the rest of the sidebar entries.
 *
 * ── Order convention ───────────────────────────────────────────────────────
 *  Within each group, items use order = 10/20/30/… in their natural sequence
 *  so plugins can insert with order 15/25 without colliding.
 */
import {
  SparkAgentLine,
  SparkBarChartLine,
  SparkBrowseLine,
  SparkDataLine,
  SparkDateLine,
  SparkDebugLine,
  SparkEmailLine,
  SparkInternetLine,
  SparkMagicWandLine,
  SparkMcpMcpLine,
  SparkMicLine,
  SparkModePlazaLine,
  SparkModifyLine,
  SparkMyApplicationLine,
  SparkOtherLine,
  SparkPluginLine,
  SparkSaveLine,
  SparkScanLine,
  SparkToolLine,
  SparkUserGroupLine,
  SparkVoiceChat01Line,
  SparkWifiLine,
} from "@agentscope-ai/icons";
import { GitBranch } from "lucide-react";
import i18next from "i18next";
import { Files } from "lucide-react";
import {
  BookOpen,
  Bot,
  Gauge,
  KeyRound,
  ScrollText,
  ShieldCheck,
  Users,
  UsersRound,
} from "lucide-react";
import { menuRegistry } from "../../plugins/registry/store";
import type { MenuItem } from "../../plugins/registry/types";
import {
  useAuthStore,
  selectIsAdmin,
} from "../../stores/authStore";

/** Translate a nav key. Falls back to defaultValue when i18n hasn't loaded. */
const navLabel = (key: string, defaultValue?: string) => (): string =>
  i18next.t(key, defaultValue ?? key);

/**
 * Admin menu visibility (M5): display-layer role filtering. The value is
 * read at render time; AuthGuard populates the identity before MainLayout
 * mounts, so the first Sidebar render already reflects the caller's role.
 * Enforcement stays server-side (`require_perm`).
 */
const adminOnly = (): boolean => selectIsAdmin(useAuthStore.getState());

export const BUILTIN_MENU: MenuItem[] = [
  // ── Agent-scoped (Sidebar Menu #1) ───────────────────────────────────────
  {
    id: "core.inbox",
    location: "primary.agentScoped",
    label: navLabel("nav.inbox"),
    icon: SparkEmailLine,
    route: "core.inbox",
    order: 10,
  },

  {
    id: "core.app-center",
    location: "primary.agentScoped",
    label: navLabel("nav.apps", "Apps"),
    icon: SparkMyApplicationLine,
    route: "core.app-center",
    order: 15,
  },

  // control-group
  {
    id: "core.control-group",
    location: "primary.agentScoped",
    label: navLabel("nav.control"),
    isGroup: true,
    order: 20,
  },
  {
    id: "core.channels",
    location: "primary.agentScoped",
    parentId: "core.control-group",
    label: navLabel("nav.channels"),
    icon: SparkWifiLine,
    route: "core.channels",
    order: 10,
  },
  {
    id: "core.sessions",
    location: "primary.agentScoped",
    parentId: "core.control-group",
    label: navLabel("nav.sessions"),
    icon: SparkUserGroupLine,
    route: "core.sessions",
    order: 20,
  },
  {
    id: "core.cron-jobs",
    location: "primary.agentScoped",
    parentId: "core.control-group",
    label: navLabel("nav.cronJobs"),
    icon: SparkDateLine,
    route: "core.cron-jobs",
    order: 30,
  },
  {
    id: "core.heartbeat",
    location: "primary.agentScoped",
    parentId: "core.control-group",
    label: navLabel("nav.heartbeat"),
    icon: SparkVoiceChat01Line,
    route: "core.heartbeat",
    order: 40,
  },

  // workspace-group
  {
    id: "core.workspace-group",
    location: "primary.agentScoped",
    label: navLabel("nav.agent"),
    isGroup: true,
    order: 30,
  },
  {
    id: "core.files",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.files"),
    icon: Files,
    route: "core.files",
    order: 5,
  },
  {
    id: "core.skills",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.skills"),
    icon: SparkMagicWandLine,
    route: "core.skills",
    order: 10,
  },
  {
    id: "core.tools",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.tools"),
    icon: SparkToolLine,
    route: "core.tools",
    order: 20,
  },
  {
    id: "core.mcp",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.mcp"),
    icon: SparkMcpMcpLine,
    route: "core.mcp",
    order: 40,
  },
  {
    id: "core.acp",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.acp"),
    icon: SparkScanLine,
    route: "core.acp",
    order: 50,
  },
  {
    id: "core.agent-config",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.agentConfig"),
    icon: SparkModifyLine,
    route: "core.agent-config",
    order: 60,
  },
  {
    id: "core.agent-stats",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.agentStats"),
    icon: SparkBarChartLine,
    route: "core.agent-stats",
    order: 70,
  },
  {
    id: "core.checkpoints",
    location: "primary.agentScoped",
    parentId: "core.agent-group",
    label: navLabel("checkpoints.nav"),
    icon: GitBranch,
    route: "core.checkpoints",
    order: 80,
  },

  // ── Settings (Sidebar Menu #2) ───────────────────────────────────────────
  {
    id: "core.settings-group",
    location: "primary.settings",
    label: navLabel("nav.settings"),
    isGroup: true,
    order: 10,
  },
  {
    id: "core.agents",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.agents"),
    icon: SparkAgentLine,
    route: "core.agents",
    order: 10,
  },
  {
    id: "core.models",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.models"),
    icon: SparkModePlazaLine,
    route: "core.models",
    order: 20,
  },
  {
    id: "core.skill-pool",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.skillPool", "Skill Pool"),
    icon: SparkOtherLine,
    route: "core.skill-pool",
    order: 30,
  },
  {
    id: "core.environments",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.environments"),
    icon: SparkInternetLine,
    route: "core.environments",
    order: 50,
  },
  {
    id: "core.offload-policy",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.offloadPolicy", "Tool Offload"),
    icon: SparkDateLine,
    route: "core.offload-policy",
    order: 55,
  },
  {
    id: "core.security",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.security"),
    icon: SparkBrowseLine,
    route: "core.security",
    order: 60,
  },
  {
    id: "core.token-usage",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.tokenUsage"),
    icon: SparkDataLine,
    route: "core.token-usage",
    order: 70,
  },
  {
    id: "core.backups",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.backups"),
    icon: SparkSaveLine,
    route: "core.backups",
    order: 80,
  },
  {
    id: "core.voice-transcription",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.voiceTranscription"),
    icon: SparkMicLine,
    route: "core.voice-transcription",
    order: 90,
  },
  {
    id: "core.debug",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.debug", "Debug"),
    icon: SparkDebugLine,
    route: "core.debug",
    order: 100,
  },
  {
    id: "core.plugin-manager",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.pluginManager", "Plugin Manager"),
    icon: SparkPluginLine,
    route: "core.plugin-manager",
    order: 110,
  },

  // ── Admin (Sidebar Menu #2, admin-only display filtering; M5) ──────────
  {
    id: "core.admin-group",
    location: "primary.settings",
    label: navLabel("nav.admin", "Administration"),
    isGroup: true,
    order: 20,
    visible: adminOnly,
  },
  {
    id: "core.admin-users",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminUsers", "Users"),
    icon: Users,
    route: "core.admin-users",
    order: 10,
    visible: adminOnly,
  },
  {
    id: "core.admin-roles",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminRoles", "Roles"),
    icon: ShieldCheck,
    route: "core.admin-roles",
    order: 20,
    visible: adminOnly,
  },
  {
    id: "core.admin-teams",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminTeams", "Teams"),
    icon: UsersRound,
    route: "core.admin-teams",
    order: 30,
    visible: adminOnly,
  },
  {
    id: "core.admin-agent-grants",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminAgentGrants", "Agent Access"),
    icon: Bot,
    route: "core.admin-agent-grants",
    order: 40,
    visible: adminOnly,
  },
  {
    id: "core.admin-model-grants",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminModelGrants", "Model Access"),
    icon: KeyRound,
    route: "core.admin-model-grants",
    order: 50,
    visible: adminOnly,
  },
  {
    id: "core.admin-quotas",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminQuotas", "Quotas"),
    icon: Gauge,
    route: "core.admin-quotas",
    order: 60,
    visible: adminOnly,
  },
  {
    id: "core.admin-audit",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminAudit", "Audit Log"),
    icon: ScrollText,
    route: "core.admin-audit",
    order: 70,
    visible: adminOnly,
  },
  {
    id: "core.admin-knowledge",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminKnowledge", "Knowledge Bases"),
    icon: BookOpen,
    route: "core.admin-knowledge",
    order: 80,
    visible: adminOnly,
  },
  {
    id: "core.admin-organization",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminOrg", "Organization"),
    icon: UsersRound,
    route: "core.admin-organization",
    order: 90,
    visible: adminOnly,
  },
  {
    id: "core.admin-experts",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminExperts", "Experts"),
    icon: Bot,
    route: "core.admin-experts",
    order: 100,
    visible: adminOnly,
  },
  {
    id: "core.admin-expert-teams",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminExpertTeams", "Expert Teams"),
    icon: UsersRound,
    route: "core.admin-expert-teams",
    order: 110,
    visible: adminOnly,
  },
  {
    id: "core.admin-workforce-runs",
    location: "primary.settings",
    parentId: "core.admin-group",
    label: navLabel("nav.adminWorkforce", "Team Runs"),
    icon: GitBranch,
    route: "core.admin-workforce-runs",
    order: 120,
    visible: adminOnly,
  },
];

// Self-register at module load. main.tsx imports this file as a side-effect.
menuRegistry.addBuiltin(BUILTIN_MENU);
