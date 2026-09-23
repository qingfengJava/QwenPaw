/**
 * PageShell — shared scaffold for the extension pages without prototype
 * coverage (Experts / Automation / Library): header area (title + subtitle
 * + action) reusing the projects vocabulary (.projects-header-area etc.).
 */
export interface PageShellProps {
  title: string;
  subtitle: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}

export default function PageShell({
  title,
  subtitle,
  action,
  children,
}: PageShellProps) {
  return (
    <div className="page-list">
      <div className="projects-header-area">
        <div className="projects-header-left">
          <h1>{title}</h1>
          <p>{subtitle}</p>
          {action}
        </div>
        <div style={{ fontSize: 60, color: "#e2e8f0" }}>
          <i className="fa-solid fa-users-viewfinder" />
        </div>
      </div>
      {children}
    </div>
  );
}
