/**
 * BrandMark 品牌标识组件测试。
 *
 * 品牌几何是全项目唯一来源（顶栏 / 登录页 / 启动页 / OS 品牌位都渲染这一份），
 * 因此这里锁定的重点是「图形不得被删减或改名」而不是样式细节：
 * - 四段几何齐全：前排头、前排肩身、后排星形头、后排线框肩；
 * - 徽章尺寸通过 --bm-size 下发，圆角与图形比例由 CSS 派生；
 * - 图形为装饰性内容，对读屏隐藏；
 * - 裸形 BrandGlyph 支持显式尺寸，且描边走 currentColor（换主题无需改图形）。
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BrandMark, { BrandGlyph } from "./index";

describe("BrandMark", () => {
  it("renders the four glyph strokes that define the crew mark", () => {
    const { container } = render(<BrandMark />);

    const paths = Array.from(container.querySelectorAll("svg path"));
    expect(paths).toHaveLength(4);

    const solid = paths.filter((p) => p.getAttribute("fill") === "currentColor");
    expect(solid).toHaveLength(3);

    const outlined = paths.filter((p) => p.getAttribute("fill") === "none");
    expect(outlined).toHaveLength(1);
    expect(outlined[0].getAttribute("stroke")).toBe("currentColor");
  });

  it("drives badge sizing through the --bm-size custom property", () => {
    const { container } = render(<BrandMark size={52} />);

    const badge = container.firstElementChild as HTMLElement;
    expect(badge.style.getPropertyValue("--bm-size")).toBe("52px");
  });

  it("falls back to the header size when no size is given", () => {
    const { container } = render(<BrandMark />);

    const badge = container.firstElementChild as HTMLElement;
    expect(badge.style.getPropertyValue("--bm-size")).toBe("30px");
  });

  it("stays hidden from assistive tech (the wordmark carries the name)", () => {
    const { container } = render(<BrandMark />);

    const badge = container.firstElementChild as HTMLElement;
    expect(badge.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("BrandGlyph", () => {
  it("honours an explicit edge length for standalone brand slots", () => {
    const { container } = render(<BrandGlyph size={20} />);

    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("20");
    expect(svg?.getAttribute("height")).toBe("20");
  });

  it("omits width/height so a parent container can size it by ratio", () => {
    const { container } = render(<BrandGlyph />);

    const svg = container.querySelector("svg");
    expect(svg?.hasAttribute("width")).toBe(false);
    expect(svg?.getAttribute("viewBox")).toBe("0 0 24 24");
  });
});
