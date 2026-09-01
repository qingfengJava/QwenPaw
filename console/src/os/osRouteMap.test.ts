import { describe, expect, it } from "vitest";
import { baseFromRoutePath, pathToRouteId } from "./osRouteMap";

const routes = [
  { id: "core.chat", path: "/chat/*", source: "core" },
  { id: "core.app-center", path: "/apps", source: "core" },
  {
    id: "core.app-center.embed",
    path: "/apps/:appId",
    source: "core",
  },
  { id: "plugin.office", path: "/apps/office", source: "office" },
  {
    id: "plugin.office.settings",
    path: "/apps/office/settings",
    source: "office",
  },
  { id: "plugin.review", path: "/apps/review", source: "review" },
];

describe("osRouteMap", () => {
  it("removes splats and parameters from window bases", () => {
    expect(baseFromRoutePath("/chat/*")).toBe("/chat");
    expect(baseFromRoutePath("/apps/:appId")).toBe("/apps");
  });

  it("routes dynamic children to their owning app", () => {
    expect(pathToRouteId("/chat/session-1", routes)).toBe("core.chat");
  });

  it("prefers a concrete PawApp over the aggregate apps route", () => {
    expect(pathToRouteId("/apps/office", routes)).toBe("plugin.office");
    expect(pathToRouteId("/apps/review", routes)).toBe("plugin.review");
  });

  it("maps secondary PawApp routes to the bundle window", () => {
    expect(pathToRouteId("/apps/office/settings", routes)).toBe(
      "plugin.office",
    );
  });

  it("falls back to App Center for unknown PawApp deep links", () => {
    expect(pathToRouteId("/apps/unknown", routes)).toBe(
      "core.app-center.embed",
    );
  });

  it("does not map unrelated paths to the root route", () => {
    expect(
      pathToRouteId("/not-registered", [
        ...routes,
        { id: "core.root", path: "/", source: "core" },
      ]),
    ).toBeUndefined();
  });

  it("keeps root navigation inside the current OS window", () => {
    expect(
      pathToRouteId("/", [
        ...routes,
        { id: "core.root", path: "/", source: "core" },
      ]),
    ).toBeUndefined();
  });

  it("prefers static agent sub-routes over the parameterized detail route", () => {
    // /agents/manage 静态段必须胜过 /agents/:aid/*（否则管理页被当成员工详情，
    // 桥接开错窗口；批次6注册 /agents/manage 系路由的前置保障）。
    const agentRoutes = [
      { id: "core.agents", path: "/agents", source: "core" },
      { id: "core.agent-detail", path: "/agents/:aid/*", source: "core" },
      { id: "core.agents-manage", path: "/agents/manage", source: "core" },
    ];
    expect(pathToRouteId("/agents/manage", agentRoutes)).toBe(
      "core.agents-manage",
    );
    expect(pathToRouteId("/agents/ops-1/chat", agentRoutes)).toBe(
      "core.agent-detail",
    );
    expect(pathToRouteId("/agents", agentRoutes)).toBe("core.agents");
  });
});
