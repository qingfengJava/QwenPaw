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
 * ── Platform-only sidebar ────────────────────────────────────────────────
 *  The sidebar carries platform-level entries only. Agent-scoped functions
 *  (chat, files, skills, tools, mcp, cron, ...) live inside the digital
 *  employee detail page (`/agents/:aid/*`), not in this data.
 *
 * ── Order convention ───────────────────────────────────────────────────────
 *  Within each group, items use order = 10/20/30/… in their natural sequence
 *  so plugins can insert with order 15/25 without colliding.
 */
import {
  SparkAgentLine,
  SparkBrowseLine,
  SparkDataLine,
  SparkDateLine,
  SparkDebugLine,
  SparkEmailLine,
  SparkInternetLine,
  SparkMicLine,
  SparkModePlazaLine,
  SparkMyApplicationLine,
  SparkOtherLine,
  SparkPluginLine,
  SparkSaveLine,
  SparkWifiLine,
} from "@agentscope-ai/icons";
import { GitBranch, LayoutDashboard } from "lucide-react";
import i18next from "i18next";
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
  // ── Platform (Sidebar Menu #1) ───────────────────────────────────────
  {
    id: "core.workbench",
    location: "primary.platform",
    label: navLabel("nav.workbench", "Workbench"),
    icon: LayoutDashboard,
    route: "core.workbench",
    order: 10,
  },

  {
    id: "core.inbox",
    location: "primary.platform",
    label: navLabel("nav.inbox"),
    icon: SparkEmailLine,
    route: "core.inbox",
    order: 40,
  },

  {
    id: "core.app-center",
    location: "primary.platform",
    label: navLabel("nav.apps", "Apps"),
    icon: SparkMyApplicationLine,
    route: "core.app-center",
    order: 50,
  },

  {
    id: "core.channels",
    location: "primary.platform",
    label: navLabel("nav.channels"),
    icon: SparkWifiLine,
    route: "core.channels",
    order: 30,
  },

  {
    id: "core.agents",
    location: "primary.platform",
    label: navLabel("nav.employees", "Digital Employees"),
    icon: SparkAgentLine,
    route: "core.agents",
    order: 20,
  },

  {
    id: "core.models",
    location: "primary.platform",
    label: navLabel("nav.models"),
    icon: SparkModePlazaLine,
    route: "core.models",
    order: 60,
  },

  {
    id: "core.skill-pool",
    location: "primary.platform",
    label: navLabel("nav.skillPool", "Skill Pool"),
    icon: SparkOtherLine,
    route: "core.skill-pool",
    order: 70,
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
    id: "core.voice-transcription",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.voiceTranscription"),
    icon: SparkMicLine,
    route: "core.voice-transcription",
    order: 10,
  },
  // data-group (数据与安全)
  {
    id: "core.data-group",
    location: "primary.settings",
    label: navLabel("nav.dataSecurity", "Data & Security"),
    isGroup: true,
    order: 15,
  },
  {
    id: "core.environments",
    location: "primary.settings",
    parentId: "core.data-group",
    label: navLabel("nav.environments"),
    icon: SparkInternetLine,
    route: "core.environments",
    order: 10,
  },
  {
    id: "core.offload-policy",
    location: "primary.settings",
    parentId: "core.data-group",
    label: navLabel("nav.offloadPolicy", "Tool Offload"),
    icon: SparkDateLine,
    route: "core.offload-policy",
    order: 20,
  },
  {
    id: "core.security",
    location: "primary.settings",
    parentId: "core.data-group",
    label: navLabel("nav.security"),
    icon: SparkBrowseLine,
    route: "core.security",
    order: 30,
  },
  {
    id: "core.token-usage",
    location: "primary.settings",
    parentId: "core.data-group",
    label: navLabel("nav.tokenUsage"),
    icon: SparkDataLine,
    route: "core.token-usage",
    order: 40,
  },
  {
    id: "core.backups",
    location: "primary.settings",
    parentId: "core.data-group",
    label: navLabel("nav.backups"),
    icon: SparkSaveLine,
    route: "core.backups",
    order: 50,
  },
  // advanced-group (高级)
  {
    id: "core.advanced-group",
    location: "primary.settings",
    label: navLabel("nav.advanced", "Advanced"),
    isGroup: true,
    order: 20,
  },
  {
    id: "core.debug",
    location: "primary.settings",
    parentId: "core.advanced-group",
    label: navLabel("nav.debug", "Debug"),
    icon: SparkDebugLine,
    route: "core.debug",
    order: 10,
  },
  {
    id: "core.plugin-manager",
    location: "primary.settings",
    parentId: "core.advanced-group",
    label: navLabel("nav.pluginManager", "Plugin Manager"),
    icon: SparkPluginLine,
    route: "core.plugin-manager",
    order: 20,
  },

  // ── Admin (Sidebar Menu #2, admin-only display filtering; M5) ──────────
  {
    id: "core.admin-group",
    location: "primary.settings",
    label: navLabel("nav.admin", "Administration"),
    isGroup: true,
    order: 30,
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
