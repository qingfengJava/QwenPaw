/**
 * workbenchSandbox — 工作台 MemoryRouter 沙箱标记上下文。
 *
 * 工作台（/studio/:aid）自挂 MemoryRouter 沙箱，且 Chat 的会话硬导航
 * 会把沙箱路径改写成 /chat/*，通用组件无法靠 router location 判断自己
 * 是否运行在沙箱内。沙箱外壳挂载时通过本上下文下发当前员工 id：
 * - 非 null：处于沙箱内，跨页跳转必须走沙箱内路径（/studio/:aid/...）；
 * - null：app 级路由（独立聊天页等），走全局路径。
 */
import { createContext, useContext } from "react";

export const WorkbenchSandboxContext = createContext<string | null>(null);

/** 返回沙箱内当前员工 id；沙箱外返回 null。 */
export function useWorkbenchSandboxAid(): string | null {
  return useContext(WorkbenchSandboxContext);
}
