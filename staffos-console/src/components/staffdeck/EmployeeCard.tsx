/**
 * staffdeck/EmployeeCard.tsx — 数字员工卡片（StaffDeck EmployeeCard 移植）。
 *
 * 结构：灰色 header 带（姓名/职称/在线胶囊/主按钮）→ 描述两行 →
 * 工作风格标签 → 底部三格计数条（技能/SOP/定时任务）。
 * 头像位用 icon 首字符 + tone 渐变（插画素材属 StaffDeck 资产，不引入）。
 */
import React from "react";
import { useTranslation } from "react-i18next";
import ExpertAvatar from "@/components/ExpertAvatar";
import { StatusPill, expertStatusTone, expertStatusLabel } from "./StatusPill";

export interface EmployeeCardProps {
  expert: {
    id: string;
    name: string;
    icon?: string;
    title?: string;
    description?: string;
    status?: string;
    department?: string;
    work_styles?: string[];
    work_modes?: string[];
    badge?: string;
  };
  counts: {
    /** 能力资产数（SOP+知识+工具绑定）。 */
    resources: number;
    skills: number;
    sops: number;
    scheduledTasks: number;
  };
  primaryActionLabel?: string;
  onPrimaryAction?: () => void;
  onClick?: () => void;
  extraMenu?: React.ReactNode;
}

export function EmployeeCard({
  expert,
  counts,
  primaryActionLabel,
  onPrimaryAction,
  onClick,
  extraMenu,
}: EmployeeCardProps) {
  const { t } = useTranslation();
  const online = expert.status === "published";
  const styles = [
    ...(expert.work_styles ?? []),
    ...(expert.work_modes ?? []),
  ].slice(0, 3);

  return (
    <div
      className="sd-card"
      data-expert-id={expert.id}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (onClick && (e.key === "Enter" || e.key === " ")) onClick();
      }}
      style={{
        cursor: onClick ? "pointer" : "default",
        transition: "box-shadow 200ms ease, transform 200ms ease",
        position: "relative",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = "var(--sd-shadow-hover)";
        e.currentTarget.style.transform = "translateY(-2px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = "none";
        e.currentTarget.style.transform = "none";
      }}
    >
      {/* 灰色 header 带 + 头像 */}
      <div
        className="sd-employee-card-band"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "0 18px",
        }}
      >
        {/* 形象头像：dicebear:// 配置生效，空值自动分配，旧值回退渐变 */}
        <ExpertAvatar
          icon={expert.icon}
          expertId={expert.id}
          name={expert.name}
          size={52}
          style={{ fontSize: 20 }}
        />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              color: "var(--sd-ink)",
              fontWeight: 600,
              fontSize: 15,
            }}
          >
            <span
              style={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {expert.name}
            </span>
            {expert.badge ? (
              <StatusPill tone="amber" dot={false}>
                {expert.badge}
              </StatusPill>
            ) : null}
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--sd-text-2)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {expert.title || expert.department || "\u00a0"}
          </div>
        </div>
        <div
          style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}
          onClick={(e) => e.stopPropagation()}
        >
          <StatusPill tone={expertStatusTone(expert.status)}>
            {expertStatusLabel(expert.status)}
          </StatusPill>
          {primaryActionLabel && onPrimaryAction && online ? (
            <button
              type="button"
              className="sd-btn-primary"
              onClick={onPrimaryAction}
              style={{
                fontSize: 12,
                padding: "4px 12px",
                cursor: "pointer",
              }}
            >
              {primaryActionLabel}
            </button>
          ) : null}
        </div>
      </div>

      {/* 更多操作菜单锚点 */}
      {extraMenu ? (
        <div
          style={{ position: "absolute", top: 14, right: 14 }}
          onClick={(e) => e.stopPropagation()}
        >
          {extraMenu}
        </div>
      ) : null}

      {/* 描述两行 */}
      <div
        style={{
          margin: "14px 18px 0",
          height: 40,
          fontSize: 13,
          lineHeight: "20px",
          color: "var(--sd-text-4)",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {expert.description || "\u00a0"}
      </div>

      {/* 工作风格标签 */}
      {styles.length > 0 ? (
        <div style={{ margin: "10px 18px 0", display: "flex", gap: 8, flexWrap: "wrap" }}>
          {styles.map((tag) => (
            <StatusPill key={tag} tone="plain" dot={false}>
              {tag}
            </StatusPill>
          ))}
        </div>
      ) : null}

      {/* 底部三格计数条：能力 / SOP / 定时任务 */}
      <div
        style={{
          margin: "16px 18px 18px",
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          border: "0.5px solid var(--sd-line)",
          borderRadius: "var(--sd-radius-lg)",
          overflow: "hidden",
        }}
      >
        {[
          {
            label: t("staffdeck.card.resources", "能力"),
            value: counts.resources,
          },
          {
            label: t("staffdeck.card.sops", "SOP"),
            value: counts.sops,
          },
          {
            label: t("staffdeck.card.scheduled", "定时任务"),
            value: counts.scheduledTasks,
          },
        ].map((cell, index) => (
          <div
            key={cell.label}
            style={{
              textAlign: "center",
              padding: "10px 0",
              borderLeft:
                index > 0 ? "0.5px solid var(--sd-line)" : undefined,
            }}
          >
            <div style={{ fontSize: 18, fontWeight: 600, color: "var(--sd-ink)" }}>
              {cell.value}
            </div>
            <div className="sd-stat-label">{cell.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
