import { type ReactNode } from "react";
import styles from "./index.module.less";

export type PageHeaderBreadcrumbItem = {
  title: ReactNode;
};

export interface PageHeaderProps {
  /**
   * @deprecated 路径面包屑已上移到顶部导航条（layouts/NavTabsBar），并由菜单数据
   * 派生。这里仅保留类型兼容：未传 current 时取末项作为页面标题。
   */
  items?: PageHeaderBreadcrumbItem[];
  /**
   * @deprecated 父级路径同样由顶部导航条从菜单树解析，页面不应再自报父级文案
   * （否则后端菜单改名后页内路径不会跟随，形成第二份数据源）。
   */
  parent?: ReactNode;
  /** 页面标题（画布带上唯一的视觉主角）。 */
  current?: ReactNode;
  center?: ReactNode;
  extra?: ReactNode;
  /** 与标题同行的附加内容（如工作区路径 chip）。 */
  afterBreadcrumb?: ReactNode;
  subRow?: ReactNode;
  className?: string;
}

/** 未显式传 current 时，从旧的面包屑 items 里取末项兜底，保证标题不丢。 */
function resolveTitle(
  current: ReactNode | undefined,
  items: PageHeaderBreadcrumbItem[] | undefined,
): ReactNode {
  if (current != null && current !== "") return current;
  const last = items?.[items.length - 1];
  return last?.title ?? null;
}

export function PageHeader({
  items,
  current,
  center,
  extra,
  afterBreadcrumb,
  subRow,
  className,
}: PageHeaderProps) {
  const title = resolveTitle(current, items);

  return (
    <div className={`${styles.pageHeader} ${className ?? ""}`.trim()}>
      <div className={styles.leading}>
        <div className={styles.leadingTop}>
          <div className={styles.breadcrumbHeader}>
            <span className={styles.breadcrumbCurrent}>{title}</span>
            {afterBreadcrumb}
          </div>
        </div>
        {subRow}
      </div>
      {center ? <div className={styles.center}>{center}</div> : null}
      {extra ? <div className={styles.extra}>{extra}</div> : null}
    </div>
  );
}

export default PageHeader;
