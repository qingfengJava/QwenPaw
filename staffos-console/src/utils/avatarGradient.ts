/**
 * avatarGradient.ts — 头像渐变工具（EmployeeCard 与员工档案栏共用）。
 *
 * 以 id+name 为种子从六组 tone 渐变中稳定取色；插画素材属 StaffDeck
 * 资产不引入，头像统一用首字符 + 渐变底呈现。
 */

export const AVATAR_TONES: [string, string][] = [
  ["#0f766e", "#14b8a6"],
  ["#a85d32", "#e29a68"],
  ["#6f7b42", "#a3b56d"],
  ["#1a71ff", "#6aa5ff"],
  ["#7c5cd6", "#a98ef0"],
  ["#b45309", "#e9a23b"],
];

/** 由种子字符串稳定映射到一组渐变色。 */
export function avatarGradient(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) % 997;
  }
  const [from, to] = AVATAR_TONES[hash % AVATAR_TONES.length];
  return `linear-gradient(145deg, ${from}, ${to})`;
}
