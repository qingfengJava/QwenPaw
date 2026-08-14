/**
 * ConfigBlock — one card in the right config panel (prototype L919-930):
 * block-top (title + add icon) + desc + children (bound items /
 * automation-item / instruction-box).
 */
export interface ConfigBlockProps {
  title: string;
  desc?: string;
  /** Content rendered under the title row (bound lists, forms…). */
  children?: React.ReactNode;
  /** Right-edge plus affordance; omit to hide. */
  onAdd?: () => void;
  onClick?: () => void;
}

export default function ConfigBlock({
  title,
  desc,
  children,
  onAdd,
  onClick,
}: ConfigBlockProps) {
  return (
    <div
      className="config-block"
      onClick={onClick}
      role={onClick ? "button" : undefined}
    >
      <div className="block-top">
        <span className="block-title">{title}</span>
        {onAdd && (
          <i
            className="fa-solid fa-plus"
            title={`添加${title}`}
            onClick={(e) => {
              e.stopPropagation();
              onAdd();
            }}
          />
        )}
      </div>
      {desc && <div className="block-desc">{desc}</div>}
      {children}
    </div>
  );
}
