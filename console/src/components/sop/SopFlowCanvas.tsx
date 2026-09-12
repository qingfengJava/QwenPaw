/**
 * sop/SopFlowCanvas.tsx — SOP 自绘画布编辑器（缺口④：React Flow 方案）。
 *
 * 编辑/只读双态同一组件：
 *  - 自定义节点 SopNodeCard：序号圆标 + 标题 + 工具徽标 + 验收要点；
 *  - 自定义条件边 SopConditionEdge：贝塞尔路径 + 中点条件徽标；
 *  - 顶部工具条（编辑态）：添加节点 / dagre 自动整理 / 撤销重做（结构
 *    操作快照，上限 50）/ 适配视图 / 保存（校验前置）；
 *  - 右侧属性面板：选中节点编辑（标题/指令/验收要点/工具）、选中边编辑
 *    流转条件、无选中时展示 SOP 元信息 + 槽位表格；
 *  - 样式全部走 staffdeck tokens，不引入额外 CSS 框架。
 */
import { useCallback, useMemo, useRef, useState } from "react";
import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  EdgeLabelRenderer,
  getBezierPath,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type EdgeProps,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Button, Empty, Input, Popconfirm, Tag, Tooltip } from "antd";
import {
  ArrowLeftRight,
  LayoutTemplate,
  Plus,
  Redo2,
  Save,
  Undo2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAppMessage } from "@/hooks/useAppMessage";
import type { SopRecord, SopSlot } from "@/api/modules/admin";
import {
  flowToSop,
  layoutSopGraph,
  nextNodeId,
  sopToFlow,
  validateSopGraph,
  type SopFlowNode,
  type SopGraph,
  type SopNodeData,
} from "./sopGraph";

// ---------------------------------------------------------------------------
// 自定义节点：SopNodeCard
// ---------------------------------------------------------------------------

function SopNodeCard({ data, selected }: NodeProps<SopFlowNode>) {
  const nodeData = data as SopNodeData;
  return (
    <div
      style={{
        width: 248,
        minHeight: 104,
        border: `0.5px solid ${selected ? "var(--sd-link, #1a71ff)" : "var(--sd-line)"}`,
        boxShadow: selected
          ? "0 0 0 2px rgba(26, 113, 255, 0.15)"
          : "none",
        borderRadius: 14,
        background: "var(--sd-card, #fff)",
        padding: "10px 14px",
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: "var(--sd-line)", width: 8, height: 8 }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            width: 20,
            height: 20,
            borderRadius: "50%",
            background: "var(--sd-ink, #18181a)",
            color: "#fff",
            fontSize: 11,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          {typeof nodeData.seq === "number" ? nodeData.seq : "•"}
        </span>
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "var(--sd-ink, #18181a)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {nodeData.title || "未命名步骤"}
        </span>
      </div>
      {(nodeData.tools ?? []).length > 0 ? (
        <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 4 }}>
          {nodeData.tools.slice(0, 4).map((tool) => (
            <Tag
              key={tool}
              style={{ margin: 0, fontSize: 11, lineHeight: "18px" }}
            >
              {tool}
            </Tag>
          ))}
        </div>
      ) : null}
      {nodeData.expectedOutcome ? (
        <div
          style={{
            marginTop: 8,
            fontSize: 11,
            color: "var(--sd-green, #2cb360)",
            background: "var(--sd-green-bg, rgba(44, 179, 96, 0.10))",
            borderRadius: 8,
            padding: "3px 8px",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          ✓ {nodeData.expectedOutcome}
        </div>
      ) : null}
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: "var(--sd-line)", width: 8, height: 8 }}
      />
    </div>
  );
}

const nodeTypes = { sopNode: SopNodeCard };

// ---------------------------------------------------------------------------
// 自定义条件边：SopConditionEdge
// ---------------------------------------------------------------------------

function SopConditionEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps) {
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });
  const label = typeof data?.label === "string" ? data.label : "";
  return (
    <>
      <BaseEdgePath
        id={id}
        path={path}
        selected={Boolean(selected)}
      />
      {label ? (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: "all",
              fontSize: 11,
              color: "var(--sd-text-2, #757f9c)",
              background: "var(--sd-card, #fff)",
              border: "0.5px solid var(--sd-line, #e3e7f1)",
              borderRadius: 999,
              padding: "1px 8px",
              maxWidth: 180,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            ◇ {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

/** BaseEdge 的轻封装（受控描边色，选中态高亮）。 */
function BaseEdgePath({
  id,
  path,
  selected,
}: {
  id: string;
  path: string;
  selected: boolean;
}) {
  return (
    <path
      id={id}
      d={path}
      fill="none"
      stroke={selected ? "var(--sd-link, #1a71ff)" : "var(--sd-line, #a8b3cf)"}
      strokeWidth={selected ? 2 : 1.5}
    />
  );
}

const edgeTypes = { sopCondition: SopConditionEdge };

// ---------------------------------------------------------------------------
// 历史栈（结构操作撤销/重做）
// ---------------------------------------------------------------------------

interface HistoryState {
  past: SopGraph[];
  future: SopGraph[];
}

const HISTORY_LIMIT = 50;

function useHistory() {
  const ref = useRef<HistoryState>({ past: [], future: [] });
  const [, force] = useState(0);

  const push = useCallback((snapshot: SopGraph) => {
    ref.current.past.push({
      nodes: snapshot.nodes.map((n) => ({ ...n })),
      edges: snapshot.edges.map((e) => ({ ...e })),
    });
    if (ref.current.past.length > HISTORY_LIMIT) {
      ref.current.past.shift();
    }
    ref.current.future = [];
    force((v) => v + 1);
  }, []);

  const undo = useCallback((): SopGraph | null => {
    const prev = ref.current.past.pop();
    if (!prev) return null;
    ref.current.future.push(prev);
    force((v) => v + 1);
    return prev;
  }, []);

  const redo = useCallback((): SopGraph | null => {
    const next = ref.current.future.pop();
    if (!next) return null;
    ref.current.past.push(next);
    force((v) => v + 1);
    return next;
  }, []);

  const canUndo = ref.current.past.length > 0;
  const canRedo = ref.current.future.length > 0;
  return { push, undo, redo, canUndo, canRedo };
}

// ---------------------------------------------------------------------------
// 主画布
// ---------------------------------------------------------------------------

export interface SopFlowSavePayload {
  nodes: ReturnType<typeof flowToSop>["nodes"];
  edges: ReturnType<typeof flowToSop>["edges"];
  slots: SopSlot[];
}

export interface SopFlowCanvasProps {
  sop: SopRecord;
  readOnly?: boolean;
  onSave?: (payload: SopFlowSavePayload) => Promise<void> | void;
}

function CanvasInner({ sop, readOnly = false, onSave }: SopFlowCanvasProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { fitView } = useReactFlow();
  const initial = useMemo(
    () => layoutInitial(sop),
    // 仅初始化一次；后续受控更新走 setNodes/setEdges
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState<SopFlowNode>(
    initial.nodes,
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const [slots, setSlots] = useState<SopSlot[]>([...(sop.slots ?? [])]);
  const [selected, setSelected] = useState<{
    kind: "node" | "edge";
    id: string;
  } | null>(null);
  const [saving, setSaving] = useState(false);
  const history = useHistory();

  // ---- 工具条动作 ----

  const addNode = useCallback(() => {
    history.push({ nodes, edges });
    const id = nextNodeId(nodes.map((n) => n.id));
    const maxY = nodes.reduce((acc, n) => Math.max(acc, n.position.y), 0);
    const newNode: SopFlowNode = {
      id,
      type: "sopNode",
      position: { x: 120, y: maxY + 152 },
      data: { title: "", instruction: "", expectedOutcome: "", tools: [], seq: nodes.length + 1 },
    };
    setNodes((nds) => [...nds, newNode]);
    setSelected({ kind: "node", id });
  }, [edges, history, nodes, setNodes]);

  const deleteSelected = useCallback(() => {
    if (!selected || readOnly) return;
    history.push({ nodes, edges });
    if (selected.kind === "node") {
      setNodes((nds) => nds.filter((n) => n.id !== selected.id));
      setEdges((eds) =>
        eds.filter((e) => e.source !== selected.id && e.target !== selected.id),
      );
    } else {
      setEdges((eds) => eds.filter((e) => e.id !== selected.id));
    }
    setSelected(null);
  }, [edges, history, nodes, readOnly, selected, setEdges, setNodes]);

  const onConnect = useCallback(
    (connection: Connection) => {
      history.push({ nodes, edges });
      setEdges((eds) =>
        addEdge(
          { ...connection, type: "sopCondition", label: "" },
          eds,
        ),
      );
    },
    [edges, history, setEdges],
  );

  const autoLayout = useCallback(() => {
    history.push({ nodes, edges });
    const laid = withSeqs(layoutSopGraph({ nodes, edges }));
    setNodes(laid.nodes);
    requestAnimationFrame(() => fitView({ padding: 0.15, duration: 300 }));
  }, [edges, fitView, history, nodes, setNodes]);

  const applyHistory = useCallback(
    (snapshot: SopGraph | null) => {
      if (!snapshot) return;
      setNodes(snapshot.nodes);
      setEdges(snapshot.edges);
    },
    [setEdges, setNodes],
  );

  const undo = useCallback(() => {
    applyHistory(history.undo());
  }, [applyHistory, history]);

  const redo = useCallback(() => {
    applyHistory(history.redo());
  }, [applyHistory, history]);

  // ---- 属性面板字段提交 ----

  const updateNodeData = useCallback(
    (id: string, patch: Partial<SopNodeData>) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === id
            ? { ...node, data: { ...node.data, ...patch } }
            : node,
        ),
      );
    },
    [setNodes],
  );

  const updateEdgeLabel = useCallback(
    (id: string, label: string) => {
      setEdges((eds) =>
        eds.map((edge) =>
          edge.id === id ? { ...edge, label } : edge,
        ),
      );
    },
    [setEdges],
  );

  // ---- 槽位编辑 ----

  const updateSlot = useCallback(
    (index: number, patch: Partial<SopSlot>) => {
      setSlots((prev) =>
        prev.map((slot, i) => (i === index ? { ...slot, ...patch } : slot)),
      );
    },
    [],
  );

  const removeSlot = useCallback((index: number) => {
    setSlots((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const addSlot = useCallback(() => {
    setSlots((prev) => [
      ...prev,
      { key: `slot_${prev.length + 1}`, label: "", required: false, ask_prompt: "" },
    ]);
  }, []);

  // ---- 保存 ----

  const handleSave = useCallback(async () => {
    const graph = { nodes, edges };
    const validation = validateSopGraph(graph);
    if (validation.errors.length > 0) {
      // 校验错误前置暴露（阻断保存，不产生脏数据）
      message.error(validation.errors.join("；"));
      return;
    }
    const payload = flowToSop(nodes, edges);
    setSaving(true);
    try {
      await onSave?.({ ...payload, slots });
    } finally {
      setSaving(false);
    }
  }, [edges, message, nodes, onSave, slots]);

  // ---- 选中对象投影 ----

  const selectedNode =
    selected?.kind === "node"
      ? nodes.find((n) => n.id === selected.id) ?? null
      : null;
  const selectedEdge =
    selected?.kind === "edge"
      ? edges.find((e) => e.id === selected.id) ?? null
      : null;

  const toolButtonStyle = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  } as const;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        border: "0.5px solid var(--sd-line, #e3e7f1)",
        borderRadius: 14,
        overflow: "hidden",
        background: "var(--sd-bg, #fcfcfc)",
      }}
    >
      {/* 工具条（编辑态） */}
      {!readOnly ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 16px",
            borderBottom: "0.5px solid var(--sd-line, #e3e7f1)",
            background: "var(--sd-card, #fff)",
            flexWrap: "wrap",
          }}
        >
          <Button size="small" style={toolButtonStyle} onClick={addNode}>
            <Plus size={14} />
            {t("staffdeck.canvas.addNode", "添加步骤")}
          </Button>
          <Tooltip title={t("staffdeck.canvas.autoLayout", "自动整理（dagre 分层）")}>
            <Button size="small" style={toolButtonStyle} onClick={autoLayout}>
              <LayoutTemplate size={14} />
              {t("staffdeck.canvas.layout", "自动整理")}
            </Button>
          </Tooltip>
          <Tooltip title={t("staffdeck.canvas.undo", "撤销")}>
            <Button
              size="small"
              style={toolButtonStyle}
              disabled={!history.canUndo}
              onClick={undo}
            >
              <Undo2 size={14} />
            </Button>
          </Tooltip>
          <Tooltip title={t("staffdeck.canvas.redo", "重做")}>
            <Button
              size="small"
              style={toolButtonStyle}
              disabled={!history.canRedo}
              onClick={redo}
            >
              <Redo2 size={14} />
            </Button>
          </Tooltip>
          <Tooltip title={t("staffdeck.canvas.fitView", "适配视图")}>
            <Button
              size="small"
              style={toolButtonStyle}
              onClick={() => fitView({ padding: 0.15, duration: 300 })}
            >
              <ArrowLeftRight size={14} />
            </Button>
          </Tooltip>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <Popconfirm
              title={t("staffdeck.canvas.deleteConfirm", "删除选中对象？")}
              onConfirm={deleteSelected}
              disabled={!selected || readOnly}
            >
              <Button
                size="small"
                danger
                disabled={!selected}
                style={toolButtonStyle}
              >
                {t("staffdeck.canvas.delete", "删除")}
              </Button>
            </Popconfirm>
            <Button
              size="small"
              type="primary"
              style={{
                ...toolButtonStyle,
                background: "var(--sd-ink, #18181a)",
              }}
              loading={saving}
              onClick={() => void handleSave()}
            >
              <Save size={14} />
              {t("staffdeck.canvas.save", "保存")}
            </Button>
          </div>
        </div>
      ) : null}

      {/* 画布 + 属性面板 */}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <div style={{ flex: 1, minHeight: 0 }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={readOnly ? undefined : onConnect}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            elementsSelectable
            onNodeClick={(_, node) => setSelected({ kind: "node", id: node.id })}
            onEdgeClick={(_, edge) => setSelected({ kind: "edge", id: edge.id })}
            onPaneClick={() => setSelected(null)}
            onNodeDragStart={() => {
              // 拖动前快照入栈（撤销语义：回到拖动前位置）
              history.push({ nodes, edges });
            }}
            onNodeDragStop={() => {
              setNodes(withSeqs({ nodes, edges }).nodes);
            }}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1}
              color="rgba(227, 231, 241, 0.9)"
            />
            <Controls showInteractive={!readOnly} />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>

        {/* 属性面板 */}
        <div
          style={{
            width: 300,
            flexShrink: 0,
            borderLeft: "0.5px solid var(--sd-line, #e3e7f1)",
            background: "var(--sd-card, #fff)",
            padding: "14px 16px",
            overflowY: "auto",
          }}
        >
          {selectedNode ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--sd-ink, #18181a)" }}>
                {t("staffdeck.canvas.nodePanel", "步骤属性")}
              </div>
              <label style={panelLabel}>
                {t("staffdeck.canvas.nodeTitle", "标题")}
              </label>
              <Input
                value={selectedNode.data.title}
                disabled={readOnly}
                onChange={(e) =>
                  updateNodeData(selectedNode.id, { title: e.target.value })
                }
              />
              <label style={panelLabel}>
                {t("staffdeck.canvas.nodeInstruction", "执行指令")}
              </label>
              <Input.TextArea
                rows={4}
                value={selectedNode.data.instruction ?? ""}
                disabled={readOnly}
                onChange={(e) =>
                  updateNodeData(selectedNode.id, {
                    instruction: e.target.value,
                  })
                }
              />
              <label style={panelLabel}>
                {t("staffdeck.canvas.nodeOutcome", "验收要点")}
              </label>
              <Input.TextArea
                rows={3}
                value={selectedNode.data.expectedOutcome ?? ""}
                disabled={readOnly}
                onChange={(e) =>
                  updateNodeData(selectedNode.id, {
                    expectedOutcome: e.target.value,
                  })
                }
              />
              <label style={panelLabel}>
                {t("staffdeck.canvas.nodeTools", "工具（逗号分隔）")}
              </label>
              <Input
                value={(selectedNode.data.tools ?? []).join(", ")}
                disabled={readOnly}
                onChange={(e) =>
                  updateNodeData(selectedNode.id, {
                    tools: e.target.value
                      .split(/[,，]/)
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
              />
            </div>
          ) : selectedEdge ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--sd-ink, #18181a)" }}>
                {t("staffdeck.canvas.edgePanel", "流转条件")}
              </div>
              <div style={{ fontSize: 12, color: "var(--sd-text-3, #858b9c)" }}>
                {selectedEdge.source} → {selectedEdge.target}
              </div>
              <Input
                value={typeof selectedEdge.label === "string" ? selectedEdge.label : ""}
                disabled={readOnly}
                placeholder={t(
                  "staffdeck.canvas.edgeConditionHint",
                  "如：客户确认后 / 金额 > 1 万",
                )}
                onChange={(e) => updateEdgeLabel(selectedEdge.id, e.target.value)}
              />
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--sd-ink, #18181a)" }}>
                {t("staffdeck.canvas.metaPanel", "SOP 信息")}
              </div>
              <div style={{ fontSize: 12, color: "var(--sd-text-2, #757f9c)" }}>
                {sop.goal || sop.description || "—"}
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--sd-ink, #18181a)", marginTop: 8 }}>
                {t("staffdeck.canvas.slots", "槽位")}
              </div>
              {slots.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t("staffdeck.canvas.noSlots", "无槽位")}
                />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {slots.map((slot, index) => (
                    <div
                      key={`${slot.key}-${index}`}
                      style={{
                        border: "0.5px solid var(--sd-line, #e3e7f1)",
                        borderRadius: 10,
                        padding: 8,
                        display: "flex",
                        flexDirection: "column",
                        gap: 6,
                      }}
                    >
                      <div style={{ display: "flex", gap: 6 }}>
                        <Input
                          size="small"
                          value={slot.key}
                          disabled={readOnly}
                          placeholder="key"
                          onChange={(e) =>
                            updateSlot(index, { key: e.target.value })
                          }
                        />
                        <Input
                          size="small"
                          value={slot.label ?? ""}
                          disabled={readOnly}
                          placeholder={t("staffdeck.canvas.slotLabel", "名称")}
                          onChange={(e) =>
                            updateSlot(index, { label: e.target.value })
                          }
                        />
                        {!readOnly ? (
                          <Button
                            size="small"
                            type="text"
                            danger
                            onClick={() => removeSlot(index)}
                          >
                            ✕
                          </Button>
                        ) : null}
                      </div>
                      <Input
                        size="small"
                        value={slot.ask_prompt ?? ""}
                        disabled={readOnly}
                        placeholder={t(
                          "staffdeck.canvas.slotAskPrompt",
                          "追问话术"
                        )}
                        onChange={(e) =>
                          updateSlot(index, { ask_prompt: e.target.value })
                        }
                      />
                      <label
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          fontSize: 12,
                          color: "var(--sd-text-2, #757f9c)",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={Boolean(slot.required)}
                          disabled={readOnly}
                          onChange={(e) =>
                            updateSlot(index, { required: e.target.checked })
                          }
                        />
                        {t("staffdeck.canvas.slotRequired", "必填")}
                      </label>
                    </div>
                  ))}
                </div>
              )}
              {!readOnly ? (
                <Button
                  size="small"
                  style={toolButtonStyle}
                  onClick={addSlot}
                >
                  <Plus size={14} />
                  {t("staffdeck.canvas.addSlot", "添加槽位")}
                </Button>
              ) : null}
              <div style={{ fontSize: 12, color: "var(--sd-text-3, #858b9c)" }}>
                {t(
                  "staffdeck.canvas.hint",
                  "选中节点/连线后在此编辑；拖拽底部锚点连线表达流转。"
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const panelLabel = {
  fontSize: 12,
  color: "var(--sd-text-2, #757f9c)",
} as const;

/** 按节点 y 坐标升序重排序号（结构变更后归一化）。 */
function withSeqs(graph: SopGraph): SopGraph {
  const ordered = [...graph.nodes].sort(
    (a, b) => a.position.y - b.position.y,
  );
  const seqById = new Map(ordered.map((node, index) => [node.id, index + 1]));
  return {
    ...graph,
    nodes: graph.nodes.map((node) => ({
      ...node,
      data: { ...node.data, seq: seqById.get(node.id) ?? 0 },
    })),
  };
}

/** 初次挂载：转换 + dagre 归位 + 序号归一化（纯函数，无副作用）。 */
function layoutInitial(sop: SopRecord): SopGraph {
  return withSeqs(layoutSopGraph(sopToFlow(sop.nodes ?? [], sop.edges ?? [])));
}

export function SopFlowCanvas(props: SopFlowCanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}
