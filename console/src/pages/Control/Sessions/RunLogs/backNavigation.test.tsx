/**
 * 运行日志详情页「返回」导航回归测试。
 *
 * 详情页挂在 splat 路由（/studio/:aid/* 或 /agents/:aid/*）之下的
 * sessions/runs/:runId。React Router 的相对路径按 route 层级解析：
 * "../.." 会越过父级 splat 解析到根路径 "/"，触发工作台
 * CatchAllNavigate 兜底重定向，导致整个工作台卸载重挂（表现为
 * 整页刷新）。返回目标必须用 "../sessions"（落回会话 Tab 列表）。
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
  useResolvedPath,
} from "react-router-dom";

interface ResolutionStore {
  backToList?: string;
  backBeyondSplat?: string;
}

function Inner({ store }: { store: ResolutionStore }) {
  function Probe() {
    // 与 RunLogDetailPage 返回按钮一致的写法。
    store.backToList = useResolvedPath("../sessions").pathname;
    // 曾经的错误写法（解析到根路径，跳出沙箱）。
    store.backBeyondSplat = useResolvedPath("../..").pathname;
    return null;
  }

  return (
    <Routes>
      <Route index element={<Probe />} />
      <Route path="sessions" element={<Probe />} />
      <Route path="sessions/runs/:runId" element={<Probe />} />
      <Route path="*" element={<Probe />} />
    </Routes>
  );
}

describe("RunLogDetailPage 返回导航目标解析", () => {
  it.each(["/studio", "/agents"] as const)(
    "在 %s 壳下 '../sessions' 解析到会话列表，'../..' 会越界到根路径（禁止使用）",
    (prefix) => {
      const store: ResolutionStore = {};
      render(
        <MemoryRouter initialEntries={[`${prefix}/agentA/sessions/runs/run123`]}>
          <Routes>
            <Route path={`${prefix}/:aid/*`} element={<Inner store={store} />} />
          </Routes>
        </MemoryRouter>,
      );
      expect(store.backToList).toBe(`${prefix}/agentA/sessions`);
      expect(store.backBeyondSplat).toBe("/");
    },
  );
});
