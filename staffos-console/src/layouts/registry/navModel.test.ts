/**
 * navModel.test.ts — 导航模型纯函数：面包屑祖先链、最长前缀匹配、标签 key 归一化。
 *
 * 这里是顶部面包屑与多标签页唯一的文案来源判定，回归会同时影响侧栏高亮、
 * 面包屑与标签名，因此重点覆盖「与 Sidebar.activeId 同规则」和「内置 route-id
 * 与动态字面 path 两种菜单都能解析」。
 */
import { describe, expect, it } from "vitest";
import {
  buildNavIndex,
  matchNavEntry,
  matchRouteId,
  normalizePathname,
  normalizeTabKey,
} from "./navModel";
import type { RouteLike } from "./navModel";
import type { MenuItem } from "../../plugins/registry/types";

/**
 * 构造一条中性 MenuItem。`__children` 是动态菜单适配器运行时挂上的字段，
 * 不在公开类型里，因此种子保留宽松形状并整体断言。
 */
type MenuSeed = { id: string; label: string } & Partial<MenuItem> & {
  // 子节点统一由 item() 构造，已经是 MenuItem 形状
  __children?: MenuItem[];
};

function item(seed: MenuSeed): MenuItem {
  return { location: "primary.platform", ...seed } as unknown as MenuItem;
}

/** 内置菜单形状：route 存路由 id，需要靠 routes 解析成 path。 */
const ROUTES: RouteLike[] = [
  { id: "core.workbench", path: "/workbench" },
  { id: "core.agents", path: "/agents" },
  { id: "core.agents-manage", path: "/agents/manage" },
  { id: "core.agent-detail", path: "/agents/:aid/*" },
  { id: "core.admin-users", path: "/admin/users" },
];

const BUILTIN_MENU: MenuItem[] = [
  item({ id: "core.nav-workbench", label: "工作台", route: "core.workbench" }),
  item({
    id: "core.nav-admin",
    label: "平台管理",
    isGroup: true,
    __children: [
      item({ id: "core.nav-admin-users", label: "用户管理", route: "core.admin-users" }),
    ],
  }),
];

/** 后端动态菜单形状：route 直接存字面 path，children 挂在 __children。 */
const DYNAMIC_MENU: MenuItem[] = [
  item({
    id: "kb.dir",
    label: "知识管理",
    isGroup: true,
    __children: [
      item({ id: "kb.base", label: "知识库", route: "/admin/knowledge" }),
    ],
  }),
  item({ id: "kb外链", label: "文档站", route: "/docs", href: "https://example.com" }),
  item({ id: "kb.hidden", label: "隐藏页", route: "/admin/hidden", visible: () => false }),
];

describe("buildNavIndex", () => {
  it("内置菜单：route-id 解析成 path，祖先 label 进 trail", () => {
    const index = buildNavIndex(BUILTIN_MENU, ROUTES);
    const entry = index.byPath.get("/admin/users");
    expect(entry).toBeDefined();
    expect(entry?.label).toBe("用户管理");
    expect(entry?.trail).toEqual(["平台管理"]);
    expect(entry?.menuId).toBe("core.nav-admin-users");
  });

  it("动态菜单：route 为字面 path 时同样可解析", () => {
    const index = buildNavIndex(DYNAMIC_MENU, ROUTES);
    const entry = index.byPath.get("/admin/knowledge");
    expect(entry?.label).toBe("知识库");
    expect(entry?.trail).toEqual(["知识管理"]);
  });

  it("外链、visible()===false 的项不进索引", () => {
    const index = buildNavIndex(DYNAMIC_MENU, ROUTES);
    expect(index.byPath.has("/docs")).toBe(false);
    expect(index.byPath.has("/admin/hidden")).toBe(false);
  });

  it("同一 path 重复注册时先到先得，后注册的插件项不抢走菜单名", () => {
    const dup = [
      item({ id: "a", label: "先注册", route: "/workbench" }),
      item({ id: "b", label: "后注册", route: "/workbench" }),
    ];
    expect(buildNavIndex(dup, ROUTES).byPath.get("/workbench")?.label).toBe("先注册");
  });
});

describe("matchNavEntry", () => {
  const index = buildNavIndex(
    [
      item({ id: "m.agents", label: "数字员工", route: "/agents" }),
      item({ id: "m.manage", label: "员工管理", route: "/agents/manage" }),
    ],
    ROUTES,
  );

  it("最长前缀胜出：/agents/manage 不应被 /agents 吞掉", () => {
    expect(matchNavEntry(index, "/agents/manage")?.label).toBe("员工管理");
    expect(matchNavEntry(index, "/agents/manage/1/runs")?.label).toBe("员工管理");
  });

  it("子路径回落到父菜单", () => {
    expect(matchNavEntry(index, "/agents/a1")?.label).toBe("数字员工");
  });

  it("尾斜杠与 query 不影响匹配", () => {
    expect(matchNavEntry(index, "/agents/?x=1")?.label).toBe("数字员工");
  });
});

describe("normalizePathname / normalizeTabKey", () => {
  it("去掉 query、hash 与尾斜杠", () => {
    expect(normalizePathname("/admin/users/?tab=a#x")).toBe("/admin/users");
    expect(normalizePathname("/")).toBe("/");
  });

  it("collapseSegments 让同一员工的子导航共用一张标签", () => {
    expect(normalizeTabKey("/agents/a1/chat", 2)).toBe("/agents/a1");
    expect(normalizeTabKey("/agents/a1/files", 2)).toBe("/agents/a1");
    // 未超过段数时保持原样
    expect(normalizeTabKey("/agents/a1", 2)).toBe("/agents/a1");
  });

  it("不传 collapseSegments 时不做截断（菜单页子路径各自一张标签）", () => {
    expect(normalizeTabKey("/admin/users/detail/9")).toBe("/admin/users/detail/9");
  });
});

describe("matchRouteId", () => {
  it("静态段优先于参数段：/agents/manage 不被 /agents/:aid/* 抢占", () => {
    expect(matchRouteId("/agents/manage", ROUTES)).toBe("core.agents-manage");
  });

  it("参数路由仍可命中", () => {
    expect(matchRouteId("/agents/a1/chat", ROUTES)).toBe("core.agent-detail");
  });

  it("根路径交给 DefaultRedirect，不参与归属判定", () => {
    expect(matchRouteId("/", ROUTES)).toBeUndefined();
  });
});
