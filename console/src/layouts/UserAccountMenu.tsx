/**
 * UserAccountMenu — Header 右上角当前登录用户头像下拉。
 *
 * 企业级后台惯例：把「账户管理 / 退出登录」收进右上角用户菜单，侧栏底部
 * 不再放孤立的操作按钮（原 Sidebar.authActions 已迁出于此）。组件自持鉴权
 * 状态、Hub 管理员判定与账户资料弹窗，Header 只需渲染
 * `<UserAccountMenu hubMode={...} />`。
 *
 * @author qingfeng
 */
import { useEffect, useRef, useState } from "react";
import {
  Avatar,
  Button,
  Divider,
  Dropdown,
  Form,
  Input,
  Modal,
  Popconfirm,
} from "antd";
import type { MenuProps } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ShieldCheck, RotateCw } from "lucide-react";
import {
  SparkExitFullscreenLine,
  SparkSearchUserLine,
} from "@agentscope-ai/icons";
import { useAppMessage } from "../hooks/useAppMessage";
import { useExpertAvatarUri } from "../hooks/useExpertAvatarUri";
import { clearAuthToken } from "../api/config";
import { authApi } from "../api/modules/auth";
import { userProfilesApi } from "../api/modules/userProfiles";
import { hubApi } from "../api/modules/hub";
import { useAuthStore } from "../stores/authStore";
import styles from "./index.module.less";

interface UserAccountMenuProps {
  /** True when the backend runs in self-hosted Hub mode (M6). */
  hubMode?: boolean;
}

