/**
 * RunDetail — workforce team-run detail: DAG wave progress, per-node
 * contract/result/verdict/rework ledger, SSE live refresh, escalation
 * intervention, clarify answers, cancel/resume, and cross-user handover.
 *
 * Data: useTeamRunsStore.loadDetail + subscribeRunEvents (each event
 * triggers one reload — the store is the single invalidation point).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import PageShell from "../components/PageShell";
import { useToast } from "../components/Toast";
import { useTeamRunsStore } from "../stores/teamRuns";
import { subscribeRunEvents } from "../lib/feedStream";
import {
  ACTIVE_RUN_STATUSES,
  RUN_STATUS_META,
} from "../lib/runStatus";
import { workforceApi } from "../api/modules";
import type { TeamRunNode } from "../api/modules";

/** 节点状态中文映射。 */
const NODE_STATUS_META: Record<string, { label: string; icon: string; tone: string }> = {
  pending: { label: "待执行", icon: "fa-regular fa-clock", tone: "#6b7280" },
  delegated: { label: "已委派", icon: "fa-solid fa-paper-plane", tone: "#2563eb" },
  running: { label: "执行中", icon: "fa-solid fa-spinner fa-spin", tone: "#2563eb" },
  verifying: { label: "验收中", icon: "fa-solid fa-clipboard-check", tone: "#2563eb" },
  repairing: { label: "返工中", icon: "fa-solid fa-screwdriver-wrench", tone: "#b45309" },
  done: { label: "完成", icon: "fa-solid fa-circle-check", tone: "#16a34a" },
  failed: { label: "失败", icon: "fa-solid fa-circle-xmark", tone: "#dc2626" },
};

/** 活跃态集合（操作条按钮的显示依据，共享映射派生）。 */
const ACTIVE_STATUSES = ACTIVE_RUN_STATUSES;

interface DagNodeDef {
  node_key: string;
  deps: string[];
  node_type: string;
  objective?: string;
}

/** 按 DAG 依赖分层为波次（与后端 topological_waves 一致的最小实现）。 */
function waveKeys(nodes: DagNodeDef[]): string[][] {
  const byKey = new Map(nodes.map((n) => [n.node_key, n]));
  const placed = new Set<string>();
  const waves: string[][] = [];
  let remaining = nodes.map((n) => n.node_key);
  while (remaining.length) {
    const ready = remaining
      .filter((k) => (byKey.get(k)?.deps ?? []).every((d) => placed.has(d)))
      .sort();
    if (!ready.length) break; // 防御：环（后端已校验，不应出现）
    waves.push(ready);
    ready.forEach((k) => placed.add(k));
    remaining = remaining.filter((k) => !placed.has(k));
  }
  return waves;
}

