import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";
import LoginPage from "./pages/Login";
import HomePage from "./pages/Home";
import ChatPage from "./pages/Chat";
import ProjectsPage from "./pages/Projects";
import ProjectDetailPage from "./pages/ProjectDetail";
import ExpertsPage from "./pages/Experts";
import AutomationPage from "./pages/Automation";
import LibraryPage from "./pages/Library";

export default function App() {
  return (
    <BrowserRouter basename="/xianwork">
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<MainLayout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/experts" element={<ExpertsPage />} />
          <Route path="/automation" element={<AutomationPage />} />
          <Route path="/library" element={<LibraryPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
