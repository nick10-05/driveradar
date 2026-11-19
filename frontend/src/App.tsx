import { Navigate, Route, Routes } from "react-router";

import { AdminDrivePage, AdminDrivesPage, NewDrivePage, RequireAdmin } from "./admin/AdminPages";
import { RequireAuth } from "./auth/RequireAuth";
import { Layout } from "./components/Layout";
import { WakingBanner } from "./components/WakingBanner";
import { DrivePage } from "./pages/DrivePage";
import { FeedPage } from "./pages/FeedPage";
import { LoginPage } from "./pages/LoginPage";
import { ProfilePage } from "./pages/ProfilePage";
import { RegisterPage } from "./pages/RegisterPage";
import { TrackerPage } from "./pages/TrackerPage";

export function App() {
  return (
    <>
      {/* Above the routes, so it also shows on the login page. */}
      <WakingBanner />
      <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<FeedPage />} />
        <Route path="drives/:id" element={<DrivePage />} />
        <Route path="tracker" element={<TrackerPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="admin" element={<RequireAdmin><AdminDrivesPage /></RequireAdmin>} />
        <Route path="admin/new" element={<RequireAdmin><NewDrivePage /></RequireAdmin>} />
        <Route path="admin/drives/:id" element={<RequireAdmin><AdminDrivePage /></RequireAdmin>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
