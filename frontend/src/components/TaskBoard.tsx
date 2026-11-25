/* Kanban board for tasks: one column per status. Cards can be dragged to
   another column or up and down its own; it lands where it was dropped and
   that order is saved per task (board_rank). Only moves the workflow allows
   light up as drop targets, and the server still has the final say (a
   refused move springs back). */
import { CalendarOutlined, HolderOutlined, LockOutlined } from '@ant-design/icons';
import { message } from 'antd';
import dayjs from 'dayjs';
import { animate, LayoutGroup, motion, useMotionValue } from 'motion/react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Task, TaskStatus } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { PriorityTag, STATUS_META } from './tags';
import './taskboard.css';

const COLUMNS: TaskStatus[] = ['todo', 'in_progress', 'revision_requested', 'submitted', 'approved'];

// mirrors backend TRANSITIONS: who may make each move
const MOVES: Record<string, 'assignee' | 'reviewer'> = {
  'todo>in_progress': 'assignee',
  'in_progress>todo': 'assignee',
  'in_progress>submitted': 'assignee',
  'revision_requested>in_progress': 'assignee',
  'submitted>approved': 'reviewer',
  'submitted>revision_requested': 'reviewer',
};

const SPRING = { type: 'spring', stiffness: 420, damping: 34 } as const;
// the landing glide: a touch softer so the card visibly settles into its slot
const LAND = { type: 'spring', stiffness: 380, damping: 32, mass: 0.8 } as const;
const LIFT = { scale: 1.04, rotate: 2 };

function initials(name: string) {
  return name.split(' ').map((p) => p[0]).slice(0, 2).join('');
}

