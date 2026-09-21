/**
 * NavTabsBar.tsx — 正文区顶部的单行多标签页导航条（侧栏右侧第二行）。
 *
 * 位置：MainLayout 的 Content 内、.page-content 之前；面包屑另在顶栏
 * （HeaderBreadcrumb）。样式对齐竞品：文本页签（无胶囊边框），激活项
 * 品牌色文字 + 底部 2px 下划线，右端仅保留全部标签总览按钮
 * （页面刷新收敛到右键菜单，不占栏内空间）。
 *
 * 单一来源：标签文字全部由菜单索引（navIndex）解析，页面不再自报父级
 * 文案；详情页的实体名通过 usePageNavTitle 回填到 pageTitleRegistry，本组件订阅
 * 其版本快照，回填后自动刷新。
 *
 * 交互清单：点击/键盘激活、中键关闭、右键菜单（刷新/关闭/其他/左/右/全部）、
 * 滚轮横向滚动、拖拽排序、溢出箭头、全部标签总览、hover 预加载、滚动位置记忆。
 *
 * @author qingfeng
 */
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type HTMLAttributes,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { Dropdown } from "antd";
import type { MenuProps } from "antd";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import {
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ChevronLeft,
  ChevronRight,
  LayoutList,
  X,
} from "lucide-react";
import styles from "../index.module.less";
import { renderIcon } from "../registry/adapter";
import { describeTab } from "../registry/tabLabel";
import { matchRouteId } from "../registry/navModel";
import {
  getPageTitleVersion,
  subscribePageTitle,
} from "../registry/pageTitleRegistry";
import { usePageNavStore } from "../../stores/pageNavStore";
import { useTabbableResolver } from "../../hooks/useNavTab";
import type { NavEntry } from "../registry/navModel";
import type { NavTranslate } from "../registry/tabLabel";
import type { PreloadableComponent } from "../../utils/lazyWithRetry";

/** 渲染用的标签视图模型。 */
interface TabVM {
  key: string;
  path: string;
  label: string;
  icon?: NavEntry["icon"];
  pinned?: boolean;
}

/** 页面正文滚动容器（.page-content 是全局类名，见 styles/layout.css）。 */
function getScrollHost(): HTMLElement | null {
  return document.querySelector<HTMLElement>(".page-content");
}

/** 可编辑元素判定：输入态下不劫持 Alt 快捷键。 */
function isEditableTarget(target: EventTarget | null): boolean {
  const node = target as HTMLElement | null;
  if (!node) return false;
  const tag = node.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    node.isContentEditable
  );
}

interface NavTabButtonProps {
  tab: TabVM;
  active: boolean;
  closeLabel: string;
  onSelect: (key: string) => void;
  onClose: (key: string) => void;
  onContextMenu: (key: string) => void;
  onHover: (tab: TabVM) => void;
}

