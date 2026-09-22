/**
 * RunDecisionPanel — 运行决策面板（团队任务详情页的人工介入入口）。
 *
 * 授权完全由服务端投影驱动：只渲染 ``allowed_actions`` 声明的动作
 * （计划批准门 / 澄清等待 / 升级裁决 / 续跑）；expected_revision 取
 * 挂起决策对象，过期修订被拒时提示刷新重试（保存冲突态）。
 */
import { useState } from "react";
import { workforceApi } from "../../api/modules";
import type { TeamRun } from "../../api/modules";

export interface RunDecisionPanelProps {
  run: TeamRun;
  /** 统一操作回调（成功提示 + 刷新详情由父级收口）。 */
  onAct: (fn: () => Promise<unknown>, okText: string) => void;
  busy: boolean;
}

export default function RunDecisionPanel({ run, onAct, busy }: RunDecisionPanelProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const actions = new Set(run.allowed_actions ?? []);
  const pending = run.pending_decision;

  const decide = (
    decisionId: string,
    action: string,
    expectedRevision: number,
    okText: string,
    comment = "",
  ) =>
    onAct(
      () =>
        workforceApi.decide(run.id, {
          decision_id: decisionId,
          action,
          expected_revision: expectedRevision,
          comment,
        }),
      okText,
    );

  return (
    <div>
      {/* ---- 计划批准门（T3；waiting_reason=plan_approval） ---- */}
      {actions.has("approve_plan") && pending && (
        <div className="list-row-card" style={{ marginBottom: 14, borderLeft: "3px solid #7c3aed" }}>
          <div style={{ width: "100%" }}>
            <div className="list-row-title" style={{ marginBottom: 6 }}>
              <i className="fa-solid fa-list-check" style={{ marginRight: 6 }} />
              中央大脑生成执行计划，等待你批准
            </div>
            {pending.summary && (
              <div className="list-row-desc" style={{ whiteSpace: "pre-wrap", marginBottom: 10 }}>
                {pending.summary.slice(0, 1200)}
              </div>
            )}
            <div className="list-row-desc" style={{ marginBottom: 10 }}>
              计划版本 v{pending.revision}（批准后按此版本执行；期间内容更新需重新批准）
            </div>
            <button
              className="btn-black"
              disabled={busy}
              onClick={() => decide(pending.decision_id, "approve_plan", pending.revision, "计划已批准，开始执行")}
            >
              批准计划
            </button>
            {actions.has("cancel") && (
              <button
                disabled={busy}
                onClick={() => onAct(() => workforceApi.cancel(run.id), "已请求取消")}
                style={{ marginLeft: 8, padding: "6px 14px", borderRadius: 8, border: "1px solid var(--border,#d1d5db)", background: "transparent", cursor: "pointer" }}
              >
                放弃任务
              </button>
            )}
          </div>
        </div>
      )}

      {/* ---- 澄清等待（requirement_confirm；决策与输入两用） ---- */}
      {run.status === "awaiting_confirm" && (run.clarification?.questions ?? []).length > 0 && (
        <div className="list-row-card" style={{ marginBottom: 14, borderLeft: "3px solid #b45309" }}>
          <div style={{ width: "100%" }}>
            <div className="list-row-title" style={{ marginBottom: 8 }}>中央大脑需要你澄清以下问题</div>
            {(run.clarification?.questions ?? []).map((q) => (
              <div key={q} style={{ marginBottom: 10 }}>
                <div className="list-row-desc" style={{ marginBottom: 4 }}>{q}</div>
                <input
                  value={answers[q] ?? ""}
                  onChange={(e) => setAnswers((prev) => ({ ...prev, [q]: e.target.value }))}
                  placeholder="输入你的答复…"
                  style={{ width: "100%", padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border,#d1d5db)", boxSizing: "border-box" }}
                />
              </div>
            ))}
            <button
              className="btn-black"
              disabled={busy || !Object.values(answers).some((v) => v.trim())}
              onClick={() => onAct(() => workforceApi.clarify(run.id, answers), "已提交答复，任务继续规划")}
            >
              提交答复
            </button>
          </div>
        </div>
      )}

      {/* ---- 升级人工裁决（escalated） ---- */}
      {actions.has("escalation") && run.status === "escalated" && (
        <EscalationCard run={run} onAct={onAct} busy={busy} />
      )}

      {/* ---- 协作挂起（paused/interrupted）续跑入口 ---- */}
      {(run.status === "paused" || run.status === "interrupted") && (
        <div className="list-row-card" style={{ marginBottom: 14, borderLeft: "3px solid #b45309" }}>
          <div style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div>
              <div className="list-row-title">任务已暂停</div>
              <div className="list-row-desc">
                {run.status === "paused"
                  ? "运行配置或成员版本发生变化，已安全挂起；确认无碍后续跑。"
                  : "上次执行被中断，已完成的工作已保存，可从断点继续。"}
              </div>
            </div>
            <button
              className="btn-black"
              disabled={busy}
              onClick={() => onAct(() => workforceApi.resume(run.id), "已恢复执行")}
            >
              续跑
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** 升级裁决卡：定位目标节点 + retry/abort。 */
function EscalationCard({ run, onAct, busy }: { run: TeamRun; onAct: RunDecisionPanelProps["onAct"]; busy: boolean }) {
  const rows = run.nodes ?? [];
  const target =
    rows.find((n) => n.verdict === "ESCALATE" && n.status !== "done") ??
    rows.find((n) => n.status !== "done");
  if (!target) return null;
  return (
    <div className="list-row-card" style={{ marginBottom: 14, borderLeft: "3px solid #dc2626" }}>
      <div className="list-row-main">
        <div>
          <div className="list-row-title">人工裁决：节点「{target.node_key}」触发熔断</div>
          <div className="list-row-desc">{run.escalation_reason || "验收多次未通过，等待人工裁决"}</div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button
          className="btn-black"
          disabled={busy}
          onClick={() =>
            onAct(
              () => workforceApi.resolveEscalation(run.id, target.node_key, "retry", "人工放行重试"),
              "已放行重试",
            )
          }
        >
          放行重试
        </button>
        <button
          disabled={busy}
          onClick={() =>
            onAct(
              () => workforceApi.resolveEscalation(run.id, target.node_key, "abort", "人工终止"),
              "已终止任务",
            )
          }
          style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid #dc2626", color: "#dc2626", background: "transparent", cursor: "pointer" }}
        >
          终止任务
        </button>
      </div>
    </div>
  );
}
