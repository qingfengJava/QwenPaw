/**
 * ExpertDetailModal — expert detail view: persona card, bound skills,
 * parent teams, the curated "专家帮你做" template rows (one click summons
 * with the prompt as kickoff) and the static showcase cards, plus the
 * black 召唤专家 button (WorkBuddy layout).
 * Loads lazily from /xian/experts/{id} while the modal is open.
 */
import { useEffect, useState } from "react";
import Modal from "../Modal";
import { expertApi } from "../../api/modules";
import type { ExpertDetail } from "../../api/modules";
import { teamModeLabel } from "./TeamCard";

export interface ExpertDetailModalProps {
  expertId: string | null;
  onClose: () => void;
  /** kickoff: 模板行点击时携带的完整任务提示词（覆盖默认开场白）。 */
  onSummon: (expert: ExpertDetail, kickoff?: string) => void;
}

export default function ExpertDetailModal({
  expertId,
  onClose,
  onSummon,
}: ExpertDetailModalProps) {
  const [detail, setDetail] = useState<ExpertDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setDetail(null);
    setError("");
    if (!expertId) {
      return;
    }
    let alive = true;
    expertApi
      .detail(expertId)
      .then((data) => {
        if (alive) {
          setDetail(data);
        }
      })
      .catch((err) => {
        if (alive) {
          setError(`加载专家详情失败：${String(err)}`);
        }
      });
    return () => {
      alive = false;
    };
  }, [expertId]);

  const skills = (detail?.skills ?? []).filter((s) => s.enabled);
  const tasks = detail?.sample_tasks ?? [];
  const showcase = detail?.showcase ?? [];

  return (
    <Modal
      open={expertId !== null}
      title="专家详情"
      onClose={onClose}
      width={560}
      footer={
        detail ? (
          <button
            type="button"
            className="btn-black"
            onClick={() => onSummon(detail)}
          >
            <i className="fa-solid fa-bolt" />
            召唤专家
          </button>
        ) : null
      }
    >
      {error && <p className="expert-detail-hint">{error}</p>}
      {!detail && !error && <p className="expert-detail-hint">加载中…</p>}
      {detail && (
        <div>
          <div className="expert-detail-head">
            <div className="expert-avatar expert-avatar-lg">
              <i className={detail.icon || "fa-solid fa-user-tie"} />
            </div>
            <div className="expert-card-head-text">
              <div className="expert-title">
                {detail.title || detail.name}
                {detail.badge ? (
                  <span className="expert-badge expert-badge-inline">
                    {detail.badge}
                  </span>
                ) : null}
              </div>
              <div className="expert-name">
                {detail.name} · 召唤 {detail.usage_count ?? 0} 次
              </div>
            </div>
          </div>
          <div className="expert-detail-section">
            <h4>简介</h4>
            <p>{detail.description || "（无简介）"}</p>
          </div>
          {tasks.length > 0 && (
            <div className="expert-detail-section">
              <h4>专家帮你做</h4>
              <div className="expert-task-list">
                {tasks.map((task) => (
                  <button
                    key={task.title}
                    type="button"
                    className="expert-task-row"
                    onClick={() => onSummon(detail, task.prompt)}
                  >
                    <span className="expert-task-title">
                      <i className="fa-solid fa-wand-magic-sparkles" />
                      {task.title}
                    </span>
                    <span className="expert-task-go">立即召唤</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {showcase.length > 0 && (
            <div className="expert-detail-section">
              <h4>使用案例</h4>
              <div className="expert-case-list">
                {showcase.map((c) => (
                  <div key={c.title} className="expert-case-card">
                    <div className="expert-case-title">{c.title}</div>
                    {c.desc && <div className="expert-case-desc">{c.desc}</div>}
                    {(c.tags ?? []).length > 0 && (
                      <div className="expert-tags">
                        {(c.tags ?? []).map((tag) => (
                          <span key={tag} className="expert-tag">
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {detail.system_prompt ? (
            <div className="expert-detail-section">
              <h4>领域人设</h4>
              <p className="expert-detail-persona">{detail.system_prompt}</p>
            </div>
          ) : null}
          <div className="expert-detail-section">
            <h4>已配置技能（对话时自动加载）</h4>
            {skills.length > 0 ? (
              <div className="expert-tags">
                {skills.map((s) => (
                  <span key={s.skill_name} className="expert-tag">
                    <i className="fa-solid fa-bolt" /> {s.skill_name}
                  </span>
                ))}
              </div>
            ) : (
              <p className="expert-detail-hint">（未绑定技能，依赖通用能力）</p>
            )}
          </div>
          {detail.teams && detail.teams.length > 0 && (
            <div className="expert-detail-section">
              <h4>所在专家团</h4>
              <div className="expert-tags">
                {detail.teams.map((t) => (
                  <span key={t.id} className="expert-tag">
                    <i className="fa-solid fa-users-rectangle" /> {t.name}
                    （{teamModeLabel(t.mode)}）
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
