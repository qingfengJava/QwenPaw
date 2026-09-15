/**
 * 品牌名文案单一来源测试。
 *
 * 背景：登录页品牌锁定字标渲染 SmartWork，而标题文案曾硬编码为「登录 QwenPaw」，
 * 同一屏出现两个产品名。修复方式是把产品名收敛到 BRAND_NAME / OS_BRAND_NAME 常量，
 * 文案改用 {{brand}} 插值。这里锁定该约定，防止后续有人把产品名又写死回文案里。
 *
 * 受约束路径：
 * - login.title：登录页标题（字标旁边的主标题）
 * - os.qwenpawMenu：桌面 OS 菜单按钮的 title / aria-label
 *
 * 注意：login 命名空间下的 Hub 法务条款（hubTerms* / hubLinks / hubDisclaimer*）
 * 指的是上游 QwenPaw 项目与 QwenPaw Hub 服务本身，属于外部实体名称，必须保留
 * QwenPaw 字样，因此不在约束范围内。
 */
import { describe, expect, it } from "vitest";

import { BRAND_NAME, OS_BRAND_NAME } from "@/components/BrandMark";
import en from "./en.json";
import id from "./id.json";
import ja from "./ja.json";
import ptBR from "./pt-BR.json";
import ru from "./ru.json";
import vi from "./vi.json";
import zh from "./zh.json";

const locales = { en, id, ja, "pt-BR": ptBR, ru, vi, zh };

function brandPlaceholders(value: string): string[] {
  return Array.from(value.matchAll(/{{(\w+)}}/g), (match) => match[1]).sort();
}

/** 所有含产品名的用户可见文案，都必须走 {{brand}} 插值 */
const BRAND_COPY_PATHS = ["login.title", "os.qwenpawMenu"];

function copyOf(locale: unknown, path: string): string {
  const value = path.split(".").reduce<unknown>((current, key) => {
    if (typeof current !== "object" || current === null) {
      return undefined;
    }
    return (current as Record<string, unknown>)[key];
  }, locale);

  return String(value);
}

describe("brand naming in locale copy", () => {
  it("keeps the product name and the OS sub-brand in one place", () => {
    expect(BRAND_NAME).toBe("SmartWork");
    expect(OS_BRAND_NAME).toBe(`${BRAND_NAME} OS`);
  });

  it.each(Object.entries(locales))(
    "%s drives brand copy from the {{brand}} placeholder",
    (_localeName, locale) => {
      for (const path of BRAND_COPY_PATHS) {
        const copy = copyOf(locale, path);

        expect(copy, `${path} 必须用插值取产品名`).toContain("{{brand}}");
        expect(copy, `${path} 不得再硬编码上游项目名`).not.toContain("QwenPaw");
      }
    },
  );

  it.each(Object.entries(locales))(
    "%s keeps brand copy interpolation variables in parity with en",
    (_localeName, locale) => {
      for (const path of BRAND_COPY_PATHS) {
        expect(brandPlaceholders(copyOf(locale, path)), path).toEqual(
          brandPlaceholders(copyOf(en, path)),
        );
      }
    },
  );
});
