import { useMemo, useState } from 'react';
import { Segmented } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { C, hexA, SOURCE_COLOR, SOURCE_LABEL, type CalSource } from '../theme/circuitTokens';

/* ------------------------------------------------------------------ *
 * CircuitCalendar — month/week calendar with continuous multi-day bars.
 * Multi-day events render as a single bar spanning the days they cover,
 * clipped per week-row (a bar that crosses the Sat→Sun boundary flattens
 * its cut end and shows a ‹ / › arrow, resuming on the next row).
 *
 * Drop-in for CalendarPage: map your API rows to CalEvent[] and render
 * <CircuitCalendar events={events} />. Wire the legend/scope toggles to
 * your existing source + "General/Me" state, or use the built-in ones.
 * ------------------------------------------------------------------ */

export interface CalEvent {
  id: string | number;
  title: string;
  source: CalSource;
  start: Dayjs | string;  // inclusive
  end: Dayjs | string;    // inclusive (== start for single-day)
  overdue?: boolean;
}

interface Seg {
  ev: CalEvent;
  startCol: number;
  span: number;
  contLeft: boolean;
  contRight: boolean;
  multi: boolean;
}
interface WeekVM {
  key: number;
  days: { date: Dayjs; inMonth: boolean; today: boolean }[];
  lanes: Seg[][];
  overflow: number[];
}

