/**
 * usePageNavTitle.ts — 详情页把实体名回填到顶部标签与面包屑。
 *
 * 菜单叶子能从菜单树查到名字，但「某个员工的详情页」「某个内嵌应用」的名字只在
 * 接口数据里。页面拿到实体名后调用本 hook 即可，标签栏与面包屑会立即刷新；
 * 未回填前由 routeNavMeta 的兜底文案顶上，不会出现空白标签。
 *
 * @author qingfeng
 */
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useTabbableResolver } from "./useNavTab";
import { normalizeTabKey } from "../layouts/registry/navModel";
import { setPageTitle } from "../layouts/registry/pageTitleRegistry";

/**
 * 声明当前页面的导航标题（标签名 + 面包屑末段）。
 *
 * @param title 实体名称；数据未就绪时传空值，本 hook 会跳过写入。
 */
export function usePageNavTitle(title: string | undefined): void {
  const location = useLocation();
  const { resolve } = useTabbableResolver();

  useEffect(() => {
    if (!title) return;
    // 与建标签完全同源取 key，保证标题写到正确的标签上。
    const hit = resolve(location.pathname);
    const key = hit?.key ?? normalizeTabKey(location.pathname);
    setPageTitle(key, title);
  }, [title, location.pathname, resolve]);
}
