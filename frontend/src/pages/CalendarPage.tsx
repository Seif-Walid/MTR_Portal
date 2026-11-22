import { DownOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons';
import type { DatesSetArg, EventApi, EventClickArg, EventInput, EventSourceFuncArg } from '@fullcalendar/core';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';
import listPlugin from '@fullcalendar/list';
import FullCalendar from '@fullcalendar/react';
import timeGridPlugin from '@fullcalendar/timegrid';
import { Button, Dropdown, message } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { CalendarItem, CalendarSource } from '../api/types';
import { SOURCE_LABEL, type CalSource } from '../theme/circuitTokens';
import '../calendar.css';

/* ------------------------------------------------------------------ *
 * Calendar — FullCalendar (month / week / day / agenda) fed by
 * /api/calendar, styled after Google Calendar's dark theme: solid
 * colour chips per source, a filled circle on today, a red "now" line.
 * Every item stays on the grid, multi-day events included. A rail
 * beside it holds the source checkboxes and what's coming up.
 * Pending requests render outlined (like an unanswered invite), overdue
 * items turn red, approved tasks are struck through.
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
const ISO = 'YYYY-MM-DD';

const spanDays = (it: CalendarItem) => (it.end ? dayjs(it.end).diff(dayjs(it.start), 'day') + 1 : 1);
const isDone = (it: CalendarItem) => it.source === 'task' && it.kind === 'approved';

function marks(it: CalendarItem): string[] {
  const c = ['mk', `mk-${it.source}`];
  if (it.overdue) c.push('mk-overdue');
  if (isDone(it)) c.push('mk-done');
  return c;
}

function toEvent(it: CalendarItem): EventInput {
  const base = {
    id: `${it.source}-${it.id}-${it.kind ?? ''}-${it.start}`,
    title: it.title,
    classNames: marks(it),
    // colours come from the mark classes; keep FullCalendar's inline ones out
    backgroundColor: 'transparent',
    borderColor: 'transparent',
    textColor: 'inherit',
    extendedProps: { item: it, order: it.overdue ? 0 : 1 },
  };
  if (it.start_time && it.end_time) {
    return { ...base, start: `${it.start}T${it.start_time}`, end: `${it.start}T${it.end_time}`, allDay: false };
  }
  // FullCalendar all-day ends are exclusive
  const end = dayjs(it.end ?? it.start).add(1, 'day').format(ISO);
  return { ...base, start: it.start, end, allDay: true };
}

const hhmm = (t: string) => dayjs(`2000-01-01T${t}`).format('h:mm A');
const KIND_WORDS: Record<string, string> = {
  todo: 'To do', in_progress: 'In progress', submitted: 'Submitted', approved: 'Approved', rejected: 'Sent back',
  needed: 'Needed', return: 'Due back', pending: 'Pending', accepted: 'Accepted', declined: 'Declined',
};
const kindWords = (k: string | null) => (k ? KIND_WORDS[k] ?? k.replace(/_/g, ' ') : '');

function dayName(d: Dayjs, today: Dayjs) {
  const diff = d.startOf('day').diff(today, 'day');
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff > 1 && diff < 7) return d.format('dddd');
  return d.format('ddd, MMM D');
}

interface Peek { item: CalendarItem; x: number; y: number }

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
  const [visible, setVisible] = useState<CalendarItem[]>([]);
  const [ahead, setAhead] = useState<CalendarItem[] | null>(null);
  const [aheadErr, setAheadErr] = useState(false);

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

  const sources = useMemo(() => ALL.filter((s) => on.has(s)).join(','), [on]);

  // a new function identity makes FullCalendar refetch with the new filters
  const fetchEvents = useMemo(() => (info: EventSourceFuncArg, ok: (e: EventInput[]) => void, fail: (e: Error) => void) => {
    if (!sources) { ok([]); return; }
    const q = new URLSearchParams({
      scope, sources,
      start: dayjs(info.start).format(ISO),
      // info.end is exclusive
      end: dayjs(info.end).subtract(1, 'day').format(ISO),
    });
    api.get<CalendarItem[]>(`/api/calendar?${q}`)
      .then((rows) => ok(rows.map(toEvent)))
      .catch((e: Error) => { message.error(e.message); fail(e); });
  }, [scope, sources]);

  // the rail's "what's next": overdue from the last 60 days + the next 14
  useEffect(() => {
    if (!sources) { setAhead([]); return; }
    const q = new URLSearchParams({
      scope, sources,
      start: dayjs().subtract(60, 'day').format(ISO),
      end: dayjs().add(14, 'day').format(ISO),
    });
    let live = true;
    setAheadErr(false);
    api.get<CalendarItem[]>(`/api/calendar?${q}`)
      .then((rows) => { if (live) setAhead(rows); })
      .catch(() => { if (live) { setAhead([]); setAheadErr(true); } });
    return () => { live = false; };
  }, [scope, sources]);

  const today = dayjs().startOf('day');
  const rail = useMemo(() => {
    const rows = ahead ?? [];
    const overdue = rows.filter((r) => r.overdue).sort((a, b) => a.start.localeCompare(b.start));
    const next = rows
      .filter((r) => !r.overdue && !isDone(r))
      // things that start in the window; long events already under way aren't "coming up"
      .filter((r) => !dayjs(r.start).isBefore(today) && !dayjs(r.start).isAfter(today.add(14, 'day')))
      .sort((a, b) => (a.start.localeCompare(b.start) || (a.start_time ?? '').localeCompare(b.start_time ?? '')));
    const groups: { day: Dayjs; items: CalendarItem[] }[] = [];
    for (const r of next) {
      const d = dayjs(r.start);
      const g = groups[groups.length - 1];
      if (g && g.day.isSame(d, 'day')) g.items.push(r); else groups.push({ day: d, items: [r] });
    }
    // "due" means a deadline: tasks, requests, checkouts — not events or team sessions
    const dueCount = next.filter((r) => r.source !== 'event' && r.source !== 'team').length;
    return { overdue, groups, dueCount };
  }, [ahead, today]);

  const counts = useMemo(() => {
    const c: Record<CalSource, number> = { tasks: 0, events: 0, inventory: 0, requests: 0, teams: 0 };
    for (const it of visible) c[SRC[it.source]] += 1;
    return c;
  }, [visible]);

  const onEventsSet = (evs: EventApi[]) => {
    setVisible(evs.map((e) => (e.extendedProps as { item: CalendarItem }).item));
  };

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

  const openPeek = (item: CalendarItem, r: DOMRect) => {
    const x = Math.min(r.left, window.innerWidth - 336);
    const y = r.bottom + 240 > window.innerHeight ? Math.max(8, r.top - 230) : r.bottom + 6;
    setPeek({ item, x: Math.max(8, x), y });
  };

  const onEventClick = (arg: EventClickArg) => {
    arg.jsEvent.preventDefault();
    openPeek((arg.event.extendedProps as { item: CalendarItem }).item, arg.el.getBoundingClientRect());
  };

  const toggle = (k: CalSource) => setOn((prev) => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; });

  const loadingRail = ahead === null;

  const finding = loadingRail ? ' '
    : aheadErr ? 'Couldn’t load what’s coming up. The grid still shows this range.'
    : [
        rail.overdue.length ? `${rail.overdue.length} overdue` : 'Nothing overdue',
        rail.dueCount ? `${rail.dueCount} due in the next 14 days` : 'nothing due in the next 14 days',
      ].join(' · ');

  const RailRow = ({ it, showDate }: { it: CalendarItem; showDate?: boolean }) => (
    <li>
      <button type="button" className={`cal-row ${marks(it).join(' ')}`}
        onClick={(e) => openPeek(it, e.currentTarget.getBoundingClientRect())}>
        <i className="cal-swatch" aria-hidden />
        <span className="cal-row-title">{it.title}</span>
        <span className="cal-row-meta">
          {showDate ? dayjs(it.start).format('MMM D')
            : it.start_time ? hhmm(it.start_time)
            : it.end ? `→ ${dayjs(it.end).format('MMM D')}`
            : kindWords(it.kind)}
        </span>
      </button>
    </li>
  );

  return (
    <div className="mtr-cal">
      {/* ---- title row ---- */}
      <div className="cal-head">
        <div className="cal-head-text">
          <h2 className="cal-title">{title}</h2>
          <p className={`cal-finding${rail.overdue.length ? ' alert' : ''}`} aria-live="polite">{finding}</p>
        </div>
        <div className="cal-nav">
          <Button onClick={() => calApi()?.today()}>Today</Button>
          <Button icon={<LeftOutlined />} onClick={() => calApi()?.prev()} aria-label="Previous" />
          <Button icon={<RightOutlined />} onClick={() => calApi()?.next()} aria-label="Next" />
        </div>
        <Dropdown trigger={['click']} menu={{
          items: VIEWS.map((v) => ({ key: v.value, label: v.label })),
          selectable: true, selectedKeys: [view],
          onClick: ({ key }) => changeView(key as View),
        }}>
          <button type="button" className="cal-viewpick" aria-label="Calendar view">
            {VIEWS.find((v) => v.value === view)?.label} <DownOutlined />
          </button>
        </Dropdown>
      </div>

      <div className="cal-body">
        <div className="cal-main">
        {/* ---- grid ---- */}
        <div className={`cal-frame view-${view}`} onDoubleClick={onDoubleClick}>
          <FullCalendar
            ref={ref}
            plugins={[dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin]}
            initialView={view}
            headerToolbar={false}
            events={fetchEvents}
            eventsSet={onEventsSet}
            eventOrder="-duration,order,start,title"
            datesSet={(a: DatesSetArg) => {
              setTitle(a.view.title);
            }}
            eventClick={onEventClick}
            navLinks
            navLinkDayClick={(d) => changeView('timeGridDay', dayjs(d).format(ISO))}
            // month: up to 5 rows per day before "+N more"; timed items are
            // full colour chips too, so a team session reads as a team session
            dayMaxEvents={5}
            eventDisplay="block"
            nowIndicator
            scrollTime="08:00:00"
            slotDuration="00:30:00"
            slotLabelFormat={{ hour: 'numeric', meridiem: 'short' }}
            eventTimeFormat={{ hour: 'numeric', minute: '2-digit', omitZeroMinute: true, meridiem: 'narrow' }}
            dayHeaderContent={(a) => (a.view.type.startsWith('timeGrid') ? (
              <span className="gc-dh">
                <span className="gc-dh-dow">{dayjs(a.date).format('ddd')}</span>
                <span className={`gc-dh-num${a.isToday ? ' today' : ''}`}>{a.date.getDate()}</span>
              </span>
            ) : <span className="gc-dh-dow">{dayjs(a.date).format('ddd')}</span>)}
            dayCellContent={(a) => (a.view.type === 'dayGridMonth'
              ? <span className={`gc-num${a.isToday ? ' today' : ''}`}>{a.date.getDate() === 1 ? dayjs(a.date).format('MMM D') : a.date.getDate()}</span>
              : a.dayNumberText)}
            allDayText="All day"
            height={view === 'listWeek' || view === 'dayGridMonth' ? 'auto' : 'max(620px, calc(100vh - 170px))'}
            fixedWeekCount={false}
            noEventsText="Nothing scheduled this week"
          />
        </div>
        </div>

        {/* ---- rail ---- */}
        <aside className="cal-rail" aria-label="Schedule">
          <section className="cal-block">
            <h2 className="cal-block-title">Show</h2>
            <div className="cal-scope" role="group" aria-label="Whose schedule">
              {([['general', 'Everyone'], ['me', 'Just me']] as const).map(([v, l]) => (
                <button key={v} type="button" className={scope === v ? 'on' : ''} aria-pressed={scope === v} onClick={() => setScope(v)}>{l}</button>
              ))}
            </div>
            <ul className="cal-key">
              {ALL.map((k) => {
                const active = on.has(k);
                const src = (Object.keys(SRC) as CalendarSource[]).find((s) => SRC[s] === k)!;
                return (
                  <li key={k}>
                    <button type="button" className={`cal-key-row mk mk-${src}${active ? '' : ' off'}`} aria-pressed={active} onClick={() => toggle(k)}>
                      <i className="cal-swatch" aria-hidden />
                      <span>{SOURCE_LABEL[k]}</span>
                      <span className="cal-count">{active ? counts[k] : '—'}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <p className="cal-key-note">Counts are for the dates on screen.</p>
          </section>

          <section className="cal-block cal-next">
            <h2 className="cal-block-title">Coming up</h2>
            {loadingRail ? (
              <div className="cal-skel" aria-busy="true"><span /><span /><span /></div>
            ) : aheadErr ? (
              <p className="cal-empty">Couldn’t load the next two weeks. Try again in a moment.</p>
            ) : (
              <>
                {rail.overdue.length > 0 && (
                  <div className="cal-group">
                    <h3 className="cal-group-day alert">Overdue</h3>
                    <ul>{rail.overdue.slice(0, 5).map((it) => <RailRow key={`o${it.source}${it.id}${it.kind}`} it={it} showDate />)}</ul>
                  </div>
                )}
                {rail.groups.slice(0, 6).map((g) => (
                  <div className="cal-group" key={g.day.format(ISO)}>
                    <h3 className="cal-group-day">{dayName(g.day, today)}</h3>
                    <ul>{g.items.map((it) => <RailRow key={`${it.source}${it.id}${it.kind}${it.start}`} it={it} />)}</ul>
                  </div>
                ))}
                {!rail.groups.length && !rail.overdue.length && (
                  <p className="cal-empty">Nothing due in the next two weeks{scope === 'me' ? ' for you' : ''}.</p>
                )}
                {rail.groups.length > 6 && (
                  <button type="button" className="cal-more" onClick={() => changeView('listWeek')}>Open the agenda</button>
                )}
              </>
            )}
          </section>
        </aside>
      </div>

      {peek && (
        <>
          <div className="mtr-cal-scrim" onClick={() => setPeek(null)} />
          <div className={`mtr-cal-peek ${marks(peek.item).join(' ')}`} style={{ left: peek.x, top: peek.y }} role="dialog" aria-label={peek.item.title}>
            <div className="peek-src">
              <i className="cal-swatch" aria-hidden />
              {SOURCE_LABEL[SRC[peek.item.source]]}
              {peek.item.kind && <span className="peek-kind">{peek.item.source === 'event' ? peek.item.kind : kindWords(peek.item.kind)}</span>}
              {peek.item.overdue && <span className="peek-overdue">Overdue</span>}
            </div>
            <div className="name">{peek.item.title}</div>
            <div className="when">
              {dayjs(peek.item.start).format('ddd, MMM D')}
              {peek.item.end && ` → ${dayjs(peek.item.end).format('ddd, MMM D')}`}
              {peek.item.start_time && peek.item.end_time && ` · ${hhmm(peek.item.start_time)} – ${hhmm(peek.item.end_time)}`}
              {peek.item.end && <span className="peek-span"> · {spanDays(peek.item)} days</span>}
            </div>
            {peek.item.detail && <div className="detail">{peek.item.detail}</div>}
            <div className="peek-actions">
              <Button size="small" type="primary" onClick={() => navigate(LINK[peek.item.source])}>Open in {SOURCE_LABEL[SRC[peek.item.source]]}</Button>
              <Button size="small" onClick={() => { changeView('timeGridDay', peek.item.start); setPeek(null); }}>View day</Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
