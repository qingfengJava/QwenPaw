import { describe, expect, it } from "vitest";
import { migrateInstalledToV2 } from "./osPluginStore";
import { OS_APPS } from "./osApps";

describe("migrateInstalledToV2 (persist v1→v2)", () => {
  it("drops retired catalog ids from the persisted install list", () => {
    const result = migrateInstalledToV2({
      installed: ["core.chat", "core.inbox", "core.workspace"],
    });
    // core.chat / core.workspace 已下架（重定向 stub / 死路由），core.inbox 保留
    expect(result.installed).toEqual(["core.inbox"]);
  });

  it("keeps the user's uninstall choices for surviving apps", () => {
    // 用户已卸载 core.channels：交集迁移不自动补装（旧并集会复活它）
    const result = migrateInstalledToV2({
      installed: ["core.inbox"],
    });
    expect(result.installed).toEqual(["core.inbox"]);
    expect(result.installed).not.toContain("core.channels");
  });

  it("falls back to an empty install list for missing/undefined state", () => {
    expect(migrateInstalledToV2(undefined).installed).toEqual([]);
    expect(migrateInstalledToV2({}).installed).toEqual([]);
  });

  it("surviving catalog apps are exactly the current OS_APPS ids", () => {
    const allSurviving = migrateInstalledToV2({
      installed: OS_APPS.map((a) => a.routeId),
    });
    expect(allSurviving.installed).toEqual(OS_APPS.map((a) => a.routeId));
  });
});
