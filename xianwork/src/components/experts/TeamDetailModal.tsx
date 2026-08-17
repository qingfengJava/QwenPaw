/**
 * TeamDetailModal — expert-team detail (WorkBuddy layout): the black
 * 召唤专家团 button, orchestration mode explanation, and the member
 * roster cards with the 主理人 badge (member_role === "lead").
 */
import Modal from "../Modal";
import type { ExpertTeam } from "../../api/modules";
import { teamModeLabel } from "./TeamCard";

export interface TeamDetailModalProps {
  team: ExpertTeam | null;
  onClose: () => void;
  onSummon: (team: ExpertTeam) => void;
}

export default function TeamDetailModal({
  team,
  onClose,
  onSummon,
}: TeamDetailModalProps) {
  const members = team?.members ?? [];
  return (
    <Modal
      open={team !== null}
      title="专家团详情"
      onClose={onClose}
      width={560}
      footer={
        team ? (
          <button
            type="button"
            className="btn-black"
            onClick={() => onSummon(team)}
          >
            <i className="fa-solid fa-bolt" />
            召唤专家团
          </button>
        ) : null
      }
    >
      {team && (
        <div>
          <div className="expert-detail-head">
            <div className="expert-avatar expert-avatar-lg">
              <i className="fa-solid fa-users-rectangle" />
            </div>
            <div className="expert-card-head-text">
              <div className="expert-title">{team.name}</div>
              <div className="expert-name">
                {teamModeLabel(team.mode)} · {team.member_count} 位成员
              </div>
            </div>
          </div>
          <div className="expert-detail-section">
            <h4>简介</h4>
            <p>{team.description || "（无简介）"}</p>
          </div>
          <div className="expert-detail-section">
            <h4>协作规则</h4>
            <p className="expert-detail-persona">
              {team.mode === "pipeline"
                ? "按成员顺序依次完成各自阶段的产出，后一阶段在前一阶段产出的基础上深化，最终汇总收束。"
                : "协调者根据请求判断最匹配的成员专家，以该专家的专业视角完整作答；跨专业问题先给结论，再分成员视角补充。"}
            </p>
          </div>
          <div className="expert-detail-section">
            <h4>团队成员</h4>
            {members.length > 0 ? (
              <div className="team-member-list">
                {members.map((m) => (
                  <div key={m.expert_id} className="team-member-card">
                    <div className="expert-avatar">
                      <i className={m.icon || "fa-solid fa-user-tie"} />
                    </div>
                    <div className="team-member-text">
                      <div className="team-member-title">
                        {m.title || m.name}
                        {m.member_role === "lead" ? (
                          <span className="expert-badge expert-badge-inline">
                            主理人
                          </span>
                        ) : null}
                      </div>
                      <div className="expert-name">
                        {m.name}
                        {m.role_hint ? ` · ${m.role_hint}` : ""}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="expert-detail-hint">（暂无成员信息）</p>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
