import {
  Layout,
  Menu,
  Button,
  Modal,
  Input,
  Form,
  Tooltip,
  Badge,
  Popover,
  Popconfirm,
  Divider,
} from "antd";
import { useState, useEffect, useMemo, useCallback, useRef, Fragment } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ShieldCheck, RotateCw } from "lucide-react";
import { useAppMessage } from "../hooks/useAppMessage";
import {
  SparkExitFullscreenLine,
  SparkSearchUserLine,
  SparkMenuExpandLine,
  SparkMenuFoldLine,
  SparkEmailLine,
  SparkSettingLine,
} from "@agentscope-ai/icons";
import SidebarSettingsPanel from "./SidebarSettingsPanel";
import { clearAuthToken } from "../api/config";
import { authApi } from "../api/modules/auth";
import { userProfilesApi } from "../api/modules/userProfiles";
import { hubApi } from "../api/modules/hub";
import api from "../api";
import { useAuthStore } from "../stores/authStore";
import { useSidebarModeStore } from "../stores/sidebarModeStore";
import { useInboxWobble } from "../hooks/useInboxWobble";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { useMenuItems, useRoutes } from "../plugins/registry/hooks";
import { Slot } from "../plugins/registry/Slot";
import {
  findMenuItem,
  findParentGroupId,
  flattenMenu,
  renderIcon,
  routeIdToPath,
  toAntdItems,
} from "./registry/adapter";
import type { MenuItem } from "../plugins/registry/types";
import type { ReactNode } from "react";

// ── Layout ────────────────────────────────────────────────────────────────

const { Sider } = Layout;
const MOBILE_SIDEBAR_QUERY = "(max-width: 768px)";

function isMobileSidebarViewport() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(MOBILE_SIDEBAR_QUERY).matches
  );
}
const INBOX_BADGE_POLLING_MS = 6000;

// ── Simple mode whitelist ─────────────────────────────────────────────────

/** Menu item IDs that remain visible in simple sidebar mode (no groups). */
const SIMPLE_MODE_WHITELIST = new Set([
  "core.workbench",
  "core.agents",
  "core.channels",
  "core.inbox",
  "core.marketplace",
  "core.models",
  "core.skill-pool",
]);

/**
 * Flatten a MenuItem tree into a leaf-only list for simple sidebar mode.
 * Groups are eliminated entirely — only whitelisted children survive
 * as top-level items.
 */
function flattenMenuForSimpleMode(items: MenuItem[]): MenuItem[] {
  const result: MenuItem[] = [];
  for (const rawItem of items) {
    const item = rawItem as MenuItem & { __children?: MenuItem[] };
    if (item.__children && item.__children.length > 0) {
      for (const child of item.__children) {
        if (SIMPLE_MODE_WHITELIST.has(child.id)) {
          result.push(child);
        }
      }
    } else if (SIMPLE_MODE_WHITELIST.has(item.id)) {
      result.push(item);
    }
  }
  return result;
}

// ── Types ─────────────────────────────────────────────────────────────────

interface SidebarProps {
  /** Route id of the currently active page (e.g. "core.workspace"). */
  selectedKey: string;
  /** True when the backend runs in self-hosted Hub mode (M6). */
  hubMode?: boolean;
}

// ── Sidebar ───────────────────────────────────────────────────────────────

