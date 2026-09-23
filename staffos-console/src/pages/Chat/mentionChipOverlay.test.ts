import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildChipSegments,
  ensureChipOverlayFor,
  setChipClassifier,
} from "./mentionChipOverlay";

/** 把段列表压平成 "kind:value" 数组，便于断言切分结果。 */
const flatten = (
  segments: ReturnType<typeof buildChipSegments>,
): string[] => segments.map((s) => `${s.kind}:${s.value}`);

afterEach(() => {
  setChipClassifier();
});

describe("buildChipSegments", () => {
  it("空文本返回空段", () => {
    expect(buildChipSegments("")).toEqual([]);
  });

  it("带空格档案引用整体识别为胶囊并记录偏移", () => {
    expect(buildChipSegments("@ PROFILE.md 帮我修改一下")).toEqual([
      { kind: "chip", value: "@ PROFILE.md", start: 0 },
      { kind: "text", value: " 帮我修改一下", start: 12 },
    ]);
  });

  it("无空格引用（菜单插入形态）同样识别", () => {
    expect(flatten(buildChipSegments("@SOUL.md 先看看"))).toEqual([
      "chip:@SOUL.md",
      "text: 先看看",
    ]);
  });

  it("中文标点紧贴 token 时不粘连（token 在标点前截断）", () => {
    expect(flatten(buildChipSegments("帮我编辑 @ AGENTS.md，先确认"))).toEqual([
      "text:帮我编辑 ",
      "chip:@ AGENTS.md",
      "text:，先确认",
    ]);
  });

  it("CJK 字符紧跟 @ 时同样识别（中文输入法高频场景）", () => {
    expect(flatten(buildChipSegments("帮我@SOUL.md改改"))).toEqual([
      "text:帮我",
      "chip:@SOUL.md",
      "text:改改",
    ]);
  });

  it("技能斜杠命令识别为胶囊", () => {
    expect(flatten(buildChipSegments("/pdf 帮我转文字"))).toEqual([
      "chip:/pdf",
      "text: 帮我转文字",
    ]);
  });

  it("URL 与日期不误染（token 前必须行首或空白）", () => {
    expect(
      flatten(buildChipSegments("访问 https://a.com/b 于 2026/09 上线")),
    ).toEqual(["text:访问 https://a.com/b 于 2026/09 上线"]);
  });

  it("邮箱不误染（@ 前是 ASCII 字母）", () => {
    expect(flatten(buildChipSegments("联系 a@b.com 确认"))).toEqual([
      "text:联系 a@b.com 确认",
    ]);
  });

  it("多个 token 保序切分", () => {
    expect(flatten(buildChipSegments("@ SOUL.md 用 /pdf 处理"))).toEqual([
      "chip:@ SOUL.md",
      "text: 用 ",
      "chip:/pdf",
      "text: 处理",
    ]);
  });
});

