/**
 * identityDocFiles.ts — 基础配置白名单文件清单（工作区根路径）。
 *
 * 档案 Tab（AgentOverviewTab）与对话修改闭环（Chat/agentDocsSync、
 * Chat/mentionCatalog）共用同一清单，保证「展示、预填、回填」三处
 * 对档案文件的定义同源，避免清单漂移。
 */

export const IDENTITY_DOC_FILES = [
  "PROFILE.md",
  "AGENTS.md",
  "SOUL.md",
  "agent.json",
] as const;

export type IdentityDocFile = (typeof IDENTITY_DOC_FILES)[number];
