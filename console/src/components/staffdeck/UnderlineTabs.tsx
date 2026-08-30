/**
 * staffdeck/UnderlineTabs.tsx — 下划线选项卡（StaffDeck UnderlineTabs 移植）。
 *
 * 受控组件：value/onChange；激活项墨色加粗 + 底部短下划线。
 */
import React from "react";

export interface UnderlineTabItem {
  key: string;
  label: React.ReactNode;
  /** 可选计数徽标（如"在线员工 7"）。 */
  count?: number;
}

export function UnderlineTabs({
  items,
  value,
  onChange,
}: {
  items: UnderlineTabItem[];
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 28, alignItems: "center" }}>
      {items.map((item) => {
        const active = item.key === value;
        return (
          <div
            key={item.key}
            onClick={() => onChange(item.key)}
            role="tab"
            aria-selected={active}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onChange(item.key);
            }}
            style={{
              position: "relative",
              cursor: "pointer",
              padding: "10px 2px",
              fontSize: 15,
              color: active ? "var(--sd-ink)" : "var(--sd-text-2)",
              fontWeight: active ? 600 : 400,
              transition: "color 150ms ease",
            }}
          >
            {item.label}
            {typeof item.count === "number" ? (
              <span
                style={{
                  marginLeft: 6,
                  fontSize: 12,
                  color: "var(--sd-text-3)",
                }}
              >
                {item.count}
              </span>
            ) : null}
            {active ? (
              <span
                style={{
                  position: "absolute",
                  left: "50%",
                  transform: "translateX(-50%)",
                  bottom: 2,
                  width: 20,
                  height: 3,
                  borderRadius: 2,
                  background: "var(--sd-ink)",
                }}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