describe("ensureChipOverlayFor", () => {
  const mountTextarea = (value: string) => {
    const parent = document.createElement("div");
    const textarea = document.createElement("textarea");
    textarea.value = value;
    parent.appendChild(textarea);
    document.body.appendChild(parent);
    return { parent, textarea };
  };

  it("挂载镜像层并把 token 渲染为竞品同款实底胶囊（名称体：名称+×）", () => {
    const { parent, textarea } = mountTextarea("@ PROFILE.md 帮我改");
    expect(ensureChipOverlayFor(textarea)).toBe(true);

    const overlay = parent.querySelector("div[data-qwenpaw-chip-overlay]");
    expect(overlay).not.toBeNull();
    expect(overlay?.getAttribute("aria-hidden")).toBe("true");

    const chip = overlay?.querySelector(".qwenpaw-chip");
    expect(chip?.textContent).toContain("@ PROFILE.md");
    // jsdom 估算宽度（约 90px < 完全体阈值）落名称体：不透明实底内容层 +
    // 可读名称（去 @ 前缀，保完整显示）+ × 删除，图标让位
    expect(chip?.querySelector(".qwenpaw-chip-fx")).not.toBeNull();
    expect(chip?.querySelector(".qwenpaw-chip-icon")).toBeNull();
    const name = chip?.querySelector(".qwenpaw-chip-name");
    expect(name?.textContent).toBe("PROFILE.md");
    const close = chip?.querySelector(".qwenpaw-chip-close");
    expect(close).not.toBeNull();
    // 删除定位信息挂在 dataset 上（偏移/长度对齐原文区间）
    expect(chip?.getAttribute("data-chip-start")).toBe("0");
    expect(chip?.getAttribute("data-chip-length")).toBe("12");
    textarea.remove();
    parent.remove();
  });

  it("完全体：原文足够宽时图标+名称+× 全量渲染", () => {
    const { parent, textarea } = mountTextarea("@ execute_shell_command 处理");
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ width: 160 } as DOMRect);
    ensureChipOverlayFor(textarea);

    const chip = parent.querySelector(".qwenpaw-chip");
    expect(chip?.querySelector(".qwenpaw-chip-icon svg"))?.not.toBeNull();
    expect(chip?.querySelector(".qwenpaw-chip-name")?.textContent).toBe(
      "execute_shell_command",
    );
    expect(chip?.querySelector(".qwenpaw-chip-close")).not.toBeNull();
    rectSpy.mockRestore();
    textarea.remove();
    parent.remove();
  });

  it("迷你体：超短 token 仅渲染半透明底透出原文，不硬塞内容", () => {
    const { parent, textarea } = mountTextarea("/ab 好");
    ensureChipOverlayFor(textarea);

    const fx = parent.querySelector(".qwenpaw-chip-fx");
    expect(fx?.classList.contains("qwenpaw-chip-fx--mini")).toBe(true);
    expect(fx?.querySelector(".qwenpaw-chip-name")).toBeNull();
    expect(fx?.querySelector(".qwenpaw-chip-close")).toBeNull();
    textarea.remove();
    parent.remove();
  });

  it("注入的分类器决定图标形态（技能闪电图标）", () => {
    const { parent, textarea } = mountTextarea("@docx 帮我");
    const thunderboltPath = "M848 359.3H627.7";
    setChipClassifier(() => "skill");
    ensureChipOverlayFor(textarea);

    const path = parent.querySelector(
      "div[data-qwenpaw-chip-overlay] .qwenpaw-chip-icon path",
    );
    expect(path?.getAttribute("d")?.startsWith(thunderboltPath)).toBe(true);
    textarea.remove();
    parent.remove();
  });

  it("点击 × 整体删除 token 并同步 React 受控值", () => {
    const { parent, textarea } = mountTextarea("先看 @ PROFILE.md 再改");
    ensureChipOverlayFor(textarea);
    const onReactChange = vi.fn();
    textarea.addEventListener("input", onReactChange);

    const close = parent.querySelector(
      "div[data-qwenpaw-chip-overlay] .qwenpaw-chip-close",
    ) as HTMLElement;
    close.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(textarea.value).toBe("先看  再改");
    // 必须冒泡 input 事件，SDK 受控 onChange 才能感知值变化
    expect(onReactChange).toHaveBeenCalled();
    textarea.remove();
    parent.remove();
  });

  it("Backspace 落在胶囊区间内时整 token 删除", () => {
    const { parent, textarea } = mountTextarea("@docx 帮我");
    ensureChipOverlayFor(textarea);
    // 光标在 token 中间（逐字删除会剥出残破 @ 文本，竞品原子实体是整体删）
    textarea.setSelectionRange(3, 3);
    const event = new KeyboardEvent("keydown", {
      key: "Backspace",
      bubbles: true,
      cancelable: true,
    });
    textarea.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
    expect(textarea.value).toBe(" 帮我");
    expect(textarea.selectionStart).toBe(0);
    textarea.remove();
    parent.remove();
  });

  it("光标不在胶囊区间时 Backspace 走原生逐字删除", () => {
    const { parent, textarea } = mountTextarea("文本 @docx");
    ensureChipOverlayFor(textarea);
    textarea.setSelectionRange(2, 2);
    const event = new KeyboardEvent("keydown", {
      key: "Backspace",
      bubbles: true,
      cancelable: true,
    });
    textarea.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
    expect(textarea.value).toBe("文本 @docx");
    textarea.remove();
    parent.remove();
  });

  it("幂等：重复调用不产生第二个镜像层，且按最新值重绘", () => {
    const { parent, textarea } = mountTextarea("@ SOUL.md");
    ensureChipOverlayFor(textarea);
    textarea.value = "/pdf 转录";
    ensureChipOverlayFor(textarea);
    ensureChipOverlayFor(textarea);

    expect(
      parent.querySelectorAll("div[data-qwenpaw-chip-overlay]").length,
    ).toBe(1);
    expect(
      parent
        .querySelector("div[data-qwenpaw-chip-overlay] .qwenpaw-chip")
        ?.textContent?.includes("/pdf"),
    ).toBe(true);
    textarea.remove();
    parent.remove();
  });

  it("SDK 重建 textarea 后清掉孤儿镜像层", () => {
    const { parent, textarea } = mountTextarea("@ AGENTS.md");
    ensureChipOverlayFor(textarea);

    // 模拟 SDK 仅替换 textarea、旧镜像滞留的场景
    const orphan = parent.querySelector("div[data-qwenpaw-chip-overlay]");
    expect(orphan).not.toBeNull();
    textarea.remove();
    const fresh = document.createElement("textarea");
    fresh.value = "新输入 @ SOUL.md";
    parent.appendChild(fresh);
    ensureChipOverlayFor(fresh);

    expect(
      parent.querySelectorAll("div[data-qwenpaw-chip-overlay]").length,
    ).toBe(1);
    expect(
      parent
        .querySelector("div[data-qwenpaw-chip-overlay] .qwenpaw-chip")
        ?.textContent?.includes("@ SOUL.md"),
    ).toBe(true);
    fresh.remove();
    parent.remove();
  });
});