/** 单张标签：memo 化避免无关状态变化时整排重渲染。 */
const NavTabButton = memo(function NavTabButton({
  tab,
  active,
  closeLabel,
  onSelect,
  onClose,
  onContextMenu,
  onHover,
}: NavTabButtonProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: tab.key, disabled: Boolean(tab.pinned) });

  /* dnd-kit 会注入 role="button" 与 tabIndex=0，必须剔掉再自己声明，
     否则 tablist/tab 语义被覆盖。 */
  const dragAttributes = Object.fromEntries(
    Object.entries(attributes ?? {}).filter(
      ([key]) => key !== "role" && key !== "tabIndex",
    ),
  ) as HTMLAttributes<HTMLDivElement>;

  const className = [
    styles.navTab,
    active ? styles.navTabActive : "",
    tab.pinned ? styles.navTabPinned : "",
    isDragging ? styles.navTabDragging : "",
  ]
    .filter(Boolean)
    .join(" ");

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const list = event.currentTarget.parentElement;
    if (!list) return;
    const siblings = Array.from(
      list.querySelectorAll<HTMLElement>('[role="tab"]'),
    );
    const index = siblings.indexOf(event.currentTarget);
    if (event.key === "ArrowRight" && index >= 0) {
      siblings[Math.min(index + 1, siblings.length - 1)]?.focus();
      event.preventDefault();
    } else if (event.key === "ArrowLeft" && index >= 0) {
      siblings[Math.max(index - 1, 0)]?.focus();
      event.preventDefault();
    } else if (event.key === "Delete" && !tab.pinned) {
      onClose(tab.key);
      event.preventDefault();
    }
  };

  return (
    <div
      ref={(node) => {
        setNodeRef(node);
        setActivatorNodeRef(node);
      }}
      style={{
        transform: CSS.Translate.toString(transform),
        transition,
      }}
      className={className}
      {...dragAttributes}
      {...listeners}
      role="tab"
      tabIndex={active ? 0 : -1}
      aria-selected={active}
      aria-controls="page-content-region"
      data-nav-tab={tab.key}
      onClick={() => onSelect(tab.key)}
      onMouseDown={(event) => {
        // 中键关闭，同时抑制浏览器默认的自动滚动光标。
        if (event.button === 1 && !tab.pinned) {
          event.preventDefault();
          onClose(tab.key);
        }
      }}
      onContextMenu={() => onContextMenu(tab.key)}
      onMouseEnter={() => onHover(tab)}
      onKeyDown={handleKeyDown}
    >
      {tab.icon ? (
        <span className={styles.navTabIcon}>{renderIcon(tab.icon, 14)}</span>
      ) : null}
      <span className={styles.navTabLabel}>{tab.label}</span>
      {tab.pinned ? null : (
        <button
          type="button"
          className={styles.navTabClose}
          aria-label={closeLabel}
          title={closeLabel}
          onClick={(event) => {
            event.stopPropagation();
            onClose(tab.key);
          }}
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
});

export default function NavTabsBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { resolve, navIndex, routes } = useTabbableResolver();

  const enabled = usePageNavStore((s) => s.enabled);
  const tabs = usePageNavStore((s) => s.tabs);
  const activeKey = usePageNavStore((s) => s.activeKey);
  const activate = usePageNavStore((s) => s.activate);
  const closeTab = usePageNavStore((s) => s.close);
  const closeOthers = usePageNavStore((s) => s.closeOthers);
  const closeLeft = usePageNavStore((s) => s.closeLeft);
  const closeRight = usePageNavStore((s) => s.closeRight);
  const closeAll = usePageNavStore((s) => s.closeAll);
  const reorder = usePageNavStore((s) => s.reorder);
  const requestRefresh = usePageNavStore((s) => s.requestRefresh);

  // describeTab 需要的最小翻译入口：显式返回 string，避开 i18next 重载类型。
  const translate = useMemo<NavTranslate>(
    () => (key, defaultValue) => String(t(key, { defaultValue })),
    [t],
  );

  // 详情页回填标题后 version 递增，借此重算标签文案。
  const titleVersion = useSyncExternalStore(
    subscribePageTitle,
    getPageTitleVersion,
    getPageTitleVersion,
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const scrollMemory = useRef<Map<string, number>>(new Map());
  const lastActiveKey = useRef(activeKey);
  const [contextKey, setContextKey] = useState<string | undefined>();
  const [contextOpen, setContextOpen] = useState(false);
  const [overflow, setOverflow] = useState(false);

  // ── 视图模型：文案与图标现算，store 只存路径与顺序 ─────────────────────
  const tabVMs = useMemo<TabVM[]>(
    () =>
      tabs.map((tab) => {
        const desc = describeTab(resolve(tab.path), navIndex, translate);
        return {
          key: tab.key,
          path: tab.path,
          label: desc?.label || tab.key,
          icon: desc?.icon,
          pinned: tab.pinned,
        };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tabs, navIndex, resolve, translate, titleVersion],
  );

  // ── 激活 / 关闭 ────────────────────────────────────────────────────────
  const handleSelect = useCallback(
    (key: string) => {
      const target = tabs.find((tab) => tab.key === key);
      if (!target) return;
      // 已激活时 URL 可能因浏览器前进后退漂移：再点一次回到标签对应页面。
      if (key === activeKey) navigate(target.path);
      else activate(key);
    },
    [tabs, activeKey, activate, navigate],
  );

  // ── hover 预加载目标分包 ───────────────────────────────────────────────
  const handleHover = useCallback(
    (tab: TabVM) => {
      const routeId = matchRouteId(tab.path, routes);
      const route = routes.find((item) => item.id === routeId);
      const preload = (route?.Component as PreloadableComponent | undefined)
        ?.preload;
      preload?.();
    },
    [routes],
  );

  // ── 右键菜单 ───────────────────────────────────────────────────────────
  const contextIndex = tabs.findIndex((tab) => tab.key === contextKey);
  const contextTarget = contextIndex >= 0 ? tabs[contextIndex] : undefined;
  const contextItems = useMemo<MenuProps["items"]>(() => {
    const closable = Boolean(contextTarget && !contextTarget.pinned);
    return [
      { key: "refresh", label: t("navTabs.refresh", "Refresh") },
      { key: "close", label: t("navTabs.close", "Close tab"), disabled: !closable },
      { type: "divider" },
      {
        key: "closeOthers",
        label: t("navTabs.closeOthers", "Close others"),
        disabled:
          tabs.filter((tab) => !tab.pinned && tab.key !== contextKey).length === 0,
      },
      {
        key: "closeLeft",
        label: t("navTabs.closeLeft", "Close to left"),
        disabled: contextIndex <= 0,
      },
      {
        key: "closeRight",
        label: t("navTabs.closeRight", "Close to right"),
        disabled: contextIndex < 0 || contextIndex >= tabs.length - 1,
      },
      {
        key: "closeAll",
        label: t("navTabs.closeAll", "Close all"),
        disabled: tabs.every((tab) => tab.pinned),
      },
    ];
  }, [tabs, contextKey, contextTarget, contextIndex, t]);

  const onContextClick: MenuProps["onClick"] = ({ key }) => {
    setContextOpen(false);
    if (!contextKey) return;
    if (key === "refresh") requestRefresh();
    else if (key === "close") closeTab(contextKey);
    else if (key === "closeOthers") closeOthers(contextKey);
    else if (key === "closeLeft") closeLeft(contextKey);
    else if (key === "closeRight") closeRight(contextKey);
    else if (key === "closeAll") closeAll();
  };

  // ── 全部标签总览下拉 ───────────────────────────────────────────────────
  const listItems = useMemo<MenuProps["items"]>(() => {
    const entries: NonNullable<MenuProps["items"]> = tabVMs.map((tab) => ({
      key: tab.key,
      label: tab.label,
    }));
    if (entries.length) entries.push({ type: "divider" });
    entries.push({
      key: "__closeAll",
      label: t("navTabs.closeAll", "Close all"),
    });
    return entries;
  }, [tabVMs, t]);

  // ── 拖拽排序 ───────────────────────────────────────────────────────────
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );
  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    reorder(String(active.id), String(over.id));
  };

  // ── 溢出检测与横向滚动 ─────────────────────────────────────────────────
  const syncOverflow = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setOverflow(el.scrollWidth - el.clientWidth > 1);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => syncOverflow())
        : undefined;
    observer?.observe(el);
    el.addEventListener("scroll", syncOverflow, { passive: true });
    return () => {
      observer?.disconnect();
      el.removeEventListener("scroll", syncOverflow);
    };
  }, [syncOverflow]);

  useEffect(() => {
    syncOverflow();
  }, [tabVMs.length, syncOverflow]);

  // 竖向滚轮转横向滚动：React 的 onWheel 是 passive 监听，需原生绑定才能 preventDefault。
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      el.scrollLeft += event.deltaY;
      event.preventDefault();
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const scrollByTab = (direction: -1 | 1) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollBy({
      left: direction * Math.max(el.clientWidth * 0.6, 160),
      behavior: "smooth",
    });
  };

  // ── 滚动位置记忆：切走时存，切回后恢复 ─────────────────────────────────
  useEffect(() => {
    if (lastActiveKey.current === activeKey) return;
    const host = getScrollHost();
    if (host) scrollMemory.current.set(lastActiveKey.current, host.scrollTop);
    lastActiveKey.current = activeKey;
  }, [activeKey]);

  useEffect(() => {
    const key = resolve(location.pathname)?.key;
    if (!key) return;
    const saved = scrollMemory.current.get(key);
    if (!saved) return;
    const frame = requestAnimationFrame(() => {
      const host = getScrollHost();
      if (host) host.scrollTop = saved;
    });
    return () => cancelAnimationFrame(frame);
  }, [location.pathname, resolve]);

  // ── 全局快捷键：Alt+W 关闭当前、Alt+1..9 切第 N 张 ─────────────────────
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return;
      }
      if (isEditableTarget(event.target)) return;
      if (event.key.toLowerCase() === "w") {
        event.preventDefault();
        closeTab(activeKey);
        return;
      }
      const digit = Number(event.key);
      if (Number.isInteger(digit) && digit >= 1 && digit <= 9) {
        const target = tabs[digit - 1];
        if (target) {
          event.preventDefault();
          activate(target.key);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled, tabs, activeKey, activate, closeTab]);

  if (!enabled) return null;

  const closeLabel = t("navTabs.close", "Close tab");

  return (
    <div className={styles.navBar}>
      {/* ── 标签行 ── */}
      <div className={styles.navTabsRow}>
        {overflow ? (
          <button
            type="button"
            className={styles.navTabScrollBtn}
            aria-label={t("navTabs.scrollLeft", "Scroll left")}
            onClick={() => scrollByTab(-1)}
          >
            <ChevronLeft size={14} />
          </button>
        ) : null}

        <Dropdown
          trigger={["contextMenu"]}
          open={contextOpen}
          onOpenChange={(next) => {
            setContextOpen(next);
            if (!next) setContextKey(undefined);
          }}
          menu={{ items: contextItems, onClick: onContextClick }}
        >
          <div className={styles.navTabsScroll} ref={scrollRef}>
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={tabVMs.map((tab) => tab.key)}
                strategy={horizontalListSortingStrategy}
              >
                <div className={styles.navTabs} role="tablist">
                  {tabVMs.map((tab) => (
                    <NavTabButton
                      key={tab.key}
                      tab={tab}
                      active={tab.key === activeKey}
                      closeLabel={closeLabel}
                      onSelect={handleSelect}
                      onClose={closeTab}
                      onContextMenu={(key) => {
                        setContextKey(key);
                        setContextOpen(true);
                      }}
                      onHover={handleHover}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          </div>
        </Dropdown>

        {overflow ? (
          <button
            type="button"
            className={styles.navTabScrollBtn}
            aria-label={t("navTabs.scrollRight", "Scroll right")}
            onClick={() => scrollByTab(1)}
          >
            <ChevronRight size={14} />
          </button>
        ) : null}

        <div className={styles.navTabActions}>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: listItems,
              selectable: true,
              selectedKeys: [activeKey],
              onClick: ({ key }) => {
                if (key === "__closeAll") closeAll();
                else activate(String(key));
              },
            }}
          >
            <button
              type="button"
              className={styles.navTabActionBtn}
              aria-label={t("navTabs.listAll", "All tabs")}
              title={t("navTabs.listAll", "All tabs")}
            >
              <LayoutList size={14} />
            </button>
          </Dropdown>
        </div>
      </div>
    </div>
  );
}
