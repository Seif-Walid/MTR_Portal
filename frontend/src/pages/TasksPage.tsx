import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, Segmented, Select, Space, Table } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Task, TaskStatus } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import NewTaskModal from '../components/NewTaskModal';
import TaskDrawer from '../components/TaskDrawer';
import { BlockedTag, PriorityTag, STATUS_META, StatusTag } from '../components/tags';

const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";
const DANGER = '#ff5a6e';

type View = 'assigned' | 'created' | 'all';

export default function TasksPage() {
  const { me } = useAuth();
  const [view, setView] = useState<View>('assigned');
  const [statusFilter, setStatusFilter] = useState<TaskStatus | undefined>();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

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

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <Space wrap size={12} align="center">
          <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>My Tasks</h2>
          <Segmented options={viewOptions} value={view} onChange={(v) => setView(v as View)} />
          <Select allowClear placeholder="Any status" style={{ width: 200 }} value={statusFilter} onChange={setStatusFilter}
            options={Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: meta.label }))} />
          <Button icon={<ReloadOutlined />} onClick={load} />
        </Space>
        {canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>Assign task</Button>}
      </div>

      <Table className="circuit-table" rowKey="id" loading={loading} dataSource={tasks}
        onRow={(t) => ({ onClick: () => setSearchParams({ task: String(t.id) }), style: { cursor: 'pointer' } })}
        pagination={{ defaultPageSize: 15, hideOnSinglePage: true }}
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
          { title: 'Assigned by', width: 180, render: (_, t) => t.assigner.full_name },
          {
            title: 'Due', dataIndex: 'due_date', width: 120,
            render: (d: string | null) => d ? (
              <span style={{ color: dayjs(d).isBefore(dayjs(), 'day') ? DANGER : undefined }}>{dayjs(d).format('DD MMM')}</span>
            ) : '—',
          },
        ]} />

      <NewTaskModal open={creating} onClose={() => setCreating(false)} onCreated={load} />
      <TaskDrawer taskId={openTaskId} onClose={() => setSearchParams({})} onChanged={load} />
    </>
  );
}
