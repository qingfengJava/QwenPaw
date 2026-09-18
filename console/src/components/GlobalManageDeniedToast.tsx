/**
 * GlobalManageDeniedToast — 后台配置域越权（403）的全局统一提示。
 *
 * request.ts 命中后端 `_deny_manage` 签名时派发 `qwenpaw:manage-denied`
 * 事件，本组件挂在 antd `<App>` 上下文内统一弹一次 toast。用固定 key 去重，
 * 避免连续越权写堆叠多条；文案直接取后端 detail（已是中文可读），无则回落
 * i18n。双平面模型下这是「无管理授权却触发写请求」的兜底提示——正常路径下
 * 管理型 UI 已按 manageable 隐藏，本 toast 仅覆盖权限中途回收等边缘场景。
 */
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";

const EVENT_NAME = "qwenpaw:manage-denied";
const TOAST_KEY = "qwenpaw-manage-denied";

export function GlobalManageDeniedToast() {
  const { message } = useAppMessage();
  const { t } = useTranslation();

  useEffect(() => {
    const onDenied = (event: Event) => {
      const detail = (event as CustomEvent<{ message?: string }>).detail;
      const content =
        detail?.message ||
        t("employee.governance.manageDenied", "无该员工配置权限");
      // 固定 key：连续越权只保留一条提示，不堆叠
      message.error({ content, key: TOAST_KEY, duration: 3 });
    };
    window.addEventListener(EVENT_NAME, onDenied);
    return () => window.removeEventListener(EVENT_NAME, onDenied);
  }, [message, t]);

  return null;
}

export default GlobalManageDeniedToast;
