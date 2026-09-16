import { useState, useEffect, useCallback } from "react";
import { Card, Alert } from "@agentscope-ai/design";
import { Modal, Switch } from "antd";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import api from "../../../../api";
import styles from "../index.module.less";

/**
 * AccountAuthTab — master switch for account authentication.
 *
 * 关闭 = 本地单用户零配置体验（默认）；开启 = API 需登录（Bearer token）。
 * 环境变量 QWENPAW_AUTH_ENABLED 显式设置时开关只读（部署级优先）。
 * 开启前若尚无任何账号，会引导先去注册管理员，避免远程访问被锁死。
 */
export function AccountAuthTab() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [envOverridden, setEnvOverridden] = useState(false);
  const [hasUsers, setHasUsers] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getAuthEnabled();
      setAuthEnabled(Boolean(data?.auth_enabled));
      setEnvOverridden(Boolean(data?.env_overridden));
      setHasUsers(data?.has_users ?? true);
    } catch {
      message.error(t("security.accountAuth.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t, message]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const persist = useCallback(
    async (next: boolean) => {
      try {
        setSaving(true);
        const data = await api.updateAuthEnabled({ auth_enabled: next });
        setAuthEnabled(Boolean(data?.auth_enabled));
        message.success(
          next
            ? t("security.accountAuth.enableSuccess")
            : t("security.accountAuth.disableSuccess"),
        );
        // 开启认证后当前免登录会话需重新走登录流程，提示刷新。
        if (next) {
          message.info(t("security.accountAuth.reloginHint"));
        }
      } catch {
        message.error(t("security.accountAuth.saveFailed"));
      } finally {
        setSaving(false);
      }
    },
    [t, message],
  );

  const handleChange = useCallback(
    (next: boolean) => {
      // 无账号时不允许直接开启：先注册管理员，避免把远程访问者全部挡在门外。
      if (next && !hasUsers) {
        Modal.confirm({
          title: t("security.accountAuth.noUserTitle"),
          content: t("security.accountAuth.noUserContent"),
          okText: t("security.accountAuth.goRegister"),
          cancelText: t("common.cancel"),
          onOk: () => {
            window.location.href = "/login";
          },
        });
        return;
      }
      if (next) {
        // 开启是高风险动作（远程访问将要求登录），二次确认。
        Modal.confirm({
          title: t("security.accountAuth.enableConfirmTitle"),
          content: t("security.accountAuth.enableConfirmContent"),
          okText: t("common.confirm"),
          cancelText: t("common.cancel"),
          onOk: () => persist(true),
        });
        return;
      }
      void persist(false);
    },
    [hasUsers, t, persist],
  );

  return (
    <div className={styles.tabContent}>
      <Alert
        message={t("security.accountAuth.title")}
        description={t("security.accountAuth.description")}
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />
      {envOverridden && (
        <Alert
          message={t("security.accountAuth.envOverridden")}
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Card className={styles.formCard} loading={loading}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <span style={{ fontWeight: 600 }}>
              {t("security.accountAuth.switchLabel")}
            </span>
            <div
              style={{
                marginTop: 4,
                color: "var(--text-muted, rgba(0,0,0,0.45))",
                fontSize: 13,
              }}
            >
              {authEnabled
                ? t("security.accountAuth.statusOn")
                : t("security.accountAuth.statusOff")}
            </div>
          </div>
          <Switch
            checked={authEnabled}
            loading={saving}
            disabled={envOverridden}
            onChange={handleChange}
          />
        </div>
      </Card>
    </div>
  );
}
