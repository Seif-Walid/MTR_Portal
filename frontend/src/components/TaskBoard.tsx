/* Kanban board for tasks: one column per status. Cards can be dragged to
   another column; only moves the workflow allows light up as drop targets,
   and the server still has the final say (a refused move springs back). */
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
  // optimistic status overrides; each one stays until the refreshed task
  // list agrees, so a card never bounces back while the reload is in flight
  const [moved, setMoved] = useState<Record<number, TaskStatus>>({});
  const [dragging, setDragging] = useState<Task | null>(null);
  const [over, setOver] = useState<TaskStatus | null>(null);
  const colRefs = useRef<Partial<Record<TaskStatus, HTMLDivElement | null>>>({});
  const flyFrom = useRef(new Map<number, Rect & { lifted: boolean }>());
  const cardEls = useRef(new Map<number, HTMLElement>());

  const statusOf = (t: Task) => moved[t.id] ?? t.status;

  useEffect(() => {
    setMoved((m) => {
      const keep = Object.entries(m).filter(([id, s]) => {
        const t = tasks.find((x) => x.id === Number(id));
        return t && t.status !== s;
      });
      return keep.length === Object.keys(m).length ? m : Object.fromEntries(keep);
    });
  }, [tasks]);

  // The UI only offers moves this person can plausibly make; the server
  // checks the reviewer chain properly.
  const canMove = (t: Task, to: TaskStatus) => {
    const who = MOVES[`${statusOf(t)}>${to}`];
    if (!who || !me) return false;
    if (who === 'assignee') return t.assignee.id === me.id;
    return t.assignee.id !== me.id;
  };

  const columnAt = (x: number, y: number): TaskStatus | null => {
    for (const s of COLUMNS) {
      const r = colRefs.current[s]?.getBoundingClientRect();
      if (r && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return s;
    }
    return null;
  };

  const move = async (t: Task, to: TaskStatus) => {
    setMoved((m) => ({ ...m, [t.id]: to }));
    try {
      await api.patch<Task>(`/api/tasks/${t.id}/status`, { status: to });
      message.success(`Moved to ${STATUS_META[to].label.toLowerCase()}`);
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Couldn’t move the task');
      // refused: fly the card back from where it sits now
      const el = cardEls.current.get(t.id);
      if (el) flyFrom.current.set(t.id, { ...centre(el), lifted: false });
      setMoved((m) => {
        const n = { ...m };
        delete n[t.id];
        return n;
      });
    }
  };

  const drop = (t: Task, x: number, y: number, el: HTMLElement) => {
    const to = columnAt(x, y);
    if (!to || to === statusOf(t) || !canMove(t, to)) return false;
    flyFrom.current.set(t.id, { ...centre(el), lifted: true });
    void move(t, to);
    return true;
  };

  return (
    <LayoutGroup id="taskboard">
      <div className="tb">
        {COLUMNS.map((s) => {
          const col = tasks.filter((t) => statusOf(t) === s);
          const allowed = dragging ? canMove(dragging, s) : false;
          const home = dragging ? statusOf(dragging) === s : false;
          const state = !dragging ? '' : allowed ? (over === s ? ' is-over' : ' is-target') : home ? '' : ' is-muted';
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
              <div className="tb-col__body">
                {col.map((t) => (
                    <BoardCard
                      key={t.id}
                      t={t}
                      status={s}
                      flyFrom={flyFrom}
                      onOpen={onOpen}
                      onDragState={(d) => { setDragging(d); if (!d) setOver(null); }}
                      onHover={(x, y) => setOver(columnAt(x, y))}
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
