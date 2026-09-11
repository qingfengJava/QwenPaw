/**
 * mentionChipOverlay.ts — 聊天输入框内 @ 引用 / 技能斜杠的「内联胶囊实体」层。
 *
 * SDK Sender 是原生 textarea，无法在文字流里渲染富文本原子。本模块在
 * textarea 底下垫一个布局完全同步的镜像 div（GitHub/ChatGPT 斜杠高亮
 * 同款技术），把命中的 token（`@ PROFILE.md`、`@docx`、`/pdf` 等）渲染成
 * 竞品同款胶囊：实底圆角 + 分类图标 + 名称 + × 删除，嵌在文字流中间
 * 与普通文本同行混排（对标 Coze/Notion 的 inline mention chip）。
 *
 * 遮盖式渲染：镜像层 zIndex 高于 textarea，胶囊底色不透明可直接盖住
 * 原文，再在胶囊内容层（.qwenpaw-chip-fx，绝对定位零布局占位）里自绘
 * 图标/名称/×；透明原文 span 继续占宽，换行与后续文字位置与 textarea
 * 逐像素一致。胶囊宽度锁定原文宽度，按宽度三级降级：完全体（图标 +
 * 名称 + ×）/ 紧凑体（图标 + 名称）/ 迷你体（仅底色，短 token 透出
 * 原文），避免内容溢出与相邻文字重叠。
 *
 * 交互增强（逼近 contenteditable 原子实体体验）：
 * - × 按钮可点击，一次删除整个 token（镜像层 pointer-events:none 放行
 *   普通点击给 textarea，仅按钮开启 pointer-events:auto）；
 * - Backspace/Delete 命中 token 区间时整 token 删除，不逐字剥；
 * - token 分类图标由宿主注入的 classifier 决定（档案/技能/通用引用）。
 *
 * 主题自适应：胶囊前景色取 textarea 计算样式的 color（--qwenpaw-chip-fg），
 * 底色基板沿 DOM 祖先链找第一个不透明背景色（--qwenpaw-chip-base，全透
 * 明链路按前景亮度回退深/浅），实底 = 前景低比例混入基板，浅色/深色
 * 主题均无需额外配置。
 *
 * 纯展示 + 删除入口：不改 token 之外的 value，`@ path` 文件协议与
 * `/skillname` 斜杠命令协议、预填链路、档案同步逻辑全部不受影响。
 */

import { IDENTITY_DOC_FILES } from "../Agents/identityDocFiles";
import { getActiveSenderTextarea } from "./utils";

/** token 分类（决定胶囊图标）：档案文件 / 技能 / 通用 @ 引用。 */
export type ChipTokenKind = "file" | "skill" | "ref";

/** 镜像层文本段：普通文本或胶囊 token。 */
export interface ChipSegment {
  /** 段类型 */
  kind: "text" | "chip";
  /** 原文切片（保持与 textarea 完全一致，保证布局对齐） */
  value: string;
  /** 段在原文中的起始偏移（× 删除 / 整 token 退格按此定位区间） */
  start: number;
}

/**
 * token 识别规则：
 * - 文件/工具/MCP 引用：行首、空白或 CJK 字符后的 `@`（中文输入法打中文
 *   后直接接 @ 是高频场景），可带一个空格（inline 协议 `@ path`），
 *   字符集限 ASCII 词符（汉字天然截断 token，避免粘连误染）；
 * - 技能/内置命令：行首或空白后 `/name`（小写字母数字开头，含 `-`/`_`），
 *   URL（`https://…`）、日期（`2026/09`）因前面非空白不会命中，
 *   邮箱（`a@b.com`，@ 前是 ASCII 字母）不误染。
 */
const CHIP_TOKEN_RE =
  /(^|\s|\P{ASCII})(@\s?[\w.\\/:+-]+|\/[a-z0-9][\w-]*)/gu;

/**
 * 将输入文本切分为 普通文本/胶囊 段序列（纯函数，供镜像层渲染与单测）。
 *
 * @param text textarea 当前值
 * @returns 顺序拼接后与 text 完全一致的段列表（各段带起始偏移）
 * @author qingfeng
 */