export default function Sidebar({
  selectedKey,
  hubMode = false,
}: SidebarProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [hubAdmin, setHubAdmin] = useState(false);
  const [hubUsername, setHubUsername] = useState("");
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [accountLoading, setAccountLoading] = useState(false);
  const [runtimeRestarting, setRuntimeRestarting] = useState(false);
  const [accountForm] = Form.useForm();
  // 当前登录用户名（资料预填用）+ 打开弹窗时记录的原始昵称（变更判定用）。
  const currentUsername = useAuthStore((s) => s.username);
  const initialDisplayNameRef = useRef<string | null>(null);
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

  // Menu + route snapshots from registry (builtin + plugin registrations merged).
  const rawPlatformMenu = useMenuItems("primary.platform");
  // Third-party plugins may still register into the legacy agentScoped bucket;
  // merge them under a trailing group so they remain reachable.
  const rawLegacyAgentMenu = useMenuItems("primary.agentScoped");
  const rawSettingsMenu = useMenuItems("primary.settings");
  const routes = useRoutes();

  // Platform menu; simple mode flattens groups via the whitelist.
  const agentMenu = useMemo(() => {
    const platformMenu =
      sidebarMode === "simple"
        ? flattenMenuForSimpleMode(rawPlatformMenu)
        : rawPlatformMenu;
    const legacy = rawLegacyAgentMenu.filter((item) => !item.isGroup);
    if (legacy.length === 0) return platformMenu;
    const pluginGroup = {
      id: "platform.plugins-group",
      label: () => t("nav.plugins", "Plugins"),
      isGroup: true,
      order: 900,
      __children: legacy.map((item) => ({
        ...item,
        parentId: "platform.plugins-group",
      })),
    } as MenuItem;
    return [...platformMenu, pluginGroup];
  }, [rawPlatformMenu, rawLegacyAgentMenu, sidebarMode, t]);
  const settingsMenu = useMemo(
    () =>
      sidebarMode === "simple"
        ? flattenMenuForSimpleMode(rawSettingsMenu)
        : rawSettingsMenu,
    [rawSettingsMenu, sidebarMode],
  );

  // Accordion groups: at most one group stays open. On startup only the
  // group holding the active item expands (fully collapsed when the active
  // item is top-level, e.g. the workbench).
  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    const initialGroup = findParentGroupId(
      [...rawPlatformMenu, ...rawSettingsMenu],
      selectedKey,
    );
    return initialGroup ? [initialGroup] : [];
  });

  // Deep links / back-forward navigation switch the open group to the one
  // containing the newly active leaf. User-initiated collapses are left
  // untouched because this only runs when the selection (or menu snapshot)
  // actually changes.
  useEffect(() => {
    const group = findParentGroupId(
      [...agentMenu, ...settingsMenu],
      selectedKey,
    );
    if (!group) return;
    setOpenKeys((prev) => (prev.includes(group) ? prev : [group]));
  }, [agentMenu, settingsMenu, selectedKey]);

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
    authApi
      .getStatus()
      .then(async (res) => {
        setAuthEnabled(res.enabled);
        if (res.mode === "hub") {
          const user = await hubApi.me();
          setHubAdmin(user.role === "admin");
          setHubUsername(user.username);
        }
      })
      .catch(() => {});
  }, []);

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
    const path = routeIdToPath(item?.route, routes);
    if (path) navigate(path);
  };

  /**
   * Session click: navigate directly without relying on ChatSessionInitializer.
   * Resolve realId (backend UUID) to avoid exposing local timestamp in URL.
   */

  const handleUpdateProfile = async (values: {
    currentPassword: string;
    newUsername?: string;
    newPassword?: string;
    displayName?: string;
  }) => {
    const trimmedUsername = values.newUsername?.trim() || undefined;
    const trimmedPassword = values.newPassword?.trim() || undefined;
    // 昵称仅在发生变化时才下发（未变则 undefined，后端不动该字段）。
    const nextDisplayName = values.displayName?.trim() ?? "";
    const displayNameChanged =
      initialDisplayNameRef.current !== null &&
      nextDisplayName !== initialDisplayNameRef.current;
    const trimmedDisplayName = displayNameChanged
      ? nextDisplayName
      : undefined;

    if (values.newPassword && !trimmedPassword) {
      message.error(t("account.passwordEmpty"));
      return;
    }

    if (values.newUsername && !trimmedUsername) {
      message.error(t("account.usernameEmpty"));
      return;
    }

    if (
      !hubMode &&
      !trimmedUsername &&
      !trimmedPassword &&
      trimmedDisplayName === undefined
    ) {
      message.warning(t("account.nothingToUpdate"));
      return;
    }

    if (hubMode && !trimmedPassword) {
      message.warning(t("account.passwordRequired"));
      return;
    }

    setAccountLoading(true);
    try {
      if (hubMode) {
        // Hub mode: the hub account's username is immutable; only the
        // password rotates (and stays logged in -- the hub JWT remains
        // valid across password changes).
        await hubApi.changePassword(trimmedPassword as string);
        message.success(t("account.updateSuccess"));
        setAccountModalOpen(false);
        accountForm.resetFields();
      } else {
        const res = await authApi.updateProfile(
          values.currentPassword,
          trimmedUsername,
          trimmedPassword,
          trimmedDisplayName,
        );
        message.success(t("account.updateSuccess"));
        setAccountModalOpen(false);
        accountForm.resetFields();
        // 仅改昵称（token 为空）保持登录态；改了用户名/密码才重新登录。
        if (res.token) {
          clearAuthToken();
          window.location.href = "/login";
        }
      }
    } catch (err: unknown) {
      const raw = err instanceof Error ? err.message : "";
      let msg = t("account.updateFailed");
      if (raw.includes("password is incorrect")) {
        msg = t("account.wrongPassword");
      } else if (raw.includes("Nothing to update")) {
        msg = t("account.nothingToUpdate");
      } else if (raw.includes("cannot be empty")) {
        msg = t("account.nothingToUpdate");
      } else if (raw) {
        msg = raw;
      }
      message.error(msg);
    } finally {
      setAccountLoading(false);
    }
  };

  /**
   * Open the account modal and prefill the current display name so the
   * nickname field reflects the saved value (change detection baseline).
   */
  const openAccountModal = async () => {
    accountForm.resetFields();
    initialDisplayNameRef.current = null;
    setAccountModalOpen(true);
    if (hubMode || !currentUsername) {
      return;
    }
    try {
      const profiles = await userProfilesApi.getProfiles([currentUsername]);
      const name = profiles.get(currentUsername)?.display_name || "";
      initialDisplayNameRef.current = name;
      accountForm.setFieldsValue({ displayName: name });
    } catch {
      // 预填失败不阻断弹窗（昵称留空，用户可手动输入）。
      initialDisplayNameRef.current = null;
    }
  };

  const handleRestartRuntime = async () => {
    setRuntimeRestarting(true);
    try {
      await hubApi.restartOwnRuntime();
      message.success(t("account.runtimeRestartSuccess"));
      window.location.reload();
    } catch (error: unknown) {
      message.error(
        error instanceof Error
          ? error.message
          : t("account.runtimeRestartFailed"),
      );
    } finally {
      setRuntimeRestarting(false);
    }
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
      {collapsed ? (
        <nav className={styles.collapsedNav}>
          {collapsedNavItems.items.map((item, index) => {
            const isActive = selectedKey === item.key;
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
                const isActive = selectedKey === entry.key;
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
              selectedKeys={[selectedKey]}
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
            selectedKeys={[selectedKey]}
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

      {authEnabled && !collapsed && (
        <div className={styles.authActions}>
          {hubAdmin && (
            <Button
              type="text"
              icon={<ShieldCheck size={16} />}
              onClick={() => navigate("/hub/admin")}
              block
              className={styles.authBtn}
            >
              {t("hub.brand.title")}
            </Button>
          )}
          <Button
            type="text"
            icon={<SparkSearchUserLine size={16} />}
            onClick={() => {
              void openAccountModal();
            }}
            block
            className={`${styles.authBtn} ${
              collapsed ? styles.authBtnCollapsed : ""
            }`}
          >
            {!collapsed && t("account.title")}
          </Button>
          <Button
            type="text"
            icon={<SparkExitFullscreenLine size={16} />}
            onClick={() => {
              clearAuthToken();
              window.location.href = "/login";
            }}
            block
            className={`${styles.authBtn} ${
              collapsed ? styles.authBtnCollapsed : ""
            }`}
          >
            {!collapsed && t("login.logout")}
          </Button>
        </div>
      )}

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

      <Modal
        open={accountModalOpen}
        onCancel={() => setAccountModalOpen(false)}
        title={t("account.title")}
        footer={null}
        destroyOnHidden
        centered
      >
        <Form
          form={accountForm}
          layout="vertical"
          onFinish={handleUpdateProfile}
        >
          {hubMode ? (
            <div className={styles.accountIdentity}>
              <span>{t("account.username")}</span>
              <strong>{hubUsername}</strong>
            </div>
          ) : (
            <>
              <Form.Item
                name="currentPassword"
                label={t("account.currentPassword")}
                rules={[
                  {
                    required: true,
                    message: t("account.currentPasswordRequired"),
                  },
                ]}
              >
                <Input.Password />
              </Form.Item>
              <Form.Item name="newUsername" label={t("account.newUsername")}>
                <Input placeholder={t("account.newUsernamePlaceholder")} />
              </Form.Item>
              <Form.Item name="displayName" label={t("account.displayName")}>
                <Input placeholder={t("account.displayNamePlaceholder")} />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="newPassword"
            label={t("account.newPassword")}
            rules={
              hubMode
                ? [
                    {
                      required: true,
                      message: t("account.passwordRequired"),
                    },
                    { min: 8, message: t("hub.validation.passwordMin") },
                  ]
                : undefined
            }
          >
            <Input.Password
              placeholder={t(
                hubMode
                  ? "account.hubPasswordPlaceholder"
                  : "account.newPasswordPlaceholder",
              )}
            />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label={t("account.confirmPassword")}
            dependencies={["newPassword"]}
            rules={[
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value && !getFieldValue("newPassword")) {
                    return Promise.resolve();
                  }
                  if (value === getFieldValue("newPassword")) {
                    return Promise.resolve();
                  }
                  return Promise.reject(
                    new Error(t("account.passwordMismatch")),
                  );
                },
              }),
            ]}
          >
            <Input.Password
              placeholder={t("account.confirmPasswordPlaceholder")}
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={accountLoading}
              block
            >
              {t("account.save")}
            </Button>
          </Form.Item>
          {hubMode && (
            <div className={styles.runtimeRecovery}>
              <Divider />
              <strong>{t("account.runtimeTitle")}</strong>
              <p>{t("account.runtimeDescription")}</p>
              <Popconfirm
                title={t("account.runtimeRestartConfirmTitle")}
                description={t("account.runtimeRestartConfirmDescription")}
                onConfirm={handleRestartRuntime}
                okText={t("account.runtimeRestart")}
                cancelText={t("common.cancel")}
              >
                <Button
                  icon={<RotateCw size={16} />}
                  loading={runtimeRestarting}
                  block
                >
                  {t("account.runtimeRestart")}
                </Button>
              </Popconfirm>
            </div>
          )}
        </Form>
      </Modal>
    </Sider>
  );
}
