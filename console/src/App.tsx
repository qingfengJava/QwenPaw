import { createGlobalStyle } from "antd-style";
import {
  ConfigProvider,
  bailianDarkTheme,
  bailianTheme,
} from "@agentscope-ai/design";
import { App as AntdApp, theme as antdTheme } from "antd";
import type { ThemeConfig } from "antd";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import jaJP from "antd/locale/ja_JP";
import ruRU from "antd/locale/ru_RU";
import idID from "antd/locale/id_ID";
import type { Locale } from "antd/es/locale";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import "dayjs/locale/ja";
import "dayjs/locale/ru";
import "dayjs/locale/id";
dayjs.extend(relativeTime);
import MainLayout from "./layouts/MainLayout";
import { ThemeProvider, useTheme } from "./contexts/ThemeContext";
import { PluginProvider } from "./plugins/PluginContext";
import { ApprovalProvider } from "./contexts/ApprovalContext";
import { DesktopUpdateProvider } from "./contexts/DesktopUpdateContext";
import { UpdateTakeoverGate } from "./components/UpdateTakeoverPage";
import { Suspense, lazy } from "react";
import { lazyImportWithRetry } from "./utils/lazyWithRetry";
import {
  addRouterBasename,
  getLoginHref,
  getLoginPath,
  getRouterBasename,
  isOsPath,
  isStudioPath,
} from "./utils/navigationMode";

const LoginPage = lazyImportWithRetry("./pages/Login/index");
const HubPage = lazyImportWithRetry("./pages/Hub/index");
// Desktop OS shell. Uses React.lazy (not lazyImportWithRetry, which only
// resolves the ./pages/** glob) so it can load from ./os/.
const DesktopOSPage = lazy(() => import("./os/DesktopOS"));
// 数字员工工作台（/studio/:aid）：独立浏览器标签页，脱离 MainLayout 侧栏。
// 与页面路由一致走 glob 懒加载；注：其依赖几乎全部已在 entry，
// Rollup 会将其内联进 entry chunk（实测增量 ~15KB，可忽略）。
const AgentWorkbenchLayout = lazyImportWithRetry(
  "./pages/Agents/workbench/AgentWorkbenchLayout",
);
import { authApi } from "./api/modules/auth";
import { languageApi } from "./api/modules/language";
import { useUploadLimitStore } from "./stores/uploadLimitStore";
import {
  useAuthStore,
  AUTH_DISABLED_IDENTITY,
} from "./stores/authStore";
import { getApiToken } from "./api/config";
import CloseWindowPrompt from "./tauri/CloseWindowPrompt";
import BackendLoadingPage from "./tauri/BackendLoadingPage";
import {
  resolveAuthGate,
  resolveBackendInfo,
  type BackendInfo,
} from "./auth/gate";
import type { AuthStatusResponse } from "./api/modules/auth";
import { hubApi, type HubHealth } from "./api/modules/hub";
import { isTauri } from "@tauri-apps/api/core";
import { isDesktopTauriRuntime } from "./utils/openExternalLink";
import { interceptBlankLinkClicks } from "./utils/interceptBlankLinkClicks";
import "./styles/layout.css";
import "./styles/form-override.css";
import "./styles/staffdeck-tokens.css";

const antdLocaleMap: Record<string, Locale> = {
  zh: zhCN,
  en: enUS,
  ja: jaJP,
  ru: ruRU,
  id: idID,
};

const dayjsLocaleMap: Record<string, string> = {
  zh: "zh-cn",
  en: "en",
  ja: "ja",
  ru: "ru",
  id: "id",
};

const GlobalStyle = createGlobalStyle`
* {
  margin: 0;
  box-sizing: border-box;
}
`;

