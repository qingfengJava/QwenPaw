/**
 * 控制台杂音过滤钩子（第三方库噪音降噪）。
 *
 * 必须作为入口 main.tsx 的**首个** import：第三方库在**模块导入阶段**就会
 * 输出告警（如 @agentscope-ai/design 的 Anchor、@agentscope-ai/chat 的
 * ActionButton 在 forwardRef() 调用时校验参数个数），而静态导入图先于
 * main.tsx 模块体求值，钩子若写在 main.tsx 模块体内则会晚于这些告警安装，
 * 导致过滤失效（历史踩坑：forwardRef 告警在启动日志中反复出现）。
 */

/** console.error 过滤关键词：命中则吞掉 */
const ERROR_FILTERS: readonly string[] = [
  ":first-child",
  "pseudo class",
  // 已知第三方库噪音：antd 内部 findDOMNode 与 chat-anywhere 库的 flushSync；
  // overlayClassName 弃用警告来自 @agentscope-ai/design 内部（项目侧 6 处
  // 已全部迁移到 classNames={{ root }}，待组件库升级后可移除此过滤）
  "findDOMNode is deprecated",
  "flushSync was called from inside a lifecycle method",
  "overlayClassName` is deprecated",
  // @agentscope-ai/design 的 Anchor 与 @agentscope-ai/chat 的 ActionButton
  // 存在单参 forwardRef 缺陷（渲染函数未声明 ref 参数），属库侧问题，待升级后移除
  "forwardRef render functions accept exactly two parameters",
];

/** console.warn 过滤关键词：命中则吞掉 */
const WARN_FILTERS: readonly string[] = [
  ":first-child",
  "pseudo class",
  "potentially unsafe",
];

if (typeof window !== "undefined") {
  const originalError = console.error;
  const originalWarn = console.warn;

  console.error = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    // 命中已知噪音白名单则直接吞掉，避免第三方库日志淹没真实报错
    if (ERROR_FILTERS.some((keyword) => msg.includes(keyword))) {
      return;
    }
    originalError.apply(console, args as []);
  };

  console.warn = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    // 命中已知噪音白名单则直接吞掉，避免第三方库日志淹没真实报错
    if (WARN_FILTERS.some((keyword) => msg.includes(keyword))) {
      return;
    }
    originalWarn.apply(console, args as []);
  };
}