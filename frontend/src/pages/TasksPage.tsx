import { AppstoreOutlined, PlusOutlined, ReloadOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { Button, Segmented, Select, Space, Table } from 'antd';
import dayjs from 'dayjs';
import { AnimatePresence, motion } from 'motion/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Task, TaskScope, TaskStatus } from '../api/types';
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
  // which event tab / team chip is open; none = every project at once
  const eventId = searchParams.get('event') ? Number(searchParams.get('event')) : null;
  const teamId = eventId != null && searchParams.get('team') ? Number(searchParams.get('team')) : null;
  const [scopes, setScopes] = useState<TaskScope[] | null>(null);
  const viewParam = searchParams.get('view');
  const view: View = viewParam === 'created' || viewParam === 'all' ? viewParam : 'assigned';
  const setView = (v: View) => patchParams({ view: v === 'assigned' ? null : v });

  const patchParams = useCallback((changes: Record<string, string | null>) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(changes)) {
        if (v == null) next.delete(k); else next.set(k, v);
      }
      return next;
    });
  }, [setSearchParams]);
  const openTask = (id: number | null) => patchParams({ task: id == null ? null : String(id) });
  const pickEvent = (id: number | null) => patchParams({ event: id == null ? null : String(id), team: null });
  const pickTeam = (id: number | null) => patchParams({ team: id == null ? null : String(id) });

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ view });
    if (statusFilter) params.set('status_filter', statusFilter);
    api.get<TaskScope[]>(`/api/tasks/scopes?${params}`).then(setScopes).catch(() => {});
    if (teamId != null) params.set('team_id', String(teamId));
    else if (eventId != null) params.set('event_id', String(eventId));
    api.get<Task[]>(`/api/tasks?${params}`).then(setTasks).finally(() => setLoading(false));
  }, [view, statusFilter, eventId, teamId]);

  useEffect(load, [load]);

  const scope = scopes?.find((sc) => sc.event_id === eventId) ?? null;
  const team = scope?.teams.find((t) => t.team_id === teamId) ?? null;

  // a tab that no longer applies (other view, event archived, team removed)
  // would silently hide every task — fall back to the wider scope instead
  useEffect(() => {
    if (scopes === null || eventId == null) return;
    if (!scope) pickEvent(null);
    else if (teamId != null && !team) pickTeam(null);
  }, [scopes, scope, team, eventId, teamId]); // eslint-disable-line react-hooks/exhaustive-deps

  const canCreate = useMemo(() => can(me, 'tasks.assign') && (me!.has_team || me!.privileges.includes('users.manage')), [me]);

  const viewOptions = [
    { label: 'Assigned to me', value: 'assigned' },
    { label: 'Assigned by me', value: 'created' },
    ...(canCreate ? [{ label: 'Everything I can see', value: 'all' }] : []),
  ];

  const empty = team ? (
    <EmptyState phrase={`No tasks on ${team.path_name} yet.`} action={{ label: 'Show the whole event', onClick: () => pickTeam(null) }} />
  ) : scope ? (
    <EmptyState phrase={`No tasks under ${scope.name} yet.`} action={{ label: 'Show all projects', onClick: () => pickEvent(null) }} />
  ) : statusFilter ? (
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

      {scopes && scopes.length > 0 && (
        <nav className="tk-scopes" aria-label="Projects">
          <div className="tk-tabs" role="tablist">
            {[{ id: null as number | null, label: 'All projects', kind: null as string | null, count: null as number | null },
              ...scopes.map((sc) => ({ id: sc.event_id, label: sc.name, kind: sc.kind_name, count: sc.task_count }))].map((tab) => (
              <button key={tab.id ?? 'all'} type="button" role="tab" aria-selected={eventId === tab.id}
                className="tk-tab" onClick={() => pickEvent(tab.id)}>
                {eventId === tab.id && <motion.span layoutId="tk-tab-thumb" className="tk-tab__thumb" transition={GLIDE} />}
                {tab.kind && <span className="tk-tab__kind">{tab.kind}</span>}
                <span className="tk-tab__name">{tab.label}</span>
                {tab.count != null && <span className="tk-tab__count">{tab.count}</span>}
              </button>
            ))}
          </div>
          <AnimatePresence initial={false}>
            {scope && (
              <motion.div key={scope.event_id} className="tk-teams" role="group" aria-label={`${scope.name} teams`}
                initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}>
                <button type="button" className="tk-team" aria-pressed={teamId == null} onClick={() => pickTeam(null)}>
                  All teams <span className="tk-team__count">{scope.task_count}</span>
                </button>
                {scope.teams.length === 0 && <span className="tk-teams__none">This event has no teams yet.</span>}
                {scope.teams.map((t) => (
                  <button key={t.team_id} type="button" className="tk-team" aria-pressed={teamId === t.team_id}
                    title={`${t.category_name} · ${t.path_name}`} onClick={() => pickTeam(t.team_id)}>
                    {t.depth > 0 && <span className="tk-team__nest" aria-hidden>{'›'.repeat(t.depth)}</span>}
                    {t.name}
                    <span className="tk-team__count">{t.task_count}</span>
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </nav>
      )}

      <AnimatePresence mode="wait" initial={false}>
      {layout === 'board' ? (
        <motion.div key="board" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.22 }}>
          {!loading && tasks.length === 0
            ? empty
            : <TaskBoard tasks={tasks} onOpen={(id) => openTask(id)} onChanged={load} />}
        </motion.div>
      ) : (
      <motion.div key="list" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.22 }}>
      <Table className="circuit-table" rowKey="id" loading={loading} dataSource={tasks} locale={{ emptyText: empty }}
        onRow={(t) => openableRow(() => openTask(t.id))}
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

      <NewTaskModal open={creating} onClose={() => setCreating(false)} onCreated={load} teamId={teamId} />
      <TaskDrawer taskId={openTaskId} onClose={() => openTask(null)} onChanged={load} />
    </>
  );
}
