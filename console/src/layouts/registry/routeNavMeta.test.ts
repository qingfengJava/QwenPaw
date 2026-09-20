/**
 * routeNavMeta.test.ts — 详情页/重定向路由的标签化判定。
 *
 * 两类回归必须钉住：
 * 1. 重定向路由（只渲染 <Navigate>）绝不能建标签，否则标签栏挂满一点就跳走的死标签；
 * 2. 详情型标签必须按 collapseSegments 归一，且判定顺序要先于菜单前缀匹配，
 *    否则 /agents/a1 会被 /agents 菜单叶子吞成「数字员工」并每人一张新标签。
 */
import { describe, expect, it } from "vitest";
import {
  NON_TABBABLE_ROUTE_IDS,
  findRouteNavMeta,
  isNonTabbableRoute,
  resolveTabbable,
} from "./routeNavMeta";
import { buildNavIndex } from "./navModel";
import type { NavIndex } from "./navModel";
import type { MenuItem } from "../../plugins/registry/types";

function item(seed: Partial<MenuItem> & { id: string; label: string }): MenuItem {
  return seed as MenuItem;
}

const NAV_INDEX: NavIndex = buildNavIndex(
  [
    item({ id: "m.agents", label: "数字员工", route: "/agents" }),
    item({ id: "m.users", label: "用户管理", route: "/admin/users" }),
  ],
  [],
);

describe("isNonTabbableRoute", () => {
  it("重定向路由在排除名单内", () => {
    expect(isNonTabbableRoute("core.chat")).toBe(true);
    expect(isNonTabbableRoute("core.admin-experts")).toBe(true);
    expect(NON_TABBABLE_ROUTE_IDS.size).toBeGreaterThan(10);
  });

  it("undefined 与未登记路由不在名单内", () => {
    expect(isNonTabbableRoute(undefined)).toBe(false);
    expect(isNonTabbableRoute("core.workbench")).toBe(false);
  });
});

describe("findRouteNavMeta", () => {
  it("员工详情声明为动态标签并折叠到 2 段", () => {
    const meta = findRouteNavMeta("core.agent-detail");
    expect(meta?.dynamic).toBe(true);
    expect(meta?.collapseSegments).toBe(2);
    expect(meta?.parentPath).toBe("/agents");
  });

  it("菜单可达的路由不需要额外声明", () => {
    expect(findRouteNavMeta("core.admin-users")).toBeUndefined();
  });
});

describe("resolveTabbable", () => {
  it("排除名单优先：重定向路由即使能命中菜单也不建标签", () => {
    expect(resolveTabbable("/agents/a1/chat", "core.chat", NAV_INDEX)).toBeUndefined();
  });

  it("菜单叶子精确命中 → menu 型标签", () => {
    const hit = resolveTabbable("/admin/users", "core.admin-users", NAV_INDEX);
    expect(hit?.kind).toBe("menu");
    expect(hit?.key).toBe("/admin/users");
    expect(hit?.navEntry?.label).toBe("用户管理");
  });

  it("详情型优先于菜单前缀：/agents/a1 不被 /agents 吞掉", () => {
    const hit = resolveTabbable("/agents/a1", "core.agent-detail", NAV_INDEX);
    expect(hit?.kind).toBe("detail");
    expect(hit?.navEntry).toBeUndefined();
  });

  it("同一员工的子导航折叠成一张标签", () => {
    const chat = resolveTabbable("/agents/a1/chat", "core.agent-detail", NAV_INDEX);
    const files = resolveTabbable("/agents/a1/files", "core.agent-detail", NAV_INDEX);
    expect(chat?.key).toBe("/agents/a1");
    expect(files?.key).toBe("/agents/a1");
  });

  it("执行记录折叠到 5 段：每个定时任务一张标签，任务内子路径不炸标签", () => {
    const a = resolveTabbable(
      "/agents/manage/e1/schedules/j1/runs",
      "core.agents-manage-schedule-runs",
      NAV_INDEX,
    );
    const aDetail = resolveTabbable(
      "/agents/manage/e1/schedules/j1/runs/9527",
      "core.agents-manage-schedule-runs",
      NAV_INDEX,
    );
    const b = resolveTabbable(
      "/agents/manage/e1/schedules/j2/runs",
      "core.agents-manage-schedule-runs",
      NAV_INDEX,
    );
    expect(a?.key).toBe("/agents/manage/e1/schedules/j1");
    // 同一任务的更深层路径仍复用这张标签
    expect(aDetail?.key).toBe("/agents/manage/e1/schedules/j1");
    // 不同任务各自一张
    expect(b?.key).toBe("/agents/manage/e1/schedules/j2");
  });

  it("菜单页子路径复用父菜单名，key 取完整路径", () => {
    const hit = resolveTabbable("/admin/users/detail/9", "some.unknown.route", NAV_INDEX);
    expect(hit?.kind).toBe("menu");
    expect(hit?.navEntry?.label).toBe("用户管理");
    expect(hit?.key).toBe("/admin/users/detail/9");
  });

  it("菜单与声明都不命中 → 不建标签（404 等兜底页）", () => {
    expect(resolveTabbable("/nowhere", "core.unknown", NAV_INDEX)).toBeUndefined();
  });
});
