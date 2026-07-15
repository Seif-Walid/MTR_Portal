import {
  ApartmentOutlined,
  AuditOutlined,
  CheckSquareOutlined,
  GoogleOutlined,
  InboxOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SendOutlined,
  SettingOutlined,
  TeamOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import { Avatar, Button, Dropdown, Layout, Menu, Space, Typography, message, theme } from 'antd';
import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { brand } from '../theme/brand';
import { LogoImage, Wordmark } from './Logo';
import NotificationsBell from './NotificationsBell';
import ThemeToggle from './ThemeToggle';
import { RoleTags } from './tags';

const { Header, Sider, Content } = Layout;

export default function AppLayout() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();
  const [collapsed, setCollapsed] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    api.get<{ google_enabled: boolean }>('/api/auth/config').then((c) => setGoogleEnabled(c.google_enabled)).catch(() => {});
  }, []);

  useEffect(() => {
    if (searchParams.get('linked') === 'true') {
      message.success('Google account linked — you can now sign in with it.');
      setSearchParams((p) => {
        const next = new URLSearchParams(p);
        next.delete('linked');
        return next;
      });
    }
  }, [searchParams, setSearchParams]);

  if (!me) return null;

  const items = [
    { key: '/tasks', icon: <CheckSquareOutlined />, label: 'My Tasks' },
    { key: '/inventory', icon: <InboxOutlined />, label: 'Inventory' },
    ...(me.is_high_staff
      ? [{ key: '/competitions', icon: <TrophyOutlined />, label: 'Competitions' }]
      : []),
    { key: '/requests', icon: <SendOutlined />, label: 'Requests' },
    ...(me.has_team || me.is_admin
      ? [{ key: '/team', icon: <TeamOutlined />, label: 'My Team' }]
      : []),
    { key: '/organization', icon: <ApartmentOutlined />, label: 'Organization' },
    ...(me.is_admin
      ? [{ key: '/admin/users', icon: <SettingOutlined />, label: 'User Management' }]
      : []),
    ...(me.is_admin
      ? [{ key: '/admin/audit', icon: <AuditOutlined />, label: 'Audit Log' }]
      : []),
  ];

  const selected = items.find((i) => location.pathname.startsWith(i.key))?.key;

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        breakpoint="lg"
        collapsedWidth="0"
        theme="dark"
        trigger={null}
        collapsible
        collapsed={collapsed}
        onBreakpoint={(broken) => setCollapsed(broken)}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '16px 14px',
            color: brand.cream,
          }}
        >
          <LogoImage size={42} radius={8} />
          <Wordmark color={brand.cream} size={15} />
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={selected ? [selected] : []}
          items={items}
          onClick={(e) => navigate(e.key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: token.colorBgContainer,
            padding: '0 24px 0 12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Button
            type="text"
            aria-label={collapsed ? 'Open menu' : 'Collapse menu'}
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed((c) => !c)}
            style={{ fontSize: 18 }}
          />
          <Space size={12} align="center">
            <ThemeToggle />
            <NotificationsBell />
          <Dropdown
            menu={{
              items: [
                ...(googleEnabled && !me.google_linked
                  ? [
                      {
                        key: 'link-google',
                        icon: <GoogleOutlined />,
                        label: 'Link Google account',
                        onClick: () => {
                          window.location.href = '/api/auth/google/login';
                        },
                      },
                    ]
                  : []),
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: 'Log out',
                  onClick: () => logout().then(() => navigate('/login')),
                },
              ],
            }}
          >
            <Space style={{ cursor: 'pointer' }}>
              <Avatar style={{ background: brand.red, color: '#fff' }}>
                {me.full_name
                  .split(' ')
                  .map((p) => p[0])
                  .slice(0, 2)
                  .join('')}
              </Avatar>
              <div style={{ lineHeight: 1.2 }}>
                <Typography.Text strong>{me.full_name}</Typography.Text>
                <div>
                  <RoleTags roles={me.roles} />
                </div>
              </div>
            </Space>
          </Dropdown>
          </Space>
        </Header>
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
