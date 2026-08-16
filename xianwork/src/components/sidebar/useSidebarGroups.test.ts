import { describe, expect, it } from "vitest";

import type {
  ChatSpecView,
  WorkspaceView,
} from "../../api/modules";
import { deriveSidebarGroups } from "./useSidebarGroups";

function ws(
  id: string,
  updatedAt: string | null | undefined,
  chats?: ChatSpecView[],
): WorkspaceView {
  return {
    id,
    name: id,
    dir_path: `D:/ws/${id}`,
    updated_at: updatedAt,
    chats,
  };
}

function chat(
  id: string,
  updatedAt: string,
  pinned = false,
): ChatSpecView {
  return {
    id,
    name: id,
    status: "idle",
    updated_at: updatedAt,
    pinned,
    session_id: `console:${id}`,
  };
}

describe("deriveSidebarGroups", () => {
  it("工作空间按 updated_at 倒序（最新在前）", () => {
    const { workspaces } = deriveSidebarGroups(
      [],
      [
        ws("old", "2026-08-01T00:00:00Z"),
        ws("newest", "2026-08-16T00:00:00Z"),
        ws("mid", "2026-08-08T00:00:00Z"),
      ],
    );
    expect(workspaces.map((w) => w.id)).toEqual(["newest", "mid", "old"]);
  });

  it("缺失 updated_at 的工作空间排最后（回落时间 0）", () => {
    const { workspaces } = deriveSidebarGroups(
      [],
      [
        ws("no-date", undefined),
        ws("dated", "2026-08-16T00:00:00Z"),
        ws("null-date", null),
      ],
    );
    expect(workspaces[0].id).toBe("dated");
    expect(
      workspaces
        .map((w) => w.id)
        .slice(1)
        .sort(),
    ).toEqual(["no-date", "null-date"]);
  });

  it("不修改传入的数组（防御性拷贝排序）", () => {
    const input = [
      ws("a", "2026-08-01T00:00:00Z"),
      ws("b", "2026-08-16T00:00:00Z"),
    ];
    deriveSidebarGroups([], input);
    expect(input.map((w) => w.id)).toEqual(["a", "b"]);
  });

  it("任务区置顶优先，其余按时间倒序", () => {
    const { unboundChats } = deriveSidebarGroups(
      [
        chat("old", "2026-07-01T00:00:00Z"),
        chat("pinned-old", "2026-07-01T00:00:00Z", true),
        chat("newest", "2026-08-16T00:00:00Z"),
        chat("pinned-new", "2026-08-10T00:00:00Z", true),
      ],
      [],
    );
    expect(unboundChats.map((c) => c.id)).toEqual([
      "pinned-new",
      "pinned-old",
      "newest",
      "old",
    ]);
  });

  it("空间组内会话同样置顶优先", () => {
    const { workspaces } = deriveSidebarGroups(
      [],
      [
        ws("w1", "2026-08-16T00:00:00Z", [
          chat("plain-new", "2026-08-16T00:00:00Z"),
          chat("pinned", "2026-08-01T00:00:00Z", true),
        ]),
      ],
    );
    expect(workspaces[0].chats?.map((c) => c.id)).toEqual([
      "pinned",
      "plain-new",
    ]);
  });
});
