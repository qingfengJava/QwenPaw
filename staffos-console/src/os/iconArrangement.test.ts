import { describe, expect, it } from "vitest";
import type { TFunction } from "i18next";
import { MessageSquare } from "lucide-react";
import { arrangeApps, iconTypeRank } from "./iconArrangement";
import { OS_APPS, STORE_APP, type OsAppDef } from "./osApps";

const pluginApp: OsAppDef = {
  routeId: "plugin.calendar",
  labelKey: "Calendar",
  fallback: "Calendar",
  Icon: MessageSquare,
  accent: "#000",
  defaultW: 600,
  defaultH: 400,
  source: "calendar",
};
const translate = ((key: string, fallback: string) =>
  fallback || key) as unknown as TFunction;

describe("iconArrangement", () => {
  // Fork IA: OS_APPS[0] is "core.agents" (Digital Employees) instead of
  // upstream's "core.chat"; assertions below follow the fork data.
  it("sorts names using translated labels", () => {
    const result = arrangeApps(
      [OS_APPS[0], pluginApp, STORE_APP],
      "name",
      translate,
      "en",
    );
    expect(result.map((app) => app.fallback)).toEqual([
      "App Store",
      "Calendar",
      "Digital Employees",
    ]);
  });

  it("sorts system, core and plugin apps by type", () => {
    expect(iconTypeRank(STORE_APP)).toBeLessThan(iconTypeRank(OS_APPS[0]));
    expect(iconTypeRank(OS_APPS[0])).toBeLessThan(iconTypeRank(pluginApp));
    const result = arrangeApps(
      [pluginApp, OS_APPS[0], STORE_APP],
      "type",
      translate,
      "en",
    );
    expect(result.map((app) => app.routeId)).toEqual([
      "os.store",
      "core.agents",
      "plugin.calendar",
    ]);
  });
});
