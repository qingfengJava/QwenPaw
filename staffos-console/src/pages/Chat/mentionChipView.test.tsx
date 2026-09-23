/**
 * mentionChipView.test.tsx — 气泡内 mention 胶囊渲染的单测。
 *
 * 覆盖：raw 用户消息分支启用胶囊（file/skill/ref 分类、文本段无损、
 * 展示名不含协议前缀）、无 token 文本原样、非 raw 数据委托 SDK 默认
 * Text 卡（Markdown 渲染不受影响）。
 *
 * @author qingfeng
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@agentscope-ai/chat", () => ({
  DefaultCards: {
    Text: (props: { data?: { content?: unknown } }) => (
      <div data-testid="sdk-default-text">
        {String(props?.data?.content ?? "")}
      </div>
    ),
  },
  useProviderContext: () => ({
    getPrefixCls: (suffix: string) => `qwenpaw-${suffix}`,
  }),
}));

import { MentionAwareTextCard } from "./mentionChipView";

/** 渲染一条 raw 用户消息并返回挂载容器。 */
function renderRaw(content: string) {
  const view = render(
    <MentionAwareTextCard data={{ content, raw: true }} />,
  );
  return view.container;
}

describe("MentionAwareTextCard — raw 用户消息", () => {
  it("档案引用渲染为 file 胶囊，展示名不含 @，前后文本保留", () => {
    const container = renderRaw("帮我编辑 @ PROFILE.md 先确认");
    const chip = container.querySelector('[data-chip-kind="file"]');
    expect(chip?.textContent).toBe("PROFILE.md");
    expect(container.textContent).toBe("帮我编辑 PROFILE.md 先确认");
  });

  it("斜杠技能渲染为 skill 胶囊", () => {
    const container = renderRaw("/pdf 帮我转文字");
    expect(
      container.querySelector('[data-chip-kind="skill"]')?.textContent,
    ).toBe("pdf");
  });

  it("非白名单 @ 引用渲染为 ref 胶囊", () => {
    const container = renderRaw("问一下 @somebody 这事");
    expect(
      container.querySelector('[data-chip-kind="ref"]')?.textContent,
    ).toBe("somebody");
  });

  it("无 token 文本原样直出（不产生胶囊节点）", () => {
    const container = renderRaw("普通消息，没有引用");
    expect(container.querySelector("[data-chip-kind]")).toBeNull();
    expect(container.textContent).toBe("普通消息，没有引用");
  });

  it("容器复用 SDK markdown 前缀类（样式与默认 Raw 分支一致）", () => {
    const container = renderRaw("hello");
    expect(container.firstElementChild?.className).toContain("markdown");
  });
});

describe("MentionAwareTextCard — 非 raw 数据委托 SDK 默认 Text 卡", () => {
  it("助手消息（无 raw 标记）不渲染胶囊，交给 Markdown", () => {
    render(<MentionAwareTextCard data={{ content: "**bold**" }} />);
    expect(screen.getByTestId("sdk-default-text").textContent).toBe(
      "**bold**",
    );
    expect(document.querySelector("[data-chip-kind]")).toBeNull();
  });
});
