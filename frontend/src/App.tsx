import { Spin } from 'antd';
import { Navigate, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth/AuthContext';
import AppLayout from './components/AppLayout';
import AdminUsersPage from './pages/AdminUsersPage';
import AuditLogPage from './pages/AuditLogPage';
import CompetitionsPage from './pages/CompetitionsPage';
import HomePage from './pages/HomePage';
import InventoryPage from './pages/InventoryPage';
import LoginPage from './pages/LoginPage';
import OrganizationPage from './pages/OrganizationPage';
import RequestsPage from './pages/RequestsPage';
import SheetsSyncPage from './pages/SheetsSyncPage';
import CalendarPage from './pages/CalendarPage';
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
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/events" element={<CompetitionsPage />} />
          <Route path="/events/:slug" element={<CompetitionsPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/team" element={<TeamPage />} />
          <Route path="/organization" element={<OrganizationPage />} />
          <Route path="/admin/users" element={<AdminUsersPage />} />
          <Route path="/admin/audit" element={<AuditLogPage />} />
          <Route path="/admin/sync" element={<SheetsSyncPage />} />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Route>
      ) : (
        <Route path="*" element={<Navigate to="/login" replace />} />
      )}
    </Routes>
  );
}
