/**
 * dynamicMenuAdapter.test.ts — 后端 rbac_menus 树 → 中性 MenuItem 的转换。
 *
 * 覆盖动态菜单驱动侧栏的核心映射：directory→分组、button/不可见被剔除、
 * 页面项 route=真实 path、外链→href、children 递归。
 */
import { describe, expect, it } from "vitest";
import {
  rbacMenusToRegistryItems,
  resolveMenuLabel,
} from "./dynamicMenuAdapter";
import type { MenuItem } from "../../stores/permissionStore";

/** 构造一条后端菜单（填齐必填字段，便于单测）。 */
function menu(over: Partial<MenuItem>): MenuItem {
  return {
    id: over.id ?? "m",
    parent_id: over.parent_id ?? null,
    name: over.name ?? "名称",
    menu_type: over.menu_type ?? "menu",
    path: over.path ?? "",
    component: over.component ?? "",
    icon: over.icon ?? "LayoutDashboard",
    perm_code: over.perm_code ?? "",
    sort_order: over.sort_order ?? 0,
    is_visible: over.is_visible ?? true,
    is_enabled: over.is_enabled ?? true,
    is_external: over.is_external ?? false,
    redirect: over.redirect ?? "",
    children: over.children,
  };
}

describe("rbacMenusToRegistryItems", () => {
  it("directory 转成 isGroup 且带子节点", () => {
    const tree = [
      menu({
        id: "grp",
        menu_type: "directory",
        name: "分组",
        children: [menu({ id: "leaf", path: "/leaf", name: "叶子" })],
      }),
    ];
    const items = rbacMenusToRegistryItems(tree);
    expect(items).toHaveLength(1);
    expect(items[0].isGroup).toBe(true);
    expect(items[0].__children).toHaveLength(1);
    expect(items[0].__children?.[0].route).toBe("/leaf");
  });

  it("button 型与不可见/禁用项被过滤，不进导航", () => {
    const tree = [
      menu({ id: "btn", menu_type: "button", name: "按钮" }),
      menu({ id: "hidden", path: "/hidden", is_visible: false }),
      menu({ id: "off", path: "/off", is_enabled: false }),
      menu({ id: "ok", path: "/ok" }),
    ];
    const items = rbacMenusToRegistryItems(tree);
    expect(items.map((i) => i.id)).toEqual(["ok"]);
  });

  it("外链菜单映射为 href（redirect 优先）", () => {
    const tree = [
      menu({
        id: "ext",
        path: "/ignored",
        is_external: true,
        redirect: "https://example.com",
      }),
    ];
    const items = rbacMenusToRegistryItems(tree);
    expect(items[0].href).toBe("https://example.com");
    expect(items[0].route).toBeUndefined();
  });

  it("空目录（无子、无 path）被丢弃，避免死条目", () => {
    const tree = [menu({ id: "emptydir", menu_type: "directory", name: "空" })];
    expect(rbacMenusToRegistryItems(tree)).toHaveLength(0);
  });

  it("label 解析：普通文本原样、命中 i18n key 才翻译", () => {
    expect(resolveMenuLabel("工作台")).toBe("工作台");
    expect(resolveMenuLabel("")).toBe("");
  });
});
