/**
 * runStatus — workforce team-run 状态元数据共享映射。
 *
 * RunDetail（详情页）/ ProjectDetail（团队任务 tab）/ TimelineList
 * （聊天 team_run 卡片）三处渲染同一条状态机，统一在此维护
 * label / icon / tone，避免多处漂移。
 */

/** run 状态中文映射（徽标 + 图标 + 色调）。 */
export const RUN_STATUS_META: Record<
  string,
  { label: string; icon: string; tone: string }
> = {
  planning: { label: "规划中", icon: "fa-solid fa-compass-drafting", tone: "#6b7280" },
  awaiting_confirm: { label: "等待澄清", icon: "fa-regular fa-circle-question", tone: "#b45309" },
  running: { label: "执行中", icon: "fa-solid fa-spinner fa-spin", tone: "#2563eb" },
  verifying: { label: "验收中", icon: "fa-solid fa-clipboard-check", tone: "#2563eb" },
  repairing: { label: "返工中", icon: "fa-solid fa-screwdriver-wrench", tone: "#b45309" },
  aggregating: { label: "汇总中", icon: "fa-solid fa-layer-group", tone: "#7c3aed" },
  done: { label: "已完成", icon: "fa-solid fa-circle-check", tone: "#16a34a" },
  failed: { label: "失败", icon: "fa-solid fa-circle-xmark", tone: "#dc2626" },
  escalated: { label: "已升级人工", icon: "fa-solid fa-user-gear", tone: "#dc2626" },
  canceled: { label: "已取消", icon: "fa-solid fa-ban", tone: "#6b7280" },
  interrupted: { label: "已中断（可续跑）", icon: "fa-solid fa-plug-circle-xmark", tone: "#b45309" },
};

/** 纯文本短标签（列表行内联展示用）。 */
export const RUN_STATUS_LABEL: Record<string, string> = Object.fromEntries(
  Object.entries(RUN_STATUS_META).map(([k, v]) => [k, v.label]),
);

/** 终态集合：订阅与轮询在这些状态后停止。 */
export const RUN_TERMINAL_STATUSES = new Set([
  "done",
  "failed",
  "escalated",
  "canceled",
  "interrupted",
]);

/** 活跃态集合（操作条按钮的显示依据）。 */
export const ACTIVE_RUN_STATUSES = new Set([
  "planning",
  "running",
  "verifying",
  "repairing",
  "aggregating",
]);
