/**
 * expertAvatar.ts — 数字员工 DiceBear 形象解析与渲染。
 *
 * experts.icon 值约定：
 *  - "dicebear://<style>/<seed>"  显式配置（管理端形象选择器写入）
 *  - 其他任何值（空串/FA 类名等遗留值）
 *                                按 expertId 稳定自动分配（同一专家
 *                                永远同一形象，无需持久化）
 *
 * DiceBear（@dicebear/core + 各风格包）一律动态 import，保证不进入
 * 首屏 bundle（console 有 verify-initial-bundle 体积门禁）。
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

/** 由风格 + 种子拼出 icon 字段值（管理端选择器写回用）。 */
export function buildExpertIcon(style: ExpertAvatarStyle, seed: string): string {
  return `dicebear://${style}/${seed}`;
}

/** 按 expertId 稳定自动分配一个形象（同一专家永远同一结果）。 */
function autoAssignAvatar(expertId: string): ResolvedExpertAvatar {
  const style =
    EXPERT_AVATAR_STYLES[stableHash(expertId) % EXPERT_AVATAR_STYLES.length];
  return { style, seed: expertId };
}

/**
 * 解析 icon → 具体形象。非 dicebear:// 格式（空串/FA 类名等遗留值），
 * 或 dicebear 值不完整（风格未知/缺 seed）时，一律按 expertId 自动
 * 分配，保证每个数字员工都有稳定形象。
 */
export function resolveExpertAvatar(
  icon: string | null | undefined,
  expertId: string,
): ResolvedExpertAvatar {
  const raw = (icon ?? "").trim();
  if (raw.startsWith("dicebear://")) {
    const rest = raw.slice("dicebear://".length);
    const slash = rest.indexOf("/");
    const style = slash > 0 ? rest.slice(0, slash) : "";
    const seed = slash > 0 ? rest.slice(slash + 1) : "";
    if (
      (EXPERT_AVATAR_STYLES as readonly string[]).includes(style) &&
      seed
    ) {
      return { style: style as ExpertAvatarStyle, seed };
    }
  }
  return autoAssignAvatar(expertId);
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
