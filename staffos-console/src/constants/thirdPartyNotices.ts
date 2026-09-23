/**
 * thirdPartyNotices.ts — 随应用分发的第三方开源资产署名。
 *
 * 数字员工形象头像使用 DiceBear 本地生成（CC BY 4.0 风格要求随分发
 * 署名）；各风格许可与作者以官方页为准：
 * https://www.dicebear.com/styles/
 */

export interface ThirdPartyNotice {
  name: string;
  usage: string;
  license: string;
  homepage: string;
  /** CC BY 4.0 等要求署名的资产在此标注作者/来源页。 */
  credits?: string;
}

export const THIRD_PARTY_NOTICES: ThirdPartyNotice[] = [
  {
    name: "DiceBear (@dicebear/core 及 @dicebear/* 风格包)",
    usage: "数字员工形象头像（确定性 SVG 生成）",
    license: "MIT License（核心库）；所选风格另有各自许可",
    homepage: "https://www.dicebear.com",
    credits:
      "所用风格作者与许可：Lorelei / Adventurer / Big Smile — " +
      "Lisa Wischofsky（CC BY 4.0）；Personas — Draftbit（CC0）；" +
      "Notionists — Z zo（CC0）；Avataaars — Pablo Stanley（免费商用）。" +
      "详见 https://www.dicebear.com/styles/",
  },
];
