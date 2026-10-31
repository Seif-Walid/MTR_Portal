import {
  Alert, Button, Descriptions, Drawer, Empty, Input, Popconfirm, Select, Space, Table, Typography, message, theme,
} from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { Application, ApplicationStatus } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import { APPLICATION_STATUS, ApplicationStatusTag } from '../components/tags';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

type Filter = ApplicationStatus | 'all';
const FILTERS: Filter[] = ['new', 'contacted', 'accepted', 'declined', 'all'];

const subteamLabel = (s: string | null) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : 'Not sure yet');

// wa.me wants the number in international form; the form is Egyptian-first,
// so a local 01x… number gets the +20 country code.
function whatsappUrl(phone: string): string {
  let d = phone.replace(/\D/g, '');
  if (d.startsWith('00')) d = d.slice(2);
  else if (d.startsWith('0')) d = `20${d.slice(1)}`;
  return `https://wa.me/${d}`;
}

function ApplicationDrawer({
  app,
  canEdit,
  onClose,
  onChanged,
}: {
  app: Application | null;
  canEdit: boolean;
  onClose: () => void;
  onChanged: (a: Application) => void;
}) {
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => setNotes(app?.notes ?? ''), [app?.id, app?.notes]);

  const run = async (call: () => Promise<Application>, done: string) => {
    setBusy(true);
    try {
      onChanged(await call());
      message.success(done);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  };

  const setStatus = (status: ApplicationStatus) =>
    app && run(() => api.patch<Application>(`/api/applications/${app.id}`, { status }), `Marked ${APPLICATION_STATUS[status].label.toLowerCase()}`);
  const saveNotes = () =>
    app && run(() => api.patch<Application>(`/api/applications/${app.id}`, { notes }), 'Notes saved');
  const addToRoster = () =>
    app && run(() => api.post<Application>(`/api/applications/${app.id}/add-to-roster`), 'On the roster');

  const match = app?.roster_matches[0];

  return (
    <Drawer
      open={app !== null}
      onClose={onClose}
      width={Math.min(640, window.innerWidth)}
      title={
        app && (
          <Space direction="vertical" size={0}>
            <span>{app.full_name}</span>
            <span className="u-mono" style={{ fontSize: 12, fontWeight: 400, color: token.colorTextTertiary }}>
              applied {dayjs(app.created_at).format('D MMM YYYY, HH:mm')}
              {app.updated_at !== app.created_at && ` · updated ${dayjs(app.updated_at).format('D MMM, HH:mm')}`}
            </span>
          </Space>
        )
      }
      extra={
        app && canEdit && (
          <Select
            value={app.status}
            disabled={busy}
            style={{ width: 140 }}
            onChange={setStatus}
            options={(Object.keys(APPLICATION_STATUS) as ApplicationStatus[]).map((s) => ({ value: s, label: APPLICATION_STATUS[s].label }))}
          />
        )
      }
    >
      {app && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {app.member_id != null ? (
            <Alert
              type="success"
              showIcon
              message={`On the roster as ${app.member_mtr_id ?? `member #${app.member_id}`}`}
              action={<Button size="small" onClick={() => navigate('/members')}>Members</Button>}
            />
          ) : app.roster_matches.length > 0 ? (
            <Alert
              type="info"
              showIcon
              message="Already on the roster?"
              description={app.roster_matches
                .map((m) => `${m.name}${m.mtr_id ? ` (${m.mtr_id})` : ''} — same ${m.matched_on.join(' & ')}`)
                .join('; ')}
            />
          ) : null}

          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="Email"><a href={`mailto:${app.email}`}>{app.email}</a></Descriptions.Item>
            <Descriptions.Item label="Phone">
              <Space size={10}>
                <span>{app.phone}</span>
                <a href={whatsappUrl(app.phone)} target="_blank" rel="noreferrer">WhatsApp</a>
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="School">{app.school}</Descriptions.Item>
            <Descriptions.Item label="Year">{app.year}</Descriptions.Item>
            <Descriptions.Item label="Applied to">{app.event_name ?? 'The team'}</Descriptions.Item>
            <Descriptions.Item label="Subteam">{subteamLabel(app.subteam)}</Descriptions.Item>
            {app.reviewed_by && (
              <Descriptions.Item label="Last status change">
                {app.reviewed_by} · {app.reviewed_at ? dayjs(app.reviewed_at).format('D MMM YYYY') : ''}
              </Descriptions.Item>
            )}
          </Descriptions>

          <div>
            <Typography.Title level={5} style={{ marginTop: 0 }}>Why they want to join</Typography.Title>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{app.motivation}</Typography.Paragraph>
          </div>

          <div>
            <Typography.Title level={5} style={{ marginTop: 0 }}>Notes</Typography.Title>
            <Input.TextArea
              rows={4}
              value={notes}
              disabled={!canEdit}
              placeholder={canEdit ? 'Calls, first session, who is following up…' : 'No notes'}
              onChange={(e) => setNotes(e.target.value)}
            />
            {canEdit && (
              <Button style={{ marginTop: 8 }} disabled={busy || notes === (app.notes ?? '')} onClick={saveNotes}>
                Save notes
              </Button>
            )}
          </div>

          {canEdit && app.member_id == null && (
            <Popconfirm
              title={match ? `Link to ${match.name}?` : 'Add to the roster?'}
              description={
                match
                  ? 'They already share an email or phone with this roster member.'
                  : 'Creates a roster member with the next MTR ID and marks the application accepted.'
              }
              okText={match ? 'Link' : 'Add'}
              onConfirm={addToRoster}
              disabled={app.roster_matches.length > 1}
            >
              <Button type="primary" loading={busy} disabled={app.roster_matches.length > 1}>
                {match ? 'Accept & link to roster member' : 'Accept & add to roster'}
              </Button>
            </Popconfirm>
          )}
        </div>
      )}
    </Drawer>
  );
}

