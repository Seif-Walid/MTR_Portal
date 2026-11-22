import { Card, Empty, Space, Table, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client';
import type { Task, TeamBlock, TeamMember } from '../api/types';
import { STATUS_META, StatusTag } from '../components/tags';
import TaskDrawer from '../components/TaskDrawer';
import TimeBlockPanel from '../components/TimeBlockPanel';
import { openableRow } from '../components/a11y';

const MONO = 'var(--font-mono)';
const DISPLAY = 'var(--font-display)';

function StatCard({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div style={{ border: `1px solid ${accent ? 'color-mix(in srgb, var(--brand-fg) 25%, transparent)' : 'var(--border)'}`, borderRadius: 12, background: 'var(--surface)', padding: '14px 16px', minWidth: 0 }}>
      <div style={{ fontFamily: MONO, fontWeight: 600, fontSize: 26, color: accent ? 'var(--brand-fg)' : 'var(--text-primary)', lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 8 }}>{label}</div>
    </div>
  );
}

function TeamSection({ block, onOpenTask }: { block: TeamBlock; onOpenTask: (id: number) => void }) {
  const [selected, setSelected] = useState<TeamMember | null>(null);
  const [memberTasks, setMemberTasks] = useState<Task[]>([]);

  useEffect(() => {
    if (!selected) return;
    // scope the drill-down to this team's board for event teams
    const teamScope = block.team_id != null ? `&event_team_id=${block.team_id}` : '';
    api.get<Task[]>(`/api/tasks?view=all&assignee_id=${selected.user.id}${teamScope}`).then(setMemberTasks);
  }, [selected, block.team_id]);

  const totals = useMemo(() => {
    const sum: Record<string, number> = {};
    for (const m of block.members) for (const [status, n] of Object.entries(m.task_counts)) sum[status] = (sum[status] ?? 0) + (n ?? 0);
    return sum;
  }, [block.members]);

  return (
    <section style={{ marginBottom: 34 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, margin: '0 0 14px' }}>
        <h3 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 18, margin: 0, color: 'var(--text-primary)' }}>{block.name}</h3>
        {block.kind === 'event' ? (
          <span style={{ fontSize: 11.5, color: 'var(--cat-violet)', background: 'color-mix(in srgb, var(--cat-violet) 8%, transparent)', padding: '2px 8px', borderRadius: 999 }}>
            {block.event_name}
          </span>
        ) : (
          <span style={{ fontSize: 11.5, color: 'var(--brand-fg)', background: 'color-mix(in srgb, var(--brand-fg) 8%, transparent)', padding: '2px 8px', borderRadius: 999 }}>
            org hierarchy
          </span>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12, marginBottom: 16 }}>
        <StatCard label="People" value={block.members.length} accent />
        {Object.entries(STATUS_META).map(([status, meta]) => (
          <StatCard key={status} label={meta.label} value={totals[status] ?? 0} />
        ))}
      </div>

      <TimeBlockPanel block={block} />

      <Table className="circuit-table" rowKey={(m) => m.user.id} dataSource={block.members}
        pagination={{ defaultPageSize: 20, hideOnSinglePage: true }} scroll={{ x: 'max-content' }}
        onRow={(m) => openableRow(() => setSelected((prev) => (prev?.user.id === m.user.id ? null : m)))}
        columns={[
          {
            title: 'Name',
            render: (_, m) => (
              <Space>
                <span style={{ color: 'var(--text-primary)' }}>{m.user.full_name}</span>
                {m.is_direct_report && (
                  <span style={{ fontSize: 11.5, color: 'var(--brand-fg)', background: 'color-mix(in srgb, var(--brand-fg) 8%, transparent)', padding: '2px 7px', borderRadius: 999 }}>direct report</span>
                )}
              </Space>
            ),
          },
          { title: 'Email', render: (_, m) => m.user.email, width: 240 },
          { title: 'Department', render: (_, m) => m.user.department ?? '—', width: 130 },
          {
            title: 'Open / total tasks', width: 200, sorter: (a, b) => a.total_tasks - b.total_tasks,
            render: (_, m) => {
              const open = (m.task_counts.todo ?? 0) + (m.task_counts.in_progress ?? 0) + (m.task_counts.submitted ?? 0) + (m.task_counts.revision_requested ?? 0);
              return (
                <Space size={8}>
                  <span style={{ fontFamily: MONO, fontWeight: 600, fontSize: 12, color: open ? 'var(--brand-fg)' : 'var(--text-tertiary)', border: `1px solid ${open ? 'color-mix(in srgb, var(--brand-fg) 30%, transparent)' : 'var(--border)'}`, background: open ? 'color-mix(in srgb, var(--brand-fg) 8%, transparent)' : 'transparent', padding: '2px 9px', borderRadius: 20, minWidth: 26, textAlign: 'center', display: 'inline-block' }}>{open}</span>
                  <Typography.Text type="secondary">of {m.total_tasks}</Typography.Text>
                </Space>
              );
            },
          },
        ]} />

      {selected && (
        <Card size="small" title={`Tasks — ${selected.user.full_name}`} style={{ marginTop: 16 }}>
          <Table className="circuit-table" rowKey="id" size="small" dataSource={memberTasks}
            pagination={{ defaultPageSize: 10, hideOnSinglePage: true }} scroll={{ x: 'max-content' }}
            onRow={(t) => openableRow(() => onOpenTask(t.id))}
            columns={[
              { title: 'Title', dataIndex: 'title', ellipsis: true },
              { title: 'Status', dataIndex: 'status', width: 190, render: (s: Task['status']) => <StatusTag status={s} /> },
              { title: 'Assigned by', width: 180, render: (_, t) => t.assigner.full_name },
              { title: 'Due', dataIndex: 'due_date', width: 120, render: (d) => d ?? '—' },
            ]} />
        </Card>
      )}
    </section>
  );
}

export default function TeamPage() {
  const [blocks, setBlocks] = useState<TeamBlock[]>([]);
  const [loading, setLoading] = useState(true);
  const [openTask, setOpenTask] = useState<number | null>(null);

  const reload = () => api.get<TeamBlock[]>('/api/team/mine').then(setBlocks).finally(() => setLoading(false));
  useEffect(() => { reload(); }, []);

  return (
    <>
      <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: '0 0 18px', color: 'var(--text-primary)' }}>My Teams</h2>

      {!loading && blocks.length === 0 && (
        <Empty description="You're not on any team yet" style={{ marginTop: 40 }} />
      )}

      {blocks.map((b) => (
        <TeamSection key={`${b.kind}-${b.team_id ?? 'org'}`} block={b} onOpenTask={setOpenTask} />
      ))}

      <TaskDrawer taskId={openTask} onClose={() => setOpenTask(null)} onChanged={reload} />
    </>
  );
}
