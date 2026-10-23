import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import type { DatesSetArg, EventClickArg, EventInput, EventSourceFuncArg } from '@fullcalendar/core';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';
import listPlugin from '@fullcalendar/list';
import FullCalendar from '@fullcalendar/react';
import timeGridPlugin from '@fullcalendar/timegrid';
import { Button, Segmented, message } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { CalendarItem, CalendarSource } from '../api/types';
import { C, hexA, SOURCE_COLOR, SOURCE_LABEL, type CalSource } from '../theme/circuitTokens';
import '../calendar.css';

/* ------------------------------------------------------------------ *
 * Calendar — FullCalendar (month / week / day / agenda) fed by
 * /api/calendar. Undated-by-hour items render in the all-day row; team
 * time blocks with a start/end time land on the hourly grid. Double-click
 * any day (month cell, week column or header) to open that day by hour.
 * ------------------------------------------------------------------ */

type View = 'dayGridMonth' | 'timeGridWeek' | 'timeGridDay' | 'listWeek';
const VIEWS: { value: View; label: string }[] = [
  { value: 'dayGridMonth', label: 'Month' },
  { value: 'timeGridWeek', label: 'Week' },
  { value: 'timeGridDay', label: 'Day' },
  { value: 'listWeek', label: 'Agenda' },
];

const SRC: Record<CalendarSource, CalSource> = { task: 'tasks', event: 'events', inventory: 'inventory', request: 'requests', team: 'teams' };
const LINK: Record<CalendarSource, string> = { task: '/tasks', event: '/events', inventory: '/inventory', request: '/requests', team: '/team' };
const ALL: CalSource[] = ['tasks', 'events', 'inventory', 'requests', 'teams'];

function toEvent(it: CalendarItem): EventInput {
  const color = it.overdue ? C.danger : SOURCE_COLOR[SRC[it.source]];
  const base = {
    id: `${it.source}-${it.id}-${it.kind ?? ''}-${it.start}`,
    title: it.title,
    backgroundColor: hexA(color, 0.18),
    borderColor: color,
    textColor: C.text,
    extendedProps: { item: it, color },
  };
  if (it.start_time && it.end_time) {
    return { ...base, start: `${it.start}T${it.start_time}`, end: `${it.start}T${it.end_time}`, allDay: false };
  }
  // FullCalendar all-day ends are exclusive
  const end = dayjs(it.end ?? it.start).add(1, 'day').format('YYYY-MM-DD');
  return { ...base, start: it.start, end, allDay: true };
}

const hhmm = (t: string) => dayjs(`2000-01-01T${t}`).format('h:mm A');

interface Peek { item: CalendarItem; color: string; x: number; y: number }

