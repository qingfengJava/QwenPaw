/**
 * SidebarSection — collapsible container for the「任务」/「空间」areas.
 *
 * Compact header: `[标题 (n)] [+ extra] [▾]` left-aligned in one visual
 * group (the action button sits right after the count, per user request —
 * not pinned to the far right). Children render only while expanded.
 */
import type { ReactNode } from "react";

interface SidebarSectionProps {
  title: string;
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  extra?: ReactNode;
  children: ReactNode;
}

export default function SidebarSection({
  title,
  count,
  collapsed,
  onToggle,
  extra,
  children,
}: SidebarSectionProps) {
  return (
    <div className="sidebar-section">
      <div className="nav-section-header sidebar-section-toggle">
        <button
          type="button"
          className="sidebar-section-title"
          onClick={onToggle}
          aria-expanded={!collapsed}
        >
          <span>
            {title} ({count})
          </span>
        </button>
        {extra}
        <button
          type="button"
          className="sidebar-icon-btn sidebar-section-chevron"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "展开" : "折叠"}
        >
          <i
            className={`fa-solid fa-chevron-${collapsed ? "right" : "down"}`}
          />
        </button>
      </div>
      {!collapsed && children}
    </div>
  );
}
