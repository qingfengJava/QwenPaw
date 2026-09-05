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
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
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
import { hubApi } from "../api/modules/hub";
import api from "../api";
import { useSidebarModeStore } from "../stores/sidebarModeStore";
import { useInboxWobble } from "../hooks/useInboxWobble";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { useMenuItems, useRoutes } from "../plugins/registry/hooks";
import { Slot } from "../plugins/registry/Slot";
import {
  deriveOpenKeys,
  findMenuItem,
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

  // Collapsible groups: start fully expanded; the user can collapse each
  // group by clicking its title (see handleOpenChange below).
  const [openKeys, setOpenKeys] = useState<string[]>(() => [
    ...deriveOpenKeys(rawPlatformMenu),
    ...deriveOpenKeys(rawSettingsMenu),
  ]);

  // Groups registered later (plugins, async agent capabilities) should also
  // start expanded; merging only adds missing keys so user-collapsed groups
  // are left untouched between menu recomputations.
  useEffect(() => {
    const defaults = [
      ...deriveOpenKeys(agentMenu),
      ...deriveOpenKeys(settingsMenu),
    ];
    setOpenKeys((prev) => {
      const merged = new Set([...prev, ...defaults]);
      return merged.size === prev.length ? prev : [...merged];
    });
  }, [agentMenu, settingsMenu]);

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
    const flat = [
      ...flattenMenu(agentMenu, routes, 18),
      ...flattenMenu(settingsMenu, routes, 18),
    ];
    return flat.map((entry) =>
      entry.key === "core.inbox"
        ? { ...entry, icon: decorateInboxIcon(entry.icon) }
        : entry,
    );
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
  }) => {
    const trimmedUsername = values.newUsername?.trim() || undefined;
    const trimmedPassword = values.newPassword?.trim() || undefined;

    if (values.newPassword && !trimmedPassword) {
      message.error(t("account.passwordEmpty"));
      return;
    }

    if (values.newUsername && !trimmedUsername) {
      message.error(t("account.usernameEmpty"));
      return;
    }

    if (!hubMode && !trimmedUsername && !trimmedPassword) {
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
        await authApi.updateProfile(
          values.currentPassword,
          trimmedUsername,
          trimmedPassword,
        );
        message.success(t("account.updateSuccess"));
        setAccountModalOpen(false);
        accountForm.resetFields();
        clearAuthToken();
        window.location.href = "/login";
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
          {collapsedNavItems.map((item) => {
            const isActive = selectedKey === item.key;
            return (
              <Tooltip
                key={item.key}
                title={item.label}
                placement="right"
                overlayInnerStyle={{
                  background: "rgba(0,0,0,0.75)",
                  color: "#fff",
                }}
              >
                <button
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
              onOpenChange={(keys) => setOpenKeys(keys as string[])}
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
            onOpenChange={(keys) => setOpenKeys(keys as string[])}
            onClick={({ key }) => handleMenuClick(String(key), settingsMenu)}
            items={settingsMenuItems}
            theme={isDark ? "dark" : "light"}
            className={styles.sideMenu}
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
              accountForm.resetFields();
              setAccountModalOpen(true);
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
