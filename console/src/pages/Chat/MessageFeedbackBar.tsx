/**
 * pages/Chat/MessageFeedbackBar.tsx — 对话气泡 👍/👎 反馈条
 * （20260830 补全项①：消息级反馈采集埋点）。
 *
 * - 仅数字员工会话（当前 agent id 为 expert_<id>）展示；普通 agent 不出；
 * - 锚点：SDK response id。历史回放场景同样成立——SDK 会话状态
 *   （含消息对象与 id）整体持久化在 session_states，重开会话恢复的
 *   消息保留原 response id，因此回放后仍可对同一回复补评/改评；
 * - 重复提交 = 覆盖（后端语义），切换评分直接再点另一枚按钮。
 */
import { useCallback, useState } from "react";
import { DislikeOutlined, LikeOutlined } from "@ant-design/icons";
import { useAgentStore } from "../../stores/agentStore";
import { isExpertAgentId, xianFeedbackApi } from "../../api/modules/xianFeedback";

type Rating = "up" | "down";

export function MessageFeedbackBar({ responseId }: { responseId: string }) {
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const expertId = isExpertAgentId(selectedAgent);
  const [rated, setRated] = useState<Rating | null>(null);

  const rate = useCallback(
    (rating: Rating) => {
      if (!expertId || !responseId) return;
      setRated(rating);
      xianFeedbackApi
        .rate(expertId, { message_id: responseId, rating })
        .catch((err: unknown) => {
          // 反馈失败静默回退按钮态（不打断对话主流程）
          console.debug("feedback rate failed", err);
          setRated(null);
        });
    },
    [expertId, responseId],
  );

  if (!expertId || !responseId) return null;

  const iconButton = (rating: Rating, icon: React.ReactNode, label: string) => (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => rate(rating)}
      style={{
        border: "none",
        background: rated === rating ? "var(--sd-blue-bg)" : "transparent",
        color:
          rated === rating
            ? "var(--sd-link)"
            : "var(--sd-text-3)",
        cursor: "pointer",
        borderRadius: "var(--sd-radius-sm)",
        padding: "2px 6px",
        fontSize: 13,
        lineHeight: "18px",
        transition: "color 150ms ease, background 150ms ease",
      }}
    >
      {icon}
    </button>
  );

  return (
    <div
      data-message-feedback={responseId}
      style={{ display: "inline-flex", gap: 4, marginTop: 4 }}
    >
      {iconButton("up", <LikeOutlined />, "有帮助")}
      {iconButton("down", <DislikeOutlined />, "需改进")}
    </div>
  );
}
