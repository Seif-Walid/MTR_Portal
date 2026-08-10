import { Empty, Table, Tag } from 'antd';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { api } from '../api/client';
import type { ArchivedEvent, ArchivedEventDetail, ArchivedTask } from '../api/types';
import { StatusTag } from '../components/tags';
import TaskDrawer from '../components/TaskDrawer';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

function fmtRange(start: string | null, end: string | null): string {
  if (!start && !end) return '—';
  return `${start ?? '?'} → ${end ?? '?'}`;
}

function EventList() {
  const [events, setEvents] = useState<ArchivedEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api.get<ArchivedEvent[]>('/api/archive/events').then(setEvents).finally(() => setLoading(false));
  }, []);

  if (!loading && events.length === 0) {
    return <Empty description="No archived events yet" style={{ marginTop: 40 }} />;
  }

  return (
    <>
      <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: '0 0 6px', color: '#eaf2ff' }}>Archive</h2>
      <p style={{ color: 'rgba(224,236,252,.5)', margin: '0 0 22px', fontSize: 13 }}>
        A public record of past events. Open one to see the tasks you took on.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
        {events.map((e) => (
          <button
            key={e.id}
            onClick={() => navigate(`/archive/${e.id}`)}
            style={{
              textAlign: 'left', cursor: 'pointer', border: '1px solid rgba(120,170,230,.14)', borderRadius: 14,
              background: 'rgba(15,20,29,.55)', padding: '18px 18px 16px', color: 'inherit',
            }}
          >
            {e.kind_name && (
              <div style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.14em', textTransform: 'uppercase', color: '#c58bff', marginBottom: 8 }}>{e.kind_name}</div>
            )}
            <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 16, color: '#eaf2ff', marginBottom: 10 }}>{e.name}</div>
            <div style={{ fontFamily: MONO, fontSize: 11, color: 'rgba(224,236,252,.45)' }}>{fmtRange(e.start_date, e.end_date)}</div>
          </button>
        ))}
      </div>
    </>
  );
}

function EventDetail({ eventId }: { eventId: number }) {
  const [detail, setDetail] = useState<ArchivedEventDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [openTask, setOpenTask] = useState<number | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    api.get<ArchivedEventDetail>(`/api/archive/events/${eventId}`).then(setDetail).finally(() => setLoading(false));
  }, [eventId]);

  const done = detail?.tasks.filter((t) => t.outcome === 'accomplished').length ?? 0;
  const total = detail?.tasks.length ?? 0;

  return (
    <>
      <button
        onClick={() => navigate('/archive')}
        style={{ cursor: 'pointer', background: 'transparent', border: 'none', color: '#5cc6ff', fontFamily: MONO, fontSize: 11, letterSpacing: '.08em', padding: 0, marginBottom: 16 }}
      >
        ← Back to archive
      </button>

      {detail && (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 6 }}>
            <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>{detail.event.name}</h2>
            {detail.event.kind_name && (
              <span style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.12em', textTransform: 'uppercase', color: '#c58bff', border: '1px solid rgba(197,139,255,.3)', background: 'rgba(197,139,255,.08)', padding: '2px 8px', borderRadius: 5 }}>{detail.event.kind_name}</span>
            )}
          </div>
          <div style={{ fontFamily: MONO, fontSize: 12, color: 'rgba(224,236,252,.5)', marginBottom: 18 }}>
            {fmtRange(detail.event.start_date, detail.event.end_date)}
            {detail.teams.length > 0 && <> · your team{detail.teams.length > 1 ? 's' : ''}: {detail.teams.join(', ')}</>}
          </div>

          {total === 0 ? (
            <Empty description="You held no tasks in this event" style={{ marginTop: 30 }} />
          ) : (
            <>
              <p style={{ fontFamily: MONO, fontSize: 12, color: 'rgba(224,236,252,.6)', margin: '0 0 14px' }}>
                You accomplished <span style={{ color: '#5cc6ff', fontWeight: 600 }}>{done}</span> of {total} task{total > 1 ? 's' : ''}.
              </p>
              <Table<ArchivedTask> className="circuit-table" rowKey={(r) => r.task.id} loading={loading} dataSource={detail.tasks}
                pagination={{ defaultPageSize: 15, hideOnSinglePage: true }}
                onRow={(r) => ({ onClick: () => setOpenTask(r.task.id), style: { cursor: 'pointer' } })}
                columns={[
                  { title: 'Title', render: (_, r) => r.task.title, ellipsis: true },
                  { title: 'Team', width: 180, render: (_, r) => r.team_name },
                  { title: 'Status', width: 190, render: (_, r) => <StatusTag status={r.task.status} /> },
                  {
                    title: 'Outcome', width: 150,
                    render: (_, r) =>
                      r.outcome === 'accomplished'
                        ? <Tag color="green">Accomplished</Tag>
                        : <Tag color="volcano">Incomplete</Tag>,
                  },
                ]} />
            </>
          )}
        </>
      )}
      <TaskDrawer taskId={openTask} onClose={() => setOpenTask(null)} onChanged={() => {}} />
    </>
  );
}

export default function ArchivePage() {
  const { eventId } = useParams();
  return eventId ? <EventDetail eventId={Number(eventId)} /> : <EventList />;
}