export default function ApplicationsPage() {
  const { me } = useAuth();
  const [rows, setRows] = useState<Application[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Filter>('new');
  const [search, setSearch] = useState('');
  const [params, setParams] = useSearchParams();
  const openId = Number(params.get('id')) || null;

  const load = useCallback(() => {
    setLoading(true);
    api.get<Application[]>('/api/applications')
      .then(setRows)
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Could not load applications'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { new: 0, contacted: 0, accepted: 0, declined: 0, all: rows.length };
    rows.forEach((r) => { c[r.status] += 1; });
    return c;
  }, [rows]);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) =>
      (filter === 'all' || r.status === filter)
      && (!q || [r.full_name, r.email, r.phone, r.school, r.event_name ?? ''].some((v) => v.toLowerCase().includes(q))));
  }, [rows, filter, search]);

  if (!can(me, 'members.view')) {
    return <Empty description="Your access level does not include the member roster" />;
  }

  const open = (id: number | null) => setParams((p) => {
    const next = new URLSearchParams(p);
    if (id == null) next.delete('id'); else next.set('id', String(id));
    return next;
  });

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>Join applications</h2>
        <Input.Search allowClear placeholder="Name, email, phone, school" style={{ width: 280 }}
          value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      <div style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4, background: 'rgba(8,11,17,.6)', border: '1px solid rgba(120,170,230,.12)', borderRadius: 10, padding: 4, marginBottom: 20 }}>
        {FILTERS.map((f) => {
          const on = filter === f;
          return (
            <div key={f} onClick={() => setFilter(f)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '7px 16px', borderRadius: 7, fontSize: 13, cursor: 'pointer',
                color: on ? '#eaf2ff' : 'rgba(224,236,252,.5)',
                background: on ? 'linear-gradient(90deg,rgba(92,198,255,.2),rgba(92,198,255,.05))' : 'transparent',
                border: `1px solid ${on ? 'rgba(92,198,255,.3)' : 'transparent'}`,
              }}>
              {f === 'all' ? 'All' : APPLICATION_STATUS[f].label}
              <span style={{ fontFamily: MONO, fontSize: 10, color: on ? '#5cc6ff' : 'inherit' }}>{counts[f]}</span>
            </div>
          );
        })}
      </div>

      <Table className="circuit-table" rowKey="id" loading={loading} dataSource={shown}
        pagination={{ defaultPageSize: 20, hideOnSinglePage: true }} scroll={{ x: 'max-content' }}
        onRow={(r) => ({ onClick: () => open(r.id), style: { cursor: 'pointer' } })}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={rows.length ? 'Nothing here' : 'No applications yet'} /> }}
        columns={[
          {
            title: 'Applicant',
            render: (_, r) => (
              <div>
                <div>{r.full_name}</div>
                <div style={{ fontFamily: MONO, fontSize: 11, color: 'rgba(224,236,252,.45)' }}>{r.email}</div>
              </div>
            ),
          },
          { title: 'Applied to', dataIndex: 'event_name', width: 170, ellipsis: true, render: (e: string | null) => e ?? 'The team' },
          { title: 'Year', dataIndex: 'year', width: 190 },
          { title: 'School', dataIndex: 'school', ellipsis: true },
          { title: 'Subteam', dataIndex: 'subteam', width: 130, render: subteamLabel },
          {
            title: 'Roster', width: 120,
            render: (_, r) => (r.member_mtr_id
              ? <span style={{ fontFamily: MONO, fontSize: 12 }}>{r.member_mtr_id}</span>
              : r.roster_matches.length ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>possible match</Typography.Text> : null),
          },
          { title: 'Received', dataIndex: 'created_at', width: 120, render: (d: string) => dayjs(d).format('DD MMM') },
          { title: 'Status', dataIndex: 'status', width: 120, render: (s: ApplicationStatus) => <ApplicationStatusTag status={s} /> },
        ]} />

      <ApplicationDrawer
        app={rows.find((r) => r.id === openId) ?? null}
        canEdit={can(me, 'members.edit')}
        onClose={() => open(null)}
        onChanged={(a) => setRows((prev) => prev.map((r) => (r.id === a.id ? a : r)))}
      />
    </>
  );
}
