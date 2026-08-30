/**
 * staffdeck/StatusPill.tsx — 表驱动状态胶囊（StaffDeck BadgeTone 移植）。
 *
 * tone → 底色/前景色全站统一映射，禁止页面内自配颜色；圆点由
 * tokens 的 ::before 绘制，dot=false 走 sd-pill-nodot 变体。
 */
import React from "react";

export type StatusTone = "green" | "red" | "blue" | "amber" | "gray" | "plain";

const TONE_CLASS: Record<StatusTone, string> = {
  green: "sd-pill sd-pill-green",
  red: "sd-pill sd-pill-red",
  blue: "sd-pill sd-pill-blue",
  amber: "sd-pill sd-pill-amber",
  gray: "sd-pill sd-pill-gray",
  plain: "sd-pill sd-pill-gray",
};

export function StatusPill({
  tone = "gray",
  children,
  dot = true,
}: {
  tone?: StatusTone;
  children: React.ReactNode;
  /** 是否带前导圆点（语气标签建议关闭）。 */
  dot?: boolean;
}) {
  const classes = [TONE_CLASS[tone], dot ? "" : "sd-pill-nodot"]
    .filter(Boolean)
    .join(" ");
  return <span className={classes}>{children}</span>;
}

/** 数字员工状态 → tone 的唯一映射（在线/离线语义）。 */
export function expertStatusTone(status?: string): StatusTone {
  switch (status) {
    case "published":
      return "green";
    case "draft":
      return "blue";
    case "archived":
      return "gray";
    default:
      return "gray";
  }
}

/** 数字员工状态 → 中文文案（与后端枚举一一对应）。 */
export function expertStatusLabel(status?: string): string {
  switch (status) {
    case "published":
      return "在线";
    case "draft":
      return "草稿";
    case "archived":
      return "已归档";
    default:
      return status || "未知";
  }
}
