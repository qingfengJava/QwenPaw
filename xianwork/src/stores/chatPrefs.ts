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
  name: "默认",
  slash_command: "",
  description: "标准守护式代理循环。",
  source: "builtin",
};

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