export default function UserAccountMenu({
  hubMode = false,
}: UserAccountMenuProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [hubAdmin, setHubAdmin] = useState(false);
  const [hubUsername, setHubUsername] = useState("");
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [accountLoading, setAccountLoading] = useState(false);
  const [runtimeRestarting, setRuntimeRestarting] = useState(false);
  // 头像下拉展开态（受控）：用于给触发器补 aria-expanded。
  const [menuOpen, setMenuOpen] = useState(false);
  const [accountForm] = Form.useForm();
  // 当前登录用户名（资料预填 + 头像种子）+ 打开弹窗时记录的原始昵称（变更判定用）。
  const storeUsername = useAuthStore((s) => s.username);
  const currentUsername = storeUsername || hubUsername;
  const initialDisplayNameRef = useRef<string | null>(null);

  // 头像种子：Hub 模式用 hub 账号名，否则用本地登录名；空值兜底 "user"。
  const avatarUri = useExpertAvatarUri("", currentUsername || "user");

  // 拉取鉴权状态；Hub 模式下再取当前用户角色/用户名以决定是否显示平台管理入口。
  useEffect(() => {
    authApi
      .getStatus()
      .then(async (res) => {
        setAuthEnabled(res.enabled);
        if (res.mode === "hub") {
          const user = await hubApi.me();
          setHubAdmin(user.role === "admin");
          setHubUsername(user.username);
        }
      })
      .catch(() => {});
  }, []);

  /**
   * 提交账户资料修改（用户名 / 密码 / 昵称）。Hub 模式账号名不可变，仅轮换密码。
   */
  const handleUpdateProfile = async (values: {
    currentPassword: string;
    newUsername?: string;
    newPassword?: string;
    displayName?: string;
  }) => {
    const trimmedUsername = values.newUsername?.trim() || undefined;
    const trimmedPassword = values.newPassword?.trim() || undefined;
    // 昵称仅在发生变化时才下发（未变则 undefined，后端不动该字段）。
    const nextDisplayName = values.displayName?.trim() ?? "";
    const displayNameChanged =
      initialDisplayNameRef.current !== null &&
      nextDisplayName !== initialDisplayNameRef.current;
    const trimmedDisplayName = displayNameChanged
      ? nextDisplayName
      : undefined;

    if (values.newPassword && !trimmedPassword) {
      message.error(t("account.passwordEmpty"));
      return;
    }

    if (values.newUsername && !trimmedUsername) {
      message.error(t("account.usernameEmpty"));
      return;
    }

    if (
      !hubMode &&
      !trimmedUsername &&
      !trimmedPassword &&
      trimmedDisplayName === undefined
    ) {
      message.warning(t("account.nothingToUpdate"));
      return;
    }

    if (hubMode && !trimmedPassword) {
      message.warning(t("account.passwordRequired"));
      return;
    }

    setAccountLoading(true);
    try {
      if (hubMode) {
        // Hub mode: the hub account's username is immutable; only the
        // password rotates (and stays logged in -- the hub JWT remains
        // valid across password changes).
        await hubApi.changePassword(trimmedPassword as string);
        message.success(t("account.updateSuccess"));
        setAccountModalOpen(false);
        accountForm.resetFields();
      } else {
        const res = await authApi.updateProfile(
          values.currentPassword,
          trimmedUsername,
          trimmedPassword,
          trimmedDisplayName,
        );
        message.success(t("account.updateSuccess"));
        setAccountModalOpen(false);
        accountForm.resetFields();
        // 仅改昵称（token 为空）保持登录态；改了用户名/密码才重新登录。
        if (res.token) {
          clearAuthToken();
          window.location.href = "/login";
        }
      }
    } catch (err: unknown) {
      const raw = err instanceof Error ? err.message : "";
      let msg = t("account.updateFailed");
      if (raw.includes("password is incorrect")) {
        msg = t("account.wrongPassword");
      } else if (raw.includes("Nothing to update")) {
        msg = t("account.nothingToUpdate");
      } else if (raw.includes("cannot be empty")) {
        msg = t("account.nothingToUpdate");
      } else if (raw) {
        msg = raw;
      }
      message.error(msg);
    } finally {
      setAccountLoading(false);
    }
  };

  /**
   * 打开账户弹窗并预填当前昵称（作为变更判定基线）。
   */
  const openAccountModal = async () => {
    accountForm.resetFields();
    initialDisplayNameRef.current = null;
    setAccountModalOpen(true);
    if (hubMode || !currentUsername) {
      return;
    }
    try {
      const profiles = await userProfilesApi.getProfiles([currentUsername]);
      const name = profiles.get(currentUsername)?.display_name || "";
      initialDisplayNameRef.current = name;
      accountForm.setFieldsValue({ displayName: name });
    } catch {
      // 预填失败不阻断弹窗（昵称留空，用户可手动输入）。
      initialDisplayNameRef.current = null;
    }
  };

  const handleRestartRuntime = async () => {
    setRuntimeRestarting(true);
    try {
      await hubApi.restartOwnRuntime();
      message.success(t("account.runtimeRestartSuccess"));
      window.location.reload();
    } catch (error: unknown) {
      message.error(
        error instanceof Error
          ? error.message
          : t("account.runtimeRestartFailed"),
      );
    } finally {
      setRuntimeRestarting(false);
    }
  };

  // 单机模式（认证关闭）不显示用户菜单。
  if (!authEnabled) {
    return null;
  }

  const menuItems: MenuProps["items"] = [
    ...(hubAdmin
      ? [
          {
            key: "hubAdmin",
            icon: <ShieldCheck size={16} />,
            label: t("hub.brand.title"),
            onClick: () => navigate("/hub/admin"),
          },
        ]
      : []),
    {
      key: "account",
      icon: <SparkSearchUserLine size={16} />,
      label: t("account.title"),
      onClick: () => {
        void openAccountModal();
      },
    },
    { type: "divider" },
    {
      key: "logout",
      icon: <SparkExitFullscreenLine size={16} />,
      label: t("login.logout"),
      onClick: () => {
        clearAuthToken();
        window.location.href = "/login";
      },
    },
  ];

  return (
    <>
      <Dropdown
        menu={{ items: menuItems }}
        placement="bottomRight"
        trigger={["click"]}
        open={menuOpen}
        onOpenChange={setMenuOpen}
      >
        <span
          className={styles.userMenuTrigger}
          role="button"
          tabIndex={0}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={currentUsername || t("account.title")}
          onKeyDown={(e) => {
            if (e.key !== "Enter" && e.key !== " ") return;
            e.preventDefault();
            (e.currentTarget as HTMLElement).click();
          }}
        >
          <Avatar
            size={32}
            src={avatarUri ?? undefined}
            icon={!avatarUri ? <SparkSearchUserLine size={18} /> : undefined}
          />
        </span>
      </Dropdown>

      <Modal
        open={accountModalOpen}
        onCancel={() => setAccountModalOpen(false)}
        title={t("account.title")}
        footer={null}
        destroyOnHidden
        centered
      >
        <Form
          form={accountForm}
          layout="vertical"
          onFinish={handleUpdateProfile}
        >
          {hubMode ? (
            <div className={styles.accountIdentity}>
              <span>{t("account.username")}</span>
              <strong>{hubUsername}</strong>
            </div>
          ) : (
            <>
              <Form.Item
                name="currentPassword"
                label={t("account.currentPassword")}
                rules={[
                  {
                    required: true,
                    message: t("account.currentPasswordRequired"),
                  },
                ]}
              >
                <Input.Password />
              </Form.Item>
              <Form.Item name="newUsername" label={t("account.newUsername")}>
                <Input placeholder={t("account.newUsernamePlaceholder")} />
              </Form.Item>
              <Form.Item name="displayName" label={t("account.displayName")}>
                <Input placeholder={t("account.displayNamePlaceholder")} />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="newPassword"
            label={t("account.newPassword")}
            rules={
              hubMode
                ? [
                    {
                      required: true,
                      message: t("account.passwordRequired"),
                    },
                    { min: 8, message: t("hub.validation.passwordMin") },
                  ]
                : undefined
            }
          >
            <Input.Password
              placeholder={t(
                hubMode
                  ? "account.hubPasswordPlaceholder"
                  : "account.newPasswordPlaceholder",
              )}
            />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label={t("account.confirmPassword")}
            dependencies={["newPassword"]}
            rules={[
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value && !getFieldValue("newPassword")) {
                    return Promise.resolve();
                  }
                  if (value === getFieldValue("newPassword")) {
                    return Promise.resolve();
                  }
                  return Promise.reject(
                    new Error(t("account.passwordMismatch")),
                  );
                },
              }),
            ]}
          >
            <Input.Password
              placeholder={t("account.confirmPasswordPlaceholder")}
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={accountLoading}
              block
            >
              {t("account.save")}
            </Button>
          </Form.Item>
          {hubMode && (
            <div className={styles.runtimeRecovery}>
              <Divider />
              <strong>{t("account.runtimeTitle")}</strong>
              <p>{t("account.runtimeDescription")}</p>
              <Popconfirm
                title={t("account.runtimeRestartConfirmTitle")}
                description={t("account.runtimeRestartConfirmDescription")}
                onConfirm={handleRestartRuntime}
                okText={t("account.runtimeRestart")}
                cancelText={t("common.cancel")}
              >
                <Button
                  icon={<RotateCw size={16} />}
                  loading={runtimeRestarting}
                  block
                >
                  {t("account.runtimeRestart")}
                </Button>
              </Popconfirm>
            </div>
          )}
        </Form>
      </Modal>
    </>
  );
}
