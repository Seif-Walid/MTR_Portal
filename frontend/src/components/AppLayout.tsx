import { BellOutlined, DownloadOutlined, GoogleOutlined, LogoutOutlined, UserOutlined } from '@ant-design/icons';
import { App as AntApp, ConfigProvider, Dropdown, message } from 'antd';
import { AnimatePresence, LayoutGroup, motion, MotionConfig } from 'motion/react';
import { useEffect, useRef, useState, type ReactElement } from 'react';
import { useLocation, useNavigate, useOutlet, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import { can, useAuth } from '../auth/AuthContext';
import { useInstallApp } from '../lib/pwa';
import { forgetDeviceOnServer, onServiceWorkerMessage, resyncPush } from '../lib/push';
import { useThemeMode } from '../theme/ThemeContext';
import { RouteEmpty } from './EmptyState';
import { LogoImage } from './Logo';
import NotificationsBell from './NotificationsBell';
import PushSettingsModal from './PushSettingsModal';

/* ==========================================================================
   App shell — "Workbench". Light/dark from role tokens; interaction in the
   Webflow vein but held to the design system's motion rules: a pill that
   glides between nav items as you hover, a sliding theme switch whose new
   theme grows out of the click, and a short page transition. All routing,
   permission gating, event-kind submenu, notifications, google-link, logout
   and the responsive collapse are unchanged.
   ========================================================================== */

const EASE = [0.33, 1, 0.68, 1] as const;

// Every empty table / list in the shell gets the mascot, a phrase for the
// page and a button somewhere useful. Pickers keep a one-line "no matches".
const PICKERS = new Set(['Select', 'TreeSelect', 'Cascader', 'Transfer', 'AutoComplete', 'Mentions', 'Table.filter']);
const renderEmpty = (name?: string) =>
  name && PICKERS.has(name)
    ? <div style={{ padding: '10px 4px', color: 'var(--text-tertiary)', fontSize: 13, textAlign: 'center' }}>No matches</div>
    : <RouteEmpty />;
const GLASS_SELECTOR = '.mtr-glass, .home-panel, .home-stat, .circuit-panel, .ant-card, .circuit-table .ant-table:not(:has(.ant-table-placeholder)), .mtr-course-card';
const GLIDE = { type: 'spring', stiffness: 520, damping: 42, mass: 0.7 } as const;

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
  '/admin/data': <Ic><rect x="3" y="4" width="14" height="12" rx="1.5" /><path d="M3 8h14M3 12h14M8.5 4v12" /></Ic>,
  '/explore': <Ic><path d="M3.5 16.5h13" /><path d="M6 13.5V9M10 13.5V5.5M14 13.5v-6" /></Ic>,
  '/members': <Ic><circle cx="10" cy="7" r="3" /><path d="M4 17c0-3.2 2.7-5 6-5s6 1.8 6 5" /></Ic>,
  '/applications': <Ic><rect x="4" y="3" width="12" height="14" rx="1.5" /><path d="M7 7.5h6M7 10.5h6M7 13.5l1.5 1.5 3-3" /></Ic>,
  '/courses': <Ic><path d="M10 5.5C8.3 4.3 6 3.8 3 4v11c3-.2 5.3.3 7 1.5 1.7-1.2 4-1.7 7-1.5V4c-3-.2-5.3.3-7 1.5z" /><path d="M10 5.5v11" /></Ic>,
  '/assistant': <Ic><path d="M4 5.5A2.5 2.5 0 016.5 3h7A2.5 2.5 0 0116 5.5v5a2.5 2.5 0 01-2.5 2.5H9l-3.5 3v-3A2.5 2.5 0 014 10.5z" /><path d="M10 5.6l.7 1.7 1.7.7-1.7.7-.7 1.7-.7-1.7-1.7-.7 1.7-.7z" /></Ic>,
  '/finance': <Ic><rect x="3" y="5" width="14" height="10.5" rx="1.5" /><path d="M3 8.5h14" /><circle cx="13" cy="12" r="1.2" /></Ic>,
};

