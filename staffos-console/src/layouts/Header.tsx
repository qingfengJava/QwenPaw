import {
  Layout,
  Space,
  Tooltip,
  Dropdown,
  Popover,
} from "antd";
import type { MenuProps } from "antd";
import LanguageSwitcher, {
  LANGUAGE_LIST,
} from "../components/LanguageSwitcher/index";
import ThemeToggleButton from "../components/ThemeToggleButton";
import UserAccountMenu from "./UserAccountMenu";
import { useTranslation } from "react-i18next";
import { Button } from "@agentscope-ai/design";
import styles from "./index.module.less";
import { openExternalLink } from "../utils/openExternalLink";
import {
  GITHUB_URL,
  getDocsUrl,
  getFeatureDemosUrl,
  getFaqUrl,
  getReleaseNotesUrl,
} from "./constants";
import { useTheme } from "../contexts/ThemeContext";
import { Slot } from "../plugins/registry/Slot";
import { useDesktopUpdate } from "../contexts/DesktopUpdateContext";
import { isDesktopApp } from "../tauri/backendRuntime";
import HeaderBreadcrumb from "./HeaderBreadcrumb";
import {
  GithubOutlined,
  FileTextOutlined,
  ReadOutlined,
  PlayCircleOutlined,
  InfoCircleOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
} from "@ant-design/icons";

const { Header: AntHeader } = Layout;

