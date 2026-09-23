/**
 * HeaderBreadcrumb — 顶栏内的路径面包屑（logo 右侧、右侧控件之前）。
 *
 * 竞品同款形态：home 图标 + 菜单树派生的「父级链 / 当前页」文本路径，
 * 标签页另起一行放正文区顶部（NavTabsBar），两者分工：
 * 面包屑答「我在哪」，标签答「我去过哪」。
 *
 * 单一来源：文案全部由菜单索引（navIndex）解析，页面不自报父级文案；
 * 详情页实体名经 usePageNavTitle 回填后随版本快照自动刷新。
 *
 * @author qingfeng
 */
import { useMemo } from "react";
import { Tooltip } from "antd";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Home } from "lucide-react";
import styles from "./index.module.less";
import { describeTab } from "./registry/tabLabel";
import type { NavTranslate } from "./registry/tabLabel";
import { HOME_TAB_KEY } from "../stores/pageNavStore";
import { useTabbableResolver } from "../hooks/useNavTab";

export default function HeaderBreadcrumb() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { resolve, navIndex, menusLoaded } = useTabbableResolver();

  // describeTab 需要的最小翻译入口：显式返回 string，避开 i18next 重载类型。
  const translate = useMemo<NavTranslate>(
    () => (key, defaultValue) => String(t(key, { defaultValue })),
    [t],
  );

  const crumb = useMemo(
    () => describeTab(resolve(location.pathname), navIndex, translate),
    [location.pathname, navIndex, resolve, translate],
  );

  return (
    <div className={styles.headerCrumb} aria-busy={!menusLoaded}>
      <Tooltip title={t("navTabs.home", "Home")} mouseEnterDelay={0.4}>
        <button
          type="button"
          className={styles.headerCrumbHome}
          aria-label={t("navTabs.home", "Home")}
          onClick={() => navigate(HOME_TAB_KEY)}
        >
          <Home size={14} />
        </button>
      </Tooltip>
      {menusLoaded && crumb?.trail.length
        ? crumb.trail.map((item, index) => (
            <span key={`${item}-${index}`} className={styles.headerCrumbParent}>
              {item}
              <span className={styles.headerCrumbSeparator}>/</span>
            </span>
          ))
        : null}
      {menusLoaded && crumb?.label ? (
        <span className={styles.headerCrumbCurrent}>{crumb.label}</span>
      ) : null}
    </div>
  );
}
