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
  const title =
    titleMap[node.title] ??
    titleMap[node.kind] ??
    (node.kind === "toolCall" || node.kind === "tool"
      ? node.title
      : node.kind === "system"
        ? t("runLogs.detail.systemContext", "系统上下文")
        : node.title);
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
