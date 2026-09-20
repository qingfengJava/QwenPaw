import {
  Layout,
  Menu,
  Button,
  Tooltip,
  Badge,
  Popover,
} from "antd";
import { useState, useEffect, useMemo, useCallback, useRef, Fragment } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  SparkMenuExpandLine,
  SparkMenuFoldLine,
  SparkEmailLine,
  SparkSettingLine,
} from "@agentscope-ai/icons";
import SidebarSettingsPanel from "./SidebarSettingsPanel";
import api from "../api";
import { useSidebarModeStore } from "../stores/sidebarModeStore";
import { useInboxWobble } from "../hooks/useInboxWobble";
import { useNavModel } from "../hooks/useNavModel";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { Slot } from "../plugins/registry/Slot";
import {
  findMenuItem,
  findParentGroupId,
  flattenMenu,
  renderIcon,
  resolveItemPath,
  toAntdItems,
} from "./registry/adapter";
import type { MenuItem } from "../plugins/registry/types";
import type { ReactNode } from "react";

// ── Layout ────────────────────────────────────────────────────────────────

const { Sider } = Layout;
const MOBILE_SIDEBAR_QUERY = "(max-width: 768px)";

// settingsMenu 在动态模式下恒为空数组——该常量现由 useNavModel 持有，且必须是
// 模块级共享引用而非每次渲染新建的 `[]`：openKeys 自动展开 effect 依赖它的引用，
// 引用每帧变化会把展开组强制重置回“当前激活项所在组”（表现为分组刚展开即回弹）。

function isMobileSidebarViewport() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(MOBILE_SIDEBAR_QUERY).matches
  );
}
const INBOX_BADGE_POLLING_MS = 6000;

// ── Simple mode whitelist ─────────────────────────────────────────────────

/** 简洁模式白名单与拍平逻辑已上收到 hooks/useNavModel，与面包屑共用一份菜单裁剪。 */

// ── Types ─────────────────────────────────────────────────────────────────

interface SidebarProps {
  /**
   * 当前高亮菜单项 id。省略时由 useNavModel 按 pathname 解析——顶部导航条上线后，
   * 侧栏高亮与面包屑/标签必须同源，故默认走 hook 解析，仅测试可显式注入。
   */
  selectedKey?: string;
}

// ── Sidebar ───────────────────────────────────────────────────────────────

