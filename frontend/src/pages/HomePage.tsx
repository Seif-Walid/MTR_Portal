import {
  CalendarOutlined,
  CheckSquareOutlined,
  InboxOutlined,
  PlusOutlined,
  RightOutlined,
  SendOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import { Alert, Skeleton, message } from 'antd';
import dayjs from 'dayjs';
import { AnimatePresence, LayoutGroup, motion, useAnimate } from 'motion/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Dashboard, DashboardItem, DashboardSection } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import NewTaskModal from '../components/NewTaskModal';
import TaskDrawer from '../components/TaskDrawer';
import { CountUp, CubeField, OrbitButton, useSpotlight, useTilt } from '../components/fx';
import './home.css';

const SOURCE_ICON: Record<DashboardItem['source'], React.ReactNode> = {
  task: <CheckSquareOutlined />,
  request: <SendOutlined />,
  inventory: <InboxOutlined />,
  event: <TrophyOutlined />,
};

const SOURCE_ROUTE: Record<DashboardItem['source'], string> = {
  task: '/tasks',
  request: '/requests',
  inventory: '/inventory',
  event: '/events',
};

const STATUS_LABEL: Record<string, string> = {
  todo: 'To do',
  in_progress: 'In progress',
  submitted: 'Submitted',
  revision_requested: 'Needs revision',
  pending: 'Pending',
  issued: 'On loan',
};

const EASE = [0.33, 1, 0.68, 1] as const;
const GLIDE = { type: 'spring', stiffness: 520, damping: 42, mass: 0.7 } as const;

function greeting(hour: number): string {
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

function dueLabel(iso: string | null): { text: string; overdue: boolean } | null {
  if (!iso) return null;
  const d = dayjs(iso).startOf('day');
  const today = dayjs().startOf('day');
  const diff = d.diff(today, 'day');
  if (diff < 0) return { text: `${-diff}d late`, overdue: true };
  if (diff === 0) return { text: 'Today', overdue: false };
  if (diff === 1) return { text: 'Tomorrow', overdue: false };
  if (diff < 7) return { text: d.format('ddd'), overdue: false };
  return { text: d.format('D MMM'), overdue: false };
}

/* ── Stat tile ───────────────────────────────────────────────────────────
   Bento tile that leans toward the cursor; on hover the brand gradient
   sweeps in from the start edge and the text turns white. */
function StatTile({
  stat, index, onJump, enter,
}: {
  stat: Dashboard['stats'][number];
  index: number;
  onJump: (key: string) => void;
  enter: object;
}) {
  const active = stat.count > 0;
  const danger = stat.tone === 'danger' && active;
  const tilt = useTilt(8);
  return (
    <motion.button
      type="button"
      className={`home-stat${active ? ' is-active' : ''}${danger ? ' is-danger' : ''}`}
      onClick={() => active && onJump(stat.key)}
      aria-disabled={!active}
      aria-label={`${stat.count} ${stat.label}${active ? ', show' : ''}`}
      whileHover={active ? { y: -4, scale: 1.02 } : undefined}
      whileTap={active ? { scale: 0.96 } : undefined}
      style={active ? tilt.style : undefined}
      {...(active ? tilt.handlers : {})}
      {...enter}
      data-i={index}
    >
      <span className="home-stat__sweep" aria-hidden />
      {active && <motion.span className="home-stat__glare" style={{ background: tilt.glare }} aria-hidden />}
      <span className="home-stat__num"><CountUp value={stat.count} /></span>
      <span className="home-stat__label">
        {danger && <span className="home-signal is-pulse" aria-hidden />}
        {stat.label}
      </span>
    </motion.button>
  );
}

export default function HomePage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => dayjs());
  const [creating, setCreating] = useState(false);
  const [hoverRow, setHoverRow] = useState<string | null>(null);
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const spot = useSpotlight();
  const [scope, animate] = useAnimate();
  // the entrance plays once per visit, not on every refetch
  const entered = useRef(false);

  const canAssign = useMemo(
    () => can(me, 'tasks.assign') && (!!me?.has_team || !!me?.privileges.includes('users.manage')),
    [me],
  );
  const openTaskId = searchParams.get('task') ? Number(searchParams.get('task')) : null;

  const load = useCallback(() => {
    api
      .get<Dashboard>('/api/dashboard')
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => {
        setError(e.message);
        message.error(e.message);
      });
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    if (data) {
      const t = window.setTimeout(() => { entered.current = true; }, 900);
      return () => window.clearTimeout(t);
    }
  }, [data]);

  useEffect(() => {
    const onFocus = () => load();
    window.addEventListener('focus', onFocus);
    const clock = window.setInterval(() => setNow(dayjs()), 30_000);
    return () => {
      window.removeEventListener('focus', onFocus);
      window.clearInterval(clock);
    };
  }, [load]);

  const openItem = (it: DashboardItem) => {
    if (it.source === 'task') setSearchParams({ task: String(it.id) });
    else navigate(SOURCE_ROUTE[it.source]);
  };

  // Jump to a section and flash it, so the eye lands where the tile pointed.
  const jumpTo = (key: string) => {
    const el = sectionRefs.current[key];
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    animate(
      el.querySelector('.home-panel') as Element,
      { boxShadow: ['0 0 0 0px var(--brand-fg)', '0 0 0 3px color-mix(in srgb, var(--brand-fg) 30%, transparent)', '0 0 0 0px transparent'] },
      { duration: 1.1, delay: 0.35, ease: 'easeOut' },
    );
  };

  const firstName = data?.greeting_name ?? me?.full_name.split(' ')[0] ?? '';
  const urgent = data?.stats.filter((s) => s.tone === 'danger' && s.count > 0).reduce((n, s) => n + s.count, 0) ?? 0;

  const rise = (i: number) =>
    entered.current
      ? {}
      : {
          initial: { opacity: 0, y: 14 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.45, ease: EASE, delay: 0.08 + i * 0.06 },
        };

  // ---- pieces ---------------------------------------------------------------

  const itemRow = (it: DashboardItem, section: DashboardSection) => {
    const due = dueLabel(it.due);
    const statusLabel = it.status ? STATUS_LABEL[it.status] : null;
    const metaParts = [it.detail, statusLabel].filter(Boolean) as string[];
    const rowKey = `${section.key}:${it.source}-${it.id}`;
    return (
      <div
        key={rowKey}
        role="button"
        tabIndex={0}
        aria-label={`${it.title}${due ? `, ${due.overdue ? due.text : 'due ' + due.text}` : ''}${it.blocked ? ', blocked' : ''}. ${it.action}.`}
        onClick={() => openItem(it)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            openItem(it);
          }
        }}
        onMouseEnter={() => setHoverRow(rowKey)}
        onFocus={() => setHoverRow(rowKey)}
        className="home-row"
      >
        {hoverRow === rowKey && (
          <motion.span layoutId={`home-row-hover-${section.key}`} className="home-row__hover" transition={GLIDE} />
        )}
        <span aria-hidden className="home-row__icon">{SOURCE_ICON[it.source]}</span>
        <div className="home-row__body">
          <div className="home-row__title">{it.title}</div>
          {(metaParts.length > 0 || it.blocked) && (
            <div className="home-row__meta">
              {metaParts.length > 0 && <span className="home-row__detail">{metaParts.join(', ')}</span>}
              {it.blocked && (
                <span className="home-row__blocked"><span className="home-signal" aria-hidden />Blocked</span>
              )}
            </div>
          )}
        </div>
        {due && <span className={`home-row__due${due.overdue ? ' is-late' : ''}`}>{due.text}</span>}
        <RightOutlined aria-hidden className="home-row__chev" />
      </div>
    );
  };

  const section = (s: DashboardSection, i: number) => (
    <motion.section
      key={s.key}
      id={`sec-${s.key}`}
      ref={(el: HTMLDivElement | null) => {
        sectionRefs.current[s.key] = el;
      }}
      className="home-section"
      aria-labelledby={`sec-h-${s.key}`}
      {...rise(4 + i)}
    >
      <div className="home-section__head">
        <h3 id={`sec-h-${s.key}`} className={s.tone === 'danger' ? 'is-danger' : undefined}>
          {s.tone === 'danger' && <span className="home-signal" aria-hidden />}
          {s.label}
        </h3>
        <span className="home-count">{s.count}</span>
      </div>
      <div className="home-panel" onMouseLeave={() => setHoverRow(null)} onBlur={() => setHoverRow(null)}>
        <LayoutGroup id={`rows-${s.key}`}>
          {s.items.map((it) => itemRow(it, s))}
        </LayoutGroup>
        {s.count > s.items.length && (
          <button
            type="button"
            onClick={() => navigate(SOURCE_ROUTE[s.items[0]?.source ?? 'task'])}
            className="home-more"
          >
            See all {s.count}
          </button>
        )}
      </div>
    </motion.section>
  );

  // ---- render ---------------------------------------------------------------

  const subline = !data
    ? 'Reading the board.'
    : data.all_clear
      ? 'Nothing needs you right now.'
      : urgent > 0
        ? `${urgent} ${urgent === 1 ? 'thing needs' : 'things need'} you first.`
        : 'Here’s what needs you.';

  return (
    <div ref={scope} className="home">
      <motion.header
        className="home-hero"
        {...spot.hostProps}
        initial={entered.current ? false : { opacity: 0, y: 18, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: EASE }}
      >
        <CubeField />
        <motion.span className="home-hero__spot" style={{ background: spot.glow }} aria-hidden />
        <span className="home-hero__orb" aria-hidden />
        <div className="home-hero__text">
          <motion.span className="home-hero__pill" {...rise(1)}>
            <CalendarOutlined aria-hidden />
            {now.format('dddd D MMMM')}
            <span className="home-hero__sep" aria-hidden />
            <span className="home-hero__time">{now.format('HH:mm')}</span>
          </motion.span>
          <motion.h2 className="home-hero__greet" {...rise(1.5)}>
            {greeting(now.hour())}
            {firstName ? `, ${firstName}` : ''}.
          </motion.h2>
          <motion.p className="home-hero__sub" {...rise(2)}>{subline}</motion.p>
        </div>
        <motion.div className="home-hero__action" {...rise(2.5)}>
          {canAssign ? (
            <OrbitButton icon={<PlusOutlined />} label="Assign task" onClick={() => setCreating(true)} />
          ) : (
            <OrbitButton icon={<CheckSquareOutlined />} label="Open tasks" onClick={() => navigate('/tasks')} />
          )}
        </motion.div>
      </motion.header>

      {error && !data && (
        <Alert
          type="error"
          showIcon
          message="Couldn’t load your board"
          description={`${error} Nothing was changed.`}
          action={<button type="button" className="mtr-link-btn" onClick={load}>Retry</button>}
          style={{ marginBottom: 16 }}
        />
      )}

      {!data && !error && (
        <>
          <Skeleton.Node active style={{ width: '100%', height: 104, marginBottom: 24, borderRadius: 16 }}>
            <span />
          </Skeleton.Node>
          <Skeleton active paragraph={{ rows: 5 }} />
        </>
      )}

      {data && data.all_clear && (
        <motion.div className="home-clear" {...rise(2)}>
          <svg width="44" height="44" viewBox="0 0 44 44" fill="none" aria-hidden>
            <circle cx="22" cy="22" r="20" stroke="currentColor" strokeWidth="1.25" opacity="0.35" />
            <motion.path
              d="M14 22.5 L19.5 28 L30 16.5"
              stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.5, delay: 0.35, ease: EASE }}
            />
          </svg>
          <div className="home-clear__title">All clear</div>
          <p>Nothing overdue, nothing waiting on you.</p>
          <a href="/tasks" className="mtr-link-btn" onClick={(e) => { e.preventDefault(); navigate('/tasks'); }}>
            Browse all tasks
          </a>
        </motion.div>
      )}

      {data && !data.all_clear && (
        <>
          <div className="home-stats">
            {data.stats.map((s, i) => (
              <StatTile key={s.key} stat={s} index={i} onJump={jumpTo} enter={rise(3 + i * 0.5)} />
            ))}
          </div>
          <AnimatePresence initial={false}>
            <div className="home-sections">{data.sections.map((s, i) => section(s, i))}</div>
          </AnimatePresence>
        </>
      )}

      <TaskDrawer taskId={openTaskId} onClose={() => setSearchParams({})} onChanged={load} />
      {canAssign && (
        <NewTaskModal open={creating} onClose={() => setCreating(false)} onCreated={() => { setCreating(false); load(); }} />
      )}
    </div>
  );
}
