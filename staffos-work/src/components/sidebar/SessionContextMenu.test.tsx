// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContextMenu } from "./SessionContextMenu";
import SessionContextMenu from "./SessionContextMenu";

// vitest runs without globals, so Testing Library's auto-cleanup never
// registers; without this, DOM from earlier `it` blocks leaks into the
// next query and getByText finds stale menus.
afterEach(cleanup);

const anchor = { x: 10, y: 10 };

function renderMenu(overrides: Partial<Parameters<typeof SessionContextMenu>[0]> = {}) {
  const handlers = {
    onBatchMode: vi.fn(),
    onOpenFolder: vi.fn(),
    onRename: vi.fn(),
    onSaveToWorkspace: vi.fn(),
    onShare: vi.fn(),
    onDelete: vi.fn(),
    onClose: vi.fn(),
  };
  const view = render(
    <SessionContextMenu
      anchor={anchor}
      chatName="任务"
      {...handlers}
      {...overrides}
    />,
  );
  return { ...handlers, ...view };
}

describe("SessionContextMenu", () => {
  it("渲染截图规格的六项菜单（顺序一致）", () => {
    renderMenu();
    const items = screen.getAllByRole("menuitem");
    expect(items.map((el) => el.textContent)).toEqual([
      "批量操作",
      "打开文件夹",
      "重命名",
      "保存到工作空间",
      "分享任务",
      "删除任务",
    ]);
  });

  it("anchor 为 null 时不渲染任何内容", () => {
    const { container } = renderMenu({ anchor: null });
    expect(container.innerHTML).toBe("");
  });

  it("点击菜单项先关闭菜单再派发动作", () => {
    const h = renderMenu();
    fireEvent.click(screen.getByText("重命名"));
    expect(h.onClose).toHaveBeenCalledTimes(1);
    expect(h.onRename).toHaveBeenCalledTimes(1);
  });

  it("删除任务为危险项（danger 样式）且点击派发 onDelete", () => {
    const h = renderMenu();
    const deleteItem = screen.getByText("删除任务").closest("button");
    expect(deleteItem?.className).toContain("danger");
    fireEvent.click(screen.getByText("删除任务"));
    expect(h.onDelete).toHaveBeenCalledTimes(1);
  });
});

describe("ContextMenu（通用右键菜单基座）", () => {
  it("禁用项不派发 onClick", () => {
    const onClick = vi.fn();
    const onClose = vi.fn();
    render(
      <ContextMenu
        anchor={anchor}
        entries={[
          { key: "a", label: "可用", icon: "fa-x", onClick },
          { key: "b", label: "禁用", icon: "fa-x", disabled: true, onClick },
        ]}
        onClose={onClose}
      />,
    );
    const items = screen.getAllByRole("menuitem");
    expect((items[1] as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(items[1]);
    expect(onClick).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("Escape 关闭菜单", () => {
    const onClose = vi.fn();
    render(
      <ContextMenu
        anchor={anchor}
        entries={[{ key: "a", label: "项", icon: "fa-x" }]}
        onClose={onClose}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
