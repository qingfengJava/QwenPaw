/**
 * RunLogDetailPage — full-page run detail (competitor style):
 * breadcrumb "运行日志 > user time 通过 channel 在 env 环境触发" on top,
 * left execution-chain tree + right Input/Output panel below. Routed at
 * sessions/runs/:runId in both agent layouts; deep-link refresh safe.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Spin } from "antd";
import { useExpertAvatarUri } from "../../../../hooks/useExpertAvatarUri";
import { useRunLogTrace } from "./useRunLogTrace";
import { buildSpanTree, buildTraceTree, truncateDetail, type TraceNode } from "./traceTree";
import { formatClock } from "./format";
import { TraceTreePanel } from "./TraceTreePanel";
import { NodeDetailPanel } from "./NodeDetailPanel";
import styles from "./runLogs.module.less";

/** Depth-first search for the selected node (falls back to root). */
function findNode(tree: TraceNode, key: string): TraceNode {
  const stack: TraceNode[] = [tree];
  while (stack.length) {
    const node = stack.pop() as TraceNode;
    if (node.key === key) {
      return node;
    }
    stack.push(...node.children);
  }
  return tree;
}

export default function RunLogDetailPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { aid, runId } = useParams<{ aid: string; runId: string }>();
  // 返回目标：会话 Tab 下的运行日志列表。必须用 "../sessions"
  // （route 层级相对路径）："../.." 会解析到根路径跳出沙箱，
  // 触发 CatchAllNavigate 整体重挂工作台（表现为整页刷新）。
  const backTarget = `../sessions`;
  const { trace, loading, error } = useRunLogTrace(aid, runId);
  const [selectedKey, setSelectedKey] = useState("root");

  const tree = useMemo(
    () =>
      trace
        ? // PG runs carry real spans; legacy file traces fall back to
          // message-based semantic guessing.
          trace.spans && trace.spans.length > 0
          ? buildSpanTree(trace)
          : buildTraceTree(trace)
        : null,
    [trace],
  );
  const selectedNode = useMemo(
    () => (tree ? findNode(tree, selectedKey) : null),
    [tree, selectedKey],
  );
  // Truncation stays lazy: only the visible payload pays the cost.
  const selectedDetail = useMemo(
    () =>
      selectedNode
        ? {
            ...selectedNode,
            detail: {
              input: truncateDetail(selectedNode.detail.input),
              output: truncateDetail(selectedNode.detail.output),
            },
          }
        : null,
    [selectedNode],
  );

  const meta = trace?.meta;
  const avatar = useExpertAvatarUri(null, meta?.user_id || "user");
  const environmentLabel =
    meta?.environment === "debug"
      ? t("runLogs.env.debug", "调试")
      : t("runLogs.env.online", "线上");

  return (
    <div className={styles.detailPage}>
      <div className={styles.detailTopbar}>
        <button
          type="button"
          className={styles.detailBack}
          title={t("runLogs.detail.backToList", "返回运行日志")}
          onClick={() => navigate(backTarget)}
        >
          <ArrowLeft size={15} />
        </button>
        <span
          className={styles.detailBreadcrumbLink}
          onClick={() => navigate(backTarget)}
          role="link"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              navigate(backTarget);
            }
          }}
        >
          {t("runLogs.title", "运行日志")}
        </span>
        <span className={styles.detailChevron}>›</span>
        {avatar ? (
          <img className={styles.detailAvatar} src={avatar} alt="" />
        ) : (
          <span className={styles.detailAvatarFallback}>
            {(meta?.user_id || "?").slice(0, 1).toUpperCase()}
          </span>
        )}
        <span className={styles.detailUser}>{meta?.user_id || "—"}</span>
        <span className={styles.detailMeta}>
          {formatClock(trace?.created_at)}
        </span>
        <span className={styles.detailMeta}>
          {t("runLogs.detail.triggeredBy", "通过")}
          {" "}
          {meta?.channel || "—"}
          {" "}
          {t("runLogs.detail.inEnv", "在")}
          {" "}
          {environmentLabel}
          {" "}
          {t("runLogs.detail.envTriggered", "环境触发")}
        </span>
      </div>

      {loading ? (
        <div className={styles.detailLoading}>
          <Spin />
        </div>
      ) : error ? (
        <div className={styles.detailError}>{error}</div>
      ) : tree && selectedDetail ? (
        <div className={styles.detailBody}>
          <TraceTreePanel
            tree={tree}
            selectedKey={selectedKey}
            titleMap={{}}
            onSelect={(node) => setSelectedKey(node.key)}
          />
          <NodeDetailPanel node={selectedDetail} trace={trace} />
        </div>
      ) : null}
    </div>
  );
}