export function buildChipSegments(text: string): ChipSegment[] {
  if (!text) {
    return [];
  }
  const segments: ChipSegment[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  CHIP_TOKEN_RE.lastIndex = 0;
  while ((match = CHIP_TOKEN_RE.exec(text)) !== null) {
    // match[1] 为 token 前的行首锚/空白/CJK 字符，胶囊从其后开始
    const tokenStart = match.index + match[1].length;
    const tokenEnd = tokenStart + match[2].length;
    if (tokenStart > cursor) {
      segments.push({ kind: "text", value: text.slice(cursor, tokenStart), start: cursor });
    }
    segments.push({ kind: "chip", value: text.slice(tokenStart, tokenEnd), start: tokenStart });
    cursor = tokenEnd;
    CHIP_TOKEN_RE.lastIndex = tokenEnd;
  }
  if (cursor < text.length) {
    segments.push({ kind: "text", value: text.slice(cursor), start: cursor });
  }
  return segments;
}

/**
 * 默认 token 分类：斜杠 → 技能；档案白名单文件 → 文件；其余 → 通用引用。
 * 宿主（Chat/index.tsx）会注入带技能名单的 classifier 覆盖工具/MCP 判定，
 * 未注入时（如单测环境）走此静态规则。
 */
function defaultClassify(token: string): ChipTokenKind {
  if (token.startsWith("/")) {
    return "skill";
  }
  const name = token.replace(/^@\s?/, "");
  return IDENTITY_DOC_FILES.some((file) => name === file)
    ? "file"
    : "ref";
}

/** 宿主注入的分类器（感知当前 agent 的技能/工具/MCP 目录）。 */
let chipClassifier: ((token: string) => ChipTokenKind) | null = null;

/**
 * 设置/清除胶囊 token 分类器；变更会导致已挂载镜像层立即重绘。
 *
 * @param classifier 分类函数，传 undefined 恢复默认静态规则
 * @author qingfeng
 */
export function setChipClassifier(
  classifier?: (token: string) => ChipTokenKind,
): void {
  chipClassifier = classifier ?? null;
  mountedTextareas.forEach((textarea) => repaintRegistry.get(textarea)?.());
}

/** 按分类返回胶囊左缘图标（SVG path 数据来自 @ant-design/icons，MIT）。 */
function createChipIcon(kind: ChipTokenKind): HTMLElement {
  const wrapper = document.createElement("span");
  wrapper.className = "qwenpaw-chip-icon";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "64 64 896 896");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute(
    "d",
    kind === "skill"
      ? "M848 359.3H627.7L825.8 109c4.1-5.3.4-13-6.3-13H436c-2.8 0-5.5 1.5-6.9 4L170 547.5c-3.1 5.3.7 12 6.9 12h174.4l-89.4 357.6c-1.9 7.8 7.5 13.3 13.3 7.7L853.5 373c5.2-4.9 1.7-13.7-5.5-13.7zM378.2 732.5l60.3-241H281.1l189.6-327.4h224.6L487 427.4h211L378.2 732.5z"
      : "M854.6 288.6L639.4 73.4c-6-6-14.1-9.4-22.6-9.4H192c-17.7 0-32 14.3-32 32v832c0 17.7 14.3 32 32 32h640c17.7 0 32-14.3 32-32V311.3c0-8.5-3.4-16.7-9.4-22.7zM790.2 326H602V137.8L790.2 326zm1.8 562H232V136h302v216a42 42 0 0042 42h216v494zM504 618H320c-4.4 0-8 3.6-8 8v48c0 4.4 3.6 8 8 8h184c4.4 0 8-3.6 8-8v-48c0-4.4-3.6-8-8-8zM312 490v48c0 4.4 3.6 8 8 8h384c4.4 0 8-3.6 8-8v-48c0-4.4-3.6-8-8-8H320c-4.4 0-8 3.6-8 8z",
  );
  svg.appendChild(path);
  wrapper.appendChild(svg);
  return wrapper;
}

/** 镜像层与 textarea 必须逐字对齐的排版属性。 */
const SYNCED_STYLES: readonly string[] = [
  "fontFamily",
  "fontSize",
  "fontStyle",
  "fontVariant",
  "fontWeight",
  "fontStretch",
  "lineHeight",
  "letterSpacing",
  "wordSpacing",
  "textTransform",
  "textIndent",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
  "tabSize",
];

/** 从 rgb()/rgba() 字符串解析颜色分量；无法解析返回 null。 */
function parseRgb(color: string): number[] | null {
  const match = /rgba?\(([^)]+)\)/.exec(color);
  if (!match) {
    return null;
  }
  const parts = match[1].split(",").map((part) => Number.parseFloat(part));
  if (parts.length < 3 || parts.some((n) => Number.isNaN(n))) {
    return null;
  }
  return parts;
}

/** 判断颜色是否为深色（相对亮度 < 0.5），用于全透明链路的基底回退。 */
function isDarkColor(color: string): boolean {
  const rgb = parseRgb(color);
  if (!rgb) {
    return false;
  }
  return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255 < 0.5;
}

/** 判断背景色是否不透明（alpha ≥ 0.9）：半透明底遮不住 textarea 原文。 */
function isOpaqueBackground(color: string): boolean {
  if (
    !color ||
    color === "transparent" ||
    /rgba\(\s*0,\s*0,\s*0,\s*0\s*\)/.test(color)
  ) {
    return false;
  }
  const rgb = parseRgb(color);
  return rgb ? rgb[3] === undefined || rgb[3] >= 0.9 : true;
}

/**
 * 解析胶囊底色基板：沿 textarea 祖先链找第一个不透明背景色（镜像层
 * 所在 SDK 子树没有可靠的主题变量，直接取样是最稳的主题适配）；
 * 全透明链路按前景亮度回退深/浅基底。
 *
 * @param textarea SDK Sender 的输入 textarea
 * @param computed textarea 的计算样式（取前景色判亮度）
 * @returns 不透明背景色（rgb 字符串或回退色值）
 * @author qingfeng
 */
function resolveChipBase(
  textarea: HTMLTextAreaElement,
  computed: CSSStyleDeclaration,
): string {
  let el: HTMLElement | null = textarea;
  for (let depth = 0; el && depth < 8; depth += 1) {
    const bg = window.getComputedStyle(el).backgroundColor;
    if (isOpaqueBackground(bg)) {
      return bg;
    }
    el = el.parentElement;
  }
  return isDarkColor(computed.color) ? "#1e1f22" : "#ffffff";
}

/** 胶囊样式 CSS 的注入点 id（类样式承载 hover 态，内联样式做不到）。 */
const CHIP_STYLE_ID = "qwenpaw-chip-overlay-style";

/**
 * 胶囊视觉：内容层 .qwenpaw-chip-fx 绝对定位零布局占位，不透明实底
 * 盖住原文后自绘图标/名称/×，左右 -3px 出血只吃 token 前后的空白，
 * 不与相邻文字重叠。颜色取宿主注入的 --qwenpaw-chip-fg / --qwenpaw-chip-base
 * （syncStyles 每次重绘同步），浅色/深色主题自适应。
 */
function ensureChipStyles(): void {
  if (document.getElementById(CHIP_STYLE_ID)) {
    return;
  }
  const style = document.createElement("style");
  style.id = CHIP_STYLE_ID;
  style.textContent = `
.qwenpaw-chip { position: relative; }
.qwenpaw-chip-fx {
  position: absolute; top: -1px; bottom: -1px; left: -3px; right: -3px;
  display: flex; align-items: center; gap: 2px;
  padding: 0 6px; border-radius: 999px; overflow: hidden;
  box-sizing: border-box;
  background: color-mix(in srgb, var(--qwenpaw-chip-fg, #1f2329) 6%, var(--qwenpaw-chip-base, #fff));
  border: 1px solid color-mix(in srgb, var(--qwenpaw-chip-fg, #1f2329) 15%, var(--qwenpaw-chip-base, #fff));
  pointer-events: none;
}
.qwenpaw-chip:hover .qwenpaw-chip-fx {
  background: color-mix(in srgb, var(--qwenpaw-chip-fg, #1f2329) 10%, var(--qwenpaw-chip-base, #fff));
  border-color: color-mix(in srgb, var(--qwenpaw-chip-fg, #1f2329) 24%, var(--qwenpaw-chip-base, #fff));
}
.qwenpaw-chip-fx--mini {
  background: color-mix(in srgb, var(--qwenpaw-chip-fg, #1f2329) 10%, transparent);
  border-color: color-mix(in srgb, var(--qwenpaw-chip-fg, #1f2329) 22%, transparent);
}
.qwenpaw-chip-name {
  flex: 1 1 auto; min-width: 0; overflow: hidden;
  padding-right: 13px; text-overflow: ellipsis; white-space: nowrap;
  font-size: 12px; line-height: 1; color: var(--qwenpaw-chip-fg, #1f2329);
}
.qwenpaw-chip-icon {
  flex: 0 0 auto; display: flex; align-items: center;
  color: var(--qwenpaw-chip-fg, #1f2329); opacity: 0.62;
}
.qwenpaw-chip-icon svg { width: 10px; height: 10px; fill: currentColor; display: block; }
.qwenpaw-chip-close {
  position: absolute; right: 2px; top: 50%; transform: translateY(-50%);
  display: flex; align-items: center; justify-content: center;
  width: 14px; height: 14px; padding: 0;
  border: none; border-radius: 50%; background: transparent;
  color: var(--qwenpaw-chip-fg, #1f2329); opacity: 0.45;
  font-size: 12px; line-height: 1; cursor: pointer; pointer-events: auto;
}
.qwenpaw-chip-close:hover { opacity: 1; color: #ff4d4f; }
`;
  document.head.appendChild(style);
}

/** 已挂载镜像层的 textarea 集合（classifier 变更时全量重绘用）。 */
const mountedTextareas = new Set<HTMLTextAreaElement>();

/** 已挂载 textarea 的重绘入口：轮询守护复用它同步字体/尺寸/滚动条变化。 */
const repaintRegistry = new WeakMap<HTMLTextAreaElement, () => void>();

/**
 * 以 React 受控组件兼容的方式改写 textarea 值。
 *
 * 原型 value setter 绕过 React 的实例属性劫持写回真值，再派发冒泡 input
 * 事件触发 SDK 的 onChange，保证受控状态与镜像层同步刷新。
 */
