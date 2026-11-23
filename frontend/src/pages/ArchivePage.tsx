import { AutoComplete, Button, Form, Input, Modal, Popconfirm, Select, Table, Tag, Typography, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type {
  ArchivedEvent,
  ArchivedEventDetail,
  ArchivedGroup,
  ArchivedStaff,
  ArchivedTask,
  ArchiveKind,
  ArchiveSummary,
  UserBrief,
} from '../api/types';
import { AwardTag, StatusTag } from '../components/tags';
import TaskDrawer from '../components/TaskDrawer';
import { openableRow } from '../components/a11y';
import { CloseOutlined } from '@ant-design/icons';
import EmptyState from '../components/EmptyState';

const MONO = 'var(--font-mono)';
const DISPLAY = 'var(--font-display)';

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
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
        gap: 8,
        borderRadius: 14, overflow: 'hidden', marginBottom: 22,
      }}
    >
      {stats.map(([label, value]) => (
        <div key={label} style={{ background: 'color-mix(in srgb, var(--text-primary) 2.5%, transparent)', borderRadius: 14, padding: '14px 16px' }}>
          <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 24, lineHeight: 1, color: 'var(--text-primary)' }}>{value}</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginTop: 8 }}>{label}</div>
        </div>
      ))}
    </div>
  );
}

/** Year an archived event belongs to, for grouping — its start, else its end. */
function yearOf(e: ArchivedEvent): string {
  const d = e.start_date ?? e.end_date;
  return d ? d.slice(0, 4) : 'Undated';
}

const plural = (label: string, n: number) => `${n} ${label.toLowerCase()}${n === 1 ? '' : 's'}`;

/** The kind switch — the same sections Events has, each with its count. */
function KindSwitch({ kinds, slug, onPick }: { kinds: ArchiveKind[]; slug: string | undefined; onPick: (slug: string) => void }) {
  if (kinds.length < 2) return null;
  return (
    <div className="mtr-pills" role="tablist">
      {kinds.map((k) => {
        const on = k.slug === slug;
        return (
          <div
            key={k.id}
            role="tab"
            tabIndex={0}
            aria-selected={on}
            onClick={() => onPick(k.slug)}
            onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onPick(k.slug); } }}
            className={`mtr-pill${on ? ' on' : ''}`}
          >
            {k.name}
            <span style={{ fontFamily: MONO, fontSize: 11, marginLeft: 8, color: on ? 'var(--brand-fg)' : 'var(--text-tertiary)' }}>{k.count}</span>
          </div>
        );
      })}
    </div>
  );
}

function EventCard({ e, onOpen, onReactivate }: { e: ArchivedEvent; onOpen: () => void; onReactivate: () => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onOpen(); } }}
      style={{
        textAlign: 'left', cursor: 'pointer', border: 'none', borderRadius: 18,
        background: 'color-mix(in srgb, var(--text-primary) 2.5%, transparent)', padding: '18px 18px 16px', color: 'inherit',
      }}
    >
      <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 16, color: 'var(--text-primary)', marginBottom: e.full_name ? 2 : 10 }}>{e.name}</div>
      {e.full_name && (
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 10 }}>{e.full_name}</div>
      )}
      <div style={{ fontFamily: MONO, fontSize: 11, color: 'var(--text-tertiary)' }}>{fmtRange(e.start_date, e.end_date)}</div>
      {e.awards && e.awards.length > 0 && (
        <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {e.awards.map((a) => <AwardTag key={a} award={a} />)}
        </div>
      )}
      {e.can_manage && (
        <Button
          size="small"
          style={{ marginTop: 12 }}
          onClick={(ev) => { ev.stopPropagation(); onReactivate(); }}
        >
          Reactivate
        </Button>
      )}
    </div>
  );
}

/** The archive, sectioned the way Events is — one section per event kind
 * (Competition, Training, R&D, any the admin adds) — and within a section,
 * grouped by year, newest first. */
