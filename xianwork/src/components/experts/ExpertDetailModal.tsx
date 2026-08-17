/**
 * ExpertDetailModal — expert detail view: persona card, bound skills,
 * parent teams, and the black 召唤专家 button (WorkBuddy layout).
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
  onSummon: (expert: ExpertDetail) => void;
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
