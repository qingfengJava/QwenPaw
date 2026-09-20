// @vitest-environment jsdom
/**
 * NavTabsBar.test.tsx — 顶部「面包屑 + 多标签页」导航条的交互回归。
 *
 * 钉住最易碎且用户最直接感知的几条：
 * 1. 标签文案来自菜单索引（不是 store 里的 key），菜单改名即自动跟随；
 * 2. 点击 / 键盘激活只写 store，不重复 navigate；再次点击已激活标签才回跳 URL；
 * 3. 固定首页不渲染关闭按钮；中键与 Alt+W 能关闭当前标签；
 * 4. enabled=false 时整条不渲染（改造的运行时回退通道）。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { HOME_TAB_KEY, usePageNavStore } from "../../stores/pageNavStore";
import { buildNavIndex } from "../registry/navModel";
import type { MenuItem } from "../../plugins/registry/types";
import type { RouteLike } from "../registry/navModel";
import NavTabsBar from "./index";

const navigate = vi.fn();

// 图标与 i18n 属于渲染依赖，与 Sidebar.test.tsx 同样显式 stub，避免拉全量图标包。
vi.mock("lucide-react", () => {
  const stub = () => null;
  return {
    Home: stub,
    X: stub,
    ChevronLeft: stub,
    ChevronRight: stub,
    RotateCw: stub,
    LayoutList: stub,
  };
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, second?: unknown) =>
      typeof second === "string" ? second : ((second as { defaultValue?: string })?.defaultValue ?? key),
  }),
}));

/** 受控的解析器替身：与 useNavTab 用同一份 navIndex / routes 语义。 */
const ROUTES: RouteLike[] = [
  { id: "core.workbench", path: "/workbench" },
  { id: "core.users", path: "/admin/users" },
  { id: "core.roles", path: "/admin/roles" },
];

const NAV_INDEX = buildNavIndex(
  [
    {
      id: "core.nav-admin",
      label: "平台管理",
      isGroup: true,
      __children: [
        { id: "core.nav-users", label: "用户管理", route: "/admin/users" },
        { id: "core.nav-roles", label: "角色管理", route: "/admin/roles" },
      ],
    },
  ] as unknown as MenuItem[],
  ROUTES,
);