function EventList() {
  const [kinds, setKinds] = useState<ArchiveKind[]>([]);
  const [events, setEvents] = useState<ArchivedEvent[]>([]);
  const [summary, setSummary] = useState<ArchiveSummary | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();

  const loadKinds = useCallback(() => {
    api.get<ArchiveKind[]>('/api/archive/kinds').then(setKinds).catch(() => setKinds([])).finally(() => setLoaded(true));
  }, []);
  useEffect(loadKinds, [loadKinds]);
  useEffect(() => {
    api.get<ArchiveSummary>('/api/archive/summary').then(setSummary).catch(() => setSummary(null));
  }, []);

  // Default section: the first kind that has anything archived.
  const slug = params.get('kind') ?? (kinds.find((k) => k.count > 0) ?? kinds[0])?.slug;
  const kind = kinds.find((k) => k.slug === slug);

  useEffect(() => {
    if (!kind) return;
    api.get<ArchivedEvent[]>(`/api/archive/events?kind_id=${kind.id}`).then(setEvents).catch(() => setEvents([]));
  }, [kind]);

  const byYear = useMemo(() => {
    const out: [string, ArchivedEvent[]][] = [];
    for (const e of events) {
      const y = yearOf(e);
      const last = out[out.length - 1];
      if (last && last[0] === y) last[1].push(e);
      else out.push([y, [e]]);
    }
    // the API sorts dated events newest first, undated last — keep that
    return out;
  }, [events]);

  const reactivate = async (id: number) => {
    try {
      await api.post(`/api/archive/events/${id}/reactivate`);
      message.success('Reactivated');
      setEvents((es) => es.filter((e) => e.id !== id));
      loadKinds();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };

  const total = kinds.reduce((n, k) => n + k.count, 0);

  return (
    <>
      <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: '0 0 6px', color: 'var(--text-primary)' }}>Archive</h2>
      <p style={{ color: 'var(--text-tertiary)', margin: '0 0 22px', fontSize: 13 }}>
        The record of past events, and the source the public site publishes from. Open one for its
        full roster, who ran it, and the tasks you took on.
      </p>
      {loaded && total === 0 ? (
        <EmptyState phrase="No archived events yet. Finished events land here." action={{ label: 'See current events', to: '/events' }} />
      ) : (
        <>
          <KindSwitch kinds={kinds} slug={slug} onPick={(s) => setParams({ kind: s }, { replace: true })} />
          {/* The Hall-of-Fame headline counts competitions only, so it heads that section alone. */}
          {kind?.slug === 'competition' && summary && <Overview summary={summary} />}
          {kind && kind.count === 0 && (
            <EmptyState phrase={`No archived ${kind.event_label.toLowerCase()}s yet.`} action={{ label: 'See current events', to: '/events' }} />
          )}
          {kind && kind.count > 0 && (
            <div style={{ fontFamily: MONO, fontSize: 11, color: 'var(--text-tertiary)', margin: '0 0 14px' }}>
              {plural(kind.event_label, kind.count)} archived
            </div>
          )}
          {byYear.map(([year, list]) => (
            <section key={year} style={{ marginBottom: 26 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
                <span style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 17, color: 'var(--text-primary)' }}>{year}</span>
                <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
                  {kind ? plural(kind.event_label, list.length) : list.length}
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
                {list.map((e) => (
                  <EventCard key={e.id} e={e} onOpen={() => navigate(`/archive/${e.id}`)} onReactivate={() => reactivate(e.id)} />
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </>
  );
}

/** Event-wide placements. Free-form chips — type one and press enter. */
function AwardsEditor({ awards, canEdit, onSave }: {
  awards: string[] | null | undefined;
  canEdit: boolean;
  onSave: (awards: string[]) => void;
}) {
  const list = awards ?? [];
  if (!canEdit) {
    if (list.length === 0) return null;
    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 16 }}>
        {list.map((a) => <AwardTag key={a} award={a} />)}
      </div>
    );
  }
  return (
    <div style={{ marginBottom: 16, maxWidth: 620 }}>
      <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)', marginBottom: 4 }}>
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

const EYEBROW = { fontSize: 11.5, color: 'var(--text-tertiary)' };

/** Who held a role seat — the PMs, coaches, leads … recorded when the event was
 * archived. Managers can strike a wrong entry. */
function StaffLines({ staff, canEdit, onChanged }: { staff: ArchivedStaff[]; canEdit: boolean; onChanged: () => void }) {
  if (staff.length === 0) return null;
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 5 }}>
      {staff.map((s) => (
        <li key={s.id} style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.3, display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 11.5, color: 'var(--cat-violet)', minWidth: 0 }}>{s.role}</span>
          <span>{s.name}</span>
          {s.team && <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>· {s.team}</span>}
          {canEdit && (
            <Popconfirm title={`Remove ${s.name} as ${s.role}?`} onConfirm={() => run(api.delete(`/api/archive/staff/${s.id}`), 'Removed', onChanged)}>
              <button type="button" className="mtr-link-btn" style={{ fontSize: 11, color: 'var(--text-tertiary)', marginInlineStart: 'auto' }} aria-label={`Remove ${s.name}`}><CloseOutlined /></button>
            </Popconfirm>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Record someone in a role by hand — how staff an event lost before the
 * archive kept them gets put back. A portal account, or just a typed name. */
function AddStaffModal({ eventId, groups, teamLabel, teamId, open, onClose, onSaved }: {
  eventId: number;
  groups: ArchivedGroup[];
  teamLabel: string;
  teamId: number | null; // preset: the card it was opened from, or event-wide
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form] = Form.useForm<{ role: string; team: number | 'event'; person: string }>();
  const [people, setPeople] = useState<UserBrief[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    // the people picker needs people.view; without it, names are typed
    api.get<UserBrief[]>('/api/users/directory').then(setPeople).catch(() => setPeople([]));
  }, [open]);

  const submit = async () => {
    const v = await form.validateFields();
    const name = v.person.trim();
    const match = people.find((u) => u.full_name.toLowerCase() === name.toLowerCase());
    setSaving(true);
    try {
      await api.post(`/api/archive/events/${eventId}/staff`, {
        role: v.role.trim(),
        team_id: v.team === 'event' ? null : v.team,
        ...(match ? { user_id: match.id } : { name }),
      });
      message.success('Recorded');
      onSaved();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Record staff" open={open} onCancel={onClose} onOk={submit} okText="Record" confirmLoading={saving} destroyOnHidden>
      <Form form={form} layout="vertical" initialValues={{ role: '', team: teamId ?? 'event', person: '' }}>
        <Form.Item name="role" label="Role" rules={[{ required: true, whitespace: true, message: 'What did they do?' }]}>
          <Input placeholder="e.g. coach, PM, mentor" />
        </Form.Item>
        <Form.Item name="team" label="For">
          <Select
            options={[
              { value: 'event', label: 'The whole event' },
              ...groups.map((g) => ({ value: g.id, label: `${teamLabel}: ${g.label}` })),
            ]}
          />
        </Form.Item>
        <Form.Item name="person" label="Person" rules={[{ required: true, whitespace: true, message: 'Pick someone or type a name' }]}
          extra="Pick a portal member, or type the name of someone without an account.">
          <AutoComplete
            options={people.map((u) => ({ value: u.full_name }))}
            filterOption={(input, option) => (option?.value ?? '').toLowerCase().includes(input.toLowerCase())}
            placeholder="Name"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** The event's own staff — its event-wide seats (PMs …) plus the free-text
 * mentors/captains its record carries. */
function EventStaff({ staff, mentors, captains, canEdit, onAdd, onChanged }: {
  staff: ArchivedStaff[];
  mentors?: string | null;
  captains?: string | null;
  canEdit: boolean;
  onAdd: () => void;
  onChanged: () => void;
}) {
  if (staff.length === 0 && !mentors && !captains && !canEdit) return null;
  return (
    <div style={{ marginBottom: 22, maxWidth: 620 }}>
      <div style={{ ...EYEBROW, display: 'flex', alignItems: 'center', gap: 12, margin: '4px 0 10px' }}>
        Staff
        {canEdit && <button type="button" className="mtr-link-btn" onClick={onAdd} style={{ fontSize: 10, color: 'var(--brand-fg)' }}>+ Record staff</button>}
      </div>
      <StaffLines staff={staff} canEdit={canEdit} onChanged={onChanged} />
      {mentors && <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 6 }}><span style={{ color: 'var(--text-tertiary)' }}>Mentors · </span>{mentors}</div>}
      {captains && <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}><span style={{ color: 'var(--text-tertiary)' }}>Captains · </span>{captains}</div>}
      {staff.length === 0 && !mentors && !captains && (
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>No event-wide staff recorded</div>
      )}
    </div>
  );
}

/** The event's roster exactly as the public site shows it: one card per team,
 * its placement, and every member with their competition role. Managers edit
 * placements and roles in place — the archive is the source of truth. */
function Roster({ groups, teamLabel, canEdit, onChanged, onAddStaff }: {
  groups: ArchivedGroup[];
  teamLabel: string;
  canEdit: boolean;
  onChanged: () => void;
  onAddStaff: (teamId: number) => void;
}) {
  if (groups.length === 0) return null;
  return (
    <>
      <div style={{ ...EYEBROW, margin: '4px 0 10px' }}>
        {teamLabel}s
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12, marginBottom: 26 }}>
        {groups.map((g) => (
          <div key={g.id} style={{ borderRadius: 16, background: 'color-mix(in srgb, var(--text-primary) 2.5%, transparent)', padding: '14px 16px' }}>
            <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 15, color: 'var(--text-primary)' }}>{g.label}</div>
            {g.sublabel && <div style={{ fontSize: 12, color: 'var(--brand-fg)', marginTop: 1 }}>{g.sublabel}</div>}
            <div style={{ marginTop: 6 }}>
              {canEdit ? (
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
            {(g.staff.length > 0 || canEdit) && (
              <div style={{ marginTop: 10, paddingBottom: 8, borderBottom: '1px solid var(--border-light)' }}>
                <StaffLines staff={g.staff} canEdit={canEdit} onChanged={onChanged} />
                {canEdit && (
                  <button type="button" className="mtr-link-btn" onClick={() => onAddStaff(g.id)} style={{ display: 'inline-block', fontSize: 11, color: 'var(--brand-fg)', marginTop: g.staff.length ? 6 : 0 }}>+ Record staff</button>
                )}
              </div>
            )}
            <ul style={{ listStyle: 'none', padding: 0, margin: '10px 0 0', display: 'grid', gap: 5 }}>
              {g.members.map((m) => (
                <li key={m.id} style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.3 }}>
                  {m.name}
                  {canEdit ? (
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
                    m.role && <span style={{ color: 'var(--text-tertiary)' }}> · {m.role}</span>
                  )}
                </li>
              ))}
              {g.members.length === 0 && g.staff.length === 0 && (
                <li style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>No members recorded</li>
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
  // the Record-staff modal: undefined = closed, null = event-wide, else a team
  const [staffFor, setStaffFor] = useState<number | null | undefined>(undefined);
  const navigate = useNavigate();

  const load = useCallback(() => {
    setLoading(true);
    api.get<ArchivedEventDetail>(`/api/archive/events/${eventId}`).then(setDetail).finally(() => setLoading(false));
  }, [eventId]);

  useEffect(load, [load]);

  const done = detail?.tasks.filter((t) => t.outcome === 'accomplished').length ?? 0;
  const total = detail?.tasks.length ?? 0;
  const canEdit = detail?.event.can_edit ?? false;
  const teamLabel = detail?.event.team_label || 'Team';
  const back = detail?.event.kind_slug ? `/archive?kind=${detail.event.kind_slug}` : '/archive';

  return (
    <>
      <button
        onClick={() => navigate(back)}
        style={{ cursor: 'pointer', background: 'transparent', border: 'none', color: 'var(--brand-fg)', fontFamily: MONO, fontSize: 11, letterSpacing: '.08em', padding: 0, marginBottom: 16 }}
      >
        ← Back to archive
      </button>

      {detail && (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
            <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: 'var(--text-primary)' }}>{detail.event.name}</h2>
            {detail.event.kind_name && (
              <span style={{ fontSize: 11.5, color: 'var(--cat-violet)', background: 'color-mix(in srgb, var(--cat-violet) 8%, transparent)', padding: '2px 8px', borderRadius: 999 }}>{detail.event.kind_name}</span>
            )}
          </div>

          {/* The official title the public site heads this record with. */}
          <div style={{ marginBottom: 8 }}>
            {canEdit ? (
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
                <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>{detail.event.full_name}</span>
              )
            )}
          </div>

          <div style={{ fontFamily: MONO, fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 14 }}>
            {fmtRange(detail.event.start_date, detail.event.end_date)}
            {detail.teams.length > 0 && <> · your team{detail.teams.length > 1 ? 's' : ''}: {detail.teams.join(', ')}</>}
          </div>

          <AwardsEditor
            awards={detail.event.awards}
            canEdit={canEdit}
            onSave={(awards) =>
              run(
                api.patch(`/api/archive/events/${eventId}`, awards.length ? { awards } : { clear_awards: true }),
                'Awards updated',
                load,
              )
            }
          />

          <EventStaff
            staff={detail.staff}
            mentors={detail.mentors}
            captains={detail.captains}
            canEdit={canEdit}
            onAdd={() => setStaffFor(null)}
            onChanged={load}
          />

          <Roster groups={detail.groups} teamLabel={teamLabel} canEdit={canEdit} onChanged={load} onAddStaff={setStaffFor} />

          <AddStaffModal
            eventId={eventId}
            groups={detail.groups}
            teamLabel={teamLabel}
            teamId={staffFor ?? null}
            open={staffFor !== undefined}
            onClose={() => setStaffFor(undefined)}
            onSaved={load}
          />

          <div style={{ ...EYEBROW, margin: '4px 0 10px' }}>
            Your tasks
          </div>
          {total === 0 ? (
            <EmptyState compact phrase="You held no tasks in this event." action={{ label: 'Open my tasks', to: '/tasks' }} />
          ) : (
            <>
              <p style={{ fontFamily: MONO, fontSize: 12, color: 'var(--text-tertiary)', margin: '0 0 14px' }}>
                You accomplished <span style={{ color: 'var(--brand-fg)', fontWeight: 600 }}>{done}</span> of {total} task{total > 1 ? 's' : ''}.
              </p>
              <Table<ArchivedTask> className="circuit-table" rowKey={(r) => r.task.id} loading={loading} dataSource={detail.tasks}
                pagination={{ defaultPageSize: 15, hideOnSinglePage: true }} scroll={{ x: 'max-content' }}
                onRow={(r) => openableRow(() => setOpenTask(r.task.id))}
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
