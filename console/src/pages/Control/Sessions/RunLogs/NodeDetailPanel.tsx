/**
 * NodeDetailPanel — right pane of the run detail page: the selected
 * node's title/status/clock header plus Input & Output cards with a
 * JSON view toggle ({}) and copy buttons, mirroring the competitor.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, ChevronDown, Code2, Copy } from "lucide-react";
import type { TraceNode } from "./traceTree";
import { copyText, formatClock, formatDuration, serializeDetail } from "./format";
import type { RunLogTrace } from "../../../../api/modules/runLogs";
import styles from "./runLogs.module.less";

/** Pretty-print a payload for the {} JSON view when it parses. */
function topretty(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function IoCard({
  label,
  role,
  text,
}: {
  label: string;
  role: string;
  text: string;
}) {
  const { t } = useTranslation();
  const [jsonMode, setJsonMode] = useState(false);
  const shown = jsonMode ? topretty(text) : text;
  return (
    <div className={styles.ioSection}>
      <div className={styles.ioSectionHead}>
        <span className={styles.ioLabel}>{label}</span>
        <span className={styles.ioActions}>
          <button
            type="button"
            className={`${styles.ioIconBtn}${jsonMode ? ` ${styles.ioIconBtnActive}` : ""}`}
            title={t("runLogs.detail.jsonToggle", "JSON 视图")}
            onClick={() => setJsonMode((prev) => !prev)}
          >
            <Code2 size={14} />
          </button>
          {text && (
            <button
              type="button"
              className={styles.ioIconBtn}
              title={t("runLogs.detail.copy", "复制")}
              onClick={() => copyText(text)}
            >
              <Copy size={14} />
            </button>
          )}
        </span>
      </div>
      <div className={styles.ioRoleTag}>
        {role}
        <ChevronDown size={12} />
      </div>
      <pre className={styles.ioPre}>
        {shown || t("runLogs.detail.empty", "（空）")}
      </pre>
    </div>
  );
}

export function NodeDetailPanel({
  node,
  trace,
}: {
  node: TraceNode;
  trace: RunLogTrace | null;
}) {
  const { t } = useTranslation();
  const titleMap: Record<string, string> = {
    root: t("runLogs.detail.overview", "运行总览"),
    system: t("runLogs.detail.systemContext", "系统上下文"),
    user: t("runLogs.detail.userInput", "用户输入"),
    intent: t("runLogs.detail.intent", "意图识别"),
    llm: t("runLogs.detail.llmThinking", "LLM 思考"),
    toolCall: t("runLogs.detail.toolCall", "工具调用"),
    end: t("runLogs.detail.logicEnd", "逻辑结束"),
  };
  const title = titleMap[node.title] ?? titleMap[node.kind] ?? node.title;
  const inputText = serializeDetail(node.detail.input);
  const outputText = serializeDetail(node.detail.output);
  const clock =
    typeof trace?.created_at === "number" ? formatClock(trace.created_at) : "—";
  const duration = node.durationMs === null ? "" : formatDuration(node.durationMs);

  return (
    <section className={styles.ioPanel}>
      <div className={styles.nodeHead}>
        <span className={styles.nodeTitle}>{title}</span>
        <CheckCircle2 size={15} className={styles.nodeStatusIcon} />
        <span className={styles.nodeMeta}>{clock}</span>
        {duration && <span className={styles.nodeMeta}>{duration}</span>}
      </div>
      <IoCard label="Input" role="User" text={inputText} />
      <IoCard label="Output" role="Assistant" text={outputText} />
    </section>
  );
}