export default function Sidebar({ selectedKey }: SidebarProps = {}) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { isDark } = useTheme();
  // Start collapsed on mobile so the first paint does not overlay/obscure
  // the main content on narrow viewports.
  const [collapsed, setCollapsed] = useState(isMobileSidebarViewport);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const [isMobile, setIsMobile] = useState(isMobileSidebarViewport);
  const [hasUnreadMessages, setHasUnreadMessages] = useState(false);
  const [hasPendingApprovals, setHasPendingApprovals] = useState(false);
  const [shakeInbox, setShakeInbox] = useState(false);
  const [wobbleEnabled] = useInboxWobble();
  const currentApprovalIdsRef = useRef<Set<string>>(new Set());
  const seenApprovalIdsRef = useRef<Set<string>>(new Set());

  // Sidebar mode: "simple" (only core items) or "full" (everything)
  const { mode: sidebarMode } = useSidebarModeStore();

  /* 菜单树、路由快照与当前高亮项统一由 useNavModel 提供：与顶部面包屑、标签页
     共用同一份判定，不会出现「侧栏高亮 A、面包屑显示 B」的漂移。 */
  const { routes, agentMenu, settingsMenu, activeId: resolvedActiveId } =
    useNavModel();
  const activeId = selectedKey ?? resolvedActiveId;

  // Accordion groups: at most one group stays open. On startup only the
  // group holding the active item expands (fully collapsed when the active
  // item is top-level, e.g. the workbench).
  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    const initialGroup = activeId
      ? findParentGroupId([...agentMenu, ...settingsMenu], activeId)
      : undefined;
    return initialGroup ? [initialGroup] : [];
  });

  // Deep links / back-forward navigation switch the open group to the one
  // containing the newly active leaf. User-initiated collapses are left
  // untouched because this only runs when the selection (or menu snapshot)
  // actually changes.
  useEffect(() => {
    const group = findParentGroupId(
      [...agentMenu, ...settingsMenu],
      activeId ?? "",
    );
    if (!group) return;
    setOpenKeys((prev) => (prev.includes(group) ? prev : [group]));
  }, [agentMenu, settingsMenu, activeId]);

  // Accordion behavior: opening a group collapses the previously open one;
  // clicking the open group's title collapses everything.
  const handleOpenChange = useCallback((keys: string[]) => {
    setOpenKeys((prev) => {
      const latestOpen = keys.find((key) => !prev.includes(key));
      return latestOpen ? [latestOpen] : [];
    });
  }, []);

  // Flat nav entries for simple mode (icon + label + path)
  const simpleFlatNav = useMemo(() => {
    if (sidebarMode !== "simple") return [];
    return [
      ...flattenMenu(agentMenu, routes, 16),
      ...flattenMenu(settingsMenu, routes, 16),
    ];
  }, [agentMenu, settingsMenu, routes, sidebarMode]);

  // ── Effects ──────────────────────────────────────────────────────────────

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }

    const mediaQuery = window.matchMedia(MOBILE_SIDEBAR_QUERY);
    const syncMobileSidebar = () => {
      setIsMobile(mediaQuery.matches);
      // Collapse on mobile to avoid covering the main content; expand again
      // when the viewport returns to desktop width.
      setCollapsed(mediaQuery.matches);
    };

    syncMobileSidebar();
    mediaQuery.addEventListener("change", syncMobileSidebar);

    return () => {
      mediaQuery.removeEventListener("change", syncMobileSidebar);
    };
  }, []);
  useEffect(() => {
    const loadUnreadState = async () => {
      try {
        const [inboxRes, pushRes] = await Promise.all([
          api.getInboxEvents({
            unread_only: true,
            limit: 1,
          }),
          api.getPushMessages(),
        ]);
        const hasUnreadEvents = (inboxRes?.events?.length || 0) > 0;
        const approvals = pushRes?.pending_approvals || [];
        const currentIds = new Set(
          approvals.map((a: { request_id: string }) => a.request_id),
        );
        currentApprovalIdsRef.current = currentIds;
        const hasNewApprovals =
          currentIds.size > 0 &&
          [...currentIds].some((id) => !seenApprovalIdsRef.current.has(id));
        setShakeInbox(hasNewApprovals);
        setHasUnreadMessages(hasUnreadEvents);
        setHasPendingApprovals(currentIds.size > 0);
      } catch {
        // Keep previous state when polling fails.
      }
    };
    void loadUnreadState();
    const timer = window.setInterval(() => {
      void loadUnreadState();
    }, INBOX_BADGE_POLLING_MS);
    return () => window.clearInterval(timer);
  }, []);

  // ── Pre-fetch sessions on mount ───────────────────────────────────────────
  // ── Inbox badge dot & wobble ─────────────────────────────────────────────
  const hasInboxUnread = hasUnreadMessages || hasPendingApprovals;
  const inboxDotColor = hasPendingApprovals
    ? "#e04848"
    : "#1a71ff";
  const effectiveShake = shakeInbox && wobbleEnabled;

  // ── Adapter: convert MenuItem trees to antd, with inbox badge decoration.

  /** Mark current approvals as "seen" so the wobble stops. */
  const handleInboxHover = useCallback(() => {
    seenApprovalIdsRef.current = new Set(currentApprovalIdsRef.current);
    setShakeInbox(false);
  }, []);

  /**
   * Bridge hover events from the antd Menu `<li>` to our handler.
   * addEventListener de-duplicates the same function reference, so re-calling
   * on the same element is harmless; old detached elements are GC'd naturally.
   */
  const inboxLiRefCallback = useCallback(
    (node: HTMLSpanElement | null) => {
      const li = node?.closest("li");
      if (!li) return;
      li.addEventListener("mouseenter", handleInboxHover);
    },
    [handleInboxHover],
  );

  /** Wrap the inbox label with the unread-Badge while keeping all other labels intact. */
  const decorateLabel = (item: MenuItem, label: ReactNode): ReactNode => {
    if (item.id !== "core.inbox" || label == null) return label;
    return (
      <span ref={inboxLiRefCallback}>
        <Badge dot={hasInboxUnread} color={inboxDotColor} offset={[5, 7]}>
          <span>{label}</span>
        </Badge>
      </span>
    );
  };

  const getItemClassName = (item: MenuItem) => {
    if (item.id === "core.inbox" && effectiveShake) {
      return styles.inboxShake;
    }
    return undefined;
  };

  const agentMenuItems = useMemo(
    () =>
      toAntdItems(agentMenu, { collapsed, decorateLabel, getItemClassName }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      agentMenu,
      collapsed,
      hasUnreadMessages,
      hasPendingApprovals,
      effectiveShake,
    ],
  );

  const settingsMenuItems = useMemo(
    () => toAntdItems(settingsMenu, { collapsed }),
    [settingsMenu, collapsed],
  );

  const collapsedNavItems = useMemo(() => {
    // Inbox in collapsed mode shows a dot overlay on its icon (kept Sidebar-local
    // for the same reason as decorateLabel: live state isn't menu data).
    const decorateInboxIcon = (icon: ReactNode): ReactNode => (
      <span style={{ position: "relative", display: "inline-flex" }}>
        {icon ?? <SparkEmailLine size={18} />}
        {hasInboxUnread && (
          <span
            style={{
              position: "absolute",
              top: -1,
              right: -3,
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: inboxDotColor,
            }}
          />
        )}
      </span>
    );
    // 平台段与系统段各自扁平化后拼接，并记下分界下标：rail 模式在该处插一条
    // 分隔线，否则三十来个图标连成一片，看不出分组。
    const platformItems = flattenMenu(agentMenu, routes, 18);
    const adminItems = flattenMenu(settingsMenu, routes, 18);
    return {
      splitIndex: platformItems.length,
      items: [...platformItems, ...adminItems].map((entry) =>
        entry.key === "core.inbox"
          ? { ...entry, icon: decorateInboxIcon(entry.icon) }
          : entry,
      ),
    };
  }, [agentMenu, settingsMenu, routes, hasInboxUnread, inboxDotColor]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleMenuClick = (key: string, allItems: MenuItem[]) => {
    const item = findMenuItem(allItems, key);
    if (item?.href) {
      window.open(item.href, "_blank", "noopener,noreferrer");
      return;
    }
    const path = resolveItemPath(item?.route, routes);
    if (path) navigate(path);
  };

  // ── Render ────────────────────────────────────────────────────────────────

  const siderWidth = collapsed ? (isMobile ? 56 : 72) : 240;
  // `renderIcon` retained for tree-shaking awareness.
  void renderIcon;

  // On mobile, the expanded sidebar shows sessions (like simple mode) instead
  // of the full menu — matching the desktop history panel UX.
  const isSimpleExpanded = (sidebarMode === "simple" || isMobile) && !collapsed;

  return (
    <Sider
      width={siderWidth}
      className={`${styles.sider}${
        collapsed ? ` ${styles.siderCollapsed}` : ""
      }${isDark ? ` ${styles.siderDark}` : ""}${
        isSimpleExpanded ? ` ${styles.siderSimple}` : ""
      }`}
    >
      {/* 菜单内容滚动区：所有导航模式（折叠/简洁/展开）的菜单主体都装在这
          个独立滚动容器里，使下方的 authActions + collapseToggleContainer
          页脚脱离滚动流、固定吸底（见 index.module.less .siderScroll）。 */}
      <div className={styles.siderScroll}>
      {collapsed ? (
        <nav className={styles.collapsedNav}>
          {collapsedNavItems.items.map((item, index) => {
            const isActive = activeId === item.key;
            return (
              <Fragment key={item.key}>
                {/* 平台段 / 系统段之间的分隔线，只在两侧都有条目时出现 */}
                {index === collapsedNavItems.splitIndex &&
                  index < collapsedNavItems.items.length - 1 && (
                    <span
                      className={styles.railDivider}
                      aria-hidden="true"
                    />
                  )}
                <Tooltip
                  title={item.label}
                  placement="right"
                  styles={{
                    body: { background: "rgba(0,0,0,0.75)", color: "#fff" },
                  }}
                >
                  <button
                    aria-label={
                      typeof item.label === "string" ? item.label : undefined
                    }
                    className={`${styles.collapsedNavItem} ${
                      isActive ? styles.collapsedNavItemActive : ""
                    }${
                      item.key === "core.inbox" && effectiveShake
                        ? ` ${styles.inboxShake}`
                        : ""
                    }`}
                    onClick={() => {
                      if (item.href) {
                        window.open(item.href, "_blank", "noopener,noreferrer");
                      } else {
                        navigate(item.path);
                      }
                    }}
                    onMouseEnter={
                      item.key === "core.inbox" ? handleInboxHover : undefined
                    }
                  >
                    {item.icon}
                  </button>
                </Tooltip>
              </Fragment>
            );
          })}
        </nav>
      ) : isSimpleExpanded ? (
        <>
          {/* Simple mode: flat nav items */}
          <div className={styles.agentScopedSection}>
            {/* Flat nav items (no groups) */}
            <div className={styles.simpleNavItems}>
              {simpleFlatNav.map((entry) => {
                const isInbox = entry.key === "core.inbox";
                const isActive = activeId === entry.key;
                return (
                  <button
                    key={entry.key}
                    className={`${styles.simpleNavItem} ${
                      isActive ? styles.simpleNavItemActive : ""
                    }${
                      isInbox && effectiveShake ? ` ${styles.inboxShake}` : ""
                    }`}
                    onMouseEnter={isInbox ? handleInboxHover : undefined}
                    onClick={() => {
                      if (entry.href) {
                        window.open(
                          entry.href,
                          "_blank",
                          "noopener,noreferrer",
                        );
                      } else {
                        navigate(entry.path);
                      }
                    }}
                  >
                    {isInbox ? (
                      <span
                        style={{
                          position: "relative",
                          display: "inline-flex",
                        }}
                      >
                        {entry.icon ?? <SparkEmailLine size={16} />}
                        {hasInboxUnread && (
                          <span
                            style={{
                              position: "absolute",
                              top: -1,
                              right: -3,
                              width: 6,
                              height: 6,
                              borderRadius: "50%",
                              background: inboxDotColor,
                            }}
                          />
                        )}
                      </span>
                    ) : (
                      entry.icon
                    )}
                    <span>{entry.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </>
      ) : (
        <>
          {/* Platform section */}
          <div className={styles.agentScopedSection}>
            <Slot name="sider.top" kind="fill" />
            <Menu
              mode="inline"
              selectedKeys={activeId ? [activeId] : []}
              openKeys={openKeys}
              onOpenChange={handleOpenChange}
              onClick={({ key }) => handleMenuClick(String(key), agentMenu)}
              items={agentMenuItems}
              theme={isDark ? "dark" : "light"}
              className={styles.sideMenu}
            />
          </div>

          {/* Global settings section */}
          <Menu
            mode="inline"
            selectedKeys={activeId ? [activeId] : []}
            openKeys={openKeys}
            onOpenChange={handleOpenChange}
            onClick={({ key }) => handleMenuClick(String(key), settingsMenu)}
            items={settingsMenuItems}
            theme={isDark ? "dark" : "light"}
            className={`${styles.sideMenu} ${styles.settingsMenu}`}
          />
          <Slot name="sider.bottom" kind="fill" />
        </>
      )}
      </div>

      <div className={styles.collapseToggleContainer}>
        {/* Gear stays visible in collapsed state too — otherwise users
            (especially on mobile, where the sidebar starts collapsed)
            cannot discover how to restore full mode. */}
        <Popover
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
          placement={collapsed ? "rightBottom" : "topRight"}
          trigger="click"
          content={
            <SidebarSettingsPanel onClose={() => setSettingsOpen(false)} />
          }
        >
          <Button
            ref={settingsButtonRef}
            type="text"
            icon={<SparkSettingLine size={18} />}
            aria-label={t("sidebar.settingsPanel", "Sidebar settings")}
            title={t("sidebar.settingsPanel", "Sidebar settings")}
            className={styles.collapseToggle}
          />
        </Popover>
        <Button
          type="text"
          icon={
            collapsed ? (
              <SparkMenuExpandLine size={20} />
            ) : (
              <SparkMenuFoldLine size={20} />
            )
          }
          onClick={() => setCollapsed(!collapsed)}
          aria-label={
            collapsed
              ? t("sidebar.expand", "Expand sidebar")
              : t("sidebar.collapse", "Collapse sidebar")
          }
          title={
            collapsed
              ? t("sidebar.expand", "Expand sidebar")
              : t("sidebar.collapse", "Collapse sidebar")
          }
          className={styles.collapseToggle}
        />
      </div>

    </Sider>
  );
}
