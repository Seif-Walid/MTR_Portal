import { GoogleOutlined, LogoutOutlined, UserOutlined } from '@ant-design/icons';
import { Dropdown, message } from 'antd';
import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import { can, useAuth } from '../auth/AuthContext';
import NotificationsBell from './NotificationsBell';

/* ==========================================================================
   CIRCUIT app shell — the bespoke rail + header from the prototype.
   Replaces the generic AntD Layout/Sider/Menu. All routing, permission
   gating, event-kind submenu, notifications, google-link, logout, and the
   responsive collapse are preserved 1:1 — only the presentation changes.
   Requires the shell classes in circuit-overrides.css (mtr-nav, mtr-sub,
   mtr-online-dot).
   ========================================================================== */

// --- icon set: prototype's thin-stroke SVGs, keyed by route -----------------
function Ic({ children }: { children: React.ReactNode }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} width={17} height={17}>
      {children}
    </svg>
  );
}
const ICONS: Record<string, React.ReactNode> = {
  '/home': <Ic><path d="M3 9l7-6 7 6" /><path d="M5 9v8h10V9" /></Ic>,
  '/tasks': <Ic><rect x="3" y="3" width="14" height="14" rx="2.5" /><path d="M6.5 10l2.3 2.3L14 7.2" /></Ic>,
  '/calendar': <Ic><rect x="3" y="4.5" width="14" height="12.5" rx="2" /><path d="M3 8.5h14M7 3v3M13 3v3" /></Ic>,
  '/inventory': <Ic><path d="M3 7l7-3.5L17 7v7l-7 3.5L3 14z" /><path d="M3 7l7 3.5L17 7M10 10.5V17.5" /></Ic>,
  '/events': <Ic><path d="M6 4h8v3.5a4 4 0 01-8 0z" /><path d="M6 5H4v1.5a2 2 0 002 2M14 5h2v1.5a2 2 0 01-2 2M10 11.5V14M7 16.5h6" /></Ic>,
  '/requests': <Ic><path d="M3.5 10h11" /><path d="M11 6l4.5 4-4.5 4" /></Ic>,
  '/team': <Ic><circle cx="7" cy="7.5" r="2.4" /><circle cx="13" cy="7.5" r="2.4" /><path d="M3 16c0-2.2 1.9-3.4 4-3.4M11 16c0-2.2 1.9-3.4 4-3.4" /></Ic>,
  '/archive': <Ic><path d="M3 5.5h14v3H3z" /><path d="M4.5 8.5v7h11v-7M8 11.5h4" /></Ic>,
  '/organization': <Ic><rect x="8" y="3" width="4" height="4" rx=".5" /><rect x="3" y="13" width="4" height="4" rx=".5" /><rect x="13" y="13" width="4" height="4" rx=".5" /><path d="M10 7v3M5 13v-1.5h10V13M10 10.5V11.5" /></Ic>,
  '/admin/users': <Ic><circle cx="10" cy="10" r="2.5" /><path d="M10 3v2M10 15v2M3 10h2M15 10h2M5 5l1.4 1.4M13.6 13.6L15 15M15 5l-1.4 1.4M6.4 13.6L5 15" /></Ic>,
  '/admin/audit': <Ic><rect x="4.5" y="3" width="11" height="14" rx="1.5" /><path d="M7.5 7.5h5M7.5 10.5h5M7.5 13.5h3" /></Ic>,
  '/admin/sync': <Ic><path d="M4 10a6 6 0 019.5-4.9M16 10a6 6 0 01-9.5 4.9" /><path d="M13.5 3v2.5H11M6.5 17v-2.5H9" /></Ic>,
};

