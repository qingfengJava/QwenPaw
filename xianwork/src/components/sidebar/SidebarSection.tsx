/**
 * SidebarSection — collapsible container for the「任务」/「空间」areas.
 *
 * Header mirrors the workspace folder rows: `标题 n ····· [+ extra] [▾]`
 * — bare count hugging the title on the left, the + and chevron packed
 * at the right edge, so headers and folder rows share one rhythm.
 * Children render only while expanded.
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
          <span>{title}</span>
          <span className="sidebar-section-count">{count}</span>
        </button>
        <div className="sidebar-section-actions">
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
      </div>
      {!collapsed && children}
    </div>
  );
}
