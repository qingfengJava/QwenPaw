/**
 * pageNavStore.ts — 控制台顶部多标签页（tags-view）的会话状态。
 *
 * 设计要点：
 * 1. **只存路径与顺序，不存标题**：标签文字在渲染时由菜单索引 / 路由声明 / 详情页
 *    回填标题实时解析，菜单改名后所有已开标签自动跟随（数据单一来源）；
 * 2. **工作台为 pinned 固定标签**，永远是第 0 个，不可关闭、不可被 LRU 淘汰；
 * 3. **持久化**只落 tabs / activeKey / enabled，rehydrate 后统一 sanitize，
 *    防御旧版本结构、手工篡改与登出残留。
 *
 * @author qingfeng
 */
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/** 固定首页标签的归一化 key（与 core.workbench 路由一致）。 */
export const HOME_TAB_KEY = "/workbench";

/** 同时打开的标签上限，超出按最近未访问淘汰（pinned 不参与淘汰）。 */
export const MAX_NAV_TABS = 20;

/** localStorage 键，沿用 console 既有 qwenpaw- 前缀风格。 */
export const PAGE_NAV_STORAGE_KEY = "qwenpaw-console-nav-tabs";

export interface PageTab {
  /** normalizeTabKey(pathname) 归一化后的 key，同一实体只有一张标签。 */
  key: string;
  /** 实际导航目标（保留 query，刷新与深链都靠它）。 */
  path: string;
  /** 菜单叶子 or 详情页。 */
  kind: "menu" | "detail";
  /** 固定标签：不可关闭、不参与淘汰。 */
  pinned?: boolean;
  openedAt: number;
  lastVisitedAt: number;
}

/** openTab 入参：时间戳由 store 内部补齐。 */
export type OpenTabInput = Pick<PageTab, "key" | "path" | "kind"> &
  Partial<Pick<PageTab, "pinned">>;

interface PageNavState {
  tabs: PageTab[];
  activeKey: string;
  /** 标签会话归属的登录身份；身份变化即整体重置，防跨账号残留。 */
  owner: string;
  /** 运行时总开关：关闭后不渲染导航条、不再记录标签（改造的回退通道）。 */
  enabled: boolean;
  /** 自增即让当前页组件重挂载，实现「刷新当前标签」。 */
  refreshNonce: number;

  openTab: (input: OpenTabInput) => void;
  activate: (key: string) => void;
  close: (key: string) => void;
  closeOthers: (key: string) => void;
  closeLeft: (key: string) => void;
  closeRight: (key: string) => void;
  closeAll: () => void;
  reorder: (fromKey: string, toKey: string) => void;
  prune: (validKeys: string[]) => void;
  requestRefresh: () => void;
  setEnabled: (enabled: boolean) => void;
  /** 绑定当前登录身份；与已存归属不一致时丢弃上一位用户的标签会话。 */
  setOwner: (owner: string) => void;
  reset: () => void;
  /** rehydrate 后的结构自愈，外部无需调用。 */
  sanitize: () => void;
}

function homeTab(): PageTab {
  const now = Date.now();
  return {
    key: HOME_TAB_KEY,
    path: HOME_TAB_KEY,
    kind: "menu",
    pinned: true,
    openedAt: now,
    lastVisitedAt: now,
  };
}

function initialState(): Pick<
  PageNavState,
  "tabs" | "activeKey" | "owner" | "enabled" | "refreshNonce"
> {
  return {
    tabs: [homeTab()],
    activeKey: HOME_TAB_KEY,
    owner: "",
    enabled: true,
    refreshNonce: 0,
  };
}

/** 在给定列表里挑一个兜底激活项：优先原位右邻，其次左邻，最后固定首页。 */
function nextActiveKey(
  remaining: PageTab[],
  fallbackIndex: number,
  preferred?: string,
): string {
  if (preferred && remaining.some((tab) => tab.key === preferred)) {
    return preferred;
  }
  if (remaining.length === 0) return HOME_TAB_KEY;
  const index = Math.min(fallbackIndex, remaining.length - 1);
  const candidate = remaining[Math.max(index, 0)];
  return candidate?.key ?? HOME_TAB_KEY;
}

