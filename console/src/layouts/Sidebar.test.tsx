// @vitest-environment jsdom
/**
 * Sidebar.test.tsx — regression for A#84552933 (missing apps nav entry)
 *
 * The "Apps" (应用中心) navigation entry must be present in the sidebar's
 * builtin menu. We test the builtinMenu data directly because the full
 * Sidebar component has heavy dependencies.
 *
 * Rewritten for the fork IA: the marketplace entry keeps its pre-M4 id
 * "core.app-center" and lives in the "primary.platform" location (M4 will
 * rename it to "core.marketplace" together with the implementation).
 *
 * Strategy:
 *   1. Verify BUILTIN_MENU contains an entry with id "core.app-center".
 *   2. Verify its location is "primary.platform" so it shows in sidebar.
 *   3. Verify its label resolves to a non-empty string (i18n).
 *   4. Verify it has a route defined for navigation.
 */
import { describe, expect, it, vi } from "vitest";

// Explicit stubs: builtinMenu and its registry/ helpers pull these icons.
// (Proxy-based wildcard mocks are not supported by this vitest version.)
vi.mock("@agentscope-ai/icons", () => {
  const stub = () => null;
  return {
    SparkAgentLine: stub,
    SparkBrowseLine: stub,
    SparkDataLine: stub,
    SparkDateLine: stub,
    SparkDebugLine: stub,
    SparkEmailLine: stub,
    SparkInternetLine: stub,
    SparkMicLine: stub,
    SparkModePlazaLine: stub,
    SparkMyApplicationLine: stub,
    SparkOtherLine: stub,
    SparkPluginLine: stub,
    SparkSaveLine: stub,
    SparkWifiLine: stub,
  };
});
vi.mock("lucide-react", () => {
  const stub = () => null;
  return {
    BookOpen: stub,
    Bot: stub,
    Gauge: stub,
    KeyRound: stub,
    LayoutDashboard: stub,
    ListTodo: stub,
    ScrollText: stub,
    ShieldCheck: stub,
    Users: stub,
    UsersRound: stub,
  };
});
vi.mock("i18next", () => ({
  default: { t: (key: string, fallback?: string) => fallback ?? key },
  t: (key: string, fallback?: string) => fallback ?? key,
}));

import { BUILTIN_MENU } from "./registry/builtinMenu";

describe("Sidebar navigation — A#84552933 应用导航入口", () => {
  it("contains the app-center entry in platform menu", () => {
    const appsEntry = BUILTIN_MENU.find(
      (item) => item.id === "core.app-center",
    );
    expect(appsEntry).toBeDefined();
    expect(appsEntry!.location).toBe("primary.platform");
  });

  it("app-center entry has a valid route for navigation", () => {
    const appsEntry = BUILTIN_MENU.find(
      (item) => item.id === "core.app-center",
    );
    expect(appsEntry).toBeDefined();
    expect(appsEntry!.route).toBeTruthy();
    expect(appsEntry!.route).toBe("core.app-center");
  });

  it("app-center label resolves to a non-empty string", () => {
    const appsEntry = BUILTIN_MENU.find(
      (item) => item.id === "core.app-center",
    );
    expect(appsEntry).toBeDefined();
    // label is a function () => string (navLabel pattern)
    const label =
      typeof appsEntry!.label === "function"
        ? (appsEntry!.label as () => string)()
        : String(appsEntry!.label);
    expect(label).toBeTruthy();
    expect(label.length).toBeGreaterThan(0);
  });

  it("app-center entry has an icon defined", () => {
    const appsEntry = BUILTIN_MENU.find(
      (item) => item.id === "core.app-center",
    );
    expect(appsEntry).toBeDefined();
    expect(appsEntry!.icon).toBeDefined();
  });

  it("platform menu has at least one entry for core navigation", () => {
    const platform = BUILTIN_MENU.filter(
      (item) => item.location === "primary.platform",
    );
    // Must have inbox and app-center at minimum
    const ids = platform.map((item) => item.id);
    expect(ids).toContain("core.inbox");
    expect(ids).toContain("core.app-center");
  });
});
