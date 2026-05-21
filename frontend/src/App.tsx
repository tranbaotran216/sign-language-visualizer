import { Routes, Route, Navigate } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import Dashboard from "./pages/Dashboard";
import MetadataPage from "./pages/MetadataPage";
import ExtractPage from "./pages/ExtractPage";
import ComparePage from "./pages/ComparePage";
import HistoryPage from "./pages/HistoryPage";
import DatasetQAPage from "./pages/DatasetQAPage";
import ModelResultsPage from "./pages/ModelResultsPage";
import ComparisonEditorPage from "./pages/ComparisonEditorPage";
import OverlayPage from "./pages/OverlayPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="/metadata" element={<MetadataPage />} />
        <Route path="/extract" element={<ExtractPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/comparison-editor" element={<ComparisonEditorPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/dataset-qa" element={<DatasetQAPage />} />
        <Route path="/model-results" element={<ModelResultsPage />} />
        <Route path="/overlay" element={<OverlayPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
