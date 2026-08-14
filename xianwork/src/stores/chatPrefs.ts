/**
 * chatPrefs — cross-page chat preferences shared by Home and Chat, mirroring
 * the console's agentStore + loopStore persistence contract:
 *   - selectedAgent  → X-Agent-Id header on every chat request
 *   - approvalLevel  → request_context.approval_level in the chat body
 *   - loopModeId     → prepends "/{slash_command}" to the next message
 * localStorage key mirrors the console's "qwenpaw-agent-storage" so both
 * front-ends stay in sync when pointed at the same backend.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { LoopModeInfo } from "../api/modules";

export type ApprovalLevel = "STRICT" | "SMART" | "AUTO" | "OFF";

export const APPROVAL_META: Record<
  ApprovalLevel,
  { label: string; description: string }
> = {
  STRICT: { label: "严格模式", description: "所有工具调用都需要审批，最高安全级别" },
  SMART: { label: "智能模式", description: "低风险工具自动放行，中高风险工具需要审批" },
  AUTO: { label: "自动模式", description: "仅被明确标记为需要审批的工具才会要求审批（默认）" },
  OFF: { label: "关闭模式", description: "关闭所有工具审批，所有工具自动执行" },
};

export const DEFAULT_LOOP_MODE: LoopModeInfo = {
  id: "default",
  name: "default",
  slash_command: "",
  description: "The standard guarded agent loop.",
  source: "builtin",
};

/**
 * Built-in mode names/descriptions mirror the console zh.json "loop.modes"
 * table — the backend /loops payload returns raw English ids, the console
 * localizes builtins client-side (resolveLoopModeName contract).
 */
const BUILTIN_LOOP_I18N: Record<
  string,
  { name: string; description: string }
> = {
  default: {
    name: "默认",
    description: "标准的受控智能体 Loop。",
  },
  goal: {
    name: "目标",
    description: "持续推进一个具体且可验证的目标。",
  },
  mission: {
    name: "任务",
    description: "运行结构化、可持续的多步骤任务。",
  },
};

function pickLocalized(
  map: Record<string, string> | null | undefined,
): string {
  if (!map) return "";
  return map["zh-CN"] || map["zh"] || "";
}

/** Console-parity name resolution: builtin i18n table → plugin zh → raw name. */
export function resolveLoopModeName(mode: LoopModeInfo): string {
  if (mode.source === "builtin") {
    return BUILTIN_LOOP_I18N[mode.id]?.name ?? mode.name;
  }
  return pickLocalized(mode.name_i18n) || mode.name;
}

/** Console-parity description: builtin table → plugin zh → raw description. */
export function resolveLoopModeDescription(mode: LoopModeInfo): string {
  if (mode.source === "builtin") {
    return BUILTIN_LOOP_I18N[mode.id]?.description ?? mode.description;
  }
  return pickLocalized(mode.description_i18n) || mode.description;
}

interface ChatPrefsState {
  selectedAgent: string;
  approvalLevel: ApprovalLevel;
  loopModeId: string;
  loopModes: LoopModeInfo[];
  setSelectedAgent: (agentId: string) => void;
  setApprovalLevel: (level: ApprovalLevel) => void;
  setLoopMode: (modeId: string) => void;
  setLoopModes: (modes: LoopModeInfo[]) => void;
}

export const useChatPrefs = create<ChatPrefsState>()(
  persist(
    (set) => ({
      selectedAgent: "default",
      approvalLevel: "AUTO",
      loopModeId: "default",
      loopModes: [DEFAULT_LOOP_MODE],
      setSelectedAgent: (agentId) => set({ selectedAgent: agentId }),
      setApprovalLevel: (approvalLevel) => set({ approvalLevel }),
      setLoopMode: (loopModeId) => set({ loopModeId }),
      setLoopModes: (loopModes) => {
        set((state) => ({
          loopModes,
          // Keep the selection valid when the catalog refreshes.
          loopModeId: loopModes.some((m) => m.id === state.loopModeId)
            ? state.loopModeId
            : "default",
        }));
      },
    }),
    {
      name: "xianwork-chat-prefs",
      partialize: (s) => ({
        selectedAgent: s.selectedAgent,
        approvalLevel: s.approvalLevel,
        loopModeId: s.loopModeId,
      }),
    },
  ),
);

/** Resolve the effective loop mode (falls back to 默认 when catalog lags). */
export function getSelectedLoopMode(
  modes: LoopModeInfo[],
  modeId: string,
): LoopModeInfo {
  return modes.find((m) => m.id === modeId) ?? DEFAULT_LOOP_MODE;
}

/** Backend loop semantics: non-default modes become a "/command" prefix. */
export function applyLoopModeCommand(
  text: string,
  mode: LoopModeInfo,
): string {
  const command = mode.slash_command.trim();
  if (!command) return text;
  const trimmed = text.trimStart();
  const prefix = `/${command}`;
  const firstToken = trimmed.split(/\s/, 1)[0];
  if (firstToken.toLowerCase() === prefix.toLowerCase()) return text;
  return `${prefix} ${text}`;
}
