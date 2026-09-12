/**
 * admin/index.ts — barrel for the M5 admin API client modules.
 *
 * These wrap the `/admin/*` router family (M4-6). Every endpoint enforces
 * `require_perm` server-side; these clients only shape requests.
 */
export * from "./types";
export { adminUsersApi } from "./users";
export type { CreateUserBody, UpdateUserBody } from "./users";
export { adminRolesApi } from "./roles";
export type { RoleBody } from "./roles";
export { adminTeamsApi } from "./teams";
export type { TeamBody } from "./teams";
export { adminGrantsApi } from "./grants";
export type { GrantBody } from "./grants";
export { adminQuotasApi } from "./quotas";
export type { QuotaRuleBody, QuotaKey } from "./quotas";
export { adminAuditApi } from "./audit";
export type { AuditQuery } from "./audit";
export { adminKbApi } from "./kb";
export type { KbBody, IngestBody, IngestResult } from "./kb";
export { adminOrgsApi } from "./orgs";
export type { OrgRecord, DepartmentTree } from "./orgs";
export { adminExpertsApi } from "./experts";
export type {
  ExpertRecord,
  ExpertCreateBody,
  ExpertUpdateBody,
  ExpertPreviewInstance,
  ExpertPreviewStatus,
  ExpertVersionInfo,
  ExpertVersionRestoreResult,
  ExpertDocRevisionInfo,
  ExpertDocRevisionsResult,
  ExpertDocRollbackResult,
} from "./experts";
export { adminExpertTeamsApi } from "./expertTeams";
export type {
  ExpertTeamRecord,
  TeamMember,
  ExpertTeamCreateBody,
  ExpertTeamUpdateBody,
} from "./expertTeams";
export { adminWorkforceApi } from "./workforce";
export type {
  AdminTeamRun,
  AdminRunStats,
  AdminRunStatus,
} from "./workforce";
export {
  expertCapabilityApi,
  sopApi,
  evolutionApi,
  attributionApi,
  openApiAuditApi,
} from "./expertCapability";
export type {
  ResourceBinding,
  ResourceType,
  CapabilityCounts,
  ApiKeyRecord,
  PendingItem,
  SopRecord,
  SopNode,
  SopEdge,
  SopSlot,
  SopVersion,
  MemoryRecord,
  ScheduledTask,
  TaskRun,
  TimelineEvent,
  WorkRecord,
  FeedbackSummary,
  EvolutionProposal,
  AttributionHeatmap,
  OpenApiAuditRow,
} from "./expertCapability";
