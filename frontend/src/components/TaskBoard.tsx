/* Kanban board for tasks: one column per status. Cards can be dragged to
   another column; only moves the workflow allows light up as drop targets,
   and the server still has the final say (a refused move springs back). */
import { CalendarOutlined, HolderOutlined, LockOutlined } from '@ant-design/icons';
import { message } from 'antd';
import dayjs from 'dayjs';
import { LayoutGroup, motion } from 'motion/react';
import { useRef, useState } from 'react';

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

function initials(name: string) {
  return name.split(' ').map((p) => p[0]).slice(0, 2).join('');
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
  // optimistic status overrides while the server confirms a move
  const [moved, setMoved] = useState<Record<number, TaskStatus>>({});
  const [dragging, setDragging] = useState<Task | null>(null);
  const [over, setOver] = useState<TaskStatus | null>(null);
  const colRefs = useRef<Partial<Record<TaskStatus, HTMLDivElement | null>>>({});
  const didDrag = useRef(false);

  const statusOf = (t: Task) => moved[t.id] ?? t.status;

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
    } finally {
      setMoved((m) => {
        const n = { ...m };
        delete n[t.id];
        return n;
      });
    }
  };

  const card = (t: Task) => {
    const due = t.due_date ? dayjs(t.due_date) : null;
    const late = !!due && due.isBefore(dayjs(), 'day') && statusOf(t) !== 'approved';
    const isDragging = dragging?.id === t.id;
    return (
      <motion.div
        key={t.id}
        layout
        layoutId={`task-${t.id}`}
        transition={SPRING}
        className={`tb-card${isDragging ? ' is-dragging' : ''}`}
        drag
        dragSnapToOrigin
        dragElastic={0.9}
        dragMomentum={false}
        whileDrag={{ scale: 1.04, rotate: 2, zIndex: 50, boxShadow: 'var(--shadow-floating)', cursor: 'grabbing' }}
        whileHover={{ y: -3 }}
        onDragStart={() => { didDrag.current = true; setDragging(t); }}
        onDrag={(_, info) => setOver(columnAt(info.point.x - window.scrollX, info.point.y - window.scrollY))}
        onDragEnd={(_, info) => {
          const to = columnAt(info.point.x - window.scrollX, info.point.y - window.scrollY);
          setDragging(null);
          setOver(null);
          if (to && to !== statusOf(t) && canMove(t, to)) void move(t, to);
          // let the click that ends a drag fall through without opening the card
          window.setTimeout(() => { didDrag.current = false; }, 0);
        }}
        onClick={() => { if (!didDrag.current) onOpen(t.id); }}
        role="button"
        tabIndex={0}
        aria-label={`${t.title}, ${STATUS_META[statusOf(t)].label}${late ? ', overdue' : ''}`}
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
                {col.map(card)}
              </div>
            </div>
          );
        })}
      </div>
    </LayoutGroup>
  );
}
