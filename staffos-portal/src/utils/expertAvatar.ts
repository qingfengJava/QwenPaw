/**
 * expertAvatar.ts — 数字员工 DiceBear 形象解析与渲染（xianwork 版，
 * 与 console/src/utils/expertAvatar.ts 保持同一 icon 值约定）。
 *
 * experts.icon 值约定：
 *  - "dicebear://<style>/<seed>"  显式配置（console 管理端形象选择器写入）
 *  - 其他旧值（Font Awesome 类名等） 保持原渲染，不受影响
 *
 * DiceBear（@dicebear/core + 各风格包）一律动态 import，控制 bundle。
 */

export const EXPERT_AVATAR_STYLES = [
  "lorelei",
  "adventurer",
  "personas",
  "notionists",
  "avataaars",
  "big-smile",
] as const;

export type ExpertAvatarStyle = (typeof EXPERT_AVATAR_STYLES)[number];

/** 头像底色板（柔和色系；DiceBear backgroundColor 用无 # 的 hex）。 */
const BG_COLORS = [
  "b6e3f4",
  "c0aede",
  "ffd5dc",
  "d1f4d9",
  "ffeaa7",
  "e0c3fc",
] as const;

export interface ResolvedExpertAvatar {
  style: ExpertAvatarStyle;
  seed: string;
}

/** djb2 稳定字符串哈希（仅用于取模分布，非安全用途）。 */
function stableHash(input: string): number {
  let hash = 5381;
  for (let i = 0; i < input.length; i += 1) {
    hash = ((hash << 5) + hash + input.charCodeAt(i)) >>> 0;
  }
  return hash;
}

/**
 * 解析显式 dicebear:// 配置；非该格式（FA 类名/空值等）返回 null，
 * 由调用方保持原渲染。
 */
export function resolveExpertAvatar(
  icon: string | null | undefined,
  /** 与 console 版签名保持一致；本版本无自动分配逻辑，不参与解析。 */
  _expertId: string,
): ResolvedExpertAvatar | null {
  const raw = (icon ?? "").trim();
  if (!raw.startsWith("dicebear://")) {
    return null;
  }
  const rest = raw.slice("dicebear://".length);
  const slash = rest.indexOf("/");
  const style = slash > 0 ? rest.slice(0, slash) : "";
  const seed = slash > 0 ? rest.slice(slash + 1) : "";
  if (!(EXPERT_AVATAR_STYLES as readonly string[]).includes(style) || !seed) {
    return null;
  }
  return { style: style as ExpertAvatarStyle, seed };
}

type StyleModule = Record<string, unknown>;

/** 每风格一个独立动态 chunk，首屏零成本。 */
const STYLE_LOADERS: Record<ExpertAvatarStyle, () => Promise<StyleModule>> = {
  lorelei: () => import("@dicebear/lorelei"),
  adventurer: () => import("@dicebear/adventurer"),
  personas: () => import("@dicebear/personas"),
  notionists: () => import("@dicebear/notionists"),
  avataaars: () => import("@dicebear/avataaars"),
  "big-smile": () => import("@dicebear/big-smile"),
};

/** 渲染 DiceBear SVG 并转 dataUri（img src 直接可用，无 XSS 注入面）。 */
export async function renderExpertAvatar({
  style,
  seed,
}: ResolvedExpertAvatar): Promise<string> {
  const [{ createAvatar }, styleMod] = await Promise.all([
    import("@dicebear/core"),
    STYLE_LOADERS[style](),
  ]);
  // 风格包导出 { meta, create, schema }（即 Style 对象本身），
  // 动态 import 的模块命名空间直接作为 createAvatar 首参。
  const styleDef = styleMod as unknown as Parameters<typeof createAvatar>[0];
  const avatar = createAvatar(styleDef, {
    seed,
    size: 128,
    backgroundColor: [BG_COLORS[stableHash(seed) % BG_COLORS.length]],
  });
  return avatar.toDataUri();
}