export default function CalendarPage() {
  const ref = useRef<FullCalendar>(null);
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [view, setView] = useState<View>(() => {
    try { return (localStorage.getItem('cal.view') as View) || 'dayGridMonth'; } catch { return 'dayGridMonth'; }
  });
  const [scope, setScope] = useState<'general' | 'me'>('general');
  const [on, setOn] = useState<Set<CalSource>>(new Set(ALL));
  const [peek, setPeek] = useState<Peek | null>(null);

  const calApi = () => ref.current?.getApi();

  const changeView = useCallback((v: View, date?: string) => {
    const a = calApi();
    if (!a) return;
    if (date) a.changeView(v, date); else a.changeView(v);
    setView(v);
    // the height swap that follows a month→hourly switch resets the scroller
    if (v.startsWith('timeGrid')) setTimeout(() => calApi()?.scrollToTime('08:00:00'), 0);
    try { localStorage.setItem('cal.view', v); } catch { /* storage blocked */ }
  }, []);

  // a new function identity makes FullCalendar refetch with the new filters
  const fetchEvents = useMemo(() => {
    const sources = ALL.filter((s) => on.has(s)).join(',');
    return (info: EventSourceFuncArg, ok: (e: EventInput[]) => void, fail: (e: Error) => void) => {
      if (!sources) { ok([]); return; }
      const q = new URLSearchParams({
        scope, sources,
        start: dayjs(info.start).format('YYYY-MM-DD'),
        // info.end is exclusive
        end: dayjs(info.end).subtract(1, 'day').format('YYYY-MM-DD'),
      });
      api.get<CalendarItem[]>(`/api/calendar?${q}`)
        .then((rows) => ok(rows.map(toEvent)))
        .catch((e: Error) => { message.error(e.message); fail(e); });
    };
  }, [scope, on]);

  // double-click a day anywhere (month cell, week column, column header) → that day by hour
  const onDoubleClick = (e: React.MouseEvent) => {
    const el = e.target as HTMLElement;
    if (el.closest('.fc-event')) return;
    const day = el.closest<HTMLElement>('[data-date]')?.dataset.date;
    if (day) changeView('timeGridDay', day.slice(0, 10));
  };

  useEffect(() => {
    if (!peek) return;
    const close = (e: KeyboardEvent) => { if (e.key === 'Escape') setPeek(null); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [peek]);

  const onEventClick = (arg: EventClickArg) => {
    arg.jsEvent.preventDefault();
    const { item, color } = arg.event.extendedProps as { item: CalendarItem; color: string };
    const r = arg.el.getBoundingClientRect();
    const x = Math.min(r.left, window.innerWidth - 316);
    const y = r.bottom + 220 > window.innerHeight ? Math.max(8, r.top - 210) : r.bottom + 6;
    setPeek({ item, color, x: Math.max(8, x), y });
  };

  const timed = view === 'timeGridWeek' || view === 'timeGridDay';

  return (
    <div className="mtr-cal">
      <div className="mtr-cal-bar">
        <h2 className="mtr-cal-title">{title}</h2>
        <span style={{ flex: 1 }} />
        <Button onClick={() => calApi()?.today()}>Today</Button>
        <Button icon={<LeftOutlined />} onClick={() => calApi()?.prev()} aria-label="Previous" />
        <Button icon={<RightOutlined />} onClick={() => calApi()?.next()} aria-label="Next" />
        <Segmented value={view} onChange={(v) => changeView(v as View)} options={VIEWS} />
      </div>

      <div className="mtr-cal-bar" style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {ALL.map((k) => {
            const active = on.has(k);
            return (
              <button
                key={k}
                type="button"
                className={`mtr-cal-chip${active ? ' on' : ''}`}
                aria-pressed={active}
                onClick={() => setOn((prev) => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; })}
              >
                <span style={{ background: active ? SOURCE_COLOR[k] : 'rgba(224,236,252,.25)' }} />
                {SOURCE_LABEL[k]}
              </button>
            );
          })}
        </div>
        <span style={{ flex: 1 }} />
        <Segmented value={scope} onChange={(v) => setScope(v as 'general' | 'me')}
          options={[{ value: 'general', label: 'Everyone' }, { value: 'me', label: 'Just me' }]} />
      </div>

      <div className="mtr-cal-frame" onDoubleClick={onDoubleClick}>
        <FullCalendar
          ref={ref}
          plugins={[dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin]}
          initialView={view}
          headerToolbar={false}
          events={fetchEvents}
          datesSet={(a: DatesSetArg) => setTitle(a.view.title)}
          eventClick={onEventClick}
          navLinks
          navLinkDayClick={(d) => changeView('timeGridDay', dayjs(d).format('YYYY-MM-DD'))}
          dayMaxEvents
          nowIndicator
          scrollTime="08:00:00"
          slotDuration="00:30:00"
          slotLabelFormat={{ hour: 'numeric', meridiem: 'short' }}
          eventTimeFormat={{ hour: 'numeric', minute: '2-digit', meridiem: 'short' }}
          allDayText="All day"
          height={timed ? 'max(560px, calc(100vh - 250px))' : 'auto'}
          fixedWeekCount={false}
          noEventsText="Nothing scheduled"
        />
      </div>

      {peek && (
        <>
          <div className="mtr-cal-scrim" onClick={() => setPeek(null)} />
          <div className="mtr-cal-peek" style={{ left: peek.x, top: peek.y, borderTopColor: peek.color }} role="dialog">
            <div className="kicker" style={{ color: peek.color }}>
              {SOURCE_LABEL[SRC[peek.item.source]]}{peek.item.kind ? ` · ${peek.item.kind}` : ''}
              {peek.item.overdue && <span style={{ color: C.danger }}> · overdue</span>}
            </div>
            <div className="name">{peek.item.title}</div>
            <div className="when">
              {dayjs(peek.item.start).format('ddd, MMM D')}
              {peek.item.end && ` → ${dayjs(peek.item.end).format('ddd, MMM D')}`}
              {peek.item.start_time && peek.item.end_time && ` · ${hhmm(peek.item.start_time)} – ${hhmm(peek.item.end_time)}`}
            </div>
            {peek.item.detail && <div className="detail">{peek.item.detail}</div>}
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <Button size="small" type="primary" onClick={() => navigate(LINK[peek.item.source])}>Open</Button>
              <Button size="small" onClick={() => { changeView('timeGridDay', peek.item.start); setPeek(null); }}>View day</Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
