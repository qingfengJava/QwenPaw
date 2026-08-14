/**
 * MainLayout — WorkBuddy-style shell: brand + new-task button, primary
 * nav (assistant / projects / experts / automation / library), project
 * quick list, and the signed-in identity in the footer.
 */
import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/auth";
import { projectApi } from "../api/modules";
import type { Project } from "../api/modules";

const NAV_ITEMS = [
  { to: "/chat", label: "助理", icon: "💬" },
  { to: "/projects", label: "项目", icon: "🗂" },
  { to: "/experts", label: "专家 · 技能 · 连接器", icon: "🧠" },
  { to: "/automation", label: "自动化", icon: "⏱" },
  { to: "/library", label: "资料库", icon: "📚" },
];

export default function MainLayout() {
  const navigate = useNavigate();
  const { token, username, signOut } = useAuthStore();
  const [projects, setProjects] = useState<Project[]>([]);

  useEffect(() => {
    if (!token) {
      navigate("/login", { replace: true });
      return;
    }
    projectApi
      .list()
      .then((list) => setProjects(list.slice(0, 6)))
      .catch(() => setProjects([]));
  }, [token, navigate]);

  const initial = username ? username[0].toUpperCase() : "U";

  return (
    <div className="xian-app">
      <aside className="xian-sidebar">
        <div className="xian-sidebar-header">
          <div className="xian-logo">
            <span className="xian-logo-title">XianWork</span>
            <span className="xian-logo-sub">企业智能工作台</span>
          </div>
          <button
            className="xian-new-task"
            onClick={() => navigate("/")}
            type="button"
          >
            ＋ 新建任务
          </button>
        </div>

        <ul className="xian-nav">
          <li className="xian-nav-section">功能</li>
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  `xian-nav-item${isActive ? " active" : ""}`
                }
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
              </NavLink>
            </li>
          ))}

          <li className="xian-nav-section">项目空间</li>
          {projects.map((project) => (
            <li key={project.id}>
              <NavLink
                to={`/projects/${project.id}`}
                className={({ isActive }) =>
                  `xian-nav-item${isActive ? " active" : ""}`
                }
              >
                <span>📁</span>
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {project.name}
                </span>
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="xian-sidebar-footer">
          <div className="xian-user">
            <div className="xian-avatar">{initial}</div>
            <span style={{ fontWeight: 600 }}>{username || "本地用户"}</span>
          </div>
          <button
            type="button"
            onClick={() => {
              signOut();
              navigate("/login", { replace: true });
            }}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              color: "var(--text-muted)",
            }}
            title="退出登录"
          >
            ⎋
          </button>
        </div>
      </aside>

      <main className="xian-main">
        <Outlet />
      </main>
    </div>
  );
}
