import {
  CheckSquareOutlined,
  InboxOutlined,
  RightOutlined,
  SendOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import { Alert, Skeleton, Typography, message, theme } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Dashboard, DashboardItem, DashboardSection } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import TaskDrawer from '../components/TaskDrawer';

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

export default function HomePage() {
  const { me } = useAuth();
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => dayjs());
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});

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

  const scrollToSection = (key: string) =>
    sectionRefs.current[key]?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const panelStyle: React.CSSProperties = {
    border: `1px solid ${token.colorBorderSecondary}`,
    borderRadius: token.borderRadiusLG,
    background: token.colorBgContainer,
    boxShadow: token.boxShadowTertiary,
  };

  // ---- instrument readout ---------------------------------------------------

  const Metric = ({
    stat,
    onJump,
  }: {
    stat: Dashboard['stats'][number];
    onJump: () => void;
  }) => {
    const active = stat.count > 0;
    const danger = stat.tone === 'danger' && active;
    return (
      <button
        type="button"
        onClick={() => active && onJump()}
        style={{
          all: 'unset',
          cursor: active ? 'pointer' : 'default',
          background: token.colorBgContainer,
          padding: '18px 20px',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          minWidth: 0,
          transition: 'background 0.2s',
        }}
        onMouseEnter={(e) => {
          if (active) e.currentTarget.style.background = token.colorFillQuaternary;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = token.colorBgContainer;
        }}
      >
        <span
          className="u-label"
          style={{ color: danger ? token.colorError : token.colorTextTertiary, display: 'flex', alignItems: 'center', gap: 6 }}
        >
          {danger && (
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: token.colorError }} />
          )}
          {stat.label}
        </span>
        <span
          className="u-mono"
          style={{
            fontSize: 40,
            fontWeight: 500,
            lineHeight: 1,
            color: danger ? token.colorError : active ? token.colorText : token.colorTextQuaternary,
          }}
        >
          {String(stat.count).padStart(2, '0')}
        </span>
      </button>
    );
  };

  // ---- queue ----------------------------------------------------------------

  const ItemRow = ({ it, last }: { it: DashboardItem; last: boolean }) => {
    const due = dueLabel(it.due);
    const statusLabel = it.status ? STATUS_LABEL[it.status] : null;
    const metaParts = [it.detail, statusLabel].filter(Boolean) as string[];
    return (
      <div
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
        className="home-row"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: '13px 16px',
          borderBottom: last ? 'none' : `1px solid ${token.colorBorderSecondary}`,
          cursor: 'pointer',
        }}
      >
        <span
          aria-hidden
          style={{ color: token.colorTextTertiary, fontSize: 15, display: 'flex', flexShrink: 0 }}
        >
          {SOURCE_ICON[it.source]}
        </span>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              color: token.colorText,
              fontSize: 15,
              lineHeight: 1.3,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {it.title}
          </div>
          {(metaParts.length > 0 || it.blocked) && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 3 }}>
              {metaParts.length > 0 && (
                <span
                  className="u-mono"
                  style={{
                    fontSize: 11,
                    color: token.colorTextTertiary,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    letterSpacing: '0.02em',
                  }}
                >
                  {metaParts.join('  ·  ')}
                </span>
              )}
              {it.blocked && (
                <span
                  className="u-label"
                  style={{ color: token.colorError, display: 'inline-flex', alignItems: 'center', gap: 5, flexShrink: 0, fontSize: 10 }}
                >
                  <span style={{ width: 5, height: 5, borderRadius: '50%', background: token.colorError }} />
                  Blocked
                </span>
              )}
            </div>
          )}
        </div>
        {due && (
          <span
            className="u-mono"
            style={{
              fontSize: 12,
              color: due.overdue ? token.colorError : token.colorTextSecondary,
              fontWeight: due.overdue ? 600 : 400,
              flexShrink: 0,
              letterSpacing: '0.01em',
            }}
          >
            {due.text}
          </span>
        )}
        <RightOutlined
          aria-hidden
          className="home-row__chev"
          style={{ color: token.colorTextQuaternary, fontSize: 11, flexShrink: 0 }}
        />
      </div>
    );
  };

  const Section = ({ section, index }: { section: DashboardSection; index: number }) => (
    <div
      id={`sec-${section.key}`}
      ref={(el) => {
        sectionRefs.current[section.key] = el;
      }}
      className="home-rise"
      style={{ animationDelay: `${140 + index * 70}ms`, scrollMarginTop: 16 }}
    >
      {/* blueprint-ruled section header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '0 16px', marginBottom: 6 }}>
        <span
          className="u-label"
          style={{ color: section.tone === 'danger' ? token.colorError : token.colorText, whiteSpace: 'nowrap' }}
        >
          {section.label}
        </span>
        <span className="u-mono" style={{ fontSize: 11, color: token.colorTextTertiary }}>
          {String(section.count).padStart(2, '0')}
        </span>
        <span style={{ flex: 1, height: 1, background: token.colorBorderSecondary }} />
      </div>
      <div style={{ ...panelStyle, overflow: 'hidden' }}>
        {section.items.map((it, i) => (
          <ItemRow key={`${it.source}-${it.id}-${section.key}`} it={it} last={i === section.items.length - 1 && section.count <= section.items.length} />
        ))}
        {section.count > section.items.length && (
          <button
            type="button"
            onClick={() => navigate(SOURCE_ROUTE[section.items[0]?.source ?? 'task'])}
            className="u-label"
            style={{
              all: 'unset',
              cursor: 'pointer',
              display: 'block',
              padding: '11px 16px',
              color: token.colorTextSecondary,
              fontSize: 10,
            }}
          >
            See all {section.count} →
          </button>
        )}
      </div>
    </div>
  );

  // ---- render ---------------------------------------------------------------

  const firstName = data?.greeting_name ?? me?.full_name.split(' ')[0] ?? '';

  const Header = () => (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        gap: 16,
        marginBottom: 28,
        flexWrap: 'wrap',
      }}
    >
      <div>
        <h1
          style={{
            margin: 0,
            fontSize: 'clamp(22px, 3vw, 28px)',
            color: token.colorText,
          }}
        >
          {greeting(now.hour())}
          {firstName ? `, ${firstName}` : ''}.
        </h1>
        <Typography.Text style={{ color: token.colorTextSecondary, fontSize: 15 }}>
          {data && !data.all_clear
            ? 'Here’s what needs you.'
            : data
              ? 'Nothing needs you right now.'
              : 'Reading the board…'}
        </Typography.Text>
      </div>
      <div style={{ textAlign: 'right', lineHeight: 1.5 }}>
        <div className="u-label" style={{ color: token.colorTextQuaternary }}>As of</div>
        <div className="u-mono" style={{ fontSize: 13, color: token.colorTextTertiary, letterSpacing: '0.04em' }}>
          {now.format('ddd DD MMM').toUpperCase()} · {now.format('HH:mm')}
        </div>
      </div>
    </div>
  );

  return (
    <>
      <Header />

      {error && !data && (
        <Alert
          type="error"
          showIcon
          message="Couldn’t load your board"
          description={error}
          action={<Typography.Link onClick={load}>Retry</Typography.Link>}
          style={{ marginBottom: 16 }}
        />
      )}

      {!data && !error && (
        <>
          <Skeleton.Node active style={{ width: '100%', height: 108, marginBottom: 24, borderRadius: token.borderRadiusLG }}>
            <span />
          </Skeleton.Node>
          <Skeleton active paragraph={{ rows: 5 }} />
        </>
      )}

      {data && data.all_clear && (
        <div
          className="home-rise"
          style={{
            ...panelStyle,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            textAlign: 'center',
            padding: '84px 24px',
          }}
        >
          <svg
            width="44"
            height="44"
            viewBox="0 0 44 44"
            fill="none"
            aria-hidden
            style={{ color: token.colorTextTertiary }}
          >
            <circle cx="22" cy="22" r="20" stroke="currentColor" strokeWidth="1.25" opacity="0.4" />
            <path
              d="M14 22.5 L19.5 28 L30 16.5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div
            style={{
              fontFamily: "'Space Grotesk Variable', 'Space Grotesk', sans-serif",
              fontWeight: 600,
              fontSize: 28,
              color: token.colorText,
              marginTop: 18,
            }}
          >
            All clear.
          </div>
          <div className="u-label" style={{ color: token.colorTextTertiary, marginTop: 10 }}>
            Nothing overdue · nothing waiting on you
          </div>
          <Typography.Link onClick={() => navigate('/tasks')} style={{ marginTop: 22 }}>
            Browse all tasks →
          </Typography.Link>
        </div>
      )}

      {data && !data.all_clear && (
        <>
          {/* the instrument readout — hairline-gridded gauge cluster */}
          <div
            className="home-rise"
            style={{
              ...panelStyle,
              overflow: 'hidden',
              display: 'grid',
              gridTemplateColumns: `repeat(auto-fit, minmax(140px, 1fr))`,
              gap: 1,
              background: token.colorBorderSecondary,
              marginBottom: 28,
            }}
          >
            {data.stats.map((s) => (
              <Metric key={s.key} stat={s} onJump={() => scrollToSection(s.key)} />
            ))}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
            {data.sections.map((section, i) => (
              <Section key={section.key} section={section} index={i} />
            ))}
          </div>
        </>
      )}

      <TaskDrawer taskId={openTaskId} onClose={() => setSearchParams({})} onChanged={load} />
    </>
  );
}
