/**
 * pageNavStore.test.ts — 多标签页会话状态：去重、LRU、关闭回落、权限剪枝、脏数据自愈。
 *
 * 这里钉住的是最容易出线上问题的几条：
 * 1. pinned 首页永远第 0 个且关不掉（否则用户会面对空标签栏）；
 * 2. 关闭当前标签的回落顺序（右邻 → 左邻 → 首页）；
 * 3. prune 只收敛菜单型标签，详情型标签不能被误删；
 * 4. 落库结构不含标题与函数，旧版本/手工篡改数据 rehydrate 后必须自愈。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  HOME_TAB_KEY,
  MAX_NAV_TABS,
  PAGE_NAV_STORAGE_KEY,
  usePageNavStore,
} from "./pageNavStore";

const api = () => usePageNavStore.getState();

function open(key: string, kind: "menu" | "detail" = "menu") {
  api().openTab({ key, path: key, kind });
}

beforeEach(() => {
  localStorage.clear();
  usePageNavStore.persist.clearStorage?.();
  api().reset();
});

describe("初始状态与固定首页", () => {
  it("默认只有一张 pinned 首页标签并处于激活态", () => {
    expect(api().tabs).toHaveLength(1);
    expect(api().tabs[0].key).toBe(HOME_TAB_KEY);
    expect(api().tabs[0].pinned).toBe(true);
    expect(api().activeKey).toBe(HOME_TAB_KEY);
  });

  it("首页标签不可关闭", () => {
    open("/admin/users");
    api().close(HOME_TAB_KEY);
    expect(api().tabs.some((tab) => tab.key === HOME_TAB_KEY)).toBe(true);
    expect(api().tabs[0].key).toBe(HOME_TAB_KEY);
  });
});

describe("openTab", () => {
  it("同一 key 复用标签，不重复新增，但更新 path（query 变化）", () => {
    open("/admin/users");
    api().openTab({ key: "/admin/users", path: "/admin/users?page=2", kind: "menu" });
    expect(api().tabs).toHaveLength(2);
    expect(api().tabs[1].path).toBe("/admin/users?page=2");
  });

  it("超出上限按最久未访问淘汰，且不淘汰新打开与当前激活", () => {
    vi.useFakeTimers();
    try {
      open("/a"); // 最早访问
      vi.advanceTimersByTime(10);
      open("/b");
      vi.advanceTimersByTime(10);
      // 一直开到超过上限
      for (let i = 0; i < MAX_NAV_TABS; i += 1) {
        api().openTab({ key: `/p${i}`, path: `/p${i}`, kind: "menu" });
        vi.advanceTimersByTime(1);
      }
      expect(api().tabs.length).toBeLessThanOrEqual(MAX_NAV_TABS);
      // 当前激活标签必定还在
      expect(api().tabs.some((tab) => tab.key === `/p${MAX_NAV_TABS - 1}`)).toBe(true);
      // 最早访问的非固定标签被淘汰
      expect(api().tabs.some((tab) => tab.key === "/a")).toBe(false);
      // pinned 首页不受淘汰影响
      expect(api().tabs[0].key).toBe(HOME_TAB_KEY);
    } finally {
      vi.useRealTimers();
    }
  });

  it("开关关闭时不再记录标签", () => {
    api().setEnabled(false);
    open("/admin/users");
    expect(api().tabs).toHaveLength(1);
  });
});

describe("close 的激活回落顺序", () => {
  beforeEach(() => {
    open("/a");
    open("/b");
    open("/c");
  });

  it("关闭当前标签优先落到右邻", () => {
    api().activate("/b");
    api().close("/b");
    expect(api().activeKey).toBe("/c");
  });

  it("没有右邻时落到左邻", () => {
    api().activate("/c");
    api().close("/c");
    expect(api().activeKey).toBe("/b");
  });

  it("关闭非激活标签不改变激活态", () => {
    api().activate("/a");
    api().close("/c");
    expect(api().activeKey).toBe("/a");
  });

  it("activate 忽略不存在的 key，保持原激活态", () => {
    const before = api().activeKey;
    api().activate("/nope");
    expect(api().activeKey).toBe(before);
  });
});

describe("批量关闭", () => {
  beforeEach(() => {
    open("/a");
    open("/b");
    open("/c");
    api().activate("/a");
  });

  it("closeOthers 保留 pinned 与目标", () => {
    api().closeOthers("/b");
    expect(api().tabs.map((tab) => tab.key)).toEqual([HOME_TAB_KEY, "/b"]);
    expect(api().activeKey).toBe("/b");
  });

  it("closeLeft 关掉目标左侧的普通标签，保留 pinned 及其自身右侧", () => {
    api().closeLeft("/c");
    expect(api().tabs.map((tab) => tab.key)).toEqual([HOME_TAB_KEY, "/c"]);
    // 原激活项 /a 已被关掉，必须落到仍然存在的标签
    expect(api().activeKey).toBe("/c");
  });

  it("closeRight 保留其左侧与自身", () => {
    api().closeRight("/a");
    expect(api().tabs.map((tab) => tab.key)).toEqual([HOME_TAB_KEY, "/a"]);
  });

  it("closeAll 只留 pinned 首页并激活它", () => {
    api().closeAll();
    expect(api().tabs.map((tab) => tab.key)).toEqual([HOME_TAB_KEY]);
    expect(api().activeKey).toBe(HOME_TAB_KEY);
  });
});

describe("reorder", () => {
  it("可调整普通标签顺序", () => {
    open("/a");
    open("/b");
    api().reorder("/b", "/a");
    expect(api().tabs.map((tab) => tab.key)).toEqual([HOME_TAB_KEY, "/b", "/a"]);
  });

  it("固定首页不参与拖拽，顺序不会被挤离第 0 位", () => {
    open("/a");
    api().reorder(HOME_TAB_KEY, "/a");
    expect(api().tabs[0].key).toBe(HOME_TAB_KEY);
    api().reorder("/a", HOME_TAB_KEY);
    expect(api().tabs[0].key).toBe(HOME_TAB_KEY);
  });
});

describe("prune（菜单权限变更后收敛）", () => {
  it("剔除失去权限的菜单标签，但保留详情型标签", () => {
    open("/admin/users");
    open("/agents/a1", "detail");
    api().activate("/admin/users");
    api().prune(["/workbench"]);
    expect(api().tabs.some((tab) => tab.key === "/admin/users")).toBe(false);
    expect(api().tabs.some((tab) => tab.key === "/agents/a1")).toBe(true);
    // 被剪掉的正是激活项时要有兜底落点
    expect(api().tabs.some((tab) => tab.key === api().activeKey)).toBe(true);
  });

  it("全部有效时保持引用不变（避免无谓重渲染）", () => {
    open("/admin/users");
    const before = api().tabs;
    api().prune(["/admin/users"]);
    expect(api().tabs).toBe(before);
  });
});

describe("身份与开关", () => {
  it("setOwner 切换身份即重置标签会话", () => {
    api().setOwner("alice");
    open("/admin/users");
    expect(api().tabs).toHaveLength(2);
    api().setOwner("bob");
    expect(api().tabs).toHaveLength(1);
    expect(api().owner).toBe("bob");
  });

  it("身份未加载（空串）时不动已恢复的会话", () => {
    open("/admin/users");
    api().setOwner("");
    expect(api().tabs).toHaveLength(2);
  });

  it("重新开启开关回到初始单标签会话", () => {
    open("/admin/users");
    api().setEnabled(false);
    expect(api().tabs).toHaveLength(1);
    api().setEnabled(true);
    expect(api().enabled).toBe(true);
  });

  it("requestRefresh 自增 nonce 供重挂载当前页", () => {
    const before = api().refreshNonce;
    api().requestRefresh();
    expect(api().refreshNonce).toBe(before + 1);
  });
});

describe("持久化与脏数据自愈", () => {
  it("落库内容不含函数与 refreshNonce", () => {
    open("/admin/users");
    const raw = localStorage.getItem(PAGE_NAV_STORAGE_KEY);
    expect(raw).toBeTruthy();
    const state = JSON.parse(raw!).state as Record<string, unknown>;
    expect(Object.keys(state).sort()).toEqual([
      "activeKey",
      "enabled",
      "owner",
      "tabs",
    ]);
    // 标签只存结构，不存标题：菜单改名后标签才会自动跟随
    for (const tab of state.tabs as Array<Record<string, unknown>>) {
      expect(tab.label).toBeUndefined();
    }
  });

  it("rehydrate 脏数据：剔除非法项、补回 pinned 首页、修正激活 key", () => {
    localStorage.setItem(
      PAGE_NAV_STORAGE_KEY,
      JSON.stringify({
        version: 1,
        state: {
          tabs: [
            { key: "", path: "", kind: "menu", openedAt: 1, lastVisitedAt: 1 },
            { key: "/x", path: 42, kind: "menu" },
            { key: "/ok", path: "/ok", kind: "menu", openedAt: 2, lastVisitedAt: 2 },
            "not-an-object",
          ],
          activeKey: "/gone",
          owner: "alice",
          enabled: true,
        },
      }),
    );
    void usePageNavStore.persist.rehydrate();
    const keys = api().tabs.map((tab) => tab.key);
    expect(keys[0]).toBe(HOME_TAB_KEY);
    expect(keys).toContain("/ok");
    expect(keys).not.toContain("");
    expect(keys.filter((k) => k === "/x")).toHaveLength(0);
    // 激活项失效后回落到存在的首个标签
    expect(keys).toContain(api().activeKey);
  });
});