// --- header eyebrow + title per route ---------------------------------------
const TITLES: Record<string, [string, string]> = {
  '/home': ['Dashboard', 'Command deck'],
  '/tasks': ['Tasks', 'My Tasks'],
  '/calendar': ['Schedule', 'Calendar'],
  '/inventory': ['Inventory', 'Components'],
  '/events': ['Events', 'Events'],
  '/requests': ['Requests', 'Work Requests'],
  '/team': ['People', 'My Teams'],
  '/archive': ['Records', 'Archive'],
  '/organization': ['Structure', 'Organization'],
  '/admin/users': ['Admin', 'User Management'],
  '/admin/audit': ['Admin', 'Audit Log'],
  '/admin/sync': ['Admin', 'Data Sync'],
};

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  const date = now
    .toLocaleDateString('en-US', { weekday: 'short', day: '2-digit', month: 'short' })
    .toUpperCase();
  const time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${date} · ${time}`;
}

export default function AppLayout() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const clock = useClock();
  const [collapsed, setCollapsed] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [eventKinds, setEventKinds] = useState<{ slug: string; name: string }[]>([]);
  const [eventsOpen, setEventsOpen] = useState(true);
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    api.get<{ google_enabled: boolean }>('/api/auth/config').then((c) => setGoogleEnabled(c.google_enabled)).catch(() => {});
  }, []);

  const canViewEvents = can(me, 'events.view');
  useEffect(() => {
    if (canViewEvents) {
      api.get<{ slug: string; name: string }[]>('/api/events/kinds').then(setEventKinds).catch(() => {});
    }
  }, [canViewEvents]);

  const onEventsRoute = location.pathname.startsWith('/events');
  useEffect(() => {
    if (onEventsRoute) setEventsOpen(true);
  }, [onEventsRoute]);

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

  // collapse rail on small screens
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 991px)');
    const apply = () => setCollapsed(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  if (!me) return null;

  // --- permission-gated nav (same rules as before) --------------------------
  type NavItem = { key: string; label: string; children?: { key: string; label: string }[] };
  const items: NavItem[] = [
    { key: '/home', label: 'Home' },
    ...(can(me, 'tasks.use') ? [{ key: '/tasks', label: 'My Tasks' }] : []),
    ...(can(me, 'tasks.use') || can(me, 'events.view') || can(me, 'inventory.view')
      ? [{ key: '/calendar', label: 'Calendar' }]
      : []),
    ...(can(me, 'inventory.view') ? [{ key: '/inventory', label: 'Inventory' }] : []),
    ...(canViewEvents
      ? [{ key: '/events', label: 'Events', ...(eventKinds.length ? { children: eventKinds.map((k) => ({ key: `/events/${k.slug}`, label: k.name })) } : {}) }]
      : []),
    ...(can(me, 'tasks.use') ? [{ key: '/requests', label: 'Requests' }] : []),
    // group break rendered before My Team
    ...(can(me, 'people.view') && (me.has_team || can(me, 'users.manage')) ? [{ key: '/team', label: 'My Teams' }] : []),
    // Archive is public — a browsable record of past events, no gate.
    { key: '/archive', label: 'Archive' },
    ...(can(me, 'org.view') ? [{ key: '/organization', label: 'Organization' }] : []),
    ...(can(me, 'users.manage') ? [{ key: '/admin/users', label: 'User Management' }] : []),
    ...(can(me, 'audit.view') ? [{ key: '/admin/audit', label: 'Audit Log' }] : []),
    ...(can(me, 'sync.export') || can(me, 'sync.rebuild') ? [{ key: '/admin/sync', label: 'Data Sync' }] : []),
    ...(can(me, 'inventory.edit') ||
    can(me, 'users.manage') ||
    can(me, 'org.edit') ||
    can(me, 'events.manage_any')
      ? [{ key: '/admin/data', label: 'Data Tables' }]
      : []),
  ];

  const allKeys = items.flatMap((i) => (i.children ? i.children.map((c) => c.key) : [i.key]));
  const selected = allKeys
    .filter((k) => location.pathname === k || location.pathname.startsWith(k + '/') || location.pathname.startsWith(k))
    .sort((a, b) => b.length - a.length)[0];
  const isActive = (key: string) =>
    key === '/events' ? location.pathname.startsWith('/events') : selected === key;

  // header eyebrow/title — for an events sub-route, show the kind name
  const base = TITLES[selected as string] ?? TITLES['/' + (location.pathname.split('/')[1] ?? 'home')] ?? ['', ''];
  let [eyebrow, title] = base;
  if (location.pathname.startsWith('/events/')) {
    const slug = location.pathname.split('/')[2];
    const kind = eventKinds.find((k) => k.slug === slug);
    if (kind) title = kind.name;
  }

  const initials = me.full_name.split(' ').map((p) => p[0]).slice(0, 2).join('');

  const userMenu = {
    items: [
      { key: 'profile', icon: <UserOutlined />, label: 'My profile', onClick: () => navigate('/profile') },
      ...(googleEnabled && !me.google_linked
        ? [{ key: 'link-google', icon: <GoogleOutlined />, label: 'Link Google account', onClick: () => { window.location.href = '/api/auth/google/login'; } }]
        : []),
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: 'Log out', onClick: () => logout().then(() => navigate('/login')) },
    ],
  };

  const railW = collapsed ? 0 : 222;

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {/* NAV RAIL */}
      <aside
        className="mtr-scroll"
        style={{
          width: railW,
          flexShrink: 0,
          background: 'linear-gradient(180deg,#080a10,#060709)',
          borderRight: railW ? '1px solid rgba(120,170,230,.1)' : 'none',
          position: 'fixed',
          insetInlineStart: 0,
          top: 0,
          height: '100vh',
          overflowY: 'auto',
          overflowX: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          zIndex: 30,
          transition: 'width .18s ease',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '18px 16px 16px', whiteSpace: 'nowrap' }}>
          <img src="/logo.png" width={38} height={38} style={{ borderRadius: 9, boxShadow: '0 0 18px rgba(92,198,255,.25)', flexShrink: 0 }} alt="MTR" />
          <div>
            <div style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 13, letterSpacing: '.14em', color: '#eaf2ff', lineHeight: 1 }}>MIND·TECH</div>
            <div style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.34em', color: '#5cc6ff', marginTop: 4 }}>ROBOTICS</div>
          </div>
        </div>
        <div style={{ height: 1, background: 'rgba(120,170,230,.1)', margin: '4px 14px 10px' }} />
        <nav style={{ flex: 1 }}>
          {items.map((it) => {
            const groupBreak = it.key === '/team';
            return (
              <div key={it.key}>
                {groupBreak && <div style={{ height: 1, background: 'rgba(120,170,230,.08)', margin: '10px 20px' }} />}
                <div className={`mtr-nav${isActive(it.key) ? ' active' : ''}`} onClick={() => navigate(it.key)}>
                  {ICONS[it.key]}
                  {it.label}
                </div>
                {it.children && eventsOpen && it.children.map((c) => (
                  <div key={c.key} className={`mtr-sub${selected === c.key ? ' active' : ''}`} onClick={() => navigate(c.key)}>
                    {c.label}
                  </div>
                ))}
              </div>
            );
          })}
        </nav>
        <div style={{ padding: '12px 16px', borderTop: '1px solid rgba(120,170,230,.08)', whiteSpace: 'nowrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontFamily: MONO, fontSize: 9.5, letterSpacing: '.16em', color: 'rgba(224,236,252,.35)' }}>
            <span className="mtr-online-dot" />SYSTEM ONLINE
          </div>
        </div>
      </aside>

      {/* CONTENT COLUMN */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', marginInlineStart: railW, transition: 'margin .18s ease' }}>
        {/* HEADER */}
        <header
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 20,
            height: 62,
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            padding: '0 24px',
            background: 'rgba(8,11,17,.72)',
            backdropFilter: 'blur(16px)',
            borderBottom: '1px solid rgba(120,170,230,.1)',
          }}
        >
          <button
            type="button"
            aria-label={collapsed ? 'Open menu' : 'Collapse menu'}
            onClick={() => setCollapsed((c) => !c)}
            className="mtr-icon-btn"
            style={{ marginInlineStart: -6 }}
          >
            <svg viewBox="0 0 20 20" width={17} height={17} fill="none" stroke="currentColor" strokeWidth={1.6}>
              <path d="M3 5h14M3 10h14M3 15h14" />
            </svg>
          </button>
          <div>
            <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: '.24em', textTransform: 'uppercase', color: '#5cc6ff' }}>{eyebrow}</div>
            <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 16, color: '#eaf2ff', lineHeight: 1.1, marginTop: 2 }}>{title}</div>
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '.08em', color: 'rgba(224,236,252,.4)' }} className="mtr-clock">{clock}</div>
          <NotificationsBell />
          <Dropdown menu={userMenu} placement="bottomRight">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, paddingInlineStart: 14, borderInlineStart: '1px solid rgba(120,170,230,.12)', cursor: 'pointer' }}>
              <div style={{ width: 36, height: 36, borderRadius: 9, background: 'linear-gradient(135deg,rgba(92,198,255,.3),rgba(92,198,255,.08))', border: '1px solid rgba(92,198,255,.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: MONO, fontWeight: 600, fontSize: 13, color: '#5cc6ff' }}>{initials}</div>
              <div style={{ lineHeight: 1.25 }} className="mtr-userchip">
                <div style={{ fontSize: 13, fontWeight: 500, color: '#eaf2ff', whiteSpace: 'nowrap' }}>{me.full_name}</div>
                <div style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.14em', textTransform: 'uppercase', color: 'rgba(224,236,252,.45)' }}>{me.level ? me.level.name : 'No level'}</div>
              </div>
            </div>
          </Dropdown>
        </header>

        {/* MAIN */}
        <main className="mtr-scroll" style={{ flex: 1, minWidth: 0, padding: '28px 28px 60px' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
