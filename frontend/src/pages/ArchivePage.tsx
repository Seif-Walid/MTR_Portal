import { Button, Empty, Select, Table, Tag, Typography, message } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type {
  ArchivedEvent,
  ArchivedEventDetail,
  ArchivedGroup,
  ArchivedTask,
  ArchiveSummary,
} from '../api/types';
import { AwardTag, StatusTag } from '../components/tags';
import TaskDrawer from '../components/TaskDrawer';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

function fmtRange(start: string | null, end: string | null): string {
  if (!start && !end) return '—';
  return `${start ?? '?'} → ${end ?? '?'}`;
}

async function run(p: Promise<unknown>, ok: string, after: () => void) {
  try {
    await p;
    message.success(ok);
    after();
  } catch (e) {
    message.error(e instanceof ApiError ? e.message : 'Failed');
  }
}

/** The overview the public site heads its Hall of Fame with. Same numbers, same
 * source — the site derives nothing of its own, so what a sponsor reads there
 * is what a member reads here. */
function Overview({ summary }: { summary: ArchiveSummary }) {
  const stats: [string, number][] = [
    ['Competitions entered', summary.competitions],
    ['Seasons', summary.seasons],
    ['Members fielded', summary.members_fielded],
    ['🥇 1st Place', summary.gold],
    ['🥈 2nd Place', summary.silver],
    ['🥉 3rd Place', summary.bronze],
    ['🏆 Special awards', summary.special],
  ];
  return (
    <div
      style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 1,
        background: 'rgba(120,170,230,.14)', border: '1px solid rgba(120,170,230,.14)',
        borderRadius: 14, overflow: 'hidden', marginBottom: 22,
      }}
    >
      {stats.map(([label, value]) => (
        <div key={label} style={{ background: 'rgba(15,20,29,.55)', padding: '14px 16px' }}>
          <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 24, lineHeight: 1, color: '#eaf2ff' }}>{value}</div>
          <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.08em', textTransform: 'uppercase', color: 'rgba(224,236,252,.45)', marginTop: 8 }}>{label}</div>
        </div>
      ))}
    </div>
  );
}

function EventList() {
  const [events, setEvents] = useState<ArchivedEvent[]>([]);
  const [summary, setSummary] = useState<ArchiveSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api.get<ArchivedEvent[]>('/api/archive/events').then(setEvents).finally(() => setLoading(false));
    api.get<ArchiveSummary>('/api/archive/summary').then(setSummary).catch(() => setSummary(null));
  }, []);

  const reactivate = async (id: number) => {
    try {
      await api.post(`/api/archive/events/${id}/reactivate`);
      message.success('Reactivated');
      setEvents((es) => es.filter((e) => e.id !== id));
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };

  if (!loading && events.length === 0) {
    return <Empty description="No archived events yet" style={{ marginTop: 40 }} />;
  }

  return (
    <>
      <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: '0 0 6px', color: '#eaf2ff' }}>Archive</h2>
      <p style={{ color: 'rgba(224,236,252,.5)', margin: '0 0 22px', fontSize: 13 }}>
        The record of past events, and the source the public site publishes from. Open one for its
        full roster and the tasks you took on.
      </p>
      {summary && <Overview summary={summary} />}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
        {events.map((e) => (
          <div
            key={e.id}
            role="button"
            tabIndex={0}
            onClick={() => navigate(`/archive/${e.id}`)}
            onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); navigate(`/archive/${e.id}`); } }}
            style={{
              textAlign: 'left', cursor: 'pointer', border: '1px solid rgba(120,170,230,.14)', borderRadius: 14,
              background: 'rgba(15,20,29,.55)', padding: '18px 18px 16px', color: 'inherit',
            }}
          >
            {e.kind_name && (
              <div style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.14em', textTransform: 'uppercase', color: '#c58bff', marginBottom: 8 }}>{e.kind_name}</div>
            )}
            <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 16, color: '#eaf2ff', marginBottom: e.full_name ? 2 : 10 }}>{e.name}</div>
            {e.full_name && (
              <div style={{ fontSize: 12, color: 'rgba(224,236,252,.45)', marginBottom: 10 }}>{e.full_name}</div>
            )}
            <div style={{ fontFamily: MONO, fontSize: 11, color: 'rgba(224,236,252,.45)' }}>{fmtRange(e.start_date, e.end_date)}</div>
            {e.awards && e.awards.length > 0 && (
              <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {e.awards.map((a) => <AwardTag key={a} award={a} />)}
              </div>
            )}
            {e.can_manage && (
              <Button
                size="small"
                style={{ marginTop: 12 }}
                onClick={(ev) => { ev.stopPropagation(); reactivate(e.id); }}
              >
                Reactivate
              </Button>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

/** Event-wide placements. Free-form chips — type one and press enter. */
function AwardsEditor({ awards, canManage, onSave }: {
  awards: string[] | null | undefined;
  canManage: boolean;
  onSave: (awards: string[]) => void;
}) {
  const list = awards ?? [];
  if (!canManage) {
    if (list.length === 0) return null;
    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 16 }}>
        {list.map((a) => <AwardTag key={a} award={a} />)}
      </div>
    );
  }
  return (
    <div style={{ marginBottom: 16, maxWidth: 620 }}>
      <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.1em', textTransform: 'uppercase', color: 'rgba(224,236,252,.4)', marginBottom: 4 }}>
        Awards — published in the Hall of Fame
      </div>
      <Select
        mode="tags"
        style={{ width: '100%' }}
        placeholder="e.g. 🥇 1st Place — Sumo, Best Documentation"
        value={list}
        open={false}
        tokenSeparators={[',']}
        onChange={(v: string[]) => onSave(v.map((s) => s.trim()).filter(Boolean))}
      />
    </div>
  );
}

