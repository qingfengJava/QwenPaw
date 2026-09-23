/**
 * sop/sopGraph.ts — SOP 结构 ↔ React Flow 图数据的纯函数桥接层。
 *
 * 职责（无 React 依赖，可单测）：
 *  - sopToFlow / flowToSop：双向转换（id 稳定映射；flow 侧 node.id =
 *    SopNode.id，data 承载业务字段；edge.label ↔ edge.condition）；
 *  - layoutSopGraph：dagre 自动布局（TB 自上而下，间距参数化）；
 *  - validateSopGraph：保存前校验（errors 阻断保存，warnings 仅提示）。
 * 保存语义：flowToSop 输出按节点 y 坐标升序排列，保持 SOP「竖向步骤
 * 链」的数组序语义（SopFlowPreview / 后端版本链依赖该序）。
 */
import dagre from "@dagrejs/dagre";
import type { Edge as RFEdge, Node as RFNode } from "@xyflow/react";

import type { SopEdge, SopNode } from "@/api/modules/admin";

/** 画布节点业务载荷。 */
export interface SopNodeData extends Record<string, unknown> {
  title: string;
  instruction?: string;
  expectedOutcome?: string;
  tools: string[];
}

/** 画布节点尺寸常量（与 SopNodeCard 视觉尺寸对齐，供 dagre 使用）。 */
export const SOP_NODE_WIDTH = 248;
export const SOP_NODE_HEIGHT = 104;

export type SopFlowNode = RFNode<SopNodeData>;
export type SopFlowEdge = RFEdge;

export interface SopGraph {
  nodes: SopFlowNode[];
  edges: SopFlowEdge[];
}

// ---------------------------------------------------------------------------
// 双向转换
// ---------------------------------------------------------------------------

export function sopToFlow(
  nodes: SopNode[] = [],
  edges: SopEdge[] = [],
): SopGraph {
  const flowNodes: SopFlowNode[] = nodes.map((node, index) => ({
    id: String(node.id),
    type: "sopNode",
    position: { x: 0, y: index * (SOP_NODE_HEIGHT + 48) },
    data: {
      title: node.title ?? "",
      instruction: node.instruction ?? "",
      expectedOutcome: node.expected_outcome ?? "",
      tools: [...(node.tools ?? [])],
    },
  }));
  const flowEdges: SopFlowEdge[] = edges.map((edge, index) => ({
    id: `e-${edge.from}-${edge.to}-${index}`,
    type: "sopCondition",
    source: String(edge.from),
    target: String(edge.to),
    label: edge.condition ?? "",
  }));
  return { nodes: flowNodes, edges: flowEdges };
}

export function flowToSop(
  nodes: SopFlowNode[],
  edges: SopFlowEdge[],
): { nodes: SopNode[]; edges: SopEdge[] } {
  // 按 y 坐标升序 → SOP 数组序（竖向步骤链语义）
  const ordered = [...nodes].sort((a, b) => a.position.y - b.position.y);
  return {
    nodes: ordered.map((node) => ({
      id: node.id,
      title: String(node.data.title ?? ""),
      instruction: node.data.instruction || undefined,
      expected_outcome: node.data.expectedOutcome || undefined,
      tools: node.data.tools.length > 0 ? [...node.data.tools] : undefined,
    })),
    edges: edges.map((edge) => ({
      from: edge.source,
      to: edge.target,
      condition:
        typeof edge.label === "string" && edge.label.trim()
          ? edge.label
          : undefined,
    })),
  };
}

// ---------------------------------------------------------------------------
// dagre 自动布局（TB 分层）
// ---------------------------------------------------------------------------

export function layoutSopGraph(graph: SopGraph, direction: "TB" | "LR" = "TB"): SopGraph {
  if (graph.nodes.length === 0) return graph;
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    nodesep: 56,
    ranksep: 56,
    marginx: 24,
    marginy: 24,
  });
  for (const node of graph.nodes) {
    g.setNode(node.id, { width: SOP_NODE_WIDTH, height: SOP_NODE_HEIGHT });
  }
  for (const edge of graph.edges) {
    // 悬挂边（端点缺失）跳过，交由 validateSopGraph 报错
    const ids = new Set(graph.nodes.map((n) => n.id));
    if (ids.has(edge.source) && ids.has(edge.target)) {
      g.setEdge(edge.source, edge.target);
    }
  }
  dagre.layout(g);

  const positioned = graph.nodes.map((node) => {
    const laid = g.node(node.id);
    return {
      ...node,
      position: {
        x: laid ? laid.x - SOP_NODE_WIDTH / 2 : node.position.x,
        y: laid ? laid.y - SOP_NODE_HEIGHT / 2 : node.position.y,
      },
    };
  });
  return { nodes: positioned, edges: graph.edges };
}

// ---------------------------------------------------------------------------
// 保存前校验
// ---------------------------------------------------------------------------

export interface SopValidation {
  errors: string[];
  warnings: string[];
}

export function validateSopGraph(graph: SopGraph): SopValidation {
  const errors: string[] = [];
  const warnings: string[] = [];
  const ids = new Set(graph.nodes.map((node) => node.id));

  for (const node of graph.nodes) {
    if (!String(node.data.title ?? "").trim()) {
      errors.push(`节点「${node.id}」标题不能为空`);
    }
  }
  for (const edge of graph.edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) {
      errors.push(
        `连线 ${edge.source} → ${edge.target} 存在缺失的端点，请删除后重连`,
      );
    } else if (typeof edge.label !== "string" || !edge.label.trim()) {
      warnings.push(`连线 ${edge.source} → ${edge.target} 建议补充流转条件`);
    }
  }
  const connected = new Set<string>();
  for (const edge of graph.edges) {
    connected.add(edge.source);
    connected.add(edge.target);
  }
  for (const node of graph.nodes) {
    if (!connected.has(node.id)) {
      warnings.push(`节点「${node.data.title || node.id}」未与任何步骤相连`);
    }
  }
  return { errors, warnings };
}

/** 生成下一个可用的节点 id（n1、n2…，取最小空洞，避开现有 id）。 */
export function nextNodeId(existingIds: Iterable<string>): string {
  const used = new Set(existingIds);
  let index = 1;
  while (used.has(`n${index}`)) {
    index += 1;
  }
  return `n${index}`;
}
