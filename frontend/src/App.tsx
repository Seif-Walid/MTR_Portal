import { Spin } from 'antd';
import { Navigate, Route, Routes } from 'react-router-dom';

import { can, useAuth } from './auth/AuthContext';
import AppLayout from './components/AppLayout';
import AdminUsersPage from './pages/AdminUsersPage';
import ArchivePage from './pages/ArchivePage';
import BulkDataPage from './pages/BulkDataPage';
import AuditLogPage from './pages/AuditLogPage';
import EventsPage from './pages/EventsPage';
import FinancePage from './pages/FinancePage';
import ExplorerPage from './pages/ExplorerPage';
import MembersPage from './pages/MembersPage';
import HomePage from './pages/HomePage';
import InventoryPage from './pages/InventoryPage';
import LoginPage from './pages/LoginPage';
import OrganizationPage from './pages/OrganizationPage';
import ProfilePage from './pages/ProfilePage';
import RequestsPage from './pages/RequestsPage';
import CalendarPage from './pages/CalendarPage';
import CoursesPage from './pages/CoursesPage';
import TasksPage from './pages/TasksPage';
import TeamPage from './pages/TeamPage';

export default function App() {
  const { me, loading } = useAuth();

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {me ? (
        <Route element={<AppLayout />}>
          <Route path="/home" element={<HomePage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route
            path="/explore/*"
            element={can(me, 'dashboard.view') ? <ExplorerPage /> : <Navigate to="/home" replace />}
          />
          <Route path="/insights" element={<Navigate to="/explore" replace />} />
          <Route path="/members" element={<MembersPage />} />
          <Route path="/finance" element={<FinancePage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/events/:slug" element={<EventsPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/courses" element={<CoursesPage />} />
          <Route path="/courses/:courseId" element={<CoursesPage />} />
          <Route path="/courses/:courseId/:materialId" element={<CoursesPage />} />
          <Route path="/team" element={<TeamPage />} />
          <Route path="/archive" element={<ArchivePage />} />
          <Route path="/archive/:eventId" element={<ArchivePage />} />
          <Route path="/organization" element={<OrganizationPage />} />
          <Route path="/admin/users" element={<AdminUsersPage />} />
          <Route path="/admin/audit" element={<AuditLogPage />} />
          <Route path="/admin/data" element={<BulkDataPage />} />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Route>
      ) : (
        <Route path="*" element={<Navigate to="/login" replace />} />
      )}
    </Routes>
  );
}