export default function CircuitCalendar({
  events,
  monthAnchor = dayjs(),
  initialView = 'month',
}: {
  events: CalEvent[];
  monthAnchor?: Dayjs;
  initialView?: 'month' | 'week';
}) {
  const [view, setView] = useState<'month' | 'week'>(initialView);
  const [scope, setScope] = useState<'general' | 'me'>('general');
  const [off, setOff] = useState<Set<CalSource>>(new Set());

  const today = dayjs();
  const monthStart = monthAnchor.startOf('month');
  const gridStart = monthStart.startOf('week'); // Sunday before the 1st

  const visible = useMemo(
    () =>
      events.filter(
        (e) =>
          !off.has(e.source) &&
          !(scope === 'me' && e.source !== 'tasks' && e.source !== 'requests'),
      ),
    [events, off, scope],
  );

  const weeks = useMemo<WeekVM[]>(() => {
    const monthView = view === 'month';
    const cap = monthView ? 3 : 8;
    const weekOfToday = today.startOf('week').diff(gridStart, 'week');
    const range = monthView ? [0, 1, 2, 3, 4, 5] : [weekOfToday];

    return range.map((wk) => {
      const weekStart = gridStart.add(wk, 'week');
      const days = Array.from({ length: 7 }, (_, dd) => {
        const date = weekStart.add(dd, 'day');
        return {
          date,
          inMonth: date.month() === monthStart.month(),
          today: date.isSame(today, 'day'),
        };
      });

      // clip each event to this week -> segment
      const segs: Seg[] = [];
      for (const ev of visible) {
        const s = dayjs(ev.start);
        const e = dayjs(ev.end);
        const cols: number[] = [];
        days.forEach((d, i) => {
          if (!d.date.isBefore(s, 'day') && !d.date.isAfter(e, 'day')) cols.push(i);
        });
        if (!cols.length) continue;
        const startCol = cols[0];
        const endCol = cols[cols.length - 1];
        segs.push({
          ev,
          startCol,
          span: endCol - startCol + 1,
          contLeft: s.isBefore(days[startCol].date, 'day'),
          contRight: e.isAfter(days[endCol].date, 'day'),
          multi: !e.isSame(s, 'day'),
        });
      }

      // greedy lane packing: longest first, no column overlap per lane
      segs.sort((a, b) => b.span - a.span || a.startCol - b.startCol);
      const lanes: Seg[][] = [];
      for (const seg of segs) {
        const lane = lanes.find((L) =>
          L.every((x) => seg.startCol > x.startCol + x.span - 1 || seg.startCol + seg.span - 1 < x.startCol),
        );
        if (lane) lane.push(seg);
        else lanes.push([seg]);
      }
      const shown = lanes.slice(0, cap);
      const overflow = new Array(7).fill(0);
      lanes.slice(cap).forEach((L) =>
        L.forEach((seg) => {
          for (let c = seg.startCol; c < seg.startCol + seg.span; c++) overflow[c]++;
        }),
      );
      return { key: wk, days, lanes: shown, overflow };
    });
  }, [view, visible, gridStart, monthStart, today]);

  const monthView = view === 'month';
  const cellH = monthView ? 116 : 460;
  const col = { display: 'grid', gridTemplateColumns: 'repeat(7,1fr)' } as const;

  return (
    <div>
      {/* controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginBottom: 14 }}>
        <span style={{ fontFamily: C.display, fontWeight: 600, fontSize: 16, color: C.text }}>
          {monthStart.format('MMMM YYYY')}
        </span>
        <Segmented value={view} onChange={(v) => setView(v as 'month' | 'week')} options={['month', 'week'].map((v) => ({ value: v, label: v[0].toUpperCase() + v.slice(1) }))} />
        <span style={{ flex: 1 }} />
        <Segmented value={scope} onChange={(v) => setScope(v as 'general' | 'me')} options={[{ value: 'general', label: 'General' }, { value: 'me', label: 'Me' }]} />
      </div>

      {/* legend */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
        {(Object.keys(SOURCE_LABEL) as CalSource[]).map((k) => {
          const on = !off.has(k);
          return (
            <div
              key={k}
              onClick={() => setOff((prev) => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; })}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 7, padding: '5px 11px', borderRadius: 7,
                fontSize: 12, cursor: 'pointer', color: on ? C.text : C.textFaint,
                border: on ? '1px solid rgba(120,170,230,.25)' : '1px dashed rgba(120,170,230,.16)',
                background: on ? 'rgba(255,255,255,.03)' : 'transparent',
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: 2, background: on ? SOURCE_COLOR[k] : 'rgba(224,236,252,.25)' }} />
              {SOURCE_LABEL[k]}
            </div>
          );
        })}
      </div>

      {/* grid */}
      <div style={{ border: `1px solid ${C.hairline}`, borderRadius: 14, overflow: 'hidden', background: C.bgPanel }}>
        {monthView && (
          <div style={{ ...col, background: 'rgba(8,11,17,.4)' }}>
            {['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'].map((d) => (
              <div key={d} style={{ padding: '9px 12px', fontFamily: C.mono, fontSize: 9, letterSpacing: '.16em', color: C.textFaint }}>{d}</div>
            ))}
          </div>
        )}

        {weeks.map((w) => (
          <div key={w.key} style={{ position: 'relative', minHeight: cellH }}>
            {/* bg tint layer */}
            <div style={{ position: 'absolute', inset: 0, ...col }}>
              {w.days.map((d, i) => (
                <div key={i} style={{
                  borderTop: `1px solid ${C.hairlineRow}`,
                  borderLeft: i ? `1px solid ${C.hairlineRow}` : 'none',
                  background: d.today ? 'rgba(92,198,255,.06)' : d.inMonth ? 'transparent' : 'rgba(0,0,0,.18)',
                }} />
              ))}
            </div>
            {/* content */}
            <div style={{ position: 'relative' }}>
              <div style={col}>
                {w.days.map((d, i) => {
                  const label = monthView ? `${d.date.date()}` : `${d.date.format('ddd').toUpperCase()} ${d.date.date()}`;
                  return (
                    <div key={i} style={{ padding: '7px 9px', display: 'flex', justifyContent: monthView ? 'flex-end' : 'flex-start' }}>
                      {d.today ? (
                        <span style={{ fontFamily: C.mono, fontSize: 11.5, fontWeight: 600, color: '#06080c', background: C.accent, minWidth: 22, height: 22, padding: '0 7px', borderRadius: 11, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 12px rgba(92,198,255,.7)' }}>{label}</span>
                      ) : (
                        <span style={{ fontFamily: C.mono, fontSize: 11.5, color: d.inMonth ? 'rgba(224,236,252,.8)' : 'rgba(224,236,252,.28)' }}>{label}</span>
                      )}
                    </div>
                  );
                })}
              </div>
              <div style={{ marginTop: 2 }}>
                {w.lanes.map((lane, li) => (
                  <div key={li} style={{ ...col, marginBottom: 3 }}>
                    {lane.map((seg) => <Bar key={`${seg.ev.id}-${seg.startCol}`} seg={seg} monthView={monthView} />)}
                  </div>
                ))}
                <div style={col}>
                  {w.overflow.map((n, i) => (
                    <div key={i} style={{ padding: '0 11px' }}>
                      {n > 0 && <span style={{ fontFamily: C.mono, fontSize: 9.5, color: C.textFaint }}>+{n} more</span>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Bar({ seg, monthView }: { seg: Seg; monthView: boolean }) {
  const color = seg.ev.overdue ? C.danger : SOURCE_COLOR[seg.ev.source];
  return (
    <div style={{
      gridColumn: `${seg.startCol + 1} / span ${seg.span}`,
      display: 'flex', alignItems: 'center', gap: 5, minWidth: 0,
      height: monthView ? 22 : 27, margin: '0 3px', padding: '0 8px',
      background: hexA(color, .15), color: C.text, fontSize: monthView ? 11 : 12.5,
      borderRadius: 5,
      borderTopLeftRadius: seg.contLeft ? 0 : 5, borderBottomLeftRadius: seg.contLeft ? 0 : 5,
      borderTopRightRadius: seg.contRight ? 0 : 5, borderBottomRightRadius: seg.contRight ? 0 : 5,
      border: `1px solid ${hexA(color, .32)}`,
      borderLeft: `3px solid ${seg.contLeft ? hexA(color, .32) : color}`,
      boxShadow: seg.multi ? `0 0 10px ${hexA(color, .22)}` : 'none',
      whiteSpace: 'nowrap', overflow: 'hidden',
    }}>
      {seg.contLeft && <span style={{ color, fontWeight: 700, flexShrink: 0 }}>‹</span>}
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{seg.ev.title}</span>
      {seg.contRight && <span style={{ color, fontWeight: 700, flexShrink: 0, marginLeft: 'auto' }}>›</span>}
    </div>
  );
}
