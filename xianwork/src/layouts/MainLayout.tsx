/**
 * MainLayout — layout shell only: sidebar chrome (logo/version, header
 * icons, new-task button, six nav items, user footer) + the routed
 * content area. The task/workspace tree and its whole interaction state
 * machine live in <SidebarChatTree />; the old projectApi quick-list is
 * gone (collaboration projects ≠ disk workspaces).
 *
 * Flicker fix: the sidebar stays mounted; only the main content area
 * suspends (equal-height skeleton) while a lazy page chunk loads. Nav
 * hover prefetches the target chunk so first clicks rarely suspend.
 */
import { Suspense, useEffect } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import Avatar from "../components/Avatar";
import SidebarChatTree from "../components/sidebar/SidebarChatTree";
import { useAuthStore } from "../stores/auth";

const APP_VERSION = "v0.1.0";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  match?: string[];
}

const NAV_ITEMS: NavItem[] = [
  { to: "/chat", label: "助理", icon: "fa-regular fa-user" },
  {
    to: "/projects",
    label: "项目",
    icon: "fa-solid fa-layer-group",
    match: ["/projects"],
  },
  { to: "/experts", label: "专家·技能·连接器", icon: "fa-solid fa-link" },
  { to: "/automation", label: "自动化", icon: "fa-regular fa-clock" },
  { to: "/library", label: "资料库", icon: "fa-regular fa-folder" },
  { to: "/more", label: "更多", icon: "fa-solid fa-border-all" },
];

/** Nav hover prefetch (dynamic import is idempotent — repeated hits noop). */
const PAGE_PRELOADS: Record<string, () => Promise<unknown>> = {
  "/chat": () => import("../pages/Chat"),
  "/projects": () => import("../pages/Projects"),
  "/experts": () => import("../pages/Experts"),
  "/automation": () => import("../pages/Automation"),
  "/library": () => import("../pages/Library"),
  "/more": () => import("../pages/More"),
};

function navActive(item: NavItem, path: string): boolean {
  if (item.match) {
    return item.match.some((prefix) => path.startsWith(prefix));
  }
  return path === item.to || path.startsWith(`${item.to}/`);
}

export default function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { token, username, signOut } = useAuthStore();

  useEffect(() => {
    if (!token) {
      navigate("/login", { replace: true });
    }
  }, [token, navigate]);

  return (
    <div className="app-shell">
      {/* Sidebar (prototype L986-1078) */}
      <div className="sidebar">
        <div className="sidebar-header">
          <div
            className="logo-area"
            style={{ cursor: "pointer" }}
            onClick={() => navigate("/")}
            title="回到首页"
          >
            <div className="logo-title">
              XianWork
              <span className="logo-version">{APP_VERSION}</span>
            </div>
            <div className="header-icons">
              <i className="fa-regular fa-square" title="窗口" />
              <i className="fa-solid fa-magnifying-glass" title="搜索" />
              <i className="fa-solid fa-filter" title="筛选" />
            </div>
          </div>

          <button
            type="button"
            className="new-task-btn"
            onClick={() => navigate("/")}
          >
            <i className="fa-solid fa-plus" />
            <span>新建任务</span>
          </button>
        </div>

        <ul className="nav-list">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={() =>
                  `nav-item${navActive(item, location.pathname) ? " active" : ""}`
                }
                onMouseEnter={() => PAGE_PRELOADS[item.to]?.()}
              >
                <div className="nav-item-left">
                  <i className={item.icon} />
                  <span>{item.label}</span>
                </div>
              </NavLink>
            </li>
          ))}

          {/* 任务 / 空间 tree + context menus + modals */}
          <SidebarChatTree />
        </ul>

        <div className="sidebar-footer">
          <div className="user-info" title={username || "本地用户"}>
            <Avatar name={username || "local"} size={28} />
            <span className="user-name">{username || "本地用户"}</span>
          </div>
          <div className="footer-icons">
            <i className="fa-regular fa-bell" title="通知" />
            <i
              className="fa-solid fa-arrow-right-from-bracket"
              title="退出登录"
              onClick={() => {
                signOut();
                navigate("/login", { replace: true });
              }}
            />
          </div>
        </div>
      </div>

      {/* Main content — only this area waits for lazy chunks; the sidebar
       * stays mounted so route switches never flash the whole tree. */}
      <div className="main-content">
        <Suspense fallback={<div className="page-loading" />}>
          <Outlet />
        </Suspense>
      </div>
    </div>
  );
}
