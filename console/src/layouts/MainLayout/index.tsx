import { Suspense, useEffect, useMemo } from "react";
import { Layout, Spin } from "antd";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Sidebar from "../Sidebar";
import Header from "../Header";
import NavTabsBar from "../NavTabsBar";
import ConsolePollService from "../../components/ConsolePollService";
import { AgentStatusPollingController } from "../../components/AgentStatusPollingController";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import { usePermissionStore } from "../../stores/permissionStore";
import { useAuthStore } from "../../stores/authStore";
import { usePageNavStore } from "../../stores/pageNavStore";
import { useTabbableResolver } from "../../hooks/useNavTab";
import { normalizeTabKey } from "../../layouts/registry/navModel";
import { buildDynamicRoutes } from "../registry/dynamicRoutes";
import { useSyncCodingMode } from "../../stores/useSyncCodingMode";
import styles from "../index.module.less";
import { useRoutes } from "../../plugins/registry/hooks";
import { Slot } from "../../plugins/registry/Slot";

const { Content } = Layout;

export default function MainLayout({ hubMode = false }: { hubMode?: boolean }) {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;
  const routes = useRoutes();

  // Backend is the source of truth for Coding Mode state — refill the
  // in-memory store every time the selected agent changes.
  useSyncCodingMode();

  // PawApp inline routes (`/apps/<id>`) are rendered *inside* the App Center
  // page (with its "← App Center" bar), never as standalone full-page routes.
  // They stay in the registry so the App Center can look up their component;
  // we just skip them here. The App Center's own `/apps/:appId` route (with a
  // colon) is kept, so a deep-link / refresh lands on the App Center wrapper.
  const renderableRoutes = useMemo(
    () => routes.filter((r) => !/^\/apps\/(?!:)/.test(r.path)),
    [routes],
  );

  // 动态路由：菜单 component → 懒加载页面，与内置路由按 path 去重，
  // 内置优先（不覆盖 chat/agent-detail/redirect 等功能路由）。
  const menus = usePermissionStore((s) => s.menus);
  const allRoutes = useMemo(() => {
    const existingPaths = new Set(
      renderableRoutes.map((r) => r.path),
    );
    const dynamic = buildDynamicRoutes(menus).filter(
      (r) => !existingPaths.has(r.path),
    );
    return [...renderableRoutes, ...dynamic];
  }, [renderableRoutes, menus]);

  // ── 顶部多标签页：URL 与标签状态双向同步 ────────────────────────────────
  const { resolve, navIndex } = useTabbableResolver();
  const navEnabled = usePageNavStore((s) => s.enabled);
  const tabs = usePageNavStore((s) => s.tabs);
  const activeKey = usePageNavStore((s) => s.activeKey);
  const openTab = usePageNavStore((s) => s.openTab);
  const pruneTabs = usePageNavStore((s) => s.prune);
  const refreshNonce = usePageNavStore((s) => s.refreshNonce);
  const setOwner = usePageNavStore((s) => s.setOwner);
  const username = useAuthStore((s) => s.username);

  // 标签会话绑定登录身份：换账号（含登出后重新登录）自动丢弃上一位用户的标签。
  useEffect(() => {
    setOwner(username);
  }, [username, setOwner]);

  // 方向一：URL → 标签。落到可标签化路径就打开/复用对应标签。
  useEffect(() => {
    if (!navEnabled) return;
    const hit = resolve(location.pathname);
    if (!hit) return;
    openTab({
      key: hit.key,
      path: location.pathname + location.search,
      kind: hit.kind,
    });
  }, [navEnabled, location.pathname, location.search, openTab, resolve]);

  // 方向二：标签 → URL。仅当激活标签与当前路径确实不是同一页时才导航，
  // 导航落地后两侧 key 相等，effect 自然停止，不会形成回环。
  //
  // 必须读取 store 的最新状态（getState）而不是本渲染快照：方向一在同一个
  // commit 的 effect 阶段刚把 activeKey 同步到新 URL，快照里的旧 activeKey
  // 会把这次导航误判成「标签漂移」并弹回旧标签；方向一再纠正回来，两个
  // effect 互相追逐，URL 在 /A ↔ /B 之间无限交换（点击菜单后页面频闪）。
  useEffect(() => {
    if (!navEnabled) return;
    const { tabs: latestTabs, activeKey: latestActiveKey } =
      usePageNavStore.getState();
    const tab = latestTabs.find((item) => item.key === latestActiveKey);
    if (!tab) return;
    const currentKey =
      resolve(location.pathname)?.key ?? normalizeTabKey(location.pathname);
    if (currentKey === latestActiveKey) return;
    navigate(tab.path);
  }, [navEnabled, tabs, activeKey, location.pathname, navigate, resolve]);

  // 权限/菜单变更后剔除已失效的菜单页标签，避免点开白屏的死标签。
  useEffect(() => {
    if (!navEnabled) return;
    pruneTabs(Array.from(navIndex.byPath.keys()).map((path) => normalizeTabKey(path)));
  }, [navEnabled, navIndex, pruneTabs]);

  return (
    <Layout className={styles.mainLayout}>
      <Header hubMode={hubMode} />
      <Layout>
        <Sidebar />
        <Content className="page-container">
          <ConsolePollService />
          <AgentStatusPollingController />
          <Slot name="content.statusBar" kind="fill" />
          <NavTabsBar />
          <div className="page-content" id="page-content-region">
            <ChunkErrorBoundary
              resetKey={`${currentPath}#${refreshNonce}`}
              canRestartRuntime={hubMode}
            >
              <Suspense
                fallback={
                  /* antd Spin 的 tip 仅支持嵌套/全屏形态：自闭合用法下 tip 本就不渲染，省略以避免控制台告警 */
                  <Spin
                    style={{ display: "block", margin: "20vh auto" }}
                  />
                }
              >
                <Routes>
                  {allRoutes.map((r) => (
                    <Route key={r.id} path={r.path} element={<r.Component />} />
                  ))}
                </Routes>
              </Suspense>
            </ChunkErrorBoundary>
          </div>
        </Content>
      </Layout>
      <Slot name="overlay.global" kind="fill" />
    </Layout>
  );
}
