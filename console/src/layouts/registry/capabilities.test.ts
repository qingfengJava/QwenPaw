import { describe, expect, it } from "vitest";
import { filterTabsForAgentCapabilities } from "./capabilities";

interface TestTab {
  key: string;
}

const ALL_TABS: TestTab[] = [
  { key: "overview" },
  { key: "chat" },
  { key: "sessions" },
  { key: "cron-jobs" },
  { key: "files" },
  { key: "skills" },
  { key: "tools" },
  { key: "mcp" },
  { key: "acp" },
  { key: "checkpoints" },
  { key: "channels" },
  { key: "config" },
  { key: "stats" },
  { key: "heartbeat" },
];

describe("filterTabsForAgentCapabilities", () => {
  it("returns tabs unchanged when workspace_ui is not false", () => {
    expect(
      filterTabsForAgentCapabilities(ALL_TABS, { workspace_ui: true }),
    ).toBe(ALL_TABS);
    expect(filterTabsForAgentCapabilities(ALL_TABS, undefined)).toBe(ALL_TABS);
  });

  it("hides workspace-only tabs for non-workspace backends", () => {
    const visible = filterTabsForAgentCapabilities(ALL_TABS, {
      workspace_ui: false,
    });
    const keys = visible.map((tab) => tab.key);
    for (const hidden of [
      "files",
      "acp",
      "checkpoints",
      "config",
      "stats",
    ]) {
      expect(keys).not.toContain(hidden);
    }
    // 基本/运维类 Tab 始终保留
    for (const kept of [
      "overview",
      "chat",
      "sessions",
      "cron-jobs",
      "channels",
      "heartbeat",
    ]) {
      expect(keys).toContain(kept);
    }
  });

  it("shows projected skills/tools/mcp when capabilities allow", () => {
    const visible = filterTabsForAgentCapabilities(ALL_TABS, {
      workspace_ui: false,
      qwenpaw_skills_projection: true,
      native_tools_ui: true,
      provider_mcp_discovery: true,
    });
    const keys = visible.map((tab) => tab.key);
    expect(keys).toContain("skills");
    expect(keys).toContain("tools");
    expect(keys).toContain("mcp");
  });

  it("hides skills/tools/mcp without any enabling capability", () => {
    const visible = filterTabsForAgentCapabilities(ALL_TABS, {
      workspace_ui: false,
    });
    const keys = visible.map((tab) => tab.key);
    expect(keys).not.toContain("skills");
    expect(keys).not.toContain("tools");
    expect(keys).not.toContain("mcp");
  });
});
