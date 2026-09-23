/**
 * Agents/console/WorkflowEmptyState.tsx — 工作流 Tab 空态。
 *
 * 工作流由外部平台对接（本期未接入），分类骨架先建好但**不造假数据**：
 * 只说明这一形态的定位与将来的接入方式，不展示占位卡片。
 */
import { useTranslation } from "react-i18next";
import { Workflow } from "lucide-react";
import styles from "./console.module.less";

export function WorkflowEmptyState() {
  const { t } = useTranslation();
  return (
    <div className={styles.empty}>
      <span className={`pg-tile ${styles.emptyTile}`} data-tone="violet">
        <Workflow size={26} />
      </span>
      <div className={styles.emptyTitle}>
        {t("employee.workflow.emptyTitle")}
      </div>
      <p className={styles.emptyDesc}>{t("employee.workflow.emptyDesc")}</p>
      <p className={styles.emptyDesc}>{t("employee.workflow.emptyHint")}</p>
    </div>
  );
}
