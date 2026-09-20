// @vitest-environment jsdom
/**
 * MainLayout.test.tsx — 顶部多标签页「URL ↔ 标签」双向同步回归。
 *
 * 钉死 2026-09 修复的频闪死循环：点击侧栏菜单（URL 变化）后，「标签→URL」
 * 方向若用本渲染快照的旧 activeKey 比较，会把刚落地的新 URL 误判为漂移并
 * 弹回旧标签；「URL→标签」再纠正回来，两个 effect 互相追逐，URL 在
 * `/A ↔ /B` 之间无限交换（表现为点菜单后 tab 与页面高频互换）。
 *
 * 断言要点：导航到新页面后 URL 必须稳定停在新页面，且 400ms 观察窗内
 * 不再发生任何漂移；activeKey 同步到新 URL。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useLocation, useNavigate } from "react-router-dom";
import { renderWithProviders } from "@/test/common_setup";
import { usePageNavStore } from "../../stores/pageNavStore";
import { buildNavIndex } from "../registry/navModel";
import type { MenuItem } from "../../plugins/registry/types";
import MainLayout from "./index";

// 受控路由表：id/path 供 matchRouteId 解析，Component 供 <Routes> 渲染。
const ROUTES = [
  {
    id: "core.workbench",
    path: "/workbench",
    Component: () => <div data-testid="page-workbench" />,
  },
  {
    id: "core.inbox",
    path: "/inbox",
    Component: () => <div data-testid="page-inbox" />,
  },
  {
    id: "core.channels",
    path: "/channels",
    Component: () => <div data-testid="page-channels" />,
  },
];

const NAV_INDEX = buildNavIndex(
  [
    {
      id: "core.nav-group",
      label: "员工与通道",
      isGroup: true,
      __children: [
        { id: "core.nav-workbench", label: "工作台", route: "/workbench" },
        { id: "core.nav-inbox", label: "收件箱", route: "/inbox" },
        { id: "core.nav-channels", label: "渠道接入", route: "/channels" },
      ],
    },
  ] as unknown as MenuItem[],
  ROUTES,
);

// ── 重依赖替身：本测试只关心两个同步 effect 的行为 ───────────────────────
// 解析器必须返回模块级稳定快照：真实 useTabbableResolver 的 resolve 是
// useCallback 稳定的，若 mock 每帧新建引用，方向一 effect 会因依赖漂移
// 反复 openTab，自己就会触发 Maximum update depth（与本次回归无关）。
const RESOLVER_SNAPSHOT = {
  navIndex: NAV_INDEX,
  routes: ROUTES,
  menusLoaded: true,
  resolve: (pathname: string) => {
    const clean =
      (pathname || "/").split(/[?#]/, 1)[0].replace(/\/+$/, "") || "/";
    const entry = NAV_INDEX.byPath.get(clean);
    return entry
      ? { key: clean, kind: "menu" as const, navEntry: entry }
      : undefined;
  },
};

vi.mock("../../hooks/useNavTab", () => ({
  useTabbableResolver: () => RESOLVER_SNAPSHOT,
}));
vi.mock("../Sidebar", () => ({ default: () => null }));
vi.mock("../Header", () => ({ default: () => null }));
vi.mock("../NavTabsBar", () => ({ default: () => null }));
vi.mock("../../components/ConsolePollService", () => ({ default: () => null }));
vi.mock("../../components/AgentStatusPollingController", () => ({
  AgentStatusPollingController: () => null,
}));
vi.mock("../../components/ChunkErrorBoundary", () => ({
  ChunkErrorBoundary: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../../stores/useSyncCodingMode", () => ({ useSyncCodingMode: () => {} }));
vi.mock("../registry/dynamicRoutes", () => ({ buildDynamicRoutes: () => [] }));
vi.mock("../../plugins/registry/hooks", () => ({ useRoutes: () => ROUTES }));
vi.mock("../../plugins/registry/Slot", () => ({ Slot: () => null }));

const api = () => usePageNavStore.getState();

/** 当前位置探针：MemoryRouter 不写 window.location，用 useLocation 读取。 */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

/** 模拟侧栏菜单点击：真实场景中 Sidebar 就是调用 navigate(真实 path)。 */
function NavTrigger({ to }: { to: string }) {
  const navigate = useNavigate();
  return (
    <button data-testid="nav-trigger" onClick={() => navigate(to)}>
      go
    </button>
  );
}

beforeEach(() => {
  localStorage.clear();
  api().reset();
});

describe("MainLayout 标签页双向同步", () => {
  it("侧栏导航到新页面后 URL 稳定不被弹回旧标签（防 ping-pong 死循环）", async () => {
    // 先进入收件箱（上一张激活标签是 /inbox）
    api().openTab({ key: "/inbox", path: "/inbox", kind: "menu" });

    renderWithProviders(
      <>
        <MainLayout />
        <LocationProbe />
        <NavTrigger to="/channels" />
      </>,
      { initialEntries: ["/inbox"] },
    );

    // 初始稳定：URL 与激活标签都在收件箱
    await waitFor(() => expect(api().activeKey).toBe("/inbox"));
    expect(screen.getByTestId("location-probe").textContent).toBe("/inbox");

    // 点击「渠道接入」等价导航
    fireEvent.click(screen.getByTestId("nav-trigger"));

    // 新页面落地且标签同步
    await waitFor(() =>
      expect(screen.getByTestId("location-probe").textContent).toBe("/channels"),
    );
    await waitFor(() => expect(api().activeKey).toBe("/channels"));

    // 观察窗：若两个同步 effect 仍在互相追逐，此处 URL 会漂回 /inbox
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(screen.getByTestId("location-probe").textContent).toBe("/channels");
    expect(api().activeKey).toBe("/channels");
  });

  it("点击标签激活（只写 store）后 URL 跟随到该标签路径", async () => {
    api().openTab({ key: "/inbox", path: "/inbox", kind: "menu" });
    api().openTab({ key: "/channels", path: "/channels", kind: "menu" });

    renderWithProviders(
      <>
        <MainLayout />
        <LocationProbe />
      </>,
      { initialEntries: ["/channels"] },
    );
    await waitFor(() => expect(api().activeKey).toBe("/channels"));

    // 模拟点击「收件箱」标签：NavTabsBar 对未激活标签只调 activate
    await act(async () => {
      api().activate("/inbox");
    });

    await waitFor(() =>
      expect(screen.getByTestId("location-probe").textContent).toBe("/inbox"),
    );
    expect(api().activeKey).toBe("/inbox");
  });
});