/**
 * patch-mentions-group.mjs — 给 @agentscope-ai/chat 的 mention 弹层打分组补丁。
 *
 * 背景：聊天输入框 @ 提及的候选弹层由 SDK 的 useMentions 渲染，候选是
 * 纯平铺列表（图标 + 名称），不支持分组标题，档案/技能/工具/MCP 混在
 * 一起难以区分（产品要求对标竞品的分类导航体验）。
 *
 * 补丁内容：在 lib 产物的 filteredItems.map 渲染处注入分组逻辑——当候选
 * 带 group 字段且与上一项不同组时，在该项前插入一个非交互的分组标题
 * div（class 由 SDK prefixCls 派生：`...-mentions-group`）。标题节点不占
 * 键盘导航索引（activeIndex 仍基于 filteredItems 扁平索引），上下键/回车
 * 行为与打补丁前完全一致；group 字段缺省时渲染结果与原版逐字节等价。
 *
 * 补丁对象是 lib/ 编译产物（vite 按 package.json#module 加载 lib/index.js；
 * 随包发布的 components/ 源码目录不参与构建，不改）。脚本幂等：已打补丁
 * 时直接跳过；SDK 升级导致锚点失配时显式报错退出，避免静默失效。
 *
 * 由 console 的 npm postinstall 钩子自动执行；本仓库内 node_modules 重装
 * 后重跑本脚本即可恢复，无需手工干预。
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";

import path from "node:path";

import { fileURLToPath } from "node:url";

const consoleRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

const target = path.join(
  consoleRoot,
  "node_modules",
  "@agentscope-ai",
  "chat",
  "lib",
  "AgentScopeRuntimeWebUI",
  "core",
  "Chat",
  "Input",
  "useMentions.js",
);

/** 补丁幂等标记：注入代码中的特征串。 */
const MARKER = "showGroup ? [groupNode, option] : option";

/**
 * 补丁替换表：original 在产物中必须唯一命中，否则视为 SDK 版本不兼容。
 * 锚点与 @agentscope-ai/chat 1.1.73-beta.1787638407498 的 lib 产物对齐。
 */
const REPLACEMENTS = [
  // 1) map 回调开头：计算当前项是否需要插入分组标题
  {
    name: "group-head",
    original: [
      `? filteredItems.map(function (item, index) {`,
      `      var _item$label;`,
    ].join("\n"),
    patched: [
      `? filteredItems.map(function (item, index) {`,
      `      var _item$label;`,
      `      var prevItem = index > 0 ? filteredItems[index - 1] : null;`,
      `      var showGroup = !!item.group && (!prevItem || prevItem.group !== item.group);`,
      `      var groupNode = showGroup ? /*#__PURE__*/_jsx("div", {`,
      `        className: "".concat(prefixCls, "-group"),`,
      `        children: item.group`,
      `      }, "".concat(item.group, "#group")) : null;`,
    ].join("\n"),
  },
  // 2) 候选 button 赋给局部变量，便于与标题一起返回
  {
    name: "option-var",
    original: `      return /*#__PURE__*/_jsxs("button", {`,
    patched: `      var option = /*#__PURE__*/_jsxs("button", {`,
  },
  // 3) map 回调返回值：组首项返回 [标题, 候选]，其余仅候选
  {
    name: "group-return",
    original: [
      `      }, "".concat(item.type || 'mention', ":").concat(item.value));`,
      `    }) : /*#__PURE__*/_jsx("div", {`,
    ].join("\n"),
    patched: [
      `      }, "".concat(item.type || 'mention', ":").concat(item.value));`,
      `      return ${MARKER};`,
      `    }) : /*#__PURE__*/_jsx("div", {`,
    ].join("\n"),
  },
];

function main() {
  if (!existsSync(target)) {
    console.error(
      "[patch-mentions-group] target not found: %s\n" +
        "请先在 console 目录执行 npm install。",
      target,
    );
    process.exit(1);
  }

  const code = readFileSync(target, "utf8");
  if (code.includes(MARKER)) {
    console.log("[patch-mentions-group] already applied, skip.");
    return;
  }

  let next = code;
  for (const { name, original, patched } of REPLACEMENTS) {
    const count = next.split(original).length - 1;
    if (count !== 1) {
      console.error(
        "[patch-mentions-group] anchor %j hit %d times (expect 1).\n" +
          "@agentscope-ai/chat 版本可能已升级，请对照 " +
          "components/AgentScopeRuntimeWebUI/core/Chat/Input/useMentions.tsx " +
          "更新本脚本的锚点。",
        name,
        count,
      );
      process.exit(1);
    }
    next = next.replace(original, patched);
  }

  writeFileSync(target, next, "utf8");
  console.log("[patch-mentions-group] patched: %s", target);
}

main();
