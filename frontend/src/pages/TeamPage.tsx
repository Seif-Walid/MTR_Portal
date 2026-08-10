import { Card, Empty, Space, Table, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client';
import type { Task, TeamBlock, TeamMember } from '../api/types';
import { STATUS_META, StatusTag } from '../components/tags';
import TaskDrawer from '../components/TaskDrawer';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

function StatCard({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div style={{ border: `1px solid ${accent ? 'rgba(92,198,255,.25)' : 'rgba(120,170,230,.12)'}`, borderRadius: 12, background: 'rgba(15,20,29,.55)', padding: '14px 16px', minWidth: 0 }}>
      <div style={{ fontFamily: MONO, fontWeight: 600, fontSize: 26, color: accent ? '#5cc6ff' : '#eaf2ff', lineHeight: 1 }}>{value}</div>
      <div style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.14em', textTransform: 'uppercase', color: 'rgba(224,236,252,.45)', marginTop: 8 }}>{label}</div>
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
        <h3 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 18, margin: 0, color: '#eaf2ff' }}>{block.name}</h3>
        {block.kind === 'event' ? (
          <span style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.1em', textTransform: 'uppercase', color: '#c58bff', border: '1px solid rgba(197,139,255,.3)', background: 'rgba(197,139,255,.08)', padding: '2px 8px', borderRadius: 5 }}>
            {block.event_name}
          </span>
        ) : (
          <span style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.1em', textTransform: 'uppercase', color: '#5cc6ff', border: '1px solid rgba(92,198,255,.3)', background: 'rgba(92,198,255,.08)', padding: '2px 8px', borderRadius: 5 }}>
            org hierarchy
          </span>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Object.keys(STATUS_META).length + 1}, minmax(0,1fr))`, gap: 12, marginBottom: 16 }}>
        <StatCard label="People" value={block.members.length} accent />
        {Object.entries(STATUS_META).map(([status, meta]) => (
          <StatCard key={status} label={meta.label} value={totals[status] ?? 0} />
        ))}
      </div>

      <Table className="circuit-table" rowKey={(m) => m.user.id} dataSource={block.members}
        pagination={{ defaultPageSize: 20, hideOnSinglePage: true }}
        onRow={(m) => ({ onClick: () => setSelected(m), style: { cursor: 'pointer' } })}
        columns={[
          {
            title: 'Name',
            render: (_, m) => (
              <Space>
                <span style={{ color: '#eaf2ff' }}>{m.user.full_name}</span>
                {m.is_direct_report && (
                  <span style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.06em', textTransform: 'uppercase', color: '#5cc6ff', border: '1px solid rgba(92,198,255,.3)', background: 'rgba(92,198,255,.08)', padding: '2px 7px', borderRadius: 5 }}>direct report</span>
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
                  <span style={{ fontFamily: MONO, fontWeight: 600, fontSize: 12, color: open ? '#5cc6ff' : 'rgba(224,236,252,.5)', border: `1px solid ${open ? 'rgba(92,198,255,.3)' : 'rgba(120,170,230,.18)'}`, background: open ? 'rgba(92,198,255,.08)' : 'transparent', padding: '2px 9px', borderRadius: 20, minWidth: 26, textAlign: 'center', display: 'inline-block' }}>{open}</span>
                  <Typography.Text type="secondary">of {m.total_tasks}</Typography.Text>
                </Space>
              );
            },
          },
        ]} />

      {selected && (
        <Card size="small" title={`Tasks — ${selected.user.full_name}`} style={{ marginTop: 16 }}>
          <Table className="circuit-table" rowKey="id" size="small" dataSource={memberTasks}
            pagination={{ defaultPageSize: 10, hideOnSinglePage: true }}
            onRow={(t) => ({ onClick: () => onOpenTask(t.id), style: { cursor: 'pointer' } })}
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
      <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: '0 0 18px', color: '#eaf2ff' }}>My Teams</h2>

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