vi.mock("../../hooks/useNavTab", () => ({
  useTabbableResolver: () => ({
    navIndex: NAV_INDEX,
    routes: ROUTES,
    menusLoaded: true,
    resolve: (pathname: string) => {
      const clean = (pathname || "/").split(/[?#]/, 1)[0].replace(/\/+$/, "") || "/";
      const entry = NAV_INDEX.byPath.get(clean);
      return entry ? { key: clean, kind: "menu" as const, navEntry: entry } : undefined;
    },
  }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

const api = () => usePageNavStore.getState();

/** 在 tablist 范围内按可见文案取标签（面包屑末项与标签同名，不能用 getByText）。 */
function findTab(label: string): HTMLElement {
  return within(screen.getByRole("tablist")).getAllByRole("tab").find((node) =>
    node.textContent?.includes(label),
  )!;
}

function open(key: string, path = key) {
  api().openTab({ key, path, kind: "menu" });
}

beforeEach(() => {
  navigate.mockClear();
  localStorage.clear();
  api().reset();
});

describe("NavTabsBar", () => {
  it("渲染 tablist，标签名取菜单名而非路径", () => {
    open("/admin/users");
    renderWithProviders(<NavTabsBar />, { initialEntries: ["/admin/users"] });

    const tablist = screen.getByRole("tablist");
    const labels = within(tablist)
      .getAllByRole("tab")
      .map((tab) => tab.textContent);
    expect(labels).toContain("用户管理");
    expect(labels).not.toContain("/admin/users");
  });

  it("当前标签高亮，面包屑显示祖先链 + 当前项", () => {
    open("/admin/users");
    const { container } = renderWithProviders(<NavTabsBar />, {
      initialEntries: ["/admin/users"],
    });
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect(tabs.find((tab) => tab.getAttribute("aria-selected") === "true")?.textContent).toContain(
      "用户管理",
    );
    expect(container.textContent).toContain("平台管理");
  });

  it("点击未激活标签只写 store，不改 URL", () => {
    open("/admin/users");
    open("/admin/roles");
    api().activate("/admin/users");
    renderWithProviders(<NavTabsBar />, { initialEntries: ["/admin/users"] });

    fireEvent.click(findTab("角色管理"));
    expect(api().activeKey).toBe("/admin/roles");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("再次点击已激活标签回到该标签对应路径（处理前进后退漂移）", () => {
    open("/admin/users", "/admin/users?page=2");
    renderWithProviders(<NavTabsBar />, { initialEntries: ["/admin/users"] });

    // 面包屑末项与标签同名，必须限定在 tablist 内取标签
    fireEvent.click(findTab("用户管理"));
    expect(navigate).toHaveBeenCalledWith("/admin/users?page=2");
  });

  it("固定首页不渲染关闭按钮，普通标签有", () => {
    open("/admin/users");
    renderWithProviders(<NavTabsBar />, { initialEntries: ["/admin/users"] });

    const tablist = screen.getByRole("tablist");
    const home = within(tablist)
      .getAllByRole("tab")
      .find((tab) => tab.textContent?.includes(HOME_TAB_KEY));
    expect(home).toBeDefined();
    expect(within(home as HTMLElement).queryByRole("button")).toBeNull();
    expect(within(tablist).getAllByRole("button").length).toBeGreaterThan(0);
  });

  it("中键按下关闭标签并阻止默认滚动", () => {
    open("/admin/users");
    renderWithProviders(<NavTabsBar />, { initialEntries: ["/admin/users"] });

    const tab = findTab("用户管理");
    // 事件类型必须用小写 "mousedown"，否则 React 的委托监听不会触发
    const event = new MouseEvent("mousedown", {
      button: 1,
      bubbles: true,
      cancelable: true,
    });
    expect(tab.dispatchEvent(event)).toBe(false);
    expect(api().tabs.some((t) => t.key === "/admin/users")).toBe(false);
  });

  it("Alt+W 关闭当前标签，输入态不劫持", () => {
    open("/admin/users");
    renderWithProviders(<NavTabsBar />, { initialEntries: ["/admin/users"] });
    expect(api().activeKey).toBe("/admin/users");

    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "w", altKey: true });
    expect(api().activeKey).toBe("/admin/users");

    fireEvent.keyDown(window, { key: "w", altKey: true });
    expect(api().activeKey).toBe(HOME_TAB_KEY);
    input.remove();
  });

  it("Alt+2 切到第二张标签", () => {
    open("/admin/users");
    open("/admin/roles");
    api().activate(HOME_TAB_KEY);
    renderWithProviders(<NavTabsBar />, { initialEntries: [HOME_TAB_KEY] });

    fireEvent.keyDown(window, { key: "2", altKey: true });
    expect(api().activeKey).toBe("/admin/users");
  });

  it("右键弹出标签操作菜单（刷新/关闭/其他/左/右/全部）", async () => {
    open("/admin/users");
    open("/admin/roles");
    renderWithProviders(<NavTabsBar />, { initialEntries: ["/admin/users"] });

    const tab = findTab("角色管理");
    fireEvent.contextMenu(tab);

    expect(await screen.findByText("Close tab")).toBeInTheDocument();
    expect(screen.getByText("Close others")).toBeInTheDocument();
    expect(screen.getByText("Close to left")).toBeInTheDocument();
    expect(screen.getByText("Close to right")).toBeInTheDocument();
    expect(screen.getByText("Close all")).toBeInTheDocument();
    expect(screen.getByText("Refresh")).toBeInTheDocument();
  });

  it("关闭开关后整条导航条不再渲染", () => {
    open("/admin/users");
    api().setEnabled(false);
    renderWithProviders(<NavTabsBar />, { initialEntries: ["/admin/users"] });
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});
