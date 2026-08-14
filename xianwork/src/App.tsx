/**
 * XianWork SPA routing.
 *
 * - Web mode (default): BrowserRouter with basename "/xianwork", served by
 *   the QwenPaw backend under the /xianwork sub-path.
 * - Tauri mode (`vite build --mode tauri`): HashRouter over a relative
 *   base, matching the console packaging path (see console/src-tauri).
 * - All pages are lazy-loaded; the vendor chunk hydrates first.
 */
import { lazy, Suspense, useEffect } from "react";
import {
  BrowserRouter,
  HashRouter,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import MainLayout from "./layouts/MainLayout";

const LoginPage = lazy(() => import("./pages/Login"));
const HomePage = lazy(() => import("./pages/Home"));
const ChatPage = lazy(() => import("./pages/Chat"));
const ProjectsPage = lazy(() => import("./pages/Projects"));
const ProjectDetailPage = lazy(() => import("./pages/ProjectDetail"));
const ExpertsPage = lazy(() => import("./pages/Experts"));
const AutomationPage = lazy(() => import("./pages/Automation"));
const LibraryPage = lazy(() => import("./pages/Library"));
const MorePage = lazy(() => import("./pages/More"));

const IS_TAURI = import.meta.env.MODE === "tauri";

/** Centralised router basename — single source of truth for both modes. */
export function getBasename(): string {
  return IS_TAURI ? "/" : "/xianwork";
}

/** Translate 401 events from request.ts into in-app navigation. */
function UnauthListener() {
  const navigate = useNavigate();
  useEffect(() => {
    const onUnauth = () => navigate("/login", { replace: true });
    window.addEventListener("xian:unauth", onUnauth);
    return () => window.removeEventListener("xian:unauth", onUnauth);
  }, [navigate]);
  return null;
}

function Router({ children }: { children: React.ReactNode }) {
  if (IS_TAURI) {
    return <HashRouter basename={getBasename()}>{children}</HashRouter>;
  }
  return <BrowserRouter basename={getBasename()}>{children}</BrowserRouter>;
}

export default function App() {
  return (
    <Router>
      <UnauthListener />
      <Suspense fallback={<div className="loading-state">加载中…</div>}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<MainLayout />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route
              path="/projects/:projectId"
              element={<ProjectDetailPage />}
            />
            <Route path="/experts" element={<ExpertsPage />} />
            <Route path="/automation" element={<AutomationPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/more" element={<MorePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Router>
  );
}
