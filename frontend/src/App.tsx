import { Spin } from 'antd';
import { Navigate, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth/AuthContext';
import AppLayout from './components/AppLayout';
import AdminUsersPage from './pages/AdminUsersPage';
import CompetitionsPage from './pages/CompetitionsPage';
import InventoryPage from './pages/InventoryPage';
import LoginPage from './pages/LoginPage';
import OrganizationPage from './pages/OrganizationPage';
import RequestsPage from './pages/RequestsPage';
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
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/competitions" element={<CompetitionsPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/team" element={<TeamPage />} />
          <Route path="/organization" element={<OrganizationPage />} />
          <Route path="/admin/users" element={<AdminUsersPage />} />
          <Route path="*" element={<Navigate to="/tasks" replace />} />
        </Route>
      ) : (
        <Route path="*" element={<Navigate to="/login" replace />} />
      )}
    </Routes>
  );
}
