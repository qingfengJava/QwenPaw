/**
 * ProjectCard — prototype L569-607 + L1168-1175: 40px icon tile, title,
 * desc, ellipsis affordance. Two flavours: owned project (icon tile with
 * #f1f5f9 background) vs template (plain #94a3b8 icon, prototype L1183+).
 */
export interface ProjectCardProps {
  icon: string;
  title: string;
  desc: string;
  onClick?: () => void;
  onMore?: (e: React.MouseEvent) => void;
  template?: boolean;
}

export default function ProjectCard({
  icon,
  title,
  desc,
  onClick,
  onMore,
  template = false,
}: ProjectCardProps) {
  return (
    <div
      className="project-card"
      onClick={onClick}
      role={onClick ? "button" : undefined}
    >
      <div
        className="card-icon"
        style={
          template
            ? { background: "transparent", color: "#94a3b8", width: "auto", height: "auto" }
            : undefined
        }
      >
        <i className={icon} />
      </div>
      <div className="card-title">{title}</div>
      <div className="card-desc">{desc}</div>
      {onMore && (
        <i
          className="fa-solid fa-ellipsis-vertical card-more"
          onClick={(e) => {
            e.stopPropagation();
            onMore(e);
          }}
        />
      )}
    </div>
  );
}