function setTextareaValue(textarea: HTMLTextAreaElement, next: string): void {
  const nativeSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  if (nativeSetter) {
    nativeSetter.call(textarea, next);
  } else {
    textarea.value = next;
  }
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

/** 整体删除 [start, start+length) 的 token 并把光标落到删除点。 */
function deleteChipToken(
  textarea: HTMLTextAreaElement,
  start: number,
  length: number,
): void {
  const next =
    textarea.value.slice(0, start) + textarea.value.slice(start + length);
  setTextareaValue(textarea, next);
  textarea.focus();
  textarea.setSelectionRange(start, start);
}

/**
 * 渲染镜像层内容：chip 段渲染为胶囊（透明原文占宽 + 绝对定位内容层），
 * 插入 DOM 后统一实测宽度并填充内容层，末尾补一行对齐 textarea 尾换行
 * 渲染。
 */
function renderOverlay(overlay: HTMLDivElement, value: string): void {
  const nodes: Node[] = buildChipSegments(value).map((segment) => {
    if (segment.kind === "text") {
      return document.createTextNode(segment.value);
    }

    const chip = document.createElement("span");
    chip.className = "qwenpaw-chip";
    chip.dataset.chipStart = String(segment.start);
    chip.dataset.chipLength = String(segment.value.length);

    // 透明原文继续占宽：镜像换行与后续文字位置和 textarea 逐像素一致
    chip.appendChild(document.createTextNode(segment.value));
    // 内容层先占位，插入 DOM 后按实测宽度统一填充（见下方遍历）
    const fx = document.createElement("span");
    fx.className = "qwenpaw-chip-fx";
    chip.appendChild(fx);
    return chip;
  });
  nodes.push(document.createTextNode("\n "));
  overlay.replaceChildren(...nodes);
  overlay.querySelectorAll<HTMLElement>(".qwenpaw-chip").forEach((chip) => {
    const token = chip.firstChild?.textContent ?? "";
    const kind = chipClassifier
      ? chipClassifier(token)
      : defaultClassify(token);
    const fx = chip.querySelector<HTMLElement>(".qwenpaw-chip-fx");
    if (!fx) {
      return;
    }
    const { nodes: fxNodes, mini } = buildChipFxContent(
      token,
      kind,
      measureChipWidth(token, chip),
    );
    fx.classList.toggle("qwenpaw-chip-fx--mini", mini);
    fx.replaceChildren(...fxNodes);
  });
}

/** 胶囊名：去掉 `@ `/`/` 协议前缀后的可读名称（竞品胶囊同款不含 @）。 */
function chipDisplayName(token: string): string {
  return token.replace(/^@\s?/, "").replace(/^\//, "");
}

/** 胶囊内容分级阈值（px，原文实测宽度）：完全体 / 名称体 / 图标体 / 迷你体。 */
const CHIP_FULL_MIN_WIDTH = 96;
const CHIP_NAMED_MIN_WIDTH = 56;
const CHIP_ICON_MIN_WIDTH = 34;

/** 测量胶囊可用宽度：优先原文实测宽，无布局环境（jsdom 等）按字宽估算。 */
function measureChipWidth(token: string, chip: HTMLElement): number {
  const width = chip.getBoundingClientRect().width;
  if (width > 0) {
    return width;
  }
  const nonAscii = (token.match(/\P{ASCII}/gu) ?? []).length;
  return (token.length - nonAscii) * 7.5 + nonAscii * 14;
}

/** 构建 × 删除按钮（绝对定位在胶囊右缘，不占内容层 flex 空间）。 */
function buildChipClose(token: string): HTMLButtonElement {
  const close = document.createElement("button");
  close.type = "button";
  close.className = "qwenpaw-chip-close";
  close.setAttribute("aria-label", `删除 ${token}`);
  close.textContent = "×";
  return close;
}

/**
 * 按可用宽度生成胶囊内容层节点（× 为绝对定位不占 flex 空间，名称预留
 * padding-right 防叠）：完全体（图标+名称+×）/ 名称体（名称+×，图标
 * 让位保名称完整）/ 图标体（图标+名称，删除交由 Backspace 整删兜底）/
 * 迷你体（空内容 + 半透明底透出原文），避免内容溢出胶囊、胶囊不侵占
 * 相邻文字空间。
 */
function buildChipFxContent(
  token: string,
  kind: ChipTokenKind,
  width: number,
): { nodes: Node[]; mini: boolean } {
  if (width < CHIP_ICON_MIN_WIDTH) {
    return { nodes: [], mini: true };
  }
  const name = document.createElement("span");
  name.className = "qwenpaw-chip-name";
  name.textContent = chipDisplayName(token);
  const nodes: Node[] = [name];
  if (width >= CHIP_FULL_MIN_WIDTH) {
    // 完全体：图标 + 名称 + ×
    nodes.unshift(createChipIcon(kind));
    nodes.push(buildChipClose(token));
  } else if (width >= CHIP_NAMED_MIN_WIDTH) {
    // 名称体：名称 + ×（图标让位保名称完整）
    nodes.push(buildChipClose(token));
  } else {
    // 图标体：图标 + 名称（删除交由 Backspace 整删兜底）
    nodes.unshift(createChipIcon(kind));
  }
  return { nodes, mini: false };
}

/** 把 textarea 的计算排版样式同步到镜像层，保证逐像素对齐。 */
function syncStyles(textarea: HTMLTextAreaElement, overlay: HTMLDivElement): void {
  const computed = window.getComputedStyle(textarea);
  // 胶囊调色板变量：前景取正文色、基板取祖先链首个不透明背景，
  // 保证浅色/深色主题下实底胶囊都能正确遮盖原文并清晰可辨
  overlay.style.setProperty("--qwenpaw-chip-fg", computed.color);
  overlay.style.setProperty("--qwenpaw-chip-base", resolveChipBase(textarea, computed));
  SYNCED_STYLES.forEach((prop) => {
    // @ts-expect-error CSSStyleDeclaration 索引起值，键名来自白名单常量
    overlay.style[prop] = computed[prop];
  });
  overlay.style.position = "absolute";
  overlay.style.whiteSpace = "pre-wrap";
  overlay.style.overflowWrap = "break-word";
  overlay.style.wordBreak = computed.wordBreak;
  overlay.style.overflow = "hidden";
  overlay.style.pointerEvents = "none";
  overlay.style.color = "transparent";
  overlay.style.background = "transparent";
  // 镜像层盖在 textarea 之上才能显示 × 按钮（层自身 pointer-events:none
  // 放行点击，仅按钮单独开启），textarea 保持可聚焦可编辑
  overlay.style.zIndex = "2";

  // textarea 自身底色不透明时会遮挡镜像，仅在这种情况下强制透明化
  const textareaBg = computed.backgroundColor;
  if (
    textareaBg &&
    textareaBg !== "transparent" &&
    textareaBg !== "rgba(0, 0, 0, 0)"
  ) {
    textarea.style.backgroundColor = "transparent";
  }

  // 盒模型直接复制 textarea 在父容器内的几何位置；textarea 出现垂直
  // 滚动条时内容区变窄，镜像层用右侧内边距补偿同宽度，保证换行一致
  const borderLeft = parseFloat(computed.borderLeftWidth) || 0;
  const scrollbarWidth = Math.max(
    textarea.offsetWidth - textarea.clientWidth - borderLeft -
      (parseFloat(computed.borderRightWidth) || 0),
    0,
  );
  overlay.style.left = `${textarea.offsetLeft}px`;
  overlay.style.top = `${textarea.offsetTop}px`;
  overlay.style.width = `${textarea.offsetWidth}px`;
  overlay.style.height = `${textarea.offsetHeight}px`;
  overlay.style.paddingRight = `${
    (parseFloat(computed.paddingRight) || 0) + scrollbarWidth
  }px`;
}

/**
 * Backspace/Delete 命中胶囊 token 区间时整 token 删除，逼近竞品
 * 原子实体行为（普通键入、选区删除均走原生链路不受影响）。
 */
function handleAtomicBackspace(event: KeyboardEvent): void {
  if (event.key !== "Backspace" && event.key !== "Delete") {
    return;
  }
  if (event.ctrlKey || event.metaKey || event.altKey) {
    return;
  }
  const textarea = event.currentTarget as HTMLTextAreaElement;
  if (textarea.selectionStart !== textarea.selectionEnd) {
    return;
  }
  const cursor = textarea.selectionStart;
  const hit = buildChipSegments(textarea.value).find(
    (segment) =>
      segment.kind === "chip" &&
      ((event.key === "Backspace" &&
        cursor > segment.start &&
        cursor <= segment.start + segment.value.length) ||
        (event.key === "Delete" && cursor === segment.start)),
  );
  if (!hit) {
    return;
  }
  event.preventDefault();
  deleteChipToken(textarea, hit.start, hit.value.length);
}

/**
 * 给单个 textarea 挂载胶囊镜像层（幂等：已挂载仅重渲染）。
 *
 * @param textarea SDK Sender 的输入 textarea
 * @returns 是否执行了挂载/渲染
 * @author qingfeng
 */
export function ensureChipOverlayFor(textarea: HTMLTextAreaElement): boolean {
  const repaintExisting = repaintRegistry.get(textarea);
  if (repaintExisting) {
    repaintExisting();
    return true;
  }
  const parent = textarea.parentElement;
  if (!parent) {
    return false;
  }

  ensureChipStyles();

  // 清理父容器内因 SDK 重建 textarea 而遗留的孤儿镜像层，避免陈旧渲染
  parent.querySelectorAll("div[data-qwenpaw-chip-overlay]").forEach((stale) => {
    stale.remove();
  });

  // absolute 镜像依赖父容器定位；static 时提升为 relative 保证 inset:0 对齐
  if (window.getComputedStyle(parent).position === "static") {
    parent.style.position = "relative";
  }

  const overlay = document.createElement("div");
  overlay.setAttribute("data-qwenpaw-chip-overlay", "1");
  overlay.setAttribute("aria-hidden", "true");
  parent.appendChild(overlay);

  const repaint = () => {
    syncStyles(textarea, overlay);
    renderOverlay(overlay, textarea.value);
    overlay.scrollTop = textarea.scrollTop;
    overlay.scrollLeft = textarea.scrollLeft;
  };
  const onInput = () => repaint();
  const onScroll = () => {
    overlay.scrollTop = textarea.scrollTop;
    overlay.scrollLeft = textarea.scrollLeft;
  };

  // × 按钮点击：镜像层 pointer-events:none 下按钮单独开启，mousedown
  // 阻止默认避免 textarea 失焦，click 整体删除对应 token
  const onOverlayClick = (event: MouseEvent) => {
    const target = event.target as HTMLElement;
    const close = target.closest<HTMLButtonElement>(".qwenpaw-chip-close");
    if (!close) {
      return;
    }
    const chip = close.closest<HTMLElement>(".qwenpaw-chip");
    if (!chip) {
      return;
    }
    deleteChipToken(
      textarea,
      Number(chip.dataset.chipStart),
      Number(chip.dataset.chipLength),
    );
  };
  const onOverlayMouseDown = (event: MouseEvent) => {
    if ((event.target as HTMLElement).closest(".qwenpaw-chip-close")) {
      event.preventDefault();
    }
  };

  // textarea 需自带堆叠层才能浮于普通文档流之上；底色必须透明露出镜像。
  // 注意：不能提前把 background 设为 transparent——SDK 可能用 inline 样式
  // 管理底色，改为仅加堆叠属性，底色由镜像层自身保持透明不遮挡
  textarea.style.position = "relative";
  textarea.style.zIndex = "1";

  textarea.addEventListener("input", onInput);
  textarea.addEventListener("scroll", onScroll);
  textarea.addEventListener("keydown", handleAtomicBackspace);
  overlay.addEventListener("click", onOverlayClick);
  overlay.addEventListener("mousedown", onOverlayMouseDown);
  repaintRegistry.set(textarea, repaint);
  mountedTextareas.add(textarea);
  repaint();
  return true;
}

/**
 * 启动聊天输入胶囊层守护：周期性地为当前活跃的 Sender textarea 补挂镜像。
 *
 * SDK 在会话切换/重挂时会重建 textarea，一次性挂载会失效；采用低频轮询
 * （纯 querySelector + dataset 判断，未变化时零 DOM 写入）覆盖重建场景。
 *
 * @returns 停止守护的清理函数
 * @author qingfeng
 */
export function startMentionChipOverlay(): () => void {
  const tick = () => {
    // 回收已被 SDK 卸载的 textarea，防 mountedTextareas 无界增长
    mountedTextareas.forEach((textarea) => {
      if (!textarea.isConnected) {
        mountedTextareas.delete(textarea);
        repaintRegistry.delete(textarea);
      }
    });
    // 复用项目内活跃 textarea 定位（聚焦优先/可见优先），避免误挂到
    // SDK 自适应高度用的隐藏测量 textarea
    const textarea = getActiveSenderTextarea();
    if (textarea) {
      ensureChipOverlayFor(textarea);
    }
  };
  tick();
  const timer = window.setInterval(tick, 1000);
  return () => window.clearInterval(timer);
}