export default function Header({
  hubMode = false,
}: {
  /** True when the backend runs in self-hosted Hub mode (M6). */
  hubMode?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const { setThemeMode } = useTheme();
  const desktop = useDesktopUpdate();
  const onDesktop = isDesktopApp();

  const resourcesMenuItems: MenuProps["items"] = [
    {
      key: "tutorial",
      icon: <ReadOutlined />,
      label: t("header.tutorial"),
      onClick: () => handleNavClick(getDocsUrl(i18n.language)),
    },
    {
      key: "featureDemos",
      icon: <PlayCircleOutlined />,
      label: t("header.featureDemos"),
      onClick: () => handleNavClick(getFeatureDemosUrl(i18n.language)),
    },
    {
      key: "changelog",
      icon: <FileTextOutlined />,
      label: t("header.changelog"),
      onClick: () => handleNavClick(getReleaseNotesUrl(i18n.language)),
    },
    {
      key: "faq",
      icon: <InfoCircleOutlined />,
      label: t("header.faq"),
      onClick: () => handleNavClick(getFaqUrl(i18n.language)),
    },
  ];

  // The standalone GitHub button is hidden on mobile, so the entry is only
  // surfaced inside the mobile menu to avoid a duplicated link on desktop.
  const githubMenuItem: MenuProps["items"] = [
    {
      key: "github",
      icon: <GithubOutlined />,
      label: t("header.github"),
      onClick: () => handleNavClick(GITHUB_URL),
    },
  ];

  const mobileMenuItems: MenuProps["items"] = [
    {
      key: "language",
      label: t("sidebar.settings.language"),
      children: LANGUAGE_LIST.map(({ key, label }) => ({
        key,
        label,
        onClick: () => {
          i18n.changeLanguage(key);
          localStorage.setItem("language", key);
        },
      })),
    },
    {
      key: "theme",
      label: t("sidebar.settings.theme"),
      children: [
        {
          key: "light",
          label: t("theme.light"),
          onClick: () => setThemeMode("light"),
        },
        {
          key: "dark",
          label: t("theme.dark"),
          onClick: () => setThemeMode("dark"),
        },
        {
          key: "system",
          label: t("theme.system"),
          onClick: () => setThemeMode("system"),
        },
      ],
    },
    { type: "divider" },
    ...resourcesMenuItems,
    ...githubMenuItem,
  ];

  const handleRestartNow = () => {
    void desktop.installDownloaded();
  };

  const handleNavClick = (url: string) => {
    openExternalLink(url);
  };

  // Background download/ready state for inline header indicator.
  const isBackgroundActive =
    onDesktop &&
    desktop.isBackground &&
    (desktop.phase === "checking" || desktop.phase === "downloading");
  const isReady = onDesktop && desktop.phase === "downloaded";
  const isApplyingDownloadedUpdate =
    onDesktop && desktop.phase === "installing";
  const isBackgroundFailed =
    onDesktop && desktop.isBackground && desktop.phase === "failed";
  const backgroundDownloadPercent =
    isBackgroundActive && desktop.phase === "downloading" && desktop.total
      ? Math.min(99, Math.round((desktop.downloaded / desktop.total) * 100))
      : undefined;
  const backgroundDownloadTitle =
    backgroundDownloadPercent !== undefined
      ? `${t(
          `sidebar.updateModal.backgroundDownloading`,
        )} ${backgroundDownloadPercent}%`
      : t(`sidebar.updateModal.backgroundDownloading`);
  const backgroundFailureTitle = desktop.error?.message
    ? `${t(`sidebar.updateModal.backgroundFailed`)}: ${desktop.error.message}`
    : t(`sidebar.updateModal.backgroundFailed`);

  return (
    <>
      <AntHeader className={styles.header}>
        {/* 顶栏只覆盖内容区（侧栏全高、logo 已迁至侧栏顶部），左起即面包屑：
            与下方标签行、正文共用同一条左缘线（padding 16px）。 */}
        <HeaderBreadcrumb />
        <Slot name="header.left" kind="fill" />
        {/* 桌面端后台下载的瞬态状态（下载中/就绪/失败），非通知入口；
            更新提示链路已随顶栏改版移除。 */}
        {isBackgroundActive && (
          <Tooltip title={backgroundDownloadTitle}>
            <SyncOutlined
              spin
              style={{
                marginLeft: 6,
                fontSize: 14,
                color: "rgba(255, 157, 77, 1)",
              }}
            />
          </Tooltip>
        )}
        {isReady && (
          <Popover
            content={
              <div style={{ textAlign: "center" }}>
                <p style={{ marginBottom: 12 }}>
                  {t(`sidebar.updateModal.readyToInstallHint`, {
                    version: desktop.version,
                  })}
                </p>
                <Button
                  type="primary"
                  size="small"
                  onClick={handleRestartNow}
                  loading={isApplyingDownloadedUpdate}
                >
                  {t(`sidebar.updateModal.restartNow`)}
                </Button>
              </div>
            }
            title={t(`sidebar.updateModal.readyToInstall`)}
            trigger="click"
          >
            <Tooltip title={t(`sidebar.updateModal.readyToInstall`)}>
              <CheckCircleOutlined
                style={{ marginLeft: 6, fontSize: 14, color: "#52c41a" }}
              />
            </Tooltip>
          </Popover>
        )}
        {isBackgroundFailed && (
          <Tooltip title={backgroundFailureTitle}>
            <ExclamationCircleOutlined
              style={{
                marginLeft: 6,
                fontSize: 14,
                color: "#ff4d4f",
                cursor: "pointer",
              }}
              onClick={() => void desktop.startBackgroundDownload()}
            />
          </Tooltip>
        )}
        <Space size="middle">
          <Slot name="header.right" kind="fill" />
          <div className={styles.headerDivider} />
          {/* 语言 / 主题两个切换按钮收进一个浅底控件组；可访问名称由各组件内部
              的 Button 承载（Tooltip 包组件会因未转发 ref 而失效） */}
          <div className={`${styles.headerControls} ${styles.hideOnMobile}`}>
            <LanguageSwitcher ariaLabel={t("sidebar.settings.language")} />
            <ThemeToggleButton ariaLabel={t("sidebar.settings.theme")} />
          </div>
          {/* 当前登录用户头像下拉（账户管理 / 退出登录 / Hub 平台管理），
              从侧栏底部迁出至右上角，侧栏底部不再堆操作按钮。 */}
          <UserAccountMenu hubMode={hubMode} />
          <Dropdown menu={{ items: mobileMenuItems }} placement="bottomRight">
            <Button
              type="text"
              icon={<InfoCircleOutlined />}
              className={styles.showOnMobile}
              title={t("header.resources")}
            />
          </Dropdown>
        </Space>
      </AntHeader>
    </>
  );
}
