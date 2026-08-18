/**
 * TeamDetailModal — expert-team detail (WorkBuddy layout): the black
 * 召唤专家团 button, orchestration mode explanation, the member roster
 * cards with the 主理人 badge (member_role === "lead"), the curated
 * "任务示例" rows (one click starts a team run with the prompt as
 * goal), the static showcase cards, and the real "最近交付" projection
 * (latest done runs — static operations content + real delivery
 * evidence side by side).
 */
import { useEffect, useState } from "react";
import Modal from "../Modal";
import { workforceApi } from "../../api/modules";
import type { ExpertTeam, TeamRun } from "../../api/modules";
import { teamModeLabel } from "./TeamCard";

export interface TeamDetailModalProps {
  team: ExpertTeam | null;
  onClose: () => void;
  /** kickoff: 模板行点击时携带的任务提示词（作为 run 的 goal）。 */
  onSummon: (team: ExpertTeam, kickoff?: string) => void;
}

export default function TeamDetailModal({
  team,
  onClose,
  onSummon,
}: TeamDetailModalProps) {
  const members = team?.members ?? [];
  const tasks = team?.sample_tasks ?? [];
  const showcase = team?.showcase ?? [];
  const [deliveries, setDeliveries] = useState<TeamRun[]>([]);
  const [deliveriesError, setDeliveriesError] = useState("");

  /** 最近交付：该团队最新 done 的 run（前 2 条真实交付佐证）。 */
  useEffect(() => {
    setDeliveries([]);
    setDeliveriesError("");
    if (!team) {
      return;
    }
    let alive = true;
    workforceApi
      .list({ team_id: team.id, status: "done" })
      .then((runs) => {
        if (alive) {
          setDeliveries(runs.slice(0, 2));
        }
      })
      .catch((err) => {
        if (alive) {
          setDeliveriesError(`最近交付加载失败：${String(err)}`);
        }
      });
    return () => {
      alive = false;
    };
  }, [team]);

  const fmtDate = (value: string | null | undefined) =>
    value ? new Date(value).toLocaleDateString("zh-CN") : "";

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
          {tasks.length > 0 && (
            <div className="expert-detail-section">
              <h4>任务示例</h4>
              <div className="expert-task-list">
                {tasks.map((task) => (
                  <button
                    key={task.title}
                    type="button"
                    className="expert-task-row"
                    onClick={() => onSummon(team, task.prompt)}
                  >
                    <span className="expert-task-title">
                      <i className="fa-solid fa-wand-magic-sparkles" />
                      {task.title}
                    </span>
                    <span className="expert-task-go">发起任务</span>
                  </button>
                ))}
              </div>
            </div>
          )}
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
          {(showcase.length > 0 || deliveries.length > 0 || deliveriesError) && (
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
                {deliveries.map((run) => (
                  <div key={run.id} className="expert-case-card">
                    <div className="expert-case-title">
                      {run.goal}
                      <span className="expert-delivery-badge">最近交付</span>
                    </div>
                    {run.summary && (
                      <div className="expert-case-desc">{run.summary}</div>
                    )}
                    <div className="expert-case-meta">
                      交付于 {fmtDate(run.updated_at ?? run.created_at)}
                    </div>
                  </div>
                ))}
                {deliveriesError && (
                  <p className="expert-detail-hint">{deliveriesError}</p>
                )}
                {deliveries.length === 0 && !deliveriesError && (
                  <p className="expert-detail-hint">
                    （该团队暂无已完成任务，召唤后交付将展示在这里）
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
