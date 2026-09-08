/**
 * RunLogDetailDrawer — competitor-style run detail:
 * breadcrumb header (user / time / channel / environment), left
 * execution-chain tree with per-node durations, right Input/Output
 * JSON panels for the selected node.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Drawer } from "@agentscope-ai/design";
import { Spin } from "antd";
import { runLogsApi, type RunLogTrace } from "../../../../api/modules/runLogs";
import type { RunLogItem } from "../../../../api/modules/runLogs";
import { buildTraceTree, type TraceNode } from "./traceTree";
import styles from "./runLogs.module.less";

/** 12500 → "12.50 s"; 950 → "950 ms"; 95000 → "1.58 min". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) {
    return "—";
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  if (ms < 60000) {
    return `${(ms / 1000).toFixed(2)} s`;
  }
  return `${(ms / 60000).toFixed(2)} min`;
}

/** 2026-09-02 15:42:01 style local clock from epoch seconds. */
export function formatClock(epochSeconds: number | undefined | null): string {
  if (!epochSeconds) {
    return "—";
  }
  const date = new Date(epochSeconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
    date.getSeconds(),
  )}`;
}

function serializeDetail(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** One indent level of the execution chain. */
function ChainNodeRow({
  node,
  depth,
  selectedKey,
  titleMap,
  onSelect,
}: {
  node: TraceNode;
  depth: number;
  selectedKey: string;
  titleMap: Record<string, string>;
  onSelect: (node: TraceNode) => void;
}) {
  const hasChildren = node.children.length > 0;
  const isRoot = node.key === "root";
  const title = titleMap[node.title] ?? node.title;
  return (
    <div>
      <button
        type="button"
        className={`${styles.chainRow}${
          selectedKey === node.key ? ` ${styles.chainRowActive}` : ""
        }`}
        style={{ paddingLeft: 12 + depth * 18 }}
        onClick={() => onSelect(node)}
      >
        <span
          className={`${styles.chainDot} ${
            isRoot ? styles.chainDotRoot : ""
          }`}
        />
        <span className={styles.chainTitle}>{title}</span>
        {node.durationMs !== null && (
          <span className={styles.chainDuration}>
            {formatDuration(node.durationMs)}
          </span>
        )}
      </button>
      {hasChildren &&
        node.children.map((child) => (
          <ChainNodeRow
            key={child.key}
            node={child}
            depth={depth + 1}
            selectedKey={selectedKey}
            titleMap={titleMap}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

export function RunLogDetailDrawer({
  open,
  run,
  onClose,
}: {
  open: boolean;
  run: RunLogItem | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [trace, setTrace] = useState<RunLogTrace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState("root");

  const titleMap: Record<string, string> = {
    root: t("runLogs.detail.overview", "运行总览"),
    user: t("runLogs.detail.userInput", "用户输入"),
    assistant: t("runLogs.detail.llmThinking", "LLM 思考"),
  };

  useEffect(() => {
    if (!open || !run) {
      setTrace(null);
      setSelectedKey("root");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    runLogsApi
      .getRunLog(run.agent_id, run.run_id)
      .then((data) => {
        if (!cancelled) {
          setTrace(data);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, run]);

  const tree = useMemo(
    () => (trace ? buildTraceTree(trace) : null),
    [trace],
  );

  const selectedNode = useMemo(() => {
    if (!tree) {
      return null;
    }
    const stack: TraceNode[] = [tree];
    while (stack.length) {
      const node = stack.pop() as TraceNode;
      if (node.key === selectedKey) {
        return node;
      }
      stack.push(...node.children);
    }
    return tree;
  }, [tree, selectedKey]);

  const inputText = serializeDetail(selectedNode?.detail.input);
  const outputText = serializeDetail(selectedNode?.detail.output);

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard unavailable (e.g. insecure context); ignore silently.
    }
  };

  const environmentLabel = run?.environment === "debug"
    ? t("runLogs.env.debug", "调试")
    : t("runLogs.env.online", "线上");

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={1080}
      destroyOnClose
      title={
        run ? (
          <div className={styles.detailHeader}>
            <span className={styles.detailBreadcrumb}>
              {t("runLogs.title", "运行日志")}
            </span>
            <span className={styles.detailUser}>{run.user_id || "—"}</span>
            <span className={styles.detailMeta}>
              {formatClock(run.started_at)}
            </span>
            <span className={styles.detailMeta}>
              {t("runLogs.detail.triggeredBy", "通过")}
              {" "}
              {run.channel || "—"}
              {" "}
              {t("runLogs.detail.inEnv", "在")}
              {" "}
              {environmentLabel}
              {" "}
              {t("runLogs.detail.envTriggered", "环境触发")}
            </span>
          </div>
        ) : null
      }
    >
      {loading ? (
        <div className={styles.detailLoading}>
          <Spin />
        </div>
      ) : error ? (
        <div className={styles.detailError}>{error}</div>
      ) : tree ? (
        <div className={styles.detailBody}>
          <aside className={styles.chainPanel}>
            <ChainNodeRow
              node={tree}
              depth={0}
              selectedKey={selectedKey}
              titleMap={titleMap}
              onSelect={(node) => setSelectedKey(node.key)}
            />
          </aside>
          <section className={styles.ioPanel}>
            <div className={styles.ioSection}>
              <div className={styles.ioSectionHead}>
                <span className={styles.ioLabel}>
                  {t("runLogs.detail.input", "Input")}
                </span>
                {inputText && (
                  <Button
                    size="small"
                    type="text"
                    onClick={() => copyText(inputText)}
                  >
                    {t("runLogs.detail.copy", "复制")}
                  </Button>
                )}
              </div>
              <pre className={styles.ioPre}>
                {inputText || t("runLogs.detail.empty", "（空）")}
              </pre>
            </div>
            <div className={styles.ioSection}>
              <div className={styles.ioSectionHead}>
                <span className={styles.ioLabel}>
                  {t("runLogs.detail.output", "Output")}
                </span>
                {outputText && (
                  <Button
                    size="small"
                    type="text"
                    onClick={() => copyText(outputText)}
                  >
                    {t("runLogs.detail.copy", "复制")}
                  </Button>
                )}
              </div>
              <pre className={styles.ioPre}>
                {outputText || t("runLogs.detail.empty", "（空）")}
              </pre>
            </div>
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}

