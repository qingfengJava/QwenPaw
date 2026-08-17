/**
 * ExpertCard — WorkBuddy-style market card: round avatar, bold title
 * (职称) with the name underneath, 2-line description, capability tag
 * pills, optional badge (特邀) and a black 召唤 button. `mine` mode
 * swaps the summon row for status + edit/delete actions.
 */
import type { Expert } from "../../api/modules";

export interface ExpertCardProps {
  expert: Expert;
  onSummon: (expert: Expert) => void;
  onDetail: (expert: Expert) => void;
  mine?: boolean;
  onEdit?: (expert: Expert) => void;
  onDelete?: (expert: Expert) => void;
}

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
};

export default function ExpertCard({
  expert,
  onSummon,
  onDetail,
  mine = false,
  onEdit,
  onDelete,
}: ExpertCardProps) {
  const tags = (expert.tags ?? []).slice(0, 4);
  return (
    <div
      className="expert-card"
      onClick={() => onDetail(expert)}
      role="button"
    >
      {expert.badge ? (
        <span className="expert-badge">{expert.badge}</span>
      ) : null}
      <div className="expert-card-head">
        <div className="expert-avatar">
          <i className={expert.icon || "fa-solid fa-user-tie"} />
        </div>
        <div className="expert-card-head-text">
          <div className="expert-title">
            {expert.title || expert.name}
            {expert.is_builtin ? (
              <span className="expert-builtin-mark" title="内置专家">
                <i className="fa-solid fa-certificate" />
              </span>
            ) : null}
          </div>
          <div className="expert-name">{expert.name}</div>
        </div>
      </div>
      <p className="expert-desc">{expert.description || "企业专家"}</p>
      {tags.length > 0 && (
        <div className="expert-tags">
          {tags.map((tag) => (
            <span key={tag} className="expert-tag">
              {tag}
            </span>
          ))}
        </div>
      )}
      {mine ? (
        <div className="expert-card-foot">
          <span className="expert-status">
            {STATUS_LABEL[expert.status ?? "draft"] ?? expert.status}
            {expert.visibility === "private" ? " · 仅自己可见" : ""}
          </span>
          <span className="expert-card-actions">
            <button
              type="button"
              className="icon-btn"
              title="编辑"
              aria-label="编辑"
              onClick={(e) => {
                e.stopPropagation();
                onEdit?.(expert);
              }}
            >
              <i className="fa-solid fa-pen" />
            </button>
            <button
              type="button"
              className="icon-btn"
              title="删除"
              aria-label="删除"
              onClick={(e) => {
                e.stopPropagation();
                onDelete?.(expert);
              }}
            >
              <i className="fa-solid fa-trash-can" />
            </button>
          </span>
        </div>
      ) : (
        <div className="expert-card-foot">
          <span className="expert-usage" title="召唤次数">
            <i className="fa-solid fa-fire" />
            {expert.usage_count ?? 0}
          </span>
          <button
            type="button"
            className="btn-black expert-summon-btn"
            onClick={(e) => {
              e.stopPropagation();
              onSummon(expert);
            }}
          >
            <i className="fa-solid fa-bolt" />
            召唤
          </button>
        </div>
      )}
    </div>
  );
}