// --- header eyebrow + title per route ---------------------------------------
const TITLES: Record<string, [string, string]> = {
  '/home': ['Home', 'Home'],
  '/tasks': ['Tasks', 'My Tasks'],
  '/calendar': ['Schedule', 'Calendar'],
  '/inventory': ['Inventory', 'Components'],
  '/events': ['Events', 'Events'],
  '/requests': ['Requests', 'Work Requests'],
  '/team': ['People', 'My Teams'],
  '/archive': ['Records', 'Archive'],
  '/organization': ['People', 'Organization'],
  '/admin/users': ['Admin', 'User Management'],
  '/admin/audit': ['Admin', 'Audit Log'],
  '/admin/data': ['Admin', 'Data Tables'],
  '/explore': ['Overview', 'Dashboard'],
  '/members': ['People', 'Members'],
  '/applications': ['People', 'Applications'],
  '/finance': ['Money', 'Finance'],
  '/courses': ['Learning', 'Courses'],
  '/assistant': ['Workspace', 'Assistant'],
  '/profile': ['Account', 'Profile'],
};


function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  const date = now.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  const time = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  return `${date}, ${time}`;
}

/* Theme switch: three options, a thumb that slides to the chosen one. */
function ThemeSwitch() {
  const { pref, setPref } = useThemeMode();
  const opts = [
    { k: 'light' as const, label: 'Light', icon: <><circle cx="10" cy="10" r="3.2" /><path d="M10 2.5v1.8M10 15.7v1.8M2.5 10h1.8M15.7 10h1.8M4.7 4.7l1.3 1.3M14 14l1.3 1.3M15.3 4.7L14 6M6 14l-1.3 1.3" /></> },
    { k: 'dark' as const, label: 'Dark', icon: <path d="M15.5 12.2A6 6 0 017.8 4.5a6 6 0 107.7 7.7z" /> },
    { k: 'system' as const, label: 'Auto', icon: <><rect x="3" y="4" width="14" height="10" rx="1.5" /><path d="M7.5 17h5M10 14v3" /></> },
  ];
  return (
    <div role="radiogroup" aria-label="Colour theme" className="mtr-theme-switch">
      {opts.map((o) => {
        const on = pref === o.k;
        return (
          <button
            key={o.k}
            type="button"
            role="radio"
            aria-checked={on}
            title={`${o.label} theme`}
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              setPref(o.k, { x: r.left + r.width / 2, y: r.top + r.height / 2 });
            }}
            className={on ? 'on' : undefined}
          >
            {on && <motion.span layoutId="theme-thumb" className="mtr-theme-thumb" transition={GLIDE} />}
            <svg viewBox="0 0 20 20" width={15} height={15} fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true">{o.icon}</svg>
            <span>{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/* Freezes the outgoing page so AnimatePresence can fade it out. */
function AnimatedOutlet() {
  const location = useLocation();
  const outlet = useOutlet();
  const [frozen] = useState<Record<string, ReactElement | null>>({});
  const key = location.pathname;
  frozen[key] = outlet;
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={key}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0, transition: { duration: 0.3, ease: EASE } }}
        exit={{ opacity: 0, y: -4, transition: { duration: 0.12, ease: [0.32, 0, 0.67, 0] } }}
      >
        {frozen[key]}
      </motion.div>
    </AnimatePresence>
  );
}

export default function AppLayout() {
  const { me, logout } = useAuth();
  const { modal } = AntApp.useApp();
  const { mode: installMode, install } = useInstallApp();
  const navigate = useNavigate();
  const [pushOpen, setPushOpen] = useState(false);

  // tapping a push notification while the portal is open routes in place
  useEffect(() => onServiceWorkerMessage((msg) => {
    if (msg.type === 'open-url' && msg.url) {
      const u = new URL(msg.url);
      if (u.origin === window.location.origin) navigate(u.pathname + u.search + u.hash);
    }
  }), [navigate]);
  // this device's notifications follow whoever is signed in now
  useEffect(() => { if (me) void resyncPush(); }, [me?.id]);
  // the bell's "turn on" link
  useEffect(() => {
    const open = () => setPushOpen(true);
    window.addEventListener('open-push-settings', open);
    return () => window.removeEventListener('open-push-settings', open);
  }, []);
  const location = useLocation();
  const clock = useClock();
  // read the breakpoint synchronously so phones never paint the rail open first
  const [collapsed, setCollapsed] = useState(() => window.matchMedia('(max-width: 991px)').matches);
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 991px)').matches);
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [eventKinds, setEventKinds] = useState<{ slug: string; name: string }[]>([]);
  const [eventsOpen, setEventsOpen] = useState(true);
  const [hovered, setHovered] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  // Desktop rail: a slim icon strip that opens while the pointer (or keyboard
  // focus) is on it and pushes the page aside; the menu button pins it open.
  const [pinned, setPinned] = useState(() => {
    try { return localStorage.getItem('mtr.nav.pinned') === '1'; } catch { return false; }
  });
  const [peek, setPeek] = useState(false);
  const peekTimer = useRef<number | undefined>(undefined);
  const schedulePeek = (open: boolean, delay: number) => {
    window.clearTimeout(peekTimer.current);
    peekTimer.current = window.setTimeout(() => setPeek(open), delay);
  };
  const togglePinned = () => setPinned((p) => {
    try { localStorage.setItem('mtr.nav.pinned', p ? '0' : '1'); } catch { /* storage off */ }
    if (p) setPeek(false);
    return !p;
  });
  const sentinel = useRef<HTMLDivElement>(null);
  // collapsed nav sections, remembered per browser
  const [closedSections, setClosedSections] = useState<Set<string>>(() => {
    // Administration starts folded for browsers that never chose; a saved choice wins
    try { return new Set(JSON.parse(localStorage.getItem('mtr.nav.closed') ?? '["admin"]')); } catch { return new Set(['admin']); }
  });
  const toggleSection = (id: string) => setClosedSections((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    try { localStorage.setItem('mtr.nav.closed', JSON.stringify([...next])); } catch { /* storage off */ }
    return next;
  });
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

  // collapse rail on small screens; below 992px the rail overlays content
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 991px)');
    const apply = () => { setCollapsed(mq.matches); setIsMobile(mq.matches); };
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  // header picks up a hairline once content scrolls under it
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setScrolled(!e.isIntersecting));
    io.observe(el);
    return () => io.disconnect();
  }, [me]);

  if (!me) return null;

  // --- permission-gated nav, grouped into collapsible sections -------------
  type NavItem = { key: string; label: string; children?: { key: string; label: string }[] };
  type NavSection = { id: string; title: string; items: NavItem[] };
  const canDataTables = can(me, 'inventory.edit') || can(me, 'users.manage') || can(me, 'org.edit') ||
    can(me, 'events.manage_any') || can(me, 'members.edit');
  const sections: NavSection[] = ([
    { id: 'work', title: 'Workspace', items: [
      { key: '/home', label: 'Home' },
      ...(can(me, 'dashboard.view') ? [{ key: '/explore', label: 'Dashboard' }] : []),
      ...(can(me, 'ai.use') ? [{ key: '/assistant', label: 'Assistant' }] : []),
      ...(can(me, 'tasks.use') ? [{ key: '/tasks', label: 'My tasks' }, { key: '/requests', label: 'Requests' }] : []),
      ...(can(me, 'tasks.use') || can(me, 'events.view') || can(me, 'inventory.view')
        ? [{ key: '/calendar', label: 'Calendar' }]
        : []),
      ...(can(me, 'courses.view') ? [{ key: '/courses', label: 'Courses' }] : []),
    ] },
    { id: 'ops', title: 'Operations', items: [
      ...(canViewEvents
        ? [{ key: '/events', label: 'Events', ...(eventKinds.length ? { children: eventKinds.map((k) => ({ key: `/events/${k.slug}`, label: k.name })) } : {}) }]
        : []),
      ...(can(me, 'inventory.view') ? [{ key: '/inventory', label: 'Inventory' }] : []),
      ...(can(me, 'finance.view') ? [{ key: '/finance', label: 'Finance' }] : []),
      // Archive is public — a browsable record of past events, no gate.
      { key: '/archive', label: 'Archive' },
    ] },
    { id: 'people', title: 'People', items: [
      ...(can(me, 'people.view') && (me.has_team || can(me, 'users.manage')) ? [{ key: '/team', label: 'My teams' }] : []),
      ...(can(me, 'org.view') ? [{ key: '/organization', label: 'Organization' }] : []),
      ...(can(me, 'members.view') ? [{ key: '/members', label: 'Members' }, { key: '/applications', label: 'Applications' }] : []),
    ] },
    { id: 'admin', title: 'Administration', items: [
      ...(can(me, 'users.manage') ? [{ key: '/admin/users', label: 'User management' }] : []),
      ...(canDataTables ? [{ key: '/admin/data', label: 'Data tables' }] : []),
      ...(can(me, 'audit.view') ? [{ key: '/admin/audit', label: 'Audit log' }] : []),
    ] },
  ] as NavSection[]).filter((sec) => sec.items.length > 0);
  const items = sections.flatMap((sec) => sec.items);

  const allKeys = items.flatMap((i) => (i.children ? i.children.map((c) => c.key) : [i.key]));
  const selected = allKeys
    .filter((k) => location.pathname === k || location.pathname.startsWith(k + '/') || location.pathname.startsWith(k))
    .sort((a, b) => b.length - a.length)[0];
  const isActive = (key: string) =>
    key === '/events' ? location.pathname.startsWith('/events') : selected === key;

  // header title — for an events sub-route, show the kind name
  const base = TITLES[selected as string] ?? TITLES['/' + (location.pathname.split('/')[1] ?? 'home')] ?? ['', ''];
  let [, title] = base;
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
      { key: 'notifications', icon: <BellOutlined />, label: 'Notifications', onClick: () => setPushOpen(true) },
      ...(installMode === 'prompt'
        ? [{ key: 'install', icon: <DownloadOutlined />, label: 'Install app', onClick: () => { void install(); } }]
        : installMode === 'ios'
          ? [{ key: 'install', icon: <DownloadOutlined />, label: 'Install app', onClick: () => modal.info({ title: 'Install on iPhone / iPad', content: 'In Safari, tap the Share button, then "Add to Home Screen".' }) }]
          : []),
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: 'Log out', onClick: () => forgetDeviceOnServer().then(logout).then(() => navigate('/login')) },
    ],
  };

  // One delegated tracker feeds every glass panel's cursor sheen (--mx/--my),
  // instead of a listener per card.
  const sheenEl = useRef<HTMLElement | null>(null);
  const trackSheen = (e: React.PointerEvent) => {
    if (e.pointerType !== 'mouse') return;
    // the outermost panel: inner boxes are flattened, so the shine lives on the outer one
    let el = (e.target as HTMLElement).closest<HTMLElement>(GLASS_SELECTOR);
    for (let up = el?.parentElement?.closest<HTMLElement>(GLASS_SELECTOR); up; up = up.parentElement?.closest<HTMLElement>(GLASS_SELECTOR)) el = up;
    if (sheenEl.current && sheenEl.current !== el) {
      sheenEl.current.style.removeProperty('--mx');
      sheenEl.current.style.removeProperty('--my');
    }
    sheenEl.current = el;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${e.clientX - r.left}px`);
    el.style.setProperty('--my', `${e.clientY - r.top}px`);
  };

  const RAIL_OPEN = 240;
  const RAIL_MINI = 72;
  const expanded = isMobile ? !collapsed : pinned || peek;
  const railW = isMobile ? (collapsed ? 0 : RAIL_OPEN) : expanded ? RAIL_OPEN : RAIL_MINI;
  // Desktop: the rail always pushes the page, so opening it shifts everything.
  // Mobile: no room to push, so the rail floats over the content.
  const contentInset = isMobile ? 0 : railW;
  const go = (key: string) => { navigate(key); if (isMobile) setCollapsed(true); };
  // real links (keyboard, middle-click, copy link) that still route client-side on a plain click
  const follow = (e: React.MouseEvent<HTMLAnchorElement>, key: string) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    go(key);
  };

  // the pill shows under the hovered item, else under the active one
  const pillOn = (key: string, active: boolean) => (hovered ? hovered === key : active);

  // a render helper, not a component: a component declared here would remount
  // on every hover and drop keyboard focus
  const navLink = (k: string, label: string, sub?: boolean) => {
    const active = sub ? selected === k : isActive(k);
    return (
      <a
        key={k}
        href={k}
        className={`${sub ? 'mtr-sub' : 'mtr-nav'}${active ? ' active' : ''}`}
        aria-current={selected === k ? 'page' : undefined}
        onClick={(e) => follow(e, k)}
        onMouseEnter={() => setHovered(k)}
        onFocus={() => setHovered(k)}
      >
        {pillOn(k, active) && (
          <motion.span layoutId="nav-pill" className={`mtr-nav-pill${active ? ' is-active' : ''}`} transition={GLIDE} />
        )}
        {active && !sub && <motion.span layoutId="nav-bar" className="mtr-nav-bar" transition={GLIDE} />}
        {!sub && <span className="mtr-nav-icon">{ICONS[k]}</span>}
        {label}
        {active && <motion.span layoutId={sub ? 'nav-dot-sub' : 'nav-dot'} className="mtr-nav-dot" transition={GLIDE} aria-hidden />}
      </a>
    );
  };

  return (
    <MotionConfig reducedMotion="user">
    <ConfigProvider renderEmpty={renderEmpty}>
    <div style={{ display: 'flex', minHeight: '100vh' }} onPointerMove={trackSheen}>
      <a href="#main" className="mtr-skip-link">Skip to content</a>
      <div className="mtr-aurora" aria-hidden="true"><span /><span /><span /><span /><span /></div>
      <AnimatePresence>
        {isMobile && !collapsed && (
          <motion.button
            type="button"
            aria-label="Close menu"
            className="mtr-nav-backdrop"
            onClick={() => setCollapsed(true)}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: { duration: 0.25 } }}
            exit={{ opacity: 0, transition: { duration: 0.18 } }}
          />
        )}
      </AnimatePresence>
      {/* NAV RAIL */}
      <aside
        className={`mtr-scroll mtr-rail${!isMobile && !expanded ? ' is-mini' : ''}`}
        aria-label="Main navigation"
        // a folded mobile rail is width 0 — keep its links out of the tab order and the reading order
        {...(isMobile && collapsed ? { inert: '' } : {})}
        onMouseEnter={() => !isMobile && !pinned && schedulePeek(true, 0)}
        onMouseLeave={() => !isMobile && !pinned && schedulePeek(false, 120)}
        onFocus={() => !isMobile && !pinned && schedulePeek(true, 0)}
        onBlur={(e) => {
          if (!isMobile && !pinned && !e.currentTarget.contains(e.relatedTarget as Node)) schedulePeek(false, 0);
        }}
        style={{
          width: railW,
          flexShrink: 0,
          position: 'fixed',
          insetInlineStart: 0,
          top: 0,
          height: '100vh',
          overflowY: expanded ? 'auto' : 'hidden',
          overflowX: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          zIndex: 30,
          borderInlineEndWidth: railW ? 1 : 0,
          boxShadow: isMobile && railW ? 'var(--shadow-floating)' : 'none',
          transition: 'width .16s cubic-bezier(0.33, 1, 0.68, 1), box-shadow .16s',
          willChange: 'width',
        }}
      >
        <a href="/home" onClick={(e) => follow(e, '/home')} className="mtr-brand" aria-label="Mind Tech Robotics, home">
          <LogoImage size={40} label="" />
          <span>
            <span className="mtr-brand__name">Mind Tech</span>
            <span className="mtr-brand__sub">Robotics portal</span>
          </span>
        </a>
        <LayoutGroup id="rail">
        <nav style={{ flex: 1, paddingBottom: 8 }} aria-label="Pages" onMouseLeave={() => setHovered(null)} onBlur={() => setHovered(null)}>
          {sections.map((sec) => {
            // the section holding the current page always shows
            const holdsActive = sec.items.some((it) => isActive(it.key));
            const open = holdsActive || !closedSections.has(sec.id);
            return (
              <div key={sec.id}>
                <button
                  type="button"
                  className="mtr-nav-section"
                  aria-expanded={open}
                  onClick={() => toggleSection(sec.id)}
                  disabled={holdsActive}
                >
                  {sec.title}
                  {!holdsActive && (
                    <svg viewBox="0 0 20 20" width={11} height={11} fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true"
                      style={{ marginInlineStart: 'auto', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .25s cubic-bezier(0.33, 1, 0.68, 1)' }}>
                      <path d="M7 5l6 5-6 5" />
                    </svg>
                  )}
                </button>
                <AnimatePresence initial={false}>
                  {open && (
                    <motion.div
                      key="items"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1, transition: { duration: 0.25, ease: EASE } }}
                      exit={{ height: 0, opacity: 0, transition: { duration: 0.2, ease: [0.32, 0, 0.67, 0] } }}
                      style={{ overflow: 'hidden' }}
                    >
                      {sec.items.map((it) => (
                        <div key={it.key} className={it.children ? 'mtr-nav-group' : undefined}>
                          {navLink(it.key, it.label)}
                          {it.children && (
                            <button
                              type="button"
                              aria-label={`${eventsOpen ? 'Hide' : 'Show'} ${it.label.toLowerCase()} kinds`}
                              aria-expanded={eventsOpen}
                              onClick={() => setEventsOpen((o) => !o)}
                              className="mtr-nav-chevron"
                            >
                              <svg viewBox="0 0 20 20" width={13} height={13} fill="none" stroke="currentColor" strokeWidth={1.7} aria-hidden="true"
                                style={{ transform: eventsOpen ? 'rotate(90deg)' : 'none', transition: 'transform .25s cubic-bezier(0.33, 1, 0.68, 1)' }}>
                                <path d="M7 5l6 5-6 5" />
                              </svg>
                            </button>
                          )}
                          {it.children && eventsOpen && expanded && it.children.map((c) => navLink(c.key, c.label, true))}
                        </div>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </nav>
        </LayoutGroup>
        <div className="mtr-rail-foot">
          <ThemeSwitch />
        </div>
      </aside>

      {/* CONTENT COLUMN */}
      <div className="mtr-shell-content" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', marginInlineStart: contentInset, transition: 'margin .16s cubic-bezier(0.33, 1, 0.68, 1)' }}>
        <div ref={sentinel} style={{ height: 1, marginBottom: -1 }} aria-hidden="true" />
        {/* HEADER */}
        <header
          className={`mtr-header${scrolled ? ' is-scrolled' : ''}`}
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 20,
            height: 60,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '0 24px',
          }}
        >
          <button
            type="button"
            aria-label={isMobile ? (collapsed ? 'Open menu' : 'Close menu') : pinned ? 'Unpin menu' : 'Pin menu open'}
            aria-expanded={expanded}
            onClick={() => (isMobile ? setCollapsed((c) => !c) : togglePinned())}
            className="mtr-icon-btn"
            style={{ marginInlineStart: -8 }}
          >
            <svg viewBox="0 0 20 20" width={17} height={17} fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true">
              <path d="M3 6h14M3 10h9M3 14h14" />
            </svg>
          </button>
          <AnimatePresence mode="wait" initial={false}>
            <motion.h1
              key={title}
              className="mtr-header__title"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0, transition: { duration: 0.25, ease: EASE } }}
              exit={{ opacity: 0, y: -6, transition: { duration: 0.12 } }}
            >
              {title}
            </motion.h1>
          </AnimatePresence>
          <div style={{ flex: 1 }} />
          <div className="mtr-clock">{clock}</div>
          <NotificationsBell />
          <PushSettingsModal open={pushOpen} onClose={() => setPushOpen(false)} />
          <Dropdown menu={userMenu} placement="bottomRight" trigger={['click']}>
            <button
              type="button"
              className="mtr-user-btn"
              aria-label={`Account menu for ${me.full_name}`}
              aria-haspopup="menu"
              style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}
            >
              <div aria-hidden="true" className="mtr-avatar">{initials}</div>
              <div style={{ lineHeight: 1.25 }} className="mtr-userchip">
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{me.full_name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{me.level ? me.level.name : 'No level'}</div>
              </div>
            </button>
          </Dropdown>
        </header>

        {/* MAIN */}
        <main id="main" tabIndex={-1} className="mtr-scroll mtr-main" style={{ flex: 1, minWidth: 0, padding: '24px 32px 64px' }}>
          <AnimatedOutlet />
        </main>
      </div>
    </div>
    </ConfigProvider>
    </MotionConfig>
  );
}