/** 保证 pinned 首页永远存在且排在最前。 */
function withHome(tabs: PageTab[]): PageTab[] {
  const home = tabs.find((tab) => tab.key === HOME_TAB_KEY);
  const others = tabs.filter(
    (tab) => tab.key !== HOME_TAB_KEY && tab.key !== "",
  );
  return [home ?? homeTab(), ...others];
}

function isTabLike(value: unknown): value is PageTab {
  const tab = value as PageTab | undefined;
  return Boolean(
    tab &&
      typeof tab.key === "string" &&
      tab.key &&
      typeof tab.path === "string" &&
      tab.path &&
      (tab.kind === "menu" || tab.kind === "detail"),
  );
}

/** 落库部分：只存会话结构，函数与 refreshNonce 不入库。 */
type PersistedPageNav = Pick<
  PageNavState,
  "tabs" | "activeKey" | "owner" | "enabled"
>;

export const usePageNavStore = create<PageNavState>()(
  persist<PageNavState, [], [], PersistedPageNav>(
    (set, get) => ({
      ...initialState(),

      openTab: (input) =>
        set((state) => {
          // 开关关闭时不记录标签，保持改造前行为。
          if (!state.enabled) return state;
          const now = Date.now();
          const existing = state.tabs.find((tab) => tab.key === input.key);

          if (existing) {
            // 同一标签：只刷新访问时间与 path（query 可能变了），顺序保持稳定。
            const tabs = state.tabs.map((tab) =>
              tab.key === input.key
                ? {
                    ...tab,
                    path: input.path,
                    kind: input.kind,
                    lastVisitedAt: now,
                  }
                : tab,
            );
            return { tabs, activeKey: input.key };
          }

          const appended: PageTab = {
            key: input.key,
            path: input.path,
            kind: input.kind,
            pinned: input.pinned,
            openedAt: now,
            lastVisitedAt: now,
          };
          let tabs = withHome([...state.tabs, appended]);

          // 超出上限：淘汰最久未访问的非固定标签，绝不淘汰新打开的与当前激活的。
          while (tabs.length > MAX_NAV_TABS) {
            const victim = tabs
              .filter(
                (tab) =>
                  !tab.pinned && tab.key !== input.key && tab.key !== state.activeKey,
              )
              .sort((a, b) => a.lastVisitedAt - b.lastVisitedAt)[0];
            if (!victim) break;
            tabs = tabs.filter((tab) => tab.key !== victim.key);
          }

          return { tabs, activeKey: input.key };
        }),

      activate: (key) =>
        set((state) => {
          if (state.activeKey === key) return state;
          if (!state.tabs.some((tab) => tab.key === key)) return state;
          const now = Date.now();
          return {
            activeKey: key,
            tabs: state.tabs.map((tab) =>
              tab.key === key ? { ...tab, lastVisitedAt: now } : tab,
            ),
          };
        }),

      close: (key) =>
        set((state) => {
          const target = state.tabs.find((tab) => tab.key === key);
          // 固定标签与不存在的标签不可关闭。
          if (!target || target.pinned) return state;

          const index = state.tabs.findIndex((tab) => tab.key === key);
          const tabs = state.tabs.filter((tab) => tab.key !== key);
          if (state.activeKey !== key) {
            return { tabs: withHome(tabs), activeKey: state.activeKey };
          }
          // 关闭的是当前标签：先试右邻（关闭后右邻落到原下标），再试左邻。
          return {
            tabs: withHome(tabs),
            activeKey: nextActiveKey(tabs, index),
          };
        }),

      closeOthers: (key) =>
        set((state) => {
          const target = state.tabs.find((tab) => tab.key === key);
          if (!target) return state;
          const tabs = state.tabs.filter(
            (tab) => tab.pinned || tab.key === key,
          );
          return { tabs: withHome(tabs), activeKey: key };
        }),

      closeLeft: (key) =>
        set((state) => {
          const index = state.tabs.findIndex((tab) => tab.key === key);
          if (index <= 0) return state;
          const keep = new Set(state.tabs.slice(index).map((tab) => tab.key));
          const tabs = state.tabs.filter(
            (tab) => keep.has(tab.key) || tab.pinned,
          );
          return {
            tabs: withHome(tabs),
            activeKey: keep.has(state.activeKey)
              ? state.activeKey
              : nextActiveKey(tabs, 0, key),
          };
        }),

      closeRight: (key) =>
        set((state) => {
          const index = state.tabs.findIndex((tab) => tab.key === key);
          if (index < 0 || index === state.tabs.length - 1) return state;
          const keep = new Set(state.tabs.slice(0, index + 1).map((tab) => tab.key));
          const tabs = state.tabs.filter(
            (tab) => keep.has(tab.key) || tab.pinned,
          );
          return {
            tabs: withHome(tabs),
            activeKey: keep.has(state.activeKey)
              ? state.activeKey
              : nextActiveKey(tabs, tabs.length - 1, key),
          };
        }),

      closeAll: () =>
        set((state) => {
          const tabs = state.tabs.filter((tab) => tab.pinned);
          return { tabs: withHome(tabs), activeKey: HOME_TAB_KEY };
        }),

      reorder: (fromKey, toKey) =>
        set((state) => {
          if (fromKey === toKey) return state;
          const from = state.tabs.findIndex((tab) => tab.key === fromKey);
          const to = state.tabs.findIndex((tab) => tab.key === toKey);
          if (from < 0 || to < 0) return state;
          // 固定标签不参与排序：既不能被拖动，也不能被别的标签挤到非首位。
          if (state.tabs[from]?.pinned || state.tabs[to]?.pinned) return state;
          const tabs = [...state.tabs];
          const [moved] = tabs.splice(from, 1);
          if (!moved) return state;
          tabs.splice(to, 0, moved);
          return { tabs };
        }),

      prune: (validKeys) =>
        set((state) => {
          const valid = new Set([...validKeys, HOME_TAB_KEY]);
          /* 只收敛菜单型标签：详情型标签（/agents/xxx）本来就不在菜单树里，
             按菜单剪枝会误删它们。 */
          const tabs = withHome(
            state.tabs.filter(
              (tab) => tab.pinned || tab.kind !== "menu" || valid.has(tab.key),
            ),
          );
          if (tabs.length === state.tabs.length) {
            return state;
          }
          const index = state.tabs.findIndex(
            (tab) => tab.key === state.activeKey,
          );
          return {
            tabs,
            activeKey: valid.has(state.activeKey)
              ? state.activeKey
              : nextActiveKey(tabs, Math.max(index, 0)),
          };
        }),

      requestRefresh: () =>
        set((state) => ({ refreshNonce: state.refreshNonce + 1 })),

      setEnabled: (enabled) =>
        set(() =>
          enabled ? { enabled: true } : { enabled: false, ...disabledPatch() },
        ),

      setOwner: (owner) =>
        set((state) => {
          // 身份尚未加载（空串）时不动已恢复的标签会话。
          if (!owner) return state;
          if (state.owner === owner) return state;
          return { ...initialState(), owner };
        }),

      reset: () => set({ ...initialState() }),

      sanitize: () => {
        const { tabs, activeKey } = get();
        const safeTabs = withHome(
          Array.isArray(tabs) ? tabs.filter(isTabLike) : [],
        );
        const deduped: PageTab[] = [];
        const seen = new Set<string>();
        safeTabs.forEach((tab) => {
          if (seen.has(tab.key)) return;
          seen.add(tab.key);
          deduped.push(tab);
        });
        const nextKey = deduped.some((tab) => tab.key === activeKey)
          ? activeKey
          : (deduped[0]?.key ?? HOME_TAB_KEY);
        set({ tabs: deduped, activeKey: nextKey });
      },
    }),
    {
      name: PAGE_NAV_STORAGE_KEY,
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        tabs: state.tabs,
        activeKey: state.activeKey,
        owner: state.owner,
        enabled: state.enabled,
      }),
      // 不写 migrate：任何版本或脏数据都由下面的 sanitize 全量修复（剔除非法项、
      // 去重、补回 pinned 首页、修正 activeKey），避免两套修复路径互相覆盖。
      onRehydrateStorage: () => (state) => {
        state?.sanitize();
      },
    },
  ),
);

/** 关闭开关时要一并清掉已记录的标签，避免重新开启后复活陈旧状态。 */
function disabledPatch(): Pick<PageNavState, "tabs" | "activeKey"> {
  return { tabs: [homeTab()], activeKey: HOME_TAB_KEY };
}
