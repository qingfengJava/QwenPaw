/**
 * Tests for reorder.ts: full-list swap computation for the console
 * card move-up/move-down actions (subset-filter safe, grouping aware).
 */
import { describe, expect, it } from "vitest";
import type { DigitalEmployee } from "@/api/modules/employeeRegistry";
import { computeReorder, respectsAgentGrouping } from "./reorder";

function row(
  agentId: string,
  overrides: Partial<DigitalEmployee> = {},
): DigitalEmployee {
  return {
    agent_id: agentId,
    entity_kind: "agent",
    entity_id: agentId,
    name: agentId,
    title: "",
    description: "",
    icon: "",
    enabled: true,
    pinned: false,
    startup_status: "running",
    lifecycle_status: "published",
    mode: "",
    backend: "qwenpaw",
    model_label: "qwen-max",
    department_id: null,
    department_name: "",
    visibility: "org",
    governed: false,
    granted_departments: [],
    granted_department_names: [],
    member_count: 0,
    members: [],
    usage_count: 0,
    is_builtin: false,
    tags: [],
    workspace_dir: `/ws/${agentId}`,
    available_in_chat: true,
    managed_by_app: null,
    backend_capabilities: {},
    owner_id: null,
    usable: true,
    ...overrides,
  };
}

describe("computeReorder", () => {
  const allRows = [
    row("default", { pinned: true }),
    row("agent_a"),
    row("agent_b"),
    row("agent_c"),
    // Draft: no runtime profile, must never enter the submitted list.
    row("expert_draft", { startup_status: undefined }),
  ];
  // Filtered view hides agent_a (e.g. department filter active).
  const visibleRows = [
    allRows[0],
    allRows[2],
    allRows[3],
    allRows[4],
  ];

  it("swaps against the full list while locating the neighbor in the filtered view", () => {
    // agent_a is hidden by the active filter; in the filtered view the
    // neighbor above agent_c is agent_b, so the swap happens in the full
    // list between agent_b and agent_c while default stays first.
    const result = computeReorder(
      allRows,
      visibleRows,
      allRows[3],
      -1,
    );

    expect(result.ok).toBe(true);
    expect(result.violatesGrouping).toBe(false);
    // Full list keeps every configured id exactly once, draft excluded.
    expect(result.ids).toEqual([
      "default",
      "agent_a",
      "agent_c",
      "agent_b",
    ]);
  });

  it("returns ok:false when the row is at the view boundary", () => {
    expect(computeReorder(allRows, visibleRows, allRows[0], -1).ok).toBe(
      false,
    );
    expect(computeReorder(allRows, visibleRows, allRows[3], 1).ok).toBe(
      false,
    );
  });

  it("flags swaps that would break the default/pinned grouping", () => {
    const pinned = [
      row("default", { pinned: true }),
      row("agent_pin", { pinned: true }),
      row("agent_x"),
    ];
    // agent_pin moved down would land after the unpinned agent_x.
    const result = computeReorder(pinned, pinned, pinned[1], 1);

    expect(result.ok).toBe(true);
    expect(result.violatesGrouping).toBe(true);
  });
});

describe("respectsAgentGrouping", () => {
  const rows = [
    row("default", { pinned: true }),
    row("p1", { pinned: true }),
    row("r1"),
  ];

  it("accepts default-first with pinned before regular", () => {
    expect(respectsAgentGrouping(rows, ["default", "p1", "r1"])).toBe(true);
  });

  it("rejects default that is not first", () => {
    expect(respectsAgentGrouping(rows, ["p1", "default", "r1"])).toBe(false);
  });

  it("rejects pinned agents after regular ones", () => {
    expect(respectsAgentGrouping(rows, ["default", "r1", "p1"])).toBe(false);
  });
});
