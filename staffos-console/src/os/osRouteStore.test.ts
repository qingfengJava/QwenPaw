import { beforeEach, describe, expect, it } from "vitest";
import { useOsRoute } from "./osRouteStore";
import { useOsWindows } from "./osWindowStore";

function resetStores(): void {
  useOsRoute.setState({ targets: {} });
  useOsWindows.setState({
    windows: {},
    order: [],
    activeId: null,
    zCounter: 100,
    launcherOpen: false,
    spaceId: "default",
    saved: {},
    missionControlOpen: false,
  });
}

describe("osRouteStore", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", {
      value: 1440,
      configurable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      value: 900,
      configurable: true,
    });
    resetStores();
  });

  it("keeps the source window for normal cross-app navigation", () => {
    useOsWindows.getState().open("core.chat");

    useOsRoute.getState().navigateTo("core.inbox", "/inbox");

    expect(useOsWindows.getState().windows["core.chat"]).toBeDefined();
    expect(useOsWindows.getState().windows["core.inbox"]).toBeDefined();
  });

  it("never opens windows or deep-links for retired apps (loop guard)", () => {
    // core.chat 已下架（现为重定向 stub）：开窗会立刻重定向到 /agents/:aid/*，
    // 被桥接解析成另一个目标又弹回自身，形成无限开窗循环（C2）。
    useOsRoute.getState().navigateTo("core.chat", "/chat/session-1");

    expect(useOsRoute.getState().targets["core.chat"]).toBeUndefined();
    expect(useOsWindows.getState().windows["core.chat"]).toBeUndefined();
  });

  it("still routes normal apps while the retired guard is active", () => {
    useOsRoute.getState().navigateTo("core.inbox", "/inbox");

    expect(useOsRoute.getState().targets["core.inbox"]).toBeDefined();
    expect(useOsWindows.getState().windows["core.inbox"]).toBeDefined();
  });
});
