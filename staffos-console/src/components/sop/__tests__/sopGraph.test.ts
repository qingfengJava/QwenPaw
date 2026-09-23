/**
 * sop/sopGraph.test.ts — SOP ↔ React Flow 桥接层单测。
 *
 * 覆盖：双向转换 roundtrip、dagre 布局不丢节点、校验器
 * （errors 阻断 / warnings 提示）、nextNodeId 生成。
 */
import { describe, expect, it } from "vitest";

import type { SopEdge, SopNode } from "@/api/modules/admin";
import {
  flowToSop,
  layoutSopGraph,
  nextNodeId,
  sopToFlow,
  validateSopGraph,
} from "../sopGraph";

const NODES: SopNode[] = [
  {
    id: "n1",
    title: "收集需求",
    instruction: "向用户确认目标",
    expected_outcome: "需求清单",
    tools: ["ask_user"],
  },
  { id: "n2", title: "执行任务", instruction: "按清单执行" },
  { id: "n3", title: "交付汇报", expected_outcome: "用户确认" },
];

const EDGES: SopEdge[] = [
  { from: "n1", to: "n2", condition: "需求明确" },
  { from: "n2", to: "n3" },
];

describe("sopToFlow / flowToSop", () => {
  it("roundtrip 保留节点业务字段与边条件", () => {
    const graph = sopToFlow(NODES, EDGES);
    expect(graph.nodes).toHaveLength(3);
    expect(graph.edges).toHaveLength(2);
    expect(graph.nodes[0].type).toBe("sopNode");
    expect(graph.nodes[0].data.title).toBe("收集需求");
    expect(graph.nodes[0].data.tools).toEqual(["ask_user"]);
    expect(graph.edges[0].source).toBe("n1");
    expect(graph.edges[0].label).toBe("需求明确");

    const back = flowToSop(graph.nodes, graph.edges);
    expect(back.nodes.map((n) => n.id)).toEqual(["n1", "n2", "n3"]);
    expect(back.nodes[0]).toEqual({
      id: "n1",
      title: "收集需求",
      instruction: "向用户确认目标",
      expected_outcome: "需求清单",
      tools: ["ask_user"],
    });
    expect(back.edges[0]).toEqual({
      from: "n1",
      to: "n2",
      condition: "需求明确",
    });
    // 空条件不落字段
    expect(back.edges[1].condition).toBeUndefined();
  });

  it("flowToSop 按 y 坐标升序输出（竖向步骤链语义）", () => {
    const graph = sopToFlow(NODES, EDGES);
    const shuffled = [
      { ...graph.nodes[2], position: { x: 0, y: 200 } },
      { ...graph.nodes[0], position: { x: 0, y: 10 } },
      { ...graph.nodes[1], position: { x: 0, y: 100 } },
    ];
    const back = flowToSop(shuffled, []);
    expect(back.nodes.map((n) => n.id)).toEqual(["n1", "n2", "n3"]);
  });
});

describe("layoutSopGraph (dagre)", () => {
  it("不丢节点且产出坐标", () => {
    const graph = sopToFlow(NODES, EDGES);
    const laid = layoutSopGraph(graph);
    expect(laid.nodes).toHaveLength(3);
    for (const node of laid.nodes) {
      expect(Number.isFinite(node.position.x)).toBe(true);
      expect(Number.isFinite(node.position.y)).toBe(true);
    }
    // 有边的两端节点 y 分层：n1 在 n2 之上（TB）
    const byId = new Map(laid.nodes.map((n) => [n.id, n.position]));
    expect(byId.get("n1")!.y).toBeLessThan(byId.get("n2")!.y);
    expect(byId.get("n2")!.y).toBeLessThan(byId.get("n3")!.y);
  });

  it("空图原样返回", () => {
    expect(layoutSopGraph({ nodes: [], edges: [] })).toEqual({
      nodes: [],
      edges: [],
    });
  });
});

describe("validateSopGraph", () => {
  it("空标题报 error，缺端点连线报 error", () => {
    const graph = sopToFlow(
      [{ id: "n1", title: " " }],
      [{ from: "n1", to: "ghost" }],
    );
    const result = validateSopGraph(graph);
    expect(result.errors.length).toBeGreaterThanOrEqual(2);
    expect(result.errors.join()).toContain("标题");
    expect(result.errors.join()).toContain("缺失的端点");
  });

  it("条件缺失与孤立节点为 warning 不阻断", () => {
    const graph = sopToFlow(
      [
        { id: "n1", title: "A" },
        { id: "n2", title: "B" },
      ],
      [{ from: "n1", to: "n2" }],
    );
    const result = validateSopGraph(graph);
    expect(result.errors).toHaveLength(0);
    expect(result.warnings.join()).toContain("流转条件");
  });
});

describe("nextNodeId", () => {
  it("避开现有 id 递增", () => {
    expect(nextNodeId(["n1", "n2"])).toBe("n3");
    expect(nextNodeId(["n1", "n3"])).toBe("n2");
    expect(nextNodeId([])).toBe("n1");
  });
});
