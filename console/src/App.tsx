import { createGlobalStyle } from "antd-style";
import {
  ConfigProvider,
  bailianDarkTheme,
  bailianTheme,
} from "@agentscope-ai/design";
import { App as AntdApp } from "antd";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import jaJP from "antd/locale/ja_JP";
import ruRU from "antd/locale/ru_RU";
import idID from "antd/locale/id_ID";
import type { Locale } from "antd/es/locale";
import { theme as antdTheme } from "antd";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import "dayjs/locale/ja";
import "dayjs/locale/ru";
import "dayjs/locale/id";
dayjs.extend(relativeTime);
import MainLayout from "./layouts/MainLayout";
import { ThemeProvider, useTheme } from "./contexts/ThemeContext";
import { PluginProvider, usePlugins } from "./plugins/PluginContext";
import { ApprovalProvider } from "./contexts/ApprovalContext";
import { DesktopUpdateProvider } from "./contexts/DesktopUpdateContext";
import { UpdateTakeoverGate } from "./components/UpdateTakeoverPage";
import { Suspense, lazy } from "react";
import { lazyImportWithRetry } from "./utils/lazyWithRetry";
import {
  getLoginHref,
  getLoginPath,
  getRouterBasename,
  isOsPath,
} from "./utils/navigationMode";

const LoginPage = lazyImportWithRetry("./pages/Login/index");
// Desktop OS shell. Uses React.lazy (not lazyImportWithRetry, which only
// resolves the ./pages/** glob) so it can load from ./os/.
const DesktopOSPage = lazy(() => import("./os/DesktopOS"));
import { authApi } from "./api/modules/auth";
import { languageApi } from "./api/modules/language";
import { useUploadLimitStore } from "./stores/uploadLimitStore";
import {
  useAuthStore,
  AUTH_DISABLED_IDENTITY,
} from "./stores/authStore";
import { getApiToken, clearAuthToken } from "./api/config";
import CloseWindowPrompt from "./tauri/CloseWindowPrompt";
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
  useHardRedirect = false,
}: {
  children: React.ReactNode;
  useHardRedirect?: boolean;
}) {
  const [status, setStatus] = useState<"loading" | "auth-required" | "ok">(
    "loading",
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authApi.getStatus();
        if (cancelled) return;
        if (!res.enabled) {
          // Single-user deployment: keep every menu visible (pre-M5 behaviour).
          useAuthStore.getState().setIdentity(AUTH_DISABLED_IDENTITY);
          setStatus("ok");
          return;
        }
        const token = getApiToken();
        if (!token) {
          setStatus("auth-required");
          return;
        }
        try {
          const r = await authApi.verify(token);
          if (cancelled) return;
          // Record identity for role-based menu/route filtering (M5).
          // Missing role fields (older backend) degrade to non-admin.
          useAuthStore.getState().setIdentity({
            username: r.username ?? "",
            role: r.role ?? "",
            roles: Array.isArray(r.roles) ? r.roles : [],
          });
          setStatus("ok");
        } catch {
          if (!cancelled) {
            clearAuthToken();
            useAuthStore.getState().clear();
            setStatus("auth-required");
          }
        }
      } catch {
        // Status probe failed (backend unreachable / dev mode): preserve the
        // historical fail-open behaviour.
        if (!cancelled) {
          useAuthStore.getState().setIdentity(AUTH_DISABLED_IDENTITY);
          setStatus("ok");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (status === "loading") return null;
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

function AppInner() {
  const basename = getRouterBasename(window.location.pathname);
  const { i18n } = useTranslation();
  const { isDark } = useTheme();
  const { loading: pluginsLoading } = usePlugins();
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

  // Wait for plugins to load before rendering routes that might be patched
  if (pluginsLoading) {
    return null;
  }

  const osActive = isOsPath(window.location.pathname);

  // The Desktop OS shell renders OUTSIDE any Router: each window supplies its
  // own MemoryRouter (WindowRouter.tsx) and React Router forbids nesting a
  // <Router> inside another. The classic browser layout keeps its BrowserRouter.
  const routedContent = osActive ? (
    <AuthGuard useHardRedirect>
      <Suspense fallback={null}>
        <DesktopOSPage />
      </Suspense>
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
          path="/*"
          element={
            <AuthGuard>
              <MainLayout />
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
          ...(selectedTheme as any)?.theme,
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
      <PluginProvider>
        <AppInner />
      </PluginProvider>
    </ThemeProvider>
  );
}

export default App;
