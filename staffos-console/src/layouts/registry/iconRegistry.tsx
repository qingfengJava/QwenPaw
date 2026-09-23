/**
 * iconRegistry.tsx — 菜单图标「名字 → 组件」注册表（动态菜单）。
 *
 * 后端 rbac_menus.icon 存的是图标名字符串（如 "LayoutDashboard"），渲染时
 * 需解析回组件。这里集中维护唯一映射源（数据单一来源规范）：菜单只存字符
 * 串，组件在渲染时按名解析，避免把 React 组件塞进数据库/接口。
 *
 * 覆盖 seed（`app/rbac/seed.py::_MENU_SEED`）用到的全部图标名，来自
 * lucide-react 与 @agentscope-ai/icons 两套库。未命中返回兜底图标，绝不
 * 返回 undefined 致侧栏渲染崩溃。
 *
 * @author qingfeng
 */
import type { ComponentType } from "react";
import {
  Building2,
  BookOpen,
  Bot,
  Database,
  Flame,
  Gauge,
  KeyRound,
  LayoutDashboard,
  Layers,
  ListTodo,
  ScrollText,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  UsersRound,
} from "lucide-react";
import {
  SparkAgentLine,
  SparkBrowseLine,
  SparkDataLine,
  SparkDateLine,
  SparkDebugLine,
  SparkEmailLine,
  SparkInternetLine,
  SparkMicLine,
  SparkModePlazaLine,
  SparkMyApplicationLine,
  SparkOtherLine,
  SparkSaveLine,
  SparkWifiLine,
} from "@agentscope-ai/icons";

/** 图标名 → 组件。key 必须与 seed 里 icon 字段字符串完全一致。 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const ICON_REGISTRY: Record<string, ComponentType<any>> = {
  // lucide-react
  LayoutDashboard,
  UsersRound,
  Layers,
  Settings2,
  Database,
  SlidersHorizontal,
  Building2,
  ListTodo,
  Flame,
  Users,
  ShieldCheck,
  Bot,
  KeyRound,
  Gauge,
  ScrollText,
  BookOpen,
  // @agentscope-ai/icons
  SparkAgentLine,
  SparkWifiLine,
  SparkEmailLine,
  SparkModePlazaLine,
  SparkOtherLine,
  SparkMyApplicationLine,
  SparkMicLine,
  SparkInternetLine,
  SparkDateLine,
  SparkBrowseLine,
  SparkDataLine,
  SparkSaveLine,
  SparkDebugLine,
};

/** 供菜单管理表单图标下拉使用的全部已注册图标名（稳定排序）。 */
export const ICON_NAMES: string[] = Object.keys(ICON_REGISTRY).sort();

/**
 * 解析菜单图标名 → 图标组件。未命中返回兜底 `SparkOtherLine`，
 * 保证渲染永不因未知图标名崩溃。
 */
export function resolveMenuIcon(
  name: string | null | undefined,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): ComponentType<any> {
  if (name && ICON_REGISTRY[name]) {
    return ICON_REGISTRY[name];
  }
  return SparkOtherLine;
}
