import type { ReactElement } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import LiveMonitor from "./pages/LiveMonitor";
import Cameras from "./pages/Cameras";
import ZoneTypes from "./pages/ZoneTypes";
import ZoneStudio from "./pages/ZoneStudio";
import CalibrationTool from "./pages/CalibrationTool";
import FisheyeSetup from "./pages/FisheyeSetup";
import CoachingWorkbench from "./pages/CoachingWorkbench";
import IncidentSearch from "./pages/IncidentSearch";
import Analytics from "./pages/Analytics";
import UsageHeatmap from "./pages/UsageHeatmap";
import ViolationsHeatmap from "./pages/ViolationsHeatmap";
import Login from "./pages/Login";
import UserManagement from "./pages/UserManagement";
import RoleManagement from "./pages/RoleManagement";
import DetectionSettingsPage from "./pages/DetectionSettings";
import ChangePassword from "./pages/ChangePassword";
import { AuthProvider, useAuth } from "./hooks/useAuth";

function RequireAuth({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="flex h-screen w-screen items-center justify-center bg-apl-midnight text-slate-400">Loading...</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password) return <ChangePassword />;
  return children;
}

function RequireAdmin({ children }: { children: ReactElement }) {
  const { role } = useAuth();
  if (!role?.is_system) return <Navigate to="/" replace />;
  return children;
}

function RedirectIfAuthed({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth();
  if (!loading && user) return <Navigate to="/" replace />;
  return children;
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route
            path="/login"
            element={
              <RedirectIfAuthed>
                <Login />
              </RedirectIfAuthed>
            }
          />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<LiveMonitor />} />
            <Route path="/admin/cameras" element={<Cameras />} />
            <Route path="/admin/zone-types" element={<ZoneTypes />} />
            <Route path="/admin/zones" element={<ZoneStudio />} />
            <Route path="/admin/calibration" element={<CalibrationTool />} />
            <Route path="/admin/fisheye" element={<FisheyeSetup />} />
            <Route path="/coaching" element={<CoachingWorkbench />} />
            <Route path="/incidents/search" element={<IncidentSearch />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/heatmap/usage" element={<UsageHeatmap />} />
            <Route path="/heatmap/violations" element={<ViolationsHeatmap />} />
            <Route
              path="/admin/users"
              element={
                <RequireAdmin>
                  <UserManagement />
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/roles"
              element={
                <RequireAdmin>
                  <RoleManagement />
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/detection-settings"
              element={
                <RequireAdmin>
                  <DetectionSettingsPage />
                </RequireAdmin>
              }
            />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