/** The event's roster exactly as the public site shows it: one card per team,
 * its placement, and every member with their competition role. Managers edit
 * placements and roles in place — the archive is the source of truth. */
function Roster({ groups, canManage, onChanged }: {
  groups: ArchivedGroup[];
  canManage: boolean;
  onChanged: () => void;
}) {
  if (groups.length === 0) return null;
  return (
    <>
      <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.12em', textTransform: 'uppercase', color: 'rgba(224,236,252,.4)', margin: '4px 0 10px' }}>
        Roster
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12, marginBottom: 26 }}>
        {groups.map((g) => (
          <div key={g.id} style={{ border: '1px solid rgba(120,170,230,.14)', borderRadius: 12, background: 'rgba(15,20,29,.55)', padding: '14px 16px' }}>
            <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 15, color: '#eaf2ff' }}>{g.label}</div>
            {g.sublabel && <div style={{ fontSize: 12, color: '#5cc6ff', marginTop: 1 }}>{g.sublabel}</div>}
            <div style={{ marginTop: 6 }}>
              {canManage ? (
                <Typography.Text
                  type={g.award ? undefined : 'secondary'}
                  style={{ fontSize: 12 }}
                  editable={{
                    tooltip: 'Set placement',
                    text: g.award ?? '',
                    onChange: (val) => {
                      const award = val.trim();
                      if (award === (g.award ?? '')) return;
                      run(
                        api.patch(`/api/archive/teams/${g.id}`, award ? { award } : { clear_award: true }),
                        'Placement updated',
                        onChanged,
                      );
                    },
                  }}
                >
                  {g.award || '🏆 Add placement'}
                </Typography.Text>
              ) : (
                g.award && <AwardTag award={g.award} />
              )}
            </div>
            <ul style={{ listStyle: 'none', padding: 0, margin: '10px 0 0', display: 'grid', gap: 5 }}>
              {g.members.map((m) => (
                <li key={m.id} style={{ fontSize: 13, color: 'rgba(224,236,252,.7)', lineHeight: 1.3 }}>
                  {m.name}
                  {canManage ? (
                    <>
                      {' '}
                      <Typography.Text
                        type="secondary"
                        style={{ fontSize: 12 }}
                        editable={{
                          tooltip: 'Set competition role',
                          text: m.role ?? '',
                          onChange: (val) => {
                            const role = val.trim();
                            if (role === (m.role ?? '')) return;
                            run(
                              api.patch(`/api/archive/members/${m.id}`, role ? { role } : { clear_role: true }),
                              'Role updated',
                              onChanged,
                            );
                          },
                        }}
                      >
                        {m.role ? `· ${m.role}` : '· role'}
                      </Typography.Text>
                    </>
                  ) : (
                    m.role && <span style={{ color: 'rgba(224,236,252,.4)' }}> · {m.role}</span>
                  )}
                </li>
              ))}
              {g.members.length === 0 && (
                <li style={{ fontSize: 12, color: 'rgba(224,236,252,.35)' }}>No members recorded</li>
              )}
            </ul>
          </div>
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

  const load = useCallback(() => {
    setLoading(true);
    api.get<ArchivedEventDetail>(`/api/archive/events/${eventId}`).then(setDetail).finally(() => setLoading(false));
  }, [eventId]);

  useEffect(load, [load]);

  const done = detail?.tasks.filter((t) => t.outcome === 'accomplished').length ?? 0;
  const total = detail?.tasks.length ?? 0;
  const canManage = detail?.event.can_manage ?? false;

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
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
            <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>{detail.event.name}</h2>
            {detail.event.kind_name && (
              <span style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.12em', textTransform: 'uppercase', color: '#c58bff', border: '1px solid rgba(197,139,255,.3)', background: 'rgba(197,139,255,.08)', padding: '2px 8px', borderRadius: 5 }}>{detail.event.kind_name}</span>
            )}
          </div>

          {/* The official title the public site heads this record with. */}
          <div style={{ marginBottom: 8 }}>
            {canManage ? (
              <Typography.Text
                type={detail.event.full_name ? undefined : 'secondary'}
                style={{ fontSize: 13 }}
                editable={{
                  tooltip: 'Set the official full name',
                  text: detail.event.full_name ?? '',
                  onChange: (val) => {
                    const full_name = val.trim();
                    if (full_name === (detail.event.full_name ?? '')) return;
                    run(
                      api.patch(`/api/archive/events/${eventId}`, full_name ? { full_name } : { clear_full_name: true }),
                      'Full name updated',
                      load,
                    );
                  },
                }}
              >
                {detail.event.full_name || 'Add the official full name'}
              </Typography.Text>
            ) : (
              detail.event.full_name && (
                <span style={{ fontSize: 13, color: 'rgba(224,236,252,.5)' }}>{detail.event.full_name}</span>
              )
            )}
          </div>

          <div style={{ fontFamily: MONO, fontSize: 12, color: 'rgba(224,236,252,.5)', marginBottom: 14 }}>
            {fmtRange(detail.event.start_date, detail.event.end_date)}
            {detail.teams.length > 0 && <> · your team{detail.teams.length > 1 ? 's' : ''}: {detail.teams.join(', ')}</>}
          </div>

          <AwardsEditor
            awards={detail.event.awards}
            canManage={canManage}
            onSave={(awards) =>
              run(
                api.patch(`/api/archive/events/${eventId}`, awards.length ? { awards } : { clear_awards: true }),
                'Awards updated',
                load,
              )
            }
          />

          <Roster groups={detail.groups} canManage={canManage} onChanged={load} />

          <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.12em', textTransform: 'uppercase', color: 'rgba(224,236,252,.4)', margin: '4px 0 10px' }}>
            Your tasks
          </div>
          {total === 0 ? (
            <Empty description="You held no tasks in this event" style={{ marginTop: 20 }} />
          ) : (
            <>
              <p style={{ fontFamily: MONO, fontSize: 12, color: 'rgba(224,236,252,.6)', margin: '0 0 14px' }}>
                You accomplished <span style={{ color: '#5cc6ff', fontWeight: 600 }}>{done}</span> of {total} task{total > 1 ? 's' : ''}.
              </p>
              <Table<ArchivedTask> className="circuit-table" rowKey={(r) => r.task.id} loading={loading} dataSource={detail.tasks}
                pagination={{ defaultPageSize: 15, hideOnSinglePage: true }} scroll={{ x: 'max-content' }}
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
