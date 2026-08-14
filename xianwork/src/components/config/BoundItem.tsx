/**
 * BoundItem — one bound resource (connector / skill) inside a ConfigBlock:
 * icon + name + remove affordance (extension, prototype vocabulary).
 */
export interface BoundItemProps {
  icon: string;
  name: string;
  sub?: string;
  onRemove?: () => void;
}

export default function BoundItem({ icon, name, sub, onRemove }: BoundItemProps) {
  return (
    <div className="bound-item">
      <div className="bound-item-name">
        <i className={icon} />
        <span title={name}>{name}</span>
      </div>
      {sub && <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{sub}</span>}
      {onRemove && (
        <i
          className="fa-solid fa-xmark"
          title="移除"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        />
      )}
    </div>
  );
}
