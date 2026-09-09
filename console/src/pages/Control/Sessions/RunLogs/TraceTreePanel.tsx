/**
 * TraceTreePanel — left execution-chain tree of the run detail page.
 * Rows carry a per-kind icon (competitor style) and wall-time; subtrees
 * deeper than two levels start collapsed and expand on the caret.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Bot,
  ChevronDown,
  ChevronRight,
  Database,
  Flag,
  Globe,
  Lightbulb,
  Search,
  User,
  Wrench,
} from "lucide-react";
import type { TraceNode, TraceNodeKind } from "./traceTree";
import { formatDuration } from "./format";
import styles from "./runLogs.module.less";

/**
 * i18n titles for structural kinds (root/system/llm/end…) and common
 * tool names. Unmapped tool names and agent display names fall through
 * to the node title verbatim.
 */
function buildTitleMap(
  t: (key: string, fallback: string) => string,
): Record<string, string> {
  return {
    root: t("runLogs.tree.root", "运行总览"),
    system: t("runLogs.tree.system", "系统上下文"),
    user: t("runLogs.tree.user", "用户输入"),
    intent: t("runLogs.tree.intent", "意图识别"),
    llm: t("runLogs.tree.llm", "LLM 思考"),
    end: t("runLogs.tree.end", "逻辑结束"),
    // Common tool names — anything unmapped keeps its original name.
    web_search: t("runLogs.tools.web_search", "联网搜索"),
    read_file: t("runLogs.tools.read_file", "读取文件"),
    write_file: t("runLogs.tools.write_file", "写入文件"),
    edit_file: t("runLogs.tools.edit_file", "编辑文件"),
    append_file: t("runLogs.tools.append_file", "追加文件"),
    execute_shell: t("runLogs.tools.execute_shell", "执行命令"),
    bash: t("runLogs.tools.bash", "执行命令"),
    glob: t("runLogs.tools.glob", "搜索文件"),
    grep: t("runLogs.tools.grep", "搜索内容"),
    submit: t("runLogs.tools.submit", "提交结果"),
    get_skills: t("runLogs.tools.get_skills", "获取技能"),
    browser_navigate: t("runLogs.tools.browser_navigate", "打开网页"),
    browser_click: t("runLogs.tools.browser_click", "点击页面"),
  };
}

const KIND_ICONS: Record<TraceNodeKind, typeof Globe> = {
  root: Globe,
  system: Database,
  user: User,
  intent: Search,
  agent: Bot,
  llm: Lightbulb,
  toolCall: Wrench,
  tool: Wrench,
  end: Flag,
};

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
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(depth >= 2);
  const hasChildren = node.children.length > 0;
  const Icon = KIND_ICONS[node.kind] ?? Globe;
  // Priority: caller overrides -> i18n by title (tool names, kind keys)
  // -> i18n by kind -> raw title (unmapped tools, agent display names).
  const defaults = buildTitleMap(t);
  const title =
    titleMap[node.title] ??
    titleMap[node.kind] ??
    defaults[node.title] ??
    defaults[node.kind] ??
    node.title;
  return (
    <div>
      <div
        className={`${styles.chainRow}${
          selectedKey === node.key ? ` ${styles.chainRowActive}` : ""
        }`}
        style={{ paddingLeft: 12 + depth * 18 }}
        onClick={() => onSelect(node)}
        role="treeitem"
        aria-selected={selectedKey === node.key}
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            onSelect(node);
          }
        }}
      >
        {hasChildren ? (
          <button
            type="button"
            className={styles.chainCaret}
            aria-label={collapsed ? "expand" : "collapse"}
            onClick={(event) => {
              event.stopPropagation();
              setCollapsed((prev) => !prev);
            }}
          >
            {collapsed ? (
              <ChevronRight size={12} />
            ) : (
              <ChevronDown size={12} />
            )}
          </button>
        ) : (
          <span className={styles.chainCaretPlaceholder} />
        )}
        <Icon
          size={13}
          className={`${styles.chainKindIcon} ${
            node.kind === "tool" ? styles.chainKindIconTool : ""
          }`}
        />
        <span className={styles.chainTitle}>{title}</span>
        {node.durationMs !== null && (
          <span className={styles.chainDuration}>
            {formatDuration(node.durationMs)}
          </span>
        )}
      </div>
      {hasChildren &&
        !collapsed &&
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

export function TraceTreePanel({
  tree,
  selectedKey,
  titleMap,
  onSelect,
}: {
  tree: TraceNode;
  selectedKey: string;
  titleMap: Record<string, string>;
  onSelect: (node: TraceNode) => void;
}) {
  return (
    <aside className={styles.chainPanel} role="tree">
      <ChainNodeRow
        node={tree}
        depth={0}
        selectedKey={selectedKey}
        titleMap={titleMap}
        onSelect={onSelect}
      />
    </aside>
  );
}
