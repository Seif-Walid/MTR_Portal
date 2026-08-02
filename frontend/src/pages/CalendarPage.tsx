import { Badge, Calendar, Card, Segmented, Space, Tag, Typography, message } from 'antd';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { CalendarItem, CalendarSource } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';

// key = the API source name (plural); item = CalendarItem.source (singular)
const SOURCE_CONFIG: {
  key: string;
  item: CalendarSource;
  label: string;
  priv: string;
  color: string;
  route: string;
}[] = [
  { key: 'tasks', item: 'task', label: 'Tasks', priv: 'tasks.use', color: 'blue', route: '/tasks' },
  { key: 'events', item: 'event', label: 'Events', priv: 'competitions.view', color: 'purple', route: '/events' },
  { key: 'inventory', item: 'inventory', label: 'Inventory', priv: 'inventory.view', color: 'gold', route: '/inventory' },
  { key: 'requests', item: 'request', label: 'Requests', priv: 'tasks.use', color: 'cyan', route: '/requests' },
];

const LS_SCOPE = 'calendar.scope';
const LS_SOURCES = 'calendar.sources';

function loadScope(): 'general' | 'me' {
  return localStorage.getItem(LS_SCOPE) === 'me' ? 'me' : 'general';
}
function loadSources(available: string[]): string[] {
  try {
    const saved = JSON.parse(localStorage.getItem(LS_SOURCES) || 'null');
    if (Array.isArray(saved)) {
      const kept = saved.filter((s) => available.includes(s));
      if (kept.length) return kept;
    }
  } catch {
    /* fall through to default */
  }
  // default: Tasks (it's a portal, tasks are the point) — but only if allowed
  return available.includes('tasks') ? ['tasks'] : available.slice(0, 1);
}

export default function CalendarPage() {
  const { me } = useAuth();
  const navigate = useNavigate();

  const available = useMemo(
    () => SOURCE_CONFIG.filter((s) => can(me, s.priv)).map((s) => s.key),
    [me],
  );
  const configByItem = useMemo(
    () => Object.fromEntries(SOURCE_CONFIG.map((s) => [s.item, s])),
    [],
  );

  const [scope, setScope] = useState<'general' | 'me'>(loadScope);
  const [sources, setSources] = useState<string[]>(() => loadSources(available));
  const [cursor, setCursor] = useState<Dayjs>(dayjs());
  const [items, setItems] = useState<CalendarItem[]>([]);

  // persist the selection — whatever you set becomes your default next visit
  useEffect(() => localStorage.setItem(LS_SCOPE, scope), [scope]);
  useEffect(() => localStorage.setItem(LS_SOURCES, JSON.stringify(sources)), [sources]);

  const load = useCallback(() => {
    if (!sources.length) {
      setItems([]);
      return;
    }
    // pad a week each side of the month so items on the grid's leading/
    // trailing days (shown from the adjacent months) are fetched too
    const start = cursor.startOf('month').subtract(7, 'day').format('YYYY-MM-DD');
    const end = cursor.endOf('month').add(7, 'day').format('YYYY-MM-DD');
    const q = new URLSearchParams({ scope, sources: sources.join(','), start, end });
    api
      .get<CalendarItem[]>(`/api/calendar?${q}`)
      .then(setItems)
      .catch((e) => message.error(e.message));
  }, [scope, sources, cursor]);

  useEffect(load, [load]);

  const toggleSource = (key: string, on: boolean) =>
    setSources((cur) => (on ? [...cur, key] : cur.filter((s) => s !== key)));

  const itemsOn = useCallback(
    (day: Dayjs) =>
      items.filter((it) => {
        const s = dayjs(it.start);
        const e = it.end ? dayjs(it.end) : s;
        return !day.isBefore(s, 'day') && !day.isAfter(e, 'day');
      }),
    [items],
  );

  const dateCell = (day: Dayjs) => {
    const dayItems = itemsOn(day);
    if (!dayItems.length) return null;
    return (
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {dayItems.map((it, i) => {
          const cfg = configByItem[it.source];
          const color = it.overdue ? 'red' : cfg?.color ?? 'default';
          const suffix =
            it.source === 'inventory' ? (it.kind === 'return' ? ' ↩' : ' ⇢') : '';
          const hover = `${cfg?.label}: ${it.title}${it.detail ? ` — ${it.detail}` : ''}`;
          return (
            <li key={`${it.source}-${it.id}-${it.kind ?? ''}-${i}`} style={{ marginBottom: 2 }}>
              <Badge
                color={color}
                text={
                  <span
                    title={hover}
                    style={{ cursor: 'pointer', fontSize: 12 }}
                    onClick={() => cfg && navigate(cfg.route)}
                  >
                    {it.title}
                    {suffix}
                  </span>
                }
              />
            </li>
          );
        })}
      </ul>
    );
  };

  return (
    <>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }} align="start" wrap>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Calendar
          </Typography.Title>
          <Typography.Text type="secondary">
            {scope === 'me'
              ? 'Only what you take part in.'
              : 'Everything you can see across the portal.'}
          </Typography.Text>
        </div>
        <Space wrap>
          <Segmented
            value={scope}
            onChange={(v) => setScope(v as 'general' | 'me')}
            options={[
              { label: 'General', value: 'general' },
              { label: 'Me', value: 'me' },
            ]}
          />
          <Space size={4} wrap>
            {SOURCE_CONFIG.filter((s) => available.includes(s.key)).map((s) => (
              <Tag.CheckableTag
                key={s.key}
                checked={sources.includes(s.key)}
                onChange={(on) => toggleSource(s.key, on)}
                style={{ borderColor: sources.includes(s.key) ? undefined : '#d9d9d9' }}
              >
                {s.label}
              </Tag.CheckableTag>
            ))}
          </Space>
        </Space>
      </Space>
      <Card size="small" styles={{ body: { padding: 8 } }}>
        <Calendar
          value={cursor}
          onSelect={(d, info) => info.source === 'date' && setCursor(d)}
          onPanelChange={(d) => setCursor(d)}
          cellRender={(current, info) =>
            info.type === 'date' ? dateCell(current) : info.originNode
          }
        />
      </Card>
    </>
  );
}
