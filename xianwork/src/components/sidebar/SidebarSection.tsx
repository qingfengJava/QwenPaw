/**
 * SidebarSection — collapsible container for the「任务」/「空间」areas.
 * Title + live count + chevron; children render only while expanded.
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
          <i
            className={`fa-solid fa-chevron-${collapsed ? "right" : "down"}`}
          />
        </button>
        {extra}
      </div>
      {!collapsed && children}
    </div>
  );
}
