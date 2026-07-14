import { Badge, Card, Col, Row, Space, Statistic, Table, Tag, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client';
import type { Task, TeamMember } from '../api/types';
import { RoleTags, STATUS_META, StatusTag } from '../components/tags';
import TaskDrawer from '../components/TaskDrawer';

export default function TeamPage() {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<TeamMember | null>(null);
  const [memberTasks, setMemberTasks] = useState<Task[]>([]);
  const [openTask, setOpenTask] = useState<number | null>(null);

  useEffect(() => {
    api
      .get<TeamMember[]>('/api/team')
      .then(setMembers)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (selected) {
      api
        .get<Task[]>(`/api/tasks?view=all&assignee_id=${selected.user.id}`)
        .then(setMemberTasks);
    }
  }, [selected]);

  const totals = useMemo(() => {
    const sum: Record<string, number> = {};
    for (const m of members) {
      for (const [status, n] of Object.entries(m.task_counts)) {
        sum[status] = (sum[status] ?? 0) + (n ?? 0);
      }
    }
    return sum;
  }, [members]);

  return (
    <>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        My Team
      </Typography.Title>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic title="People" value={members.length} />
          </Card>
        </Col>
        {Object.entries(STATUS_META).map(([status, meta]) => (
          <Col span={4} key={status}>
            <Card size="small">
              <Statistic title={meta.label} value={totals[status] ?? 0} />
            </Card>
          </Col>
        ))}
      </Row>

      <Table
        rowKey={(m) => m.user.id}
        loading={loading}
        dataSource={members}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        onRow={(m) => ({ onClick: () => setSelected(m), style: { cursor: 'pointer' } })}
        columns={[
          {
            title: 'Name',
            render: (_, m) => (
              <Space>
                {m.user.full_name}
                {m.is_direct_report && <Tag color="cyan">direct report</Tag>}
              </Space>
            ),
          },
          { title: 'Email', render: (_, m) => m.user.email, width: 240 },
          { title: 'Roles', render: (_, m) => <RoleTags roles={m.user.roles} /> },
          {
            title: 'Department',
            render: (_, m) => m.user.department ?? '—',
            width: 130,
          },
          {
            title: 'Open / total tasks',
            width: 200,
            sorter: (a, b) => a.total_tasks - b.total_tasks,
            render: (_, m) => {
              const open =
                (m.task_counts.todo ?? 0) +
                (m.task_counts.in_progress ?? 0) +
                (m.task_counts.submitted ?? 0) +
                (m.task_counts.revision_requested ?? 0);
              return (
                <Space>
                  <Badge count={open} color={open ? 'blue' : 'green'} showZero />
                  <Typography.Text type="secondary">of {m.total_tasks}</Typography.Text>
                </Space>
              );
            },
          },
        ]}
      />

      {selected && (
        <Card size="small" title={`Tasks — ${selected.user.full_name}`} style={{ marginTop: 16 }}>
          <Table
            rowKey="id"
            size="small"
            dataSource={memberTasks}
            pagination={{ pageSize: 10, hideOnSinglePage: true }}
            onRow={(t) => ({ onClick: () => setOpenTask(t.id), style: { cursor: 'pointer' } })}
            columns={[
              { title: 'Title', dataIndex: 'title', ellipsis: true },
              {
                title: 'Status',
                dataIndex: 'status',
                width: 190,
                render: (s: Task['status']) => <StatusTag status={s} />,
              },
              { title: 'Assigned by', width: 180, render: (_, t) => t.assigner.full_name },
              { title: 'Due', dataIndex: 'due_date', width: 120, render: (d) => d ?? '—' },
            ]}
          />
        </Card>
      )}
      <TaskDrawer taskId={openTask} onClose={() => setOpenTask(null)} onChanged={() => selected && setSelected({ ...selected })} />
    </>
  );
}
