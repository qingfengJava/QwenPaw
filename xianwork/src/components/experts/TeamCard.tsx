/**
 * TeamCard — expert-team market card (WorkBuddy style): avatar, team
 * name, mode + member count line, description, capability tag pills.
 * Click opens the team detail (members + summon).
 */
import type { ExpertTeam } from "../../api/modules";

export interface TeamCardProps {
  team: ExpertTeam;
  onOpen: (team: ExpertTeam) => void;
}

export function teamModeLabel(mode: string): string {
  if (mode === "pipeline") {
    return "流水线协作";
  }
  return "按需路由";
}

export default function TeamCard({ team, onOpen }: TeamCardProps) {
  const tags = (team.tags ?? []).slice(0, 4);
  return (
    <div
      className="expert-card"
      onClick={() => onOpen(team)}
      role="button"
    >
      <div className="expert-card-head">
        <div className="expert-avatar">
          <i className="fa-solid fa-users-rectangle" />
        </div>
        <div className="expert-card-head-text">
          <div className="expert-title">{team.name}</div>
          <div className="expert-name">
            {teamModeLabel(team.mode)} · {team.member_count} 位成员
          </div>
        </div>
      </div>
      <p className="expert-desc">{team.description || "专家团"}</p>
      {tags.length > 0 && (
        <div className="expert-tags">
          {tags.map((tag) => (
            <span key={tag} className="expert-tag">
              {tag}
            </span>
          ))}
        </div>
      )}
      <div className="expert-card-foot">
        <span className="expert-usage">
          <i className="fa-solid fa-arrow-pointer" />
          点击查看团队
        </span>
      </div>
    </div>
  );
}