export default function RunDetailPage() {
  const toast = useToast();
  const { runId = "" } = useParams();
  const { detail, detailLoading, loadDetail, clearDetail } = useTeamRunsStore();
  const [expanded, setExpanded] = useState<string>("");
  const [clarifyAnswers, setClarifyAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  // 初载 + 卸载清理（store 详情缓存随路由进出）
  useEffect(() => {
    loadDetail(runId).catch((err) => toast.error(`加载任务失败：${String(err)}`));
    return () => clearDetail();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // SSE 实时刷新：每条事件触发一次详情重载（节流交给 store 的 seq 机制）
  useEffect(() => {
    if (!runId) return;
    const handle = subscribeRunEvents(runId, {
      onEvent: () => {
        loadDetail(runId).catch(() => undefined);
      },
    });
    return () => handle.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const run = detail;

  // 波次视图（plan 节点定义 + 节点行状态 join）
  const nodeRows = useMemo(() => new Map((run?.nodes ?? []).map((n) => [n.node_key, n])), [run]);
  const waves = useMemo(() => waveKeys(((run?.plan?.nodes ?? []) as DagNodeDef[])), [run]);

  // 熔断干预目标节点：verdict=ESCALATE 或最后非 done 节点
  const escalateNodeKey = useMemo(() => {
    if (run?.status !== "escalated") return "";
    const rows = run.nodes ?? [];
    const target = rows.find((n) => n.verdict === "ESCALATE" && n.status !== "done");
    return target?.node_key ?? rows.find((n) => n.status !== "done")?.node_key ?? "";
  }, [run]);

  // ---- 操作（全部走 workforceApi，成功后刷新详情） ----
  const act = useCallback(
    async (fn: () => Promise<unknown>, okText: string) => {
      setBusy(true);
      try {
        await fn();
        toast.success(okText);
        await loadDetail(runId);
      } catch (err) {
        toast.error(`操作失败：${String(err)}`);
      } finally {
        setBusy(false);
      }
    },
    [toast, runId, loadDetail],
  );

  if (detailLoading && !run) {
    return (
      <div className="view active">
        <PageShell title="专家团任务" subtitle="加载中…">
          <div className="blank-state">加载中…</div>
        </PageShell>
      </div>
    );
  }
  if (!run) {
    return (
      <div className="view active">
        <PageShell title="专家团任务" subtitle="任务不存在或无权访问">
          <div className="blank-state">任务不存在或无权访问</div>
        </PageShell>
      </div>
    );
  }

  const meta = RUN_STATUS_META[run.status] ?? RUN_STATUS_META.planning;
  const totalTokens = (run.nodes ?? []).reduce((sum, n) => sum + (n.token_cost || 0), 0);

  return (
    <div className="view active">
      <PageShell title="专家团任务" subtitle={run.goal}>
        {/* ---- 状态头部卡 ---- */}
        <div className="list-row-card" style={{ marginBottom: 14 }}>
          <div className="list-row-main">
            <div className="card-icon" style={{ width: 42, height: 42, fontSize: 17, marginBottom: 0, color: meta.tone }}>
              <i className={meta.icon} />
            </div>
            <div>
              <div className="list-row-title" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span style={{ color: meta.tone }}>{meta.label}</span>
                <span className="task-status">上下文 v{run.context_version}</span>
                <span className="task-status">返工 {run.repair_count} 次</span>
                <span className="task-status">{totalTokens > 0 ? `${(totalTokens / 1000).toFixed(1)}K tokens` : "—"}</span>
              </div>
              <div className="list-row-desc">
                发起人 {run.initiator_id === "local" ? "本地用户" : run.initiator_id} ·
                团队 {run.team_id.slice(0, 12)} ·
                {run.created_at?.slice(0, 16)?.replace("T", " ") ?? ""}
                {run.error ? ` · 错误：${run.error.slice(0, 80)}` : ""}
                {run.escalation_reason ? ` · 熔断：${run.escalation_reason.slice(0, 80)}` : ""}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {ACTIVE_STATUSES.has(run.status) && (
              <button
                className="btn-black"
                disabled={busy}
                onClick={() => act(() => workforceApi.cancel(run.id), "已请求取消")}
              >
                取消任务
              </button>
            )}
            {run.status === "interrupted" && (
              <button
                className="btn-black"
                disabled={busy}
                onClick={() => act(() => workforceApi.resume(run.id), "已恢复执行")}
              >
                续跑
              </button>
            )}
          </div>
        </div>

        {/* ---- 熔断人工干预条 ---- */}
        {run.status === "escalated" && escalateNodeKey && (
          <div className="list-row-card" style={{ marginBottom: 14, borderLeft: "3px solid #dc2626" }}>
            <div className="list-row-main">
              <div>
                <div className="list-row-title">人工裁决：节点「{escalateNodeKey}」触发熔断</div>
                <div className="list-row-desc">{run.escalation_reason || "验收多次未通过，等待人工裁决"}</div>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className="btn-black"
                disabled={busy}
                onClick={() =>
                  act(
                    () => workforceApi.resolveEscalation(run.id, escalateNodeKey, "retry", "人工放行重试"),
                    "已放行重试",
                  )
                }
              >
                放行重试
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  act(
                    () => workforceApi.resolveEscalation(run.id, escalateNodeKey, "abort", "人工终止"),
                    "已终止任务",
                  )
                }
                style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid #dc2626", color: "#dc2626", background: "transparent", cursor: "pointer" }}
              >
                终止任务
              </button>
            </div>
          </div>
        )}

        {/* ---- 澄清问答卡 ---- */}
        {run.status === "awaiting_confirm" && (
          <div className="list-row-card" style={{ marginBottom: 14, borderLeft: "3px solid #b45309" }}>
            <div style={{ width: "100%" }}>
              <div className="list-row-title" style={{ marginBottom: 8 }}>中央大脑需要你澄清以下问题</div>
              {(run.clarification?.questions ?? []).map((q) => (
                <div key={q} style={{ marginBottom: 10 }}>
                  <div className="list-row-desc" style={{ marginBottom: 4 }}>{q}</div>
                  <input
                    value={clarifyAnswers[q] ?? ""}
                    onChange={(e) => setClarifyAnswers((prev) => ({ ...prev, [q]: e.target.value }))}
                    placeholder="输入你的答复…"
                    style={{ width: "100%", padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border,#d1d5db)", boxSizing: "border-box" }}
                  />
                </div>
              ))}
              <button
                className="btn-black"
                disabled={busy || !Object.values(clarifyAnswers).some((v) => v.trim())}
                onClick={() =>
                  act(() => workforceApi.clarify(run.id, clarifyAnswers), "已提交答复，任务继续规划")
                }
              >
                提交答复
              </button>
            </div>
          </div>
        )}

        {/* ---- 最终汇总卡 ---- */}
        {run.status === "done" && run.summary && (
          <div className="list-row-card" style={{ marginBottom: 14, borderLeft: "3px solid #16a34a" }}>
            <div style={{ width: "100%" }}>
              <div className="list-row-title" style={{ marginBottom: 6 }}>
                <i className="fa-solid fa-flag-checkered" style={{ marginRight: 6 }} />
                最终交付
              </div>
              <div className="list-row-desc" style={{ whiteSpace: "pre-wrap" }}>
                {run.summary.slice(0, 2000)}
              </div>
            </div>
          </div>
        )}

        {/* ---- DAG 波次进度 ---- */}
        {waves.map((wave, idx) => (
          <div key={idx} style={{ marginBottom: 14 }}>
            <div className="list-row-desc" style={{ margin: "6px 2px", fontWeight: 600 }}>
              第 {idx + 1} 波（{wave.length > 1 ? "并行" : "单节点"}）
            </div>
            {wave.map((key) => (
              <NodeCard
                key={key}
                nodeKey={key}
                def={((run.plan?.nodes ?? []) as DagNodeDef[]).find((n) => n.node_key === key)}
                row={nodeRows.get(key)}
                expanded={expanded === key}
                onToggle={() => setExpanded(expanded === key ? "" : key)}
              />
            ))}
          </div>
        ))}
        {!waves.length && <div className="blank-state">尚未生成任务规划</div>}

        {run.source_chat_id && (
          <div className="list-row-desc" style={{ marginTop: 8 }}>
            <Link to={`/chat?chat=${run.source_chat_id}`}>← 返回来源会话</Link>
          </div>
        )}
      </PageShell>
    </div>
  );
}

/** 单节点卡片：状态/专家/目标/计数 + 展开后的契约-结果-返工时间线。 */
function NodeCard({
  nodeKey,
  def,
  row,
  expanded,
  onToggle,
}: {
  nodeKey: string;
  def?: DagNodeDef;
  row?: TeamRunNode;
  expanded: boolean;
  onToggle: () => void;
}) {
  const status = row?.status ?? "pending";
  const meta = NODE_STATUS_META[status] ?? NODE_STATUS_META.pending;
  const objective = (row?.contract?.objective as string) || def?.objective || nodeKey;
  const isBrain = def?.node_type === "final" || def?.node_type === "integration";
  const resultText =
    (row?.result?.result_text as string) || JSON.stringify(row?.result?.result ?? {}, null, 2);
  const repairIssues = (row?.repair?.issues as string[]) ?? [];
  const verdictTone =
    row?.verdict === "PASS" ? "#16a34a" : row?.verdict === "FAIL" ? "#dc2626" : row?.verdict === "ESCALATE" ? "#dc2626" : "#6b7280";

  return (
    <div className="list-row-card" style={{ cursor: "pointer", marginBottom: 8 }} onClick={onToggle}>
      <div className="list-row-main">
        <div className="card-icon" style={{ width: 34, height: 34, fontSize: 13, marginBottom: 0, color: meta.tone }}>
          <i className={isBrain ? "fa-solid fa-brain" : meta.icon} />
        </div>
        <div>
          <div className="list-row-title" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span>{isBrain ? "中央大脑" : nodeKey}</span>
            <span style={{ color: meta.tone, fontSize: 12 }}>{meta.label}</span>
            {row?.verdict ? (
              <span style={{ color: verdictTone, fontSize: 12 }}>验收 {row.verdict}</span>
            ) : null}
            {row && row.attempt > 1 && <span className="task-status">第 {row.attempt} 轮</span>}
            {row && row.repair_count > 0 && (
              <span className="task-status" style={{ color: "#b45309" }}>返工 {row.repair_count}</span>
            )}
            {row?.assignee_user_id ? (
              <span className="task-status" style={{ color: "#7c3aed" }}>
                已移交 {row.assignee_user_id === "local" ? "本地用户" : row.assignee_user_id}
              </span>
            ) : null}
          </div>
          <div className="list-row-desc">{String(objective).slice(0, 120)}</div>
        </div>
      </div>
      <div className="task-time">
        {row?.token_cost ? `${(row.token_cost / 1000).toFixed(1)}K` : ""}{" "}
        <i className={`fa-solid fa-chevron-${expanded ? "up" : "down"}`} style={{ marginLeft: 6, fontSize: 11 }} />
      </div>

      {expanded && (
        <div style={{ width: "100%", marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border,#ececf1)" }} onClick={(e) => e.stopPropagation()}>
          {def?.deps?.length ? (
            <div className="list-row-desc">依赖：{def.deps.join("、")}</div>
          ) : null}
          {Array.isArray(row?.contract?.expected_output) && (row?.contract?.expected_output as string[]).length ? (
            <div className="list-row-desc">
              期望产出：{(row?.contract?.expected_output as string[]).join("；")}
            </div>
          ) : null}
          {Array.isArray(row?.contract?.quality_criteria) && (row?.contract?.quality_criteria as string[]).length ? (
            <div className="list-row-desc">
              验收标准：{(row?.contract?.quality_criteria as string[]).join("；")}
            </div>
          ) : null}
          {repairIssues.length ? (
            <div className="list-row-desc" style={{ color: "#dc2626", marginTop: 6 }}>
              返工问题：{repairIssues.map((s, i) => `${i + 1}. ${s}`).join("　")}
            </div>
          ) : null}
          {row?.result && Object.keys(row.result).length ? (
            <div
              className="list-row-desc"
              style={{ marginTop: 8, whiteSpace: "pre-wrap", maxHeight: 260, overflow: "auto", background: "var(--bg-inset,#f7f7f8)", padding: 10, borderRadius: 8 }}
            >
              {String(resultText).slice(0, 4000) || "（无正文产出）"}
            </div>
          ) : (
            <div className="list-row-desc" style={{ marginTop: 8 }}>（尚未执行）</div>
          )}
        </div>
      )}
    </div>
  );
}