type Rect = { cx: number; cy: number };
// where a dragged card would land: column, slot in it, insertion-line y (px from the column body top)
type Target = { col: TaskStatus; index: number; line: number };
const centre = (el: Element): Rect => {
  const r = el.getBoundingClientRect();
  return { cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
};

/* One card. A card that changes column is a fresh element in the new column,
   so it flies itself in from wherever the old one was last seen (a manual
   FLIP): `flyFrom` holds that spot, keyed by task id. */
function BoardCard({
  t, status, flyFrom, onOpen, onDragState, onHover, onDrop, register,
}: {
  t: Task;
  status: TaskStatus;
  flyFrom: React.MutableRefObject<Map<number, Rect & { lifted: boolean }>>;
  onOpen: (id: number) => void;
  onDragState: (t: Task | null) => void;
  onHover: (x: number, y: number) => void;
  onDrop: (t: Task, x: number, y: number, el: HTMLElement) => boolean;
  register: (el: HTMLElement | null) => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const scale = useMotionValue(1);
  const rotate = useMotionValue(0);
  const [dragging, setDragging] = useState(false);
  const didDrag = useRef(false);

  useLayoutEffect(() => {
    const from = flyFrom.current.get(t.id);
    const el = ref.current;
    if (!from || !el) return;
    flyFrom.current.delete(t.id);
    const to = centre(el);
    x.set(from.cx - to.cx);
    y.set(from.cy - to.cy);
    if (from.lifted) { scale.set(LIFT.scale); rotate.set(LIFT.rotate); }
    // no cleanup on purpose: StrictMode's mount→unmount→mount would stop the
    // glide and the second run no longer finds `from`, stranding the card
    animate(x, 0, LAND);
    animate(y, 0, LAND);
    animate(scale, 1, LAND);
    animate(rotate, 0, LAND);
    // only on mount: a card that switched column is a new element
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const settle = () => {
    animate(x, 0, SPRING);
    animate(y, 0, SPRING);
    animate(scale, 1, SPRING);
    animate(rotate, 0, SPRING);
  };

  const due = t.due_date ? dayjs(t.due_date) : null;
  const late = !!due && due.isBefore(dayjs(), 'day') && status !== 'approved';
  return (
    <motion.div
      ref={(el: HTMLDivElement | null) => { ref.current = el; register(el); }}
      layout="position"
      transition={SPRING}
      style={{ x, y, scale, rotate }}
      className={`tb-card${dragging ? ' is-dragging' : ''}`}
      drag
      dragMomentum={false}
      onDragStart={() => {
        didDrag.current = true;
        setDragging(true);
        onDragState(t);
        animate(scale, LIFT.scale, SPRING);
        animate(rotate, LIFT.rotate, SPRING);
      }}
      onDrag={(_, info) => onHover(info.point.x - window.scrollX, info.point.y - window.scrollY)}
      onDragEnd={(_, info) => {
        setDragging(false);
        onDragState(null);
        const el = ref.current;
        const landed = !!el && onDrop(t, info.point.x - window.scrollX, info.point.y - window.scrollY, el);
        if (!landed) settle();
        // let the click that ends a drag fall through without opening the card
        window.setTimeout(() => { didDrag.current = false; }, 0);
      }}
      onClick={() => { if (!didDrag.current) onOpen(t.id); }}
      role="button"
      tabIndex={0}
      aria-label={`${t.title}, ${STATUS_META[status].label}${late ? ', overdue' : ''}`}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(t.id); }
      }}
    >
      <div className="tb-card__top">
        <span className="tb-card__ctx">{t.event_team_name ?? t.assigner.full_name}</span>
        <PriorityTag priority={t.priority} />
        <HolderOutlined className="tb-card__grip" aria-hidden />
      </div>
      <div className="tb-card__title">{t.title}</div>
      <div className="tb-card__foot">
        {due && (
          <span className={`tb-card__due${late ? ' is-late' : ''}`}>
            <CalendarOutlined aria-hidden /> {due.format('D MMM')}
          </span>
        )}
        {t.is_blocked && <span className="tb-card__blocked"><LockOutlined aria-hidden /> Blocked</span>}
        <span className="tb-card__avatar" title={t.assignee.full_name} aria-hidden>{initials(t.assignee.full_name)}</span>
      </div>
    </motion.div>
  );
}

export default function TaskBoard({
  tasks,
  onOpen,
  onChanged,
}: {
  tasks: Task[];
  onOpen: (id: number) => void;
  onChanged: () => void;
}) {
  const { me } = useAuth();
  // Optimistic overrides (column and place in it); each one stays until the
  // refreshed task list agrees, so a card never bounces back mid-reload.
  const [moved, setMoved] = useState<Record<number, TaskStatus>>({});
  const [ranks, setRanks] = useState<Record<number, number>>({});
  // bumping a card's nonce remounts it, which is what makes it fly in
  const [nonce, setNonce] = useState<Record<number, number>>({});
  const [dragging, setDragging] = useState<Task | null>(null);
  const [over, setOver] = useState<Target | null>(null);
  const colRefs = useRef<Partial<Record<TaskStatus, HTMLDivElement | null>>>({});
  const bodyRefs = useRef<Partial<Record<TaskStatus, HTMLDivElement | null>>>({});
  const flyFrom = useRef(new Map<number, Rect & { lifted: boolean }>());
  const cardEls = useRef(new Map<number, HTMLElement>());

  const statusOf = (t: Task) => moved[t.id] ?? t.status;
  const rankOf = (t: Task) => ranks[t.id] ?? t.board_rank;

  useEffect(() => {
    const byId = new Map(tasks.map((t) => [t.id, t]));
    setMoved((m) => {
      const keep = Object.entries(m).filter(([id, s]) => {
        const t = byId.get(Number(id));
        return t && t.status !== s;
      });
      return keep.length === Object.keys(m).length ? m : Object.fromEntries(keep);
    });
    setRanks((m) => {
      const keep = Object.entries(m).filter(([id, r]) => {
        const t = byId.get(Number(id));
        return t && t.board_rank !== r;
      });
      return keep.length === Object.keys(m).length ? m : Object.fromEntries(keep);
    });
  }, [tasks]);

  // A column top to bottom: cards nobody has arranged yet sit on top (newest
  // first, as the server sends them), then the arranged ones in their order.
  const columnOf = (s: TaskStatus) => {
    const col = tasks.filter((t) => statusOf(t) === s);
    return col
      .map((t, i) => ({ t, i, r: rankOf(t) }))
      .sort((a, b) => {
        if (a.r == null || b.r == null) return a.r == null && b.r == null ? a.i - b.i : a.r == null ? -1 : 1;
        return a.r - b.r || a.i - b.i;
      })
      .map((x) => x.t);
  };

  // The UI only offers moves this person can plausibly make; the server
  // checks the reviewer chain properly.
  const canMove = (t: Task, to: TaskStatus) => {
    const who = MOVES[`${statusOf(t)}>${to}`];
    if (!who || !me) return false;
    if (who === 'assignee') return t.assignee.id === me.id;
    return t.assignee.id !== me.id;
  };
  const canDropIn = (t: Task, s: TaskStatus) => statusOf(t) === s || canMove(t, s);

  // Which column the pointer is over, and where in it the card would land:
  // its slot among the other cards plus the y of the insertion line.
  const targetAt = (t: Task, x: number, y: number): Target | null => {
    for (const s of COLUMNS) {
      const r = colRefs.current[s]?.getBoundingClientRect();
      if (!r || x < r.left || x > r.right || y < r.top || y > r.bottom) continue;
      const body = bodyRefs.current[s]?.getBoundingClientRect();
      const others = columnOf(s)
        .filter((o) => o.id !== t.id)
        .map((o) => cardEls.current.get(o.id)?.getBoundingClientRect())
        .filter((b): b is DOMRect => !!b);
      let index = others.findIndex((b) => y < b.top + b.height / 2);
      if (index === -1) index = others.length;
      const top = body?.top ?? r.top;
      const before = others[index - 1];
      const after = others[index];
      const lineY = before && after ? (before.bottom + after.top) / 2
        : after ? after.top - 5 : before ? before.bottom + 5 : top + 8;
      return { col: s, index, line: lineY - top };
    }
    return null;
  };

  const flyBack = (t: Task) => {
    const el = cardEls.current.get(t.id);
    if (el) flyFrom.current.set(t.id, { ...centre(el), lifted: false });
    setNonce((n) => ({ ...n, [t.id]: (n[t.id] ?? 0) + 1 }));
  };

  const forget = <V,>(set: React.Dispatch<React.SetStateAction<Record<number, V>>>, ids: number[]) =>
    set((m) => {
      const n = { ...m };
      ids.forEach((id) => delete n[id]);
      return n;
    });

  const place = async (t: Task, to: TaskStatus, ids: number[]) => {
    const changesColumn = to !== statusOf(t);
    if (changesColumn) setMoved((m) => ({ ...m, [t.id]: to }));
    setRanks((m) => ({ ...m, ...Object.fromEntries(ids.map((id, i) => [id, i])) }));
    try {
      if (changesColumn) {
        await api.patch<Task>(`/api/tasks/${t.id}/status`, { status: to });
        message.success(`Moved to ${STATUS_META[to].label.toLowerCase()}`);
      }
      await api.put('/api/tasks/board-order', { ids });
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Couldn’t move the task');
      // refused: fly the card back from where it sits now
      flyBack(t);
      forget(setMoved, [t.id]);
      forget(setRanks, ids);
      onChanged();
    }
  };

  const drop = (t: Task, x: number, y: number, el: HTMLElement) => {
    const target = targetAt(t, x, y);
    if (!target || !canDropIn(t, target.col)) return false;
    const before = columnOf(target.col).map((o) => o.id);
    const ids = before.filter((id) => id !== t.id);
    ids.splice(target.index, 0, t.id);
    if (target.col === statusOf(t) && ids.every((id, i) => id === before[i])) return false;
    flyFrom.current.set(t.id, { ...centre(el), lifted: true });
    setNonce((n) => ({ ...n, [t.id]: (n[t.id] ?? 0) + 1 }));
    void place(t, target.col, ids);
    return true;
  };

  return (
    <LayoutGroup id="taskboard">
      <div className="tb">
        {COLUMNS.map((s) => {
          const col = columnOf(s);
          const allowed = dragging ? canMove(dragging, s) : false;
          const home = dragging ? statusOf(dragging) === s : false;
          const isOver = !!dragging && over?.col === s && canDropIn(dragging, s);
          const state = !dragging ? '' : isOver && !home ? ' is-over' : allowed ? ' is-target' : home ? '' : ' is-muted';
          return (
            <div
              key={s}
              ref={(el) => { colRefs.current[s] = el; }}
              className={`tb-col${state}`}
              style={{ ['--col' as string]: STATUS_META[s].color }}
            >
              <div className="tb-col__head">
                <span className="tb-col__name">{STATUS_META[s].label}</span>
                <motion.span key={col.length} className="tb-col__count" initial={{ scale: 1.4 }} animate={{ scale: 1 }} transition={SPRING}>
                  {col.length}
                </motion.span>
              </div>
              <div className="tb-col__body" ref={(el) => { bodyRefs.current[s] = el; }}>
                {isOver && over && (
                  <motion.div
                    className="tb-drop-line"
                    aria-hidden
                    initial={false}
                    animate={{ y: over.line }}
                    transition={{ type: 'spring', stiffness: 700, damping: 45 }}
                  />
                )}
                {col.map((t) => (
                  <BoardCard
                    key={`${t.id}.${nonce[t.id] ?? 0}`}
                    t={t}
                    status={s}
                    flyFrom={flyFrom}
                    onOpen={onOpen}
                    onDragState={(d) => { setDragging(d); if (!d) setOver(null); }}
                    onHover={(x, y) => {
                      const next = targetAt(t, x, y);
                      setOver((prev) =>
                        prev && next && prev.col === next.col && prev.index === next.index && Math.abs(prev.line - next.line) < 1
                          ? prev : next);
                    }}
                    onDrop={drop}
                    register={(el) => { if (el) cardEls.current.set(t.id, el); else cardEls.current.delete(t.id); }}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </LayoutGroup>
  );
}
