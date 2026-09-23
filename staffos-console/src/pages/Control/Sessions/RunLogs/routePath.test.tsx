/**
 * routePath 工具单测 + 工作台沙箱相对导航越界的表征测试。
 *
 * 背景：工作台（/studio/:aid）沙箱右栏改为按 pathname 条件渲染，子页面没有
 * <Route> 匹配上下文。此时相对导航会以 "/" 为基准解析（越界），useParams 返回
 * 空。routePath 工具用「当前 pathname 派生绝对路径」规避该问题，两套壳通用。
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useResolvedPath } from "react-router-dom";

import {
  buildRunDetailPath,
  buildSessionsListPath,
  parseRunDetailPath,
} from "./routePath";

describe("buildRunDetailPath", () => {
  it.each(["/studio", "/agents"] as const)(
    "在 %s 壳下由会话列表页派生详情页绝对路径",
    (prefix) => {
      expect(buildRunDetailPath(`${prefix}/agentA/sessions`, "run123")).toBe(
        `${prefix}/agentA/sessions/runs/run123`,
      );
    },
  );

  it("容忍尾斜杠，不产生双斜杠", () => {
    expect(buildRunDetailPath("/studio/agentA/sessions/", "run123")).toBe(
      "/studio/agentA/sessions/runs/run123",
    );
  });
});

describe("parseRunDetailPath", () => {
  it.each(["/studio", "/agents"] as const)(
    "在 %s 壳下解析出 aid 与 runId",
    (prefix) => {
      expect(
        parseRunDetailPath(`${prefix}/agentA/sessions/runs/run123`),
      ).toEqual({ aid: "agentA", runId: "run123" });
    },
  );

  it("兼容带前缀/草稿后缀的 aid", () => {
    expect(
      parseRunDetailPath("/studio/expert_1__draft/sessions/runs/abc"),
    ).toEqual({ aid: "expert_1__draft", runId: "abc" });
  });

  it("非详情页路径返回 null", () => {
    expect(parseRunDetailPath("/studio/agentA/sessions")).toBeNull();
  });
});

describe("buildSessionsListPath", () => {
  it.each(["/studio", "/agents"] as const)(
    "在 %s 壳下由详情页返回会话列表页",
    (prefix) => {
      expect(
        buildSessionsListPath(`${prefix}/agentA/sessions/runs/run123`),
      ).toBe(`${prefix}/agentA/sessions`);
    },
  );
});

describe("列表 → 详情 → 返回 往返一致", () => {
  it.each(["/studio", "/agents"] as const)("%s 壳往返路径闭环", (prefix) => {
    const list = `${prefix}/agentA/sessions`;
    const detail = buildRunDetailPath(list, "run123");
    expect(parseRunDetailPath(detail)).toEqual({
      aid: "agentA",
      runId: "run123",
    });
    expect(buildSessionsListPath(detail)).toBe(list);
  });
});

/**
 * 表征测试：证明「无 <Routes> 的沙箱」里相对导航会越界到 "/"，
 * 这正是必须改用绝对路径派生（routePath）的原因。
 */
describe("沙箱相对导航语义（根因表征）", () => {
  it("无 <Routes> 时 'runs/x' 与 '../sessions' 均解析到根路径（越界）", () => {
    const store: { forward?: string; back?: string } = {};

    function Probe() {
      // 与旧 RunLogsPage / RunLogDetailPage 一致的相对写法。
      store.forward = useResolvedPath("runs/run123").pathname;
      store.back = useResolvedPath("../sessions").pathname;
      return null;
    }

    render(
      <MemoryRouter initialEntries={["/studio/agentA/sessions"]}>
        {/* 复刻工作台沙箱：直接渲染组件，外层没有 <Routes>/<Route>。 */}
        <Probe />
      </MemoryRouter>,
    );

    // 空 route 匹配 → 基准退化为 "/"，相对段被拼到根路径。
    expect(store.forward).toBe("/runs/run123");
    expect(store.back).toBe("/sessions");
  });

  it("有嵌套 <Routes> 时同样的相对写法才解析正确（对照 /agents 壳）", () => {
    function Shell({
      url,
      store,
    }: {
      url: string;
      store: { forward?: string; back?: string };
    }) {
      function Probe() {
        store.forward = useResolvedPath("runs/run123").pathname;
        store.back = useResolvedPath("../sessions").pathname;
        return null;
      }
      return (
        <MemoryRouter initialEntries={[url]}>
          <Routes>
            <Route
              path="/agents/:aid/*"
              element={
                <Routes>
                  <Route path="sessions" element={<Probe />} />
                  <Route path="sessions/runs/:runId" element={<Probe />} />
                </Routes>
              }
            />
          </Routes>
        </MemoryRouter>
      );
    }

    // 前进：列表页（…/sessions）下 'runs/x' 相对 sessions 路由解析。
    const listStore: { forward?: string; back?: string } = {};
    render(<Shell url="/agents/agentA/sessions" store={listStore} />);
    expect(listStore.forward).toBe("/agents/agentA/sessions/runs/run123");

    // 返回：详情页（…/sessions/runs/:runId）下 '../sessions' 落回列表。
    const detailStore: { forward?: string; back?: string } = {};
    render(
      <Shell
        url="/agents/agentA/sessions/runs/run123"
        store={detailStore}
      />,
    );
    expect(detailStore.back).toBe("/agents/agentA/sessions");
  });
});
