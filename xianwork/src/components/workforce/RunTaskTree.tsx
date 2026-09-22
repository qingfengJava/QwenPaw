/**
 * RunTaskTree — 运行任务树（团队任务详情页的 DAG 投影视图）。
 *
 * 图从 plan/node 权威投影渲染（波次分层 + 节点契约/结果/返工时间线），
 * 不解析聊天文本自造状态；空计划/加载中/无节点留痕各有显式空态。
 */
import { useState } from "react";
import type { TeamRun, TeamRunNode } from "../../api/modules";

/** 节点状态中文映射（与 runStatus 共同的色板体系）。 */
const NODE_STATUS_META: Record<string, { label: string; icon: string; tone: string }> = {
  pending: { label: "待执行", icon: "fa-regular fa-clock", tone: "#6b7280" },
  delegated: { label: "已委派", icon: "fa-solid fa-paper-plane", tone: "#2563eb" },
  running: { label: "执行中", icon: "fa-solid fa-spinner fa-spin", tone: "#2563eb" },
  verifying: { label: "验收中", icon: "fa-solid fa-clipboard-check", tone: "#2563eb" },
  repairing: { label: "返工中", icon: "fa-solid fa-screwdriver-wrench", tone: "#b45309" },
  done: { label: "完成", icon: "fa-solid fa-circle-check", tone: "#16a34a" },
  failed: { label: "失败", icon: "fa-solid fa-circle-xmark", tone: "#dc2626" },
};

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

export default function RunTaskTree({ run }: { run: TeamRun }) {
  const [expanded, setExpanded] = useState<string>("");
  const nodeRows = new Map((run.nodes ?? []).map((n) => [n.node_key, n]));
  const defs = (run.plan?.nodes ?? []) as DagNodeDef[];
  const waves = waveKeys(defs);

  if (!waves.length) {
    return <div className="blank-state">尚未生成任务规划</div>;
  }

  return (
    <div>
      {waves.map((wave, idx) => (
        <div key={idx} style={{ marginBottom: 14 }}>
          <div className="list-row-desc" style={{ margin: "6px 2px", fontWeight: 600 }}>
            第 {idx + 1} 波（{wave.length > 1 ? "并行" : "单节点"}）
          </div>
          {wave.map((key) => (
            <NodeCard
              key={key}
              nodeKey={key}
              def={defs.find((n) => n.node_key === key)}
              row={nodeRows.get(key)}
              expanded={expanded === key}
              onToggle={() => setExpanded(expanded === key ? "" : key)}
            />
          ))}
        </div>
      ))}
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
