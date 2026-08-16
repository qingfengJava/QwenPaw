// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import ChatListItem from "./ChatListItem";
import type { ChatSpecView } from "../../api/modules";

// vitest runs without globals, so Testing Library's auto-cleanup never
// registers; earlier `it` DOM would leak into later queries without this.
afterEach(cleanup);

function chat(overrides: Partial<ChatSpecView> = {}): ChatSpecView {
  return {
    id: "c1",
    name: "任务一",
    status: "idle",
    updated_at: "2026-08-16T11:00:00Z",
    pinned: false,
    session_id: "console:alice",
    ...overrides,
  };
}

function renderItem(overrides: Partial<ChatSpecView> = {}) {
  const handlers = {
    onRenamingChange: vi.fn(),
    onToggleCheck: vi.fn(),
    onOpenMenu: vi.fn(),
    onRenamed: vi.fn(),
    onArchive: vi.fn(),
    onTogglePin: vi.fn(),
  };
  const view = render(
    <MemoryRouter>
      <ChatListItem
        chat={chat(overrides)}
        active={false}
        batchMode={false}
        checked={false}
        renaming={false}
        {...handlers}
      />
    </MemoryRouter>,
  );
  return { ...handlers, ...view };
}

describe("ChatListItem 悬停操作组", () => {
  it("渲染 更多/归档/置顶 三个按钮（截图规格）", () => {
    renderItem();
    expect(screen.getByTitle("更多操作")).toBeTruthy();
    expect(screen.getByTitle("归档")).toBeTruthy();
    expect(screen.getByTitle("置顶")).toBeTruthy();
  });

  it("点击「更多」以按钮位置为锚点打开菜单（不导航）", () => {
    const h = renderItem();
    fireEvent.click(screen.getByTitle("更多操作"));
    expect(h.onOpenMenu).toHaveBeenCalledTimes(1);
    const [openedChat, anchor] = h.onOpenMenu.mock.calls[0];
    expect(openedChat.id).toBe("c1");
    expect(anchor).toEqual({ x: expect.any(Number), y: expect.any(Number) });
  });

  it("点击「归档」与「置顶」直接派发对应动作", () => {
    const h = renderItem();
    fireEvent.click(screen.getByTitle("归档"));
    expect(h.onArchive).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTitle("置顶"));
    expect(h.onTogglePin).toHaveBeenCalledTimes(1);
  });

  it("右键同样打开菜单（锚点为鼠标坐标）", () => {
    const h = renderItem();
    const row = screen.getByText("任务一").closest(".chat-row")!;
    fireEvent.contextMenu(row, {
      clientX: 100,
      clientY: 200,
    });
    expect(h.onOpenMenu).toHaveBeenCalledTimes(1);
    const [, anchor] = h.onOpenMenu.mock.calls[0];
    expect(anchor).toEqual({ x: 100, y: 200 });
  });

  it("已置顶任务：按钮高亮 + 行首置顶指示", () => {
    renderItem({ pinned: true });
    const pinBtn = screen.getByTitle("取消置顶");
    expect(pinBtn.className).toContain("pinned");
    expect(screen.getByTitle("已置顶")).toBeTruthy();
  });

  it("回复中的任务归档按钮禁用", () => {
    renderItem({ status: "running" });
    expect(
      (screen.getByTitle("归档") as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("批量模式不渲染操作组，改为复选框", () => {
    const handlers = {
      onRenamingChange: vi.fn(),
      onToggleCheck: vi.fn(),
      onOpenMenu: vi.fn(),
      onRenamed: vi.fn(),
      onArchive: vi.fn(),
      onTogglePin: vi.fn(),
    };
    render(
      <MemoryRouter>
        <ChatListItem
          chat={chat()}
          active={false}
          batchMode
          checked
          renaming={false}
          {...handlers}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByTitle("更多操作")).toBeNull();
    expect(screen.queryByTitle("归档")).toBeNull();
    expect(screen.queryByTitle("置顶")).toBeNull();
    expect(
      (screen.getByRole("checkbox") as HTMLInputElement).checked,
    ).toBe(true);
  });
});
