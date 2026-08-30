/**
 * staffdeck/StatCard.tsx — 统计卡（StaffDeck StatCard 移植）。
 *
 * 34px 半增大字 + 12px 灰标签；tone 决定数字与底色（好评绿/差评红）。
 * onClick 可选（StaffDeck 用统计卡当筛选器）。
 */
import React from "react";

export type StatTone = "default" | "green" | "red";

const TONE_COLOR: Record<StatTone, string> = {
  default: "var(--sd-ink)",
  green: "var(--sd-green)",
  red: "var(--sd-red)",
};

const TONE_BG: Record<StatTone, string> = {
  default: "transparent",
  green: "var(--sd-green-bg)",
  red: "var(--sd-red-bg)",
};

export function StatCard({
  value,
  label,
  sublabel,
  tone = "default",
  onClick,
}: {
  value: React.ReactNode;
  label: string;
  sublabel?: string;
  tone?: StatTone;
  onClick?: () => void;
}) {
  const clickable = typeof onClick === "function";
  return (
    <div
      onClick={onClick}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") onClick?.();
            }
          : undefined
      }
      style={{
        flex: "1 1 0",
        minWidth: 140,
        padding: "18px 28px",
        borderRadius: "var(--sd-radius-xl)",
        background: TONE_BG[tone],
        border: "0.5px solid var(--sd-line)",
        cursor: clickable ? "pointer" : "default",
        transition: "box-shadow 150ms ease",
      }}
      onMouseEnter={(e) => {
        if (clickable) e.currentTarget.style.boxShadow =
          "var(--sd-shadow-pop)";
      }}
      onMouseLeave={(e) => {
        if (clickable) e.currentTarget.style.boxShadow = "none";
      }}
    >
      <div
        className="sd-stat-number"
        style={{ color: TONE_COLOR[tone] }}
      >
        {value}
      </div>
      <div className="sd-stat-label">
        {label}
        {sublabel ? (
          <span style={{ marginLeft: 8, color: "var(--sd-text-3)" }}>
            {sublabel}
          </span>
        ) : null}
      </div>
    </div>
  );
}
