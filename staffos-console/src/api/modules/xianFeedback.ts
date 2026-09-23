/**
 * xianFeedback.ts — 数字员工消息反馈客户端（用户面 /api/xian 通道）。
 *
 * 对话气泡 👍/👎 埋点（20260830 补全项①）：任何可访问该专家的用户
 * 均可评分（每人每消息一票，重复提交=覆盖）；expert_id 从当前会话
 * agent id（expert_<id>）解析，非专家会话不展示反馈按钮。
 */
import { request } from "../request";

export interface RateFeedbackBody {
  message_id: string;
  session_id?: string;
  rating: "up" | "down";
  comment?: string;
}

export function isExpertAgentId(agentId: string | undefined): string {
  /**expert_<id> → <id>；非专家 agent 返回空串。*/
  if (!agentId || !agentId.startsWith("expert_")) return "";
  return agentId.slice("expert_".length);
}

export const xianFeedbackApi = {
  rate: (expertId: string, body: RateFeedbackBody) =>
    request<{ message_id: string; rating: string; updated: boolean }>(
      `/xian/experts/${encodeURIComponent(expertId)}/feedback`,
      { method: "POST", body: JSON.stringify(body) },
    ),
};
