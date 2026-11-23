import { AppstoreOutlined, PlusOutlined, ReloadOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { Button, Segmented, Select, Space, Table } from 'antd';
import dayjs from 'dayjs';
import { AnimatePresence, motion } from 'motion/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Task, TaskStatus } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import NewTaskModal from '../components/NewTaskModal';
import EmptyState from '../components/EmptyState';
import TaskBoard from '../components/TaskBoard';
import TaskDrawer from '../components/TaskDrawer';
import { BlockedTag, PriorityTag, STATUS_META, StatusTag } from '../components/tags';
import { openableRow } from '../components/a11y';

const DISPLAY = 'var(--font-display)';
const DANGER = 'var(--error)';

type View = 'assigned' | 'created' | 'all';
type Layout = 'board' | 'list';
const GLIDE = { type: 'spring', stiffness: 520, damping: 42, mass: 0.7 } as const;

export default function TasksPage() {
  const { me } = useAuth();
  const [view, setView] = useState<View>('assigned');
  const [statusFilter, setStatusFilter] = useState<TaskStatus | undefined>();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const [layout, setLayoutState] = useState<Layout>(() => {
    try { return localStorage.getItem('mtr.tasks.layout') === 'list' ? 'list' : 'board'; } catch { return 'board'; }
  });
  const setLayout = (l: Layout) => {
    setLayoutState(l);
    try { localStorage.setItem('mtr.tasks.layout', l); } catch { /* storage off */ }
  };

  const openTaskId = searchParams.get('task') ? Number(searchParams.get('task')) : null;

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ view });
    if (statusFilter) params.set('status_filter', statusFilter);
    api.get<Task[]>(`/api/tasks?${params}`).then(setTasks).finally(() => setLoading(false));
  }, [view, statusFilter]);

  useEffect(load, [load]);

  const canCreate = useMemo(() => can(me, 'tasks.assign') && (me!.has_team || me!.privileges.includes('users.manage')), [me]);

  const viewOptions = [
    { label: 'Assigned to me', value: 'assigned' },
    { label: 'Assigned by me', value: 'created' },
    ...(canCreate ? [{ label: 'Everything I can see', value: 'all' }] : []),
  ];

  const empty = statusFilter ? (
    <EmptyState phrase="No tasks with that status." action={{ label: 'Show every status', onClick: () => setStatusFilter(undefined) }} />
  ) : view === 'assigned' ? (
    <EmptyState phrase="Nothing on your plate right now." action={{ label: 'Open the calendar', to: '/calendar' }} />
  ) : canCreate ? (
    <EmptyState phrase="You haven't handed out any tasks yet." action={{ label: 'Assign a task', onClick: () => setCreating(true) }} />
  ) : (
    <EmptyState phrase="No tasks to show." action={{ label: 'See my teams', to: '/team' }} />
  );

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <Space wrap size={12} align="center">
          <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: 'var(--text-primary)' }}>My Tasks</h2>
          <Segmented options={viewOptions} value={view} onChange={(v) => setView(v as View)} />
          <Select allowClear placeholder="Any status" style={{ width: 200 }} value={statusFilter} onChange={setStatusFilter}
            options={Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: meta.label }))} />
          <Button aria-label="Reload tasks" icon={<ReloadOutlined />} onClick={load} />
          <div className="tk-layout" role="group" aria-label="Layout">
            {([['board', 'Board', <AppstoreOutlined key="b" />], ['list', 'List', <UnorderedListOutlined key="l" />]] as const).map(([k, label, icon]) => (
              <button key={k} type="button" aria-pressed={layout === k} onClick={() => setLayout(k)}>
                {layout === k && <motion.span layoutId="tk-layout-thumb" className="tk-layout__thumb" transition={GLIDE} />}
                {icon}{label}
              </button>
            ))}
          </div>
        </Space>
        {canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>Assign task</Button>}
      </div>

      <AnimatePresence mode="wait" initial={false}>
      {layout === 'board' ? (
        <motion.div key="board" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.22 }}>
          {!loading && tasks.length === 0
            ? empty
            : <TaskBoard tasks={tasks} onOpen={(id) => setSearchParams({ task: String(id) })} onChanged={load} />}
        </motion.div>
      ) : (
      <motion.div key="list" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.22 }}>
      <Table className="circuit-table" rowKey="id" loading={loading} dataSource={tasks} locale={{ emptyText: empty }}
        onRow={(t) => openableRow(() => setSearchParams({ task: String(t.id) }))}
        pagination={{ defaultPageSize: 15, hideOnSinglePage: true }} scroll={{ x: 'max-content' }}
        columns={[
          { title: 'Title', dataIndex: 'title', ellipsis: true },
          {
            title: 'Status', dataIndex: 'status', width: 200,
            render: (s: TaskStatus, t) => (
              <Space size={4}>
                <StatusTag status={s} />
                {t.is_blocked && <BlockedTag />}
              </Space>
            ),
          },
          { title: 'Priority', dataIndex: 'priority', width: 110, render: (p: Task['priority']) => <PriorityTag priority={p} /> },
          { title: 'Assignee', width: 180, render: (_, t) => t.assignee.full_name },
          { title: 'Team', width: 140, render: (_, t) => t.event_team_name ?? '—' },
          { title: 'Assigned by', width: 180, render: (_, t) => t.assigner.full_name },
          {
            title: 'Due', dataIndex: 'due_date', width: 120,
            render: (d: string | null) => d ? (
              <span style={{ color: dayjs(d).isBefore(dayjs(), 'day') ? DANGER : undefined }}>{dayjs(d).format('DD MMM')}</span>
            ) : '—',
          },
        ]} />
      </motion.div>
      )}
      </AnimatePresence>

      <NewTaskModal open={creating} onClose={() => setCreating(false)} onCreated={load} />
      <TaskDrawer taskId={openTaskId} onClose={() => setSearchParams({})} onChanged={load} />
    </>
  );
}
