import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout.jsx";
import AnalyzePage from "./pages/AnalyzePage.jsx";
import CleaningPage from "./pages/CleaningPage.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import ExportPage from "./pages/ExportPage.jsx";
import MixerPage from "./pages/MixerPage.jsx";
import ProjectDetail from "./pages/ProjectDetail.jsx";
import SectionPlaceholder from "./pages/SectionPlaceholder.jsx";
import UploadStems from "./pages/UploadStems.jsx";
import VocalEnhancerPage from "./pages/VocalEnhancerPage.jsx";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="projects/:projectId" element={<ProjectDetail />} />
        <Route path="projects/:projectId/upload" element={<UploadStems />} />
        <Route path="projects/:projectId/analyze" element={<AnalyzePage />} />
        <Route path="projects/:projectId/cleaning" element={<CleaningPage />} />
        <Route path="projects/:projectId/vocals" element={<VocalEnhancerPage />} />
        <Route path="projects/:projectId/mixer" element={<MixerPage />} />
        <Route path="projects/:projectId/mastering" element={<ExportPage />} />
        <Route path="projects/:projectId/export" element={<ExportPage />} />
        <Route path="projects/:projectId/:section" element={<SectionPlaceholder />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
