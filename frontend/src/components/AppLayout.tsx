import {
  ApartmentOutlined,
  AuditOutlined,
  CalendarOutlined,
  CheckSquareOutlined,
  CloudSyncOutlined,
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
import { Avatar, Button, Dropdown, Layout, Menu, Space, Tag, Typography, message, theme } from 'antd';
import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import { can, useAuth } from '../auth/AuthContext';
import { brand } from '../theme/brand';
import { LogoImage, Wordmark } from './Logo';
import NotificationsBell from './NotificationsBell';
import ThemeToggle from './ThemeToggle';

const { Header, Sider, Content } = Layout;

export default function AppLayout() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();
  const [collapsed, setCollapsed] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [eventKinds, setEventKinds] = useState<{ slug: string; name: string }[]>([]);
  const [openKeys, setOpenKeys] = useState<string[]>(['/events']);
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    api.get<{ google_enabled: boolean }>('/api/auth/config').then((c) => setGoogleEnabled(c.google_enabled)).catch(() => {});
  }, []);

  const canViewEvents = can(me, 'competitions.view');
  useEffect(() => {
    if (canViewEvents) {
      api.get<{ slug: string; name: string }[]>('/api/competitions/kinds').then(setEventKinds).catch(() => {});
    }
  }, [canViewEvents]);

  // Keep the Events submenu expanded whenever we're inside it (and once its
  // children have loaded), so the active kind stays visible. onOpenChange
  // still lets the user collapse it while browsing elsewhere.
  const onEventsRoute = location.pathname.startsWith('/events');
  useEffect(() => {
    if (onEventsRoute && eventKinds.length) {
      setOpenKeys((k) => (k.includes('/events') ? k : [...k, '/events']));
    }
  }, [onEventsRoute, eventKinds.length]);

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
    ...(can(me, 'tasks.use')
      ? [{ key: '/tasks', icon: <CheckSquareOutlined />, label: 'My Tasks' }]
      : []),
    ...(can(me, 'tasks.use') || can(me, 'competitions.view') || can(me, 'inventory.view')
      ? [{ key: '/calendar', icon: <CalendarOutlined />, label: 'Calendar' }]
      : []),
    ...(can(me, 'inventory.view')
      ? [{ key: '/inventory', icon: <InboxOutlined />, label: 'Inventory' }]
      : []),
    ...(canViewEvents
      ? [{
          key: '/events',
          icon: <TrophyOutlined />,
          label: 'Events',
          // a plain link until kinds exist, so a fresh admin can reach the
          // page to define event types; a submenu of kinds once they do
          ...(eventKinds.length
            ? { children: eventKinds.map((k) => ({ key: `/events/${k.slug}`, label: k.name })) }
            : {}),
        }]
      : []),
    ...(can(me, 'tasks.use')
      ? [{ key: '/requests', icon: <SendOutlined />, label: 'Requests' }]
      : []),
    ...(can(me, 'people.view') && (me.has_team || can(me, 'users.manage'))
      ? [{ key: '/team', icon: <TeamOutlined />, label: 'My Team' }]
      : []),
    ...(can(me, 'org.view')
      ? [{ key: '/organization', icon: <ApartmentOutlined />, label: 'Organization' }]
      : []),
    ...(can(me, 'users.manage')
      ? [{ key: '/admin/users', icon: <SettingOutlined />, label: 'User Management' }]
      : []),
    ...(can(me, 'audit.view')
      ? [{ key: '/admin/audit', icon: <AuditOutlined />, label: 'Audit Log' }]
      : []),
    ...(can(me, 'sync.export') || can(me, 'sync.rebuild')
      ? [{ key: '/admin/sync', icon: <CloudSyncOutlined />, label: 'Data Sync' }]
      : []),
  ];

  // longest matching key wins, so /events/training highlights the sub-item,
  // not just the /events parent.
  const allKeys = items.flatMap((i) =>
    'children' in i && i.children ? i.children.map((c) => c.key) : [i.key],
  );
  const selected = allKeys
    .filter((k) => location.pathname === k || location.pathname.startsWith(k + '/') || location.pathname.startsWith(k))
    .sort((a, b) => b.length - a.length)[0];

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
        style={{
          position: 'fixed',
          insetInlineStart: 0,
          top: 0,
          bottom: 0,
          height: '100vh',
          overflow: 'auto',
        }}
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
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          items={items}
          onClick={(e) => navigate(e.key)}
        />
      </Sider>
      <Layout style={{ marginInlineStart: collapsed ? 0 : 200, transition: 'margin-inline-start 0.2s' }}>
        <Header
          style={{
            background: token.colorBgContainer,
            padding: '0 24px 0 12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            position: 'sticky',
            top: 0,
            zIndex: 10,
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
                  {me.level ? <Tag>{me.level.name}</Tag> : <Tag>No level</Tag>}
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
