/**
 * MainLayout — prototype sidebar (L986-1078) + main content area:
 * logo/version + header icons, new-task button, six nav items with Font
 * Awesome icons,「任务」/「空间」sections, user footer with bell/gear.
 * Token guard and project quick-list logic preserved from the scaffold.
 */
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import Avatar from "../components/Avatar";
import { chatApi, projectApi } from "../api/modules";
import type { ChatSummary, Project } from "../api/modules";
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
  const [projects, setProjects] = useState<Project[]>([]);
  const [chats, setChats] = useState<ChatSummary[]>([]);

  useEffect(() => {
    if (!token) {
      navigate("/login", { replace: true });
      return;
    }
    projectApi
      .list()
      .then((list) => setProjects(list.filter((p) => !p.template_tag).slice(0, 6)))
      .catch(() => setProjects([]));
    chatApi
      .list(username)
      .then((list) => setChats(list.slice(0, 5)))
      .catch(() => setChats([]));
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
              >
                <div className="nav-item-left">
                  <i className={item.icon} />
                  <span>{item.label}</span>
                </div>
              </NavLink>
            </li>
          ))}

          <div className="nav-section-header">
            <span>任务 ({chats.length})</span>
            <i className="fa-solid fa-chevron-down" />
          </div>
          {chats.map((chat) => (
            <li key={chat.id}>
              <NavLink to={`/chat?chat=${chat.id}`} className="nav-item">
                <div className="nav-item-left">
                  <span>{chat.name || "新任务"}</span>
                </div>
                <div className="nav-item-right">
                  {chat.updated_at?.slice(5, 10).replace("-", "/")}
                </div>
              </NavLink>
            </li>
          ))}

          <div className="nav-section-header">
            <span>空间 ({projects.length})</span>
            <i className="fa-solid fa-chevron-down" />
          </div>
          {projects.map((project) => (
            <li key={project.id}>
              <NavLink
                to={`/projects/${project.id}`}
                className="nav-item"
              >
                <div className="nav-item-left">
                  <i
                    className="fa-regular fa-folder"
                    style={{ color: "#64748b" }}
                  />
                  <span>{project.name}</span>
                </div>
              </NavLink>
            </li>
          ))}
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

      {/* Main content */}
      <div className="main-content">
        <Outlet />
      </div>
    </div>
  );
}
