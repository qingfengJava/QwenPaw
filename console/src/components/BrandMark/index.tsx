import type { CSSProperties } from "react";
import styles from "./index.module.less";

/**
 * 产品名（字标）唯一来源：顶栏与登录页字标、以及带品牌名的 i18n 文案（如
 * login.title 的 {{brand}} 插值）均从此取值，避免产品名散落多处改不齐。
 */
export const BRAND_NAME = "SmartWork";

/**
 * 桌面 OS 子品牌名：OS 启动页与桌面水印统一取此值。
 * 与原生桌面包名（src-tauri/tauri.conf.json 的 productName = "QwenPaw Desktop"）
 * 是两个独立实体：前者只是壳内渲染文字，后者影响安装路径与更新器身份。
 */
export const OS_BRAND_NAME = `${BRAND_NAME} OS`;

/**
 * 品牌图形几何（方向 A「数字团队编队」）：统一画在 24 视框内。
 *
 * 语义构成：
 * - 前排「实心圆头 + 肩身」= 真人视角下的一位员工；
 * - 后排「四角星头 + 线框肩」= 由系统编排出来的那一位数字员工，
 *   星形（sparkle）在此从装饰主角降级为「数字员工」的身份标记；
 * - 两者前后错位并列，读作「你带的一支 AI 团队」。
 *
 * 全图形由 currentColor 驱动，亮/暗主题只换底不改几何，因此几何常量集中在此，
 * 顶栏 / 登录页 / 启动页 / OS 品牌位均不得另存副本。
 */
const GLYPH = {
  /** 前排员工头部（实心圆） */
  head: "M9.5 11.9a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z",
  /** 前排员工肩身（底边平切的半椭圆） */
  bust: "M3.2 19.2c0-3.5 2.8-6.1 6.3-6.1s6.3 2.6 6.3 6.1z",
  /** 后排数字员工头部（四角星） */
  starHead: "M17.1 11.3l1 2.2 2.2 1-2.2 1-1 2.2-1-2.2-2.2-1 2.2-1z",
  /** 后排数字员工肩身（线框弧，弱化以拉开前后层级） */
  trailBust: "M15.4 19.2c.3-2.7 2-4.4 4.3-4.4",
};

/** 后排线框弧相对实心的透明度：低于此值 16px 下会消失，高于此值前后层级会糊 */
const TRAIL_OPACITY = 0.7;

interface BrandGlyphProps {
  /** 显式边长（px）；放进 BrandMark 时不传，由徽章内部比例自动撑满 */
  size?: number;
  /** 附加类名 */
  className?: string;
}

/**
 * 品牌裸形（无底）：用于已经自带容器/底色的品牌位。
 *
 * @param size 显式边长，缺省时交由父级 CSS 控制
 * @param className 附加类名
 * @author qingfeng
 */
export function BrandGlyph({ size, className }: BrandGlyphProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <path d={GLYPH.head} fill="currentColor" />
      <path d={GLYPH.bust} fill="currentColor" />
      <path d={GLYPH.starHead} fill="currentColor" />
      <path
        d={GLYPH.trailBust}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.9}
        strokeLinecap="round"
        opacity={TRAIL_OPACITY}
      />
    </svg>
  );
}

interface BrandMarkProps {
  /** 徽章边长（px）：圆角按 0.34、内部图形按 0.62 比例派生，缩放无需另配样式 */
  size?: number;
  /** 附加类名（用于外部定位，不改品牌外观） */
  className?: string;
}

/**
 * 品牌徽章（图形 + 渐变方底）：SmartWork 品牌标识的唯一渲染入口。
 *
 * @param size 徽章边长，默认 30（顶栏尺寸）
 * @param className 附加类名
 * @author qingfeng
 */
export default function BrandMark({
  size = 30,
  className,
}: BrandMarkProps) {
  const badgeStyle = { "--bm-size": `${size}px` } as CSSProperties;

  return (
    <span
      className={className ? `${styles.badge} ${className}` : styles.badge}
      style={badgeStyle}
      aria-hidden="true"
    >
      <BrandGlyph />
    </span>
  );
}
