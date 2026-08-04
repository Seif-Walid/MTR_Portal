import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { Button, message } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client';
import type { CalendarItem } from '../api/types';
import CircuitCalendar, { type CalEvent } from '../components/CircuitCalendar';
import type { CalSource } from '../theme/circuitTokens';

const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";
const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";

const SRC: Record<CalendarItem['source'], CalSource> = { task: 'tasks', event: 'events', inventory: 'inventory', request: 'requests' };
const ALL_SOURCES = 'tasks,events,inventory,requests';

export default function CalendarPage() {
  const [cursor, setCursor] = useState<Dayjs>(dayjs());
  const [items, setItems] = useState<CalendarItem[]>([]);

  const load = useCallback(() => {
    const start = cursor.startOf('month').subtract(7, 'day').format('YYYY-MM-DD');
    const end = cursor.endOf('month').add(7, 'day').format('YYYY-MM-DD');
    const q = new URLSearchParams({ scope: 'general', sources: ALL_SOURCES, start, end });
    api.get<CalendarItem[]>(`/api/calendar?${q}`).then(setItems).catch((e) => message.error(e.message));
  }, [cursor]);

  useEffect(load, [load]);

  const events = useMemo<CalEvent[]>(
    () => items.map((it) => ({
      id: `${it.source}-${it.id}-${it.kind ?? ''}`,
      title: it.title,
      source: SRC[it.source],
      start: it.start,
      end: it.end ?? it.start,
      overdue: it.overdue,
    })),
    [items],
  );

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16, flexWrap: 'wrap' }}>
        <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>Calendar</h2>
        <span style={{ fontFamily: MONO, fontSize: 13, letterSpacing: '.08em', color: '#5cc6ff' }}>{cursor.format('MMMM YYYY').toUpperCase()}</span>
        <span style={{ flex: 1 }} />
        <Button icon={<LeftOutlined />} onClick={() => setCursor((c) => c.subtract(1, 'month'))} aria-label="Previous month" />
        <Button onClick={() => setCursor(dayjs())}>Today</Button>
        <Button icon={<RightOutlined />} onClick={() => setCursor((c) => c.add(1, 'month'))} aria-label="Next month" />
      </div>
      <CircuitCalendar events={events} monthAnchor={cursor} />
    </>
  );
}
