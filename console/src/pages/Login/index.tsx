import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Checkbox, Form, Input, Modal, Select } from "antd";
import { useAppMessage } from "../../hooks/useAppMessage";
import type { LucideIcon } from "lucide-react";
import {
  Boxes,
  Github,
  Globe2,
  Languages,
  LockKeyhole,
  ShieldAlert,
  ShieldCheck,
  UserRound,
  Users,
  Workflow,
} from "lucide-react";
import { authApi, type OrgInfo } from "../../api/modules/auth";
import { setAuthToken } from "../../api/config";
import BrandMark, { BRAND_NAME, OS_BRAND_NAME } from "../../components/BrandMark";
import { getPostLoginHref } from "../../utils/navigationMode";
import styles from "./index.module.less";

/**
 * 品牌展示区能力卡片元数据：图标 + 文案键。
 * 文案全部走 login.* i18n 键，此处只固定图标与键名，禁止出现任何硬编码业务文案。
 */
const BRAND_FEATURES: {
  key: string;
  Icon: LucideIcon;
}[] = [
  { key: "Team", Icon: Users },
  { key: "Orchestrate", Icon: Workflow },
  { key: "Skills", Icon: Boxes },
];

export default function LoginPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const [hasUsers, setHasUsers] = useState(true);
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  // 默认超管仍用内置口令时展示提示条（引导首次登录后立即改密）。
  const [defaultAdminHint, setDefaultAdminHint] = useState(false);
  const [isHub, setIsHub] = useState(false);
  const [disclaimerAccepted, setDisclaimerAccepted] = useState(false);
  const [termsOpen, setTermsOpen] = useState(false);
  const [termsRead, setTermsRead] = useState(false);
  // Phase 4: 注册页组织下拉 + 登录页"记住我"。
  const [organizations, setOrganizations] = useState<OrgInfo[]>([]);
  const [rememberMe, setRememberMe] = useState(false);
  const [pendingCredentials, setPendingCredentials] = useState<{
    username: string;
    password: string;
    orgId?: string;
  } | null>(null);
  const { message } = useAppMessage();
  const rawRedirect = searchParams.get("redirect") || "/chat";
  const redirect =
    rawRedirect.startsWith("/") && !rawRedirect.startsWith("//")
      ? rawRedirect
      : "/chat";

  const finishNavigation = useCallback(
    (target: string) => {
      const osHref = getPostLoginHref(window.location.pathname, target);
      if (osHref) {
        window.location.replace(osHref);
        return;
      }
      navigate(target, { replace: true });
    },
    [navigate],
  );

  useEffect(() => {
    authApi
      .getStatus()
      .then((res) => {
        if (!res.enabled) {
          finishNavigation(redirect);
          return;
        }
        setHasUsers(res.has_users);
        setRegistrationEnabled(Boolean(res.registration_enabled));
        setDefaultAdminHint(Boolean(res.default_admin_hint));
        setIsHub(res.mode === "hub");
        if (!res.has_users) {
          setIsRegister(true);
        }
      })
      .catch(() => {});
  }, [finishNavigation, redirect]);

  // Phase 4: 进入注册模式时拉取可选组织列表。
  // 后端 orgs service 不可用时返回空列表，下拉自动隐藏（参见下方渲染）。
  useEffect(() => {
    if (!isRegister) {
      return;
    }
    let cancelled = false;
    authApi
      .getOrgs()
      .then((orgs) => {
        if (!cancelled) {
          setOrganizations(orgs);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setOrganizations([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isRegister]);

  const submitCredentials = async (values: {
    username: string;
    password: string;
    orgId?: string;
  }) => {
    setLoading(true);
    try {
      if (isRegister) {
        const res = await authApi.register(
          values.username,
          values.password,
          values.orgId,
        );
        if (res.token) {
          setAuthToken(res.token);
          message.success(t("login.registerSuccess"));
          finishNavigation(redirect);
        }
      } else {
        const res = await authApi.login(
          values.username,
          values.password,
          rememberMe,
        );
        if (res.token) {
          setAuthToken(res.token);
          finishNavigation(redirect);
        } else {
          message.info(t("login.authNotEnabled"));
          finishNavigation(redirect);
        }
      }
    } catch (err) {
      let errorMsg = t("login.failed");

      // Check if it's an Error object and use the backend message directly
      if (err instanceof Error) {
        // Use the backend message directly without complex parsing
        errorMsg = err.message;
      } else if (isRegister) {
        errorMsg = t("login.registerFailed");
      }

      message.error(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const onFinish = async (values: {
    username: string;
    password: string;
    org_id?: string;
  }) => {
    const payload = {
      username: values.username,
      password: values.password,
      orgId: values.org_id,
    };
    if (isHub && !disclaimerAccepted) {
      setPendingCredentials(payload);
      openTerms();
      return;
    }
    await submitCredentials(payload);
  };

  const openTerms = () => {
    setTermsRead(false);
    setTermsOpen(true);
  };

  const acceptTerms = () => {
    if (!termsRead) {
      return;
    }
    setDisclaimerAccepted(true);
    setTermsOpen(false);
    if (pendingCredentials) {
      const credentials = pendingCredentials;
      setPendingCredentials(null);
      void submitCredentials(credentials);
    }
  };

  const cancelTerms = () => {
    setTermsOpen(false);
    setPendingCredentials(null);
  };

  const isChinese = (i18n.resolvedLanguage || i18n.language || "en").startsWith(
    "zh",
  );

  const switchHubLanguage = () => {
    const language = isChinese ? "en" : "zh";
    void i18n.changeLanguage(language);
    localStorage.setItem("language", language);
  };

  return (
    <div className={styles.page}>
      {/* 左栏品牌展示区：体现 SmartWork「数字员工 OS」核心定位，
          文案全部来自 login.* i18n 键（品牌名走 {{brand}} 插值）。 */}
      <section className={styles.brandPanel}>
        <div className={styles.brandGlow} aria-hidden="true" />
        <div className={styles.brandInner}>
          <div className={styles.brandHead}>
            <BrandMark size={52} />
            <span className={styles.brandName}>{OS_BRAND_NAME}</span>
          </div>
          <h1 className={styles.slogan}>
            {t("login.brandSlogan", { brand: BRAND_NAME })}
          </h1>
          <p className={styles.subSlogan}>{t("login.brandSubSlogan")}</p>
          <div className={styles.featureGrid}>
            {BRAND_FEATURES.map(({ key, Icon }) => (
              <div className={styles.featureCard} key={key}>
                <span className={styles.featureIcon}>
                  <Icon size={18} />
                </span>
                <div className={styles.featureText}>
                  <div className={styles.featureTitle}>
                    {t(`login.feature${key}Title`)}
                  </div>
                  <div className={styles.featureDesc}>
                    {t(`login.feature${key}Desc`)}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className={styles.brandFoot}>
            <ShieldCheck size={14} aria-hidden="true" />
            <span>{t("login.brandPrivacyNote")}</span>
          </div>
        </div>
      </section>

      {/* 右栏表单区：窄屏时顶部补精简品牌头，宽屏隐藏。 */}
      <section className={styles.formPanel}>
        <div className={styles.formInner}>
          <div className={styles.mobileBrand}>
            <BrandMark size={40} />
            <span className={styles.mobileBrandName}>{BRAND_NAME}</span>
          </div>
          <div className={styles.formHeader}>
            <h2 className={styles.formTitle}>
              {isRegister
                ? t("login.registerTitle")
                : t("login.title", { brand: BRAND_NAME })}
            </h2>
            {!hasUsers && <p className={styles.formHint}>{t("login.firstUserHint")}</p>}
          </div>

          {defaultAdminHint && (
            <div className={styles.defaultAdminHint}>
              <ShieldAlert size={16} aria-hidden="true" />
              <span>
                {t(
                  "login.defaultAdminHint",
                  "默认管理员 admin / 密码 admin123，首次登录后请立即修改密码",
                )}
              </span>
            </div>
          )}

        <Form
          layout="vertical"
          onFinish={onFinish}
          autoComplete="off"
          size="large"
        >
          <Form.Item
            name="username"
            rules={[{ required: true, message: t("login.usernameRequired") }]}
          >
            <Input
              prefix={<UserRound size={16} className={styles.inputIcon} />}
              placeholder={t("login.usernamePlaceholder")}
              autoFocus
            />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[{ required: true, message: t("login.passwordRequired") }]}
          >
            <Input.Password
              prefix={<LockKeyhole size={16} className={styles.inputIcon} />}
              placeholder={t("login.passwordPlaceholder")}
            />
          </Form.Item>

          {/* Phase 4: 注册模式下显示所属组织下拉（后端 orgs service
              不可用时 organizations 为空，自动隐藏）。
              只有一个组织时预选中，避免多余点击。 */}
          {isRegister && organizations.length > 0 && (
            <Form.Item
              name="org_id"
              label={t("login.organizationLabel")}
              initialValue={
                organizations.length === 1 ? organizations[0].id : undefined
              }
              rules={
                organizations.length > 1
                  ? [
                      {
                        required: true,
                        message: t("login.organizationRequired"),
                      },
                    ]
                  : []
              }
            >
              <Select
                placeholder={t("login.organizationPlaceholder")}
                options={organizations.map((org) => ({
                  value: org.id,
                  label: org.name,
                }))}
                disabled={organizations.length === 1}
              />
            </Form.Item>
          )}

          {/* Phase 4: 登录模式下显示"记住我"。勾选后 token 永久有效，
              否则默认 7 天（后端 LoginRequest.expires_in 控制）。 */}
          {!isRegister && (
            <Form.Item style={{ marginBottom: 8 }}>
              <Checkbox
                checked={rememberMe}
                onChange={(event) => setRememberMe(event.target.checked)}
              >
                {t("login.rememberMe")}
              </Checkbox>
            </Form.Item>
          )}

          {isHub && (
            <div className={styles.hubDisclaimer}>
              <div className={styles.disclaimerHeading}>
                <ShieldAlert size={16} aria-hidden="true" />
                <span>{t("login.hubDisclaimerTitle")}</span>
              </div>
              <ul className={styles.disclaimerPoints}>
                {[1, 2, 3].map((point) => (
                  <li key={point}>{t(`login.hubDisclaimerPoint${point}`)}</li>
                ))}
              </ul>
              <Checkbox
                checked={disclaimerAccepted}
                aria-label={t("login.hubDisclaimerAccept")}
                onChange={(event) => {
                  if (event.target.checked) {
                    openTerms();
                    return;
                  }
                  setDisclaimerAccepted(false);
                }}
              />
              <span className={styles.consentText}>
                {t("login.hubDisclaimerAcceptPrefix")}
                <button type="button" onClick={openTerms}>
                  {t("login.hubTerms")}
                </button>
              </span>
            </div>
          )}

          <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              style={{ height: 44, borderRadius: 8, fontWeight: 500 }}
            >
              {isRegister ? t("login.register") : t("login.submit")}
            </Button>
          </Form.Item>
        </Form>
        {hasUsers && registrationEnabled && (
          <Button
            type="link"
            block
            onClick={() => setIsRegister((current) => !current)}
            style={{ marginTop: 14 }}
          >
            {isRegister ? t("login.returnToSignIn") : t("login.createAccount")}
          </Button>
        )}
        {isHub && (
          <nav className={styles.hubLinks} aria-label={t("login.hubLinks")}>
            <a
              href="https://github.com/agentscope-ai/QwenPaw"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Github size={14} strokeWidth={1.8} aria-hidden="true" />
              GitHub
            </a>
            <span aria-hidden="true" />
            <a
              href="https://qwenpaw.agentscope.io/"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Globe2 size={14} strokeWidth={1.8} aria-hidden="true" />
              {t("login.officialWebsite")}
            </a>
            <span aria-hidden="true" />
            <button
              type="button"
              aria-label={t("login.switchLanguage")}
              onClick={switchHubLanguage}
            >
              <Languages size={14} strokeWidth={1.8} aria-hidden="true" />
              {isChinese ? "English" : "简体中文"}
            </button>
          </nav>
        )}
        </div>
      </section>
      {isHub && (
        <Modal
          className={styles.termsModal}
          open={termsOpen}
          title={t("login.hubTermsTitle")}
          onCancel={cancelTerms}
          footer={
            <Button type="primary" disabled={!termsRead} onClick={acceptTerms}>
              {t("login.hubTermsAgree")}
            </Button>
          }
          centered
          width={620}
          destroyOnHidden
        >
          <div
            className={styles.termsScroll}
            onScroll={(event) => {
              const target = event.currentTarget;
              const remaining =
                target.scrollHeight - target.scrollTop - target.clientHeight;
              if (remaining <= 4) {
                setTermsRead(true);
              }
            }}
          >
            <p className={styles.termsLead}>{t("login.hubTermsLead")}</p>
            {[1, 2, 3, 4, 5, 6].map((section) => (
              <section key={section}>
                <h3>{t(`login.hubTermsSection${section}Title`)}</h3>
                <p>{t(`login.hubTermsSection${section}Body`)}</p>
              </section>
            ))}
            <p className={styles.termsEnd}>{t("login.hubTermsEnd")}</p>
          </div>
          {!termsRead && (
            <p className={styles.scrollHint}>{t("login.hubTermsScrollHint")}</p>
          )}
        </Modal>
      )}
    </div>
  );
}
