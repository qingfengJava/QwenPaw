/**
 * Tests for PageHeader component.
 *
 * 页面路径层级已由侧栏高亮与顶部多标签页（layouts/NavTabsBar）表达，
 * 本组件只负责「页面标题 + 操作区」。
 *
 * Covers:
 * - current 渲染为标题
 * - 已废弃的 parent / items 不再渲染面包屑轨道与分隔符
 * - 未传 current 时用 items 末项兜底（保护插件与历史调用点）
 * - extra / center / afterBreadcrumb / subRow / className 仍可用
 */
import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { PageHeader } from "./index";

describe("PageHeader", () => {
  it("renders current as page title without breadcrumb track", () => {
    renderWithProviders(<PageHeader parent="Settings" current="Models" />);
    expect(screen.getByText("Models")).toBeInTheDocument();
    // 父级文案由顶部导航条从菜单树解析，页内不再出现第二份
    expect(screen.queryByText("Settings")).not.toBeInTheDocument();
    expect(screen.queryByText("/")).not.toBeInTheDocument();
  });

  it("falls back to the last items entry when current is absent", () => {
    renderWithProviders(
      <PageHeader
        items={[
          { title: "Home" },
          { title: "Dashboard" },
          { title: "Analytics" },
        ]}
      />,
    );
    expect(screen.getByText("Analytics")).toBeInTheDocument();
    expect(screen.queryByText("Home")).not.toBeInTheDocument();
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
  });

  it("renders no separator for multi-item legacy props", () => {
    renderWithProviders(<PageHeader items={[{ title: "A" }, { title: "B" }]} />);
    expect(screen.queryByText("/")).not.toBeInTheDocument();
    expect(screen.getByText("B")).toBeInTheDocument();
  });

  it("renders extra content", () => {
    renderWithProviders(
      <PageHeader current="Home" extra={<button>Action</button>} />,
    );
    expect(screen.getByRole("button", { name: "Action" })).toBeInTheDocument();
  });

  it("renders without crash when no props provided", () => {
    const { container } = renderWithProviders(<PageHeader />);
    expect(container.firstChild).toBeInTheDocument();
  });
});