function AuthGuard({
  children,
  authStatus,
  useHardRedirect = false,
}: {
  children: React.ReactNode;
  authStatus: AuthStatusResponse;
  useHardRedirect?: boolean;
}) {
  const [status, setStatus] = useState<
    "loading" | "auth-required" | "ok" | "error"
  >("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setErrorMessage("");
    resolveAuthGate(authStatus)
      .then(async (nextStatus) => {
        // SmartWork RBAC (M1/M4): record the caller's identity for
        // role-based menu/route filtering. Hub mode records identity too
        // -- the hub JWT is verified by the same /auth/verify endpoint --
        // while the role fields degrade to non-admin when absent.
        if (nextStatus === "ok" && authStatus.enabled) {
          const token = getApiToken();
          if (token) {
            try {
              const r = await authApi.verify(token);
              if (!cancelled) {
                useAuthStore.getState().setIdentity({
                  username: r.username ?? "",
                  role: r.role ?? "",
                  roles: Array.isArray(r.roles) ? r.roles : [],
                });
              }
            } catch {
              // Identity lookup failed: degrade to non-admin, do not block.
            }
          }
        } else if (nextStatus === "auth-required") {
          useAuthStore.getState().clear();
        } else if (!authStatus.enabled) {
          // Single-user deployment: keep every menu visible.
          useAuthStore.getState().setIdentity(AUTH_DISABLED_IDENTITY);
        }
        if (!cancelled) setStatus(nextStatus);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setErrorMessage(
          error instanceof Error ? error.message : "Authentication failed",
        );
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [authStatus, retryKey]);

  if (status === "loading") {
    return null;
  }
  if (status === "error") {
    return (
      <BackendLoadingPage
        status="error"
        elapsed={0}
        totalSec={1}
        errorMessage={errorMessage}
        onRetry={() => setRetryKey((current) => current + 1)}
      />
    );
  }
  if (status === "auth-required") {
    const loginTo = getLoginPath(window.location);
    if (useHardRedirect) {
      // The OS shell renders outside a Router, so <Navigate> is unavailable.
      window.location.replace(getLoginHref(window.location));
      return null;
    }
    return <Navigate to={loginTo} replace />;
  }
  return <>{children}</>;
}

function RuntimeAvailabilityGuard({
  children,
  enabled,
}: {
  children: React.ReactNode;
  enabled: boolean;
}) {
  const { t } = useTranslation();
  const [health, setHealth] = useState<HubHealth | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [restarting, setRestarting] = useState(false);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setHealth(null);
    setErrorMessage("");
    hubApi
      .getHealth()
      .then((nextHealth) => {
        if (!cancelled) setHealth(nextHealth);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "Runtime security preflight failed",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, retryKey]);

  const restartRuntime = async () => {
    setRestarting(true);
    setErrorMessage("");
    try {
      await hubApi.restartOwnRuntime();
      setRetryKey((current) => current + 1);
    } catch (error: unknown) {
      setErrorMessage(
        error instanceof Error ? error.message : "Runtime restart failed",
      );
    } finally {
      setRestarting(false);
    }
  };

  useEffect(() => {
    if (!enabled || !health || health.runtime_available) return;
    window.location.replace(
      addRouterBasename(window.location.pathname, "/hub/admin"),
    );
  }, [enabled, health]);

  if (!enabled) return <>{children}</>;
  if (!health && !errorMessage) return null;
  if (health?.runtime_desired_state === "stopped") {
    const ownerCanStart = health.runtime_start_policy === "owner_allowed";
    return (
      <BackendLoadingPage
        status="error"
        elapsed={0}
        totalSec={1}
        statusText={t(
          ownerCanStart
            ? "account.runtimeStoppedTitle"
            : "account.runtimeDisabledTitle",
        )}
        hintText={t(
          ownerCanStart
            ? "account.runtimeStoppedDescription"
            : "account.runtimeDisabledDescription",
        )}
        errorMessage={errorMessage}
        onRetry={restartRuntime}
        retryLabel={
          restarting
            ? t("account.runtimeRestarting")
            : t("account.runtimeRestart")
        }
        showRetry={ownerCanStart}
        retryDisabled={restarting}
      />
    );
  }
  if (health?.runtime_available) return <>{children}</>;

  if (health) return null;

  return (
    <BackendLoadingPage
      status="error"
      elapsed={0}
      totalSec={1}
      errorMessage={errorMessage}
      onRetry={() => setRetryKey((current) => current + 1)}
    />
  );
}

function AppInner({ backendInfo }: { backendInfo: BackendInfo }) {
  const hubMode = backendInfo.mode === "hub";
  const basename = getRouterBasename(window.location.pathname);
  const { i18n } = useTranslation();
  const { isDark } = useTheme();
  const selectedTheme = isDark ? bailianDarkTheme : bailianTheme;
  const lang = i18n.resolvedLanguage || i18n.language || "en";
  const [antdLocale, setAntdLocale] = useState<Locale>(
    antdLocaleMap[lang] ?? enUS,
  );

  useEffect(() => {
    if (!localStorage.getItem("language")) {
      languageApi
        .getLanguage()
        .then(({ language }) => {
          if (language && language !== i18n.language) {
            i18n.changeLanguage(language);
            localStorage.setItem("language", language);
          }
        })
        .catch((err) =>
          console.error("Failed to fetch language preference:", err),
        );
    }
    useUploadLimitStore.getState().fetch();
  }, []);

  useEffect(() => {
    const handleLanguageChanged = (lng: string) => {
      const shortLng = lng.split("-")[0];
      setAntdLocale(antdLocaleMap[shortLng] ?? enUS);
      dayjs.locale(dayjsLocaleMap[shortLng] ?? "en");
    };

    // Set initial dayjs locale
    dayjs.locale(dayjsLocaleMap[lang.split("-")[0]] ?? "en");

    i18n.on("languageChanged", handleLanguageChanged);
    return () => {
      i18n.off("languageChanged", handleLanguageChanged);
    };
  }, [i18n]);

  // Disable the default browser context menu in the Tauri desktop build so
  // users cannot open DevTools via right-click. DevTools is still available
  // through the hidden 8-click logo gesture handled in Header.tsx.
  useEffect(() => {
    if (!isTauri()) return;
    const preventContextMenu = (e: MouseEvent) => e.preventDefault();
    window.addEventListener("contextmenu", preventContextMenu);
    return () => window.removeEventListener("contextmenu", preventContextMenu);
  }, []);

  // Vendor-rendered markdown (e.g. chat bubbles) emits native
  // `<a target="_blank">` anchors we cannot override at the React level. The
  // Tauri WebView ignores such clicks, so route them to the system browser.
  useEffect(() => {
    if (!isDesktopTauriRuntime()) return;
    return interceptBlankLinkClicks();
  }, []);

  const osActive = isOsPath(window.location.pathname);
  const studioActive = isStudioPath(window.location.pathname);

  // The Desktop OS shell and the agent workbench render OUTSIDE any Router:
  // both supply their own MemoryRouter (WindowRouter.tsx / WorkbenchLayout)
  // and React Router forbids nesting a <Router> inside another. The classic
  // browser layout keeps its BrowserRouter.
  const routedContent = studioActive ? (
    // 数字员工工作台：全屏三段（顶栏 + 左固定聊天 + 右信息 Tab），
    // 不进 MainLayout（新标签页无侧栏）；Router 由工作台自挂。
    <AuthGuard authStatus={backendInfo.authStatus} useHardRedirect>
      <RuntimeAvailabilityGuard enabled={hubMode}>
        <Suspense fallback={null}>
          <AgentWorkbenchLayout />
        </Suspense>
      </RuntimeAvailabilityGuard>
    </AuthGuard>
  ) : osActive ? (
    <AuthGuard authStatus={backendInfo.authStatus} useHardRedirect>
      <RuntimeAvailabilityGuard enabled={hubMode}>
        <Suspense fallback={null}>
          <DesktopOSPage />
        </Suspense>
      </RuntimeAvailabilityGuard>
    </AuthGuard>
  ) : (
    <BrowserRouter basename={basename}>
      <Routes>
        <Route
          path="/login"
          element={
            <Suspense fallback={null}>
              <LoginPage />
            </Suspense>
          }
        />
        <Route
          path="/hub/admin"
          element={
            hubMode ? (
              <AuthGuard authStatus={backendInfo.authStatus}>
                <Suspense fallback={null}>
                  <HubPage />
                </Suspense>
              </AuthGuard>
            ) : (
              <Navigate to="/" replace />
            )
          }
        />
        <Route
          path="/*"
          element={
            <AuthGuard authStatus={backendInfo.authStatus}>
              <RuntimeAvailabilityGuard enabled={hubMode}>
                <MainLayout hubMode={hubMode} />
              </RuntimeAvailabilityGuard>
            </AuthGuard>
          }
        />
      </Routes>
    </BrowserRouter>
  );

  return (
    <>
      <GlobalStyle />
      <ConfigProvider
        {...selectedTheme}
        prefix="qwenpaw"
        prefixCls="qwenpaw"
        locale={antdLocale}
        theme={{
          ...(selectedTheme as { theme?: ThemeConfig }).theme,
          algorithm: isDark
            ? antdTheme.darkAlgorithm
            : antdTheme.defaultAlgorithm,
          token: {
            // StaffDeck 设计语言（docs/design/2026-08-30-…md §七）：
            // 墨色主按钮 + 链接蓝 + 冷白布局底 + 控件圆角 10
            colorPrimary: "#18181a",
            colorLink: "#1a71ff",
            colorInfo: "#1a71ff",
            colorBgLayout: "#fcfcfc",
            colorBgContainer: "#ffffff",
            borderRadius: 10,
          },
          components: {
            Menu: {
              // 侧栏菜单：白底 + 浅灰选中 + 墨色文字（去橙色/米色高亮）
              itemBg: "#ffffff",
              subMenuItemBg: "#ffffff",
              popupBg: "#ffffff",
              itemSelectedBg: "#f6f6f6",
              itemSelectedColor: "#18181a",
              itemHoverBg: "#f6f6f6",
              itemHoverColor: "#18181a",
              activeBarBorderWidth: 0,
            },
            Tabs: {
              itemSelectedColor: "#18181a",
              itemColor: "#757f9c",
              inkBarColor: "#18181a",
            },
          },
        }}
      >
        <AntdApp>
          <CloseWindowPrompt />
          <DesktopUpdateProvider>
            <UpdateTakeoverGate>
              <ApprovalProvider>{routedContent}</ApprovalProvider>
            </UpdateTakeoverGate>
          </DesktopUpdateProvider>
        </AntdApp>
      </ConfigProvider>
    </>
  );
}

function App() {
  return (
    <ThemeProvider>
      <BackendModeRouter />
    </ThemeProvider>
  );
}

function BackendModeRouter() {
  const [backendInfo, setBackendInfo] = useState<
    "loading" | "error" | BackendInfo
  >("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setBackendInfo("loading");
    setErrorMessage("");
    resolveBackendInfo()
      .then((nextInfo) => {
        if (!cancelled) setBackendInfo(nextInfo);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setErrorMessage(
          error instanceof Error ? error.message : "Backend detection failed",
        );
        setBackendInfo("error");
      });
    return () => {
      cancelled = true;
    };
  }, [retryKey]);

  if (backendInfo === "loading") {
    return null;
  }
  if (backendInfo === "error") {
    return (
      <BackendLoadingPage
        status="error"
        elapsed={0}
        totalSec={1}
        errorMessage={errorMessage}
        onRetry={() => setRetryKey((current) => current + 1)}
      />
    );
  }
  return (
    <PluginProvider>
      <AppInner backendInfo={backendInfo} />
    </PluginProvider>
  );
}

export default App;
