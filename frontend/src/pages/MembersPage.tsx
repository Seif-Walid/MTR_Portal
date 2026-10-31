import { PlusOutlined, SearchOutlined, WarningOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Checkbox,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
  theme,
} from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { DuplicateHit, RosterMember, RosterMemberDetail, RosterStats } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import { StatRow, StatTile } from '../components/charts';

const dash = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v));

const CONFIDENCE: Record<string, { color: string; label: string }> = {
  high: { color: 'success', label: 'high' },
  single: { color: 'default', label: 'single source' },
  review: { color: 'warning', label: 'needs review' },
  manual: { color: 'processing', label: 'added by hand' },
};

const FIELDS: { name: string; label: string; kind?: 'number' | 'date' | 'datetime' }[] = [
  { name: 'full_name', label: 'Name' },
  { name: 'mtr_id', label: 'MTR ID' },
  { name: 'email', label: 'Gmail' },
  { name: 'phone', label: 'Phone' },
  { name: 'national_id', label: 'National ID' },
  { name: 'birthday', label: 'Birthday', kind: 'date' },
  { name: 'location', label: 'Governorate' },
  { name: 'university', label: 'University' },
  { name: 'college', label: 'College' },
  { name: 'major', label: 'Major' },
  { name: 'uni_id', label: 'College ID' },
  { name: 'graduating_year', label: 'Graduating year', kind: 'number' },
  { name: 'guardian_phone', label: "Guardian's number" },
  { name: 'guardian_kinship', label: "Guardian's kinship" },
  { name: 'joined_at', label: 'First registration', kind: 'datetime' },
  { name: 'review_note', label: 'Review note' },
];

type FormValues = Record<string, string | number | dayjs.Dayjs | null | undefined>;

function toPayload(values: FormValues): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of FIELDS) {
    if (!(f.name in values)) continue;
    const v = values[f.name];
    if (v === undefined) continue;
    if (dayjs.isDayjs(v)) out[f.name] = f.kind === 'date' ? v.format('YYYY-MM-DD') : v.toISOString();
    else out[f.name] = v === '' ? null : v;
  }
  return out;
}

function toForm(m: RosterMemberDetail | null): FormValues {
  if (!m) return {};
  const v: FormValues = {};
  for (const f of FIELDS) {
    const raw = (m as unknown as Record<string, unknown>)[f.name];
    if (raw == null) v[f.name] = undefined;
    else if (f.kind === 'date' || f.kind === 'datetime') v[f.name] = dayjs(String(raw));
    else v[f.name] = raw as string | number;
  }
  if (!v.full_name) v.full_name = m.name;
  return v;
}

function MemberForm({ form, onChange }: { form: ReturnType<typeof Form.useForm<FormValues>>[0]; onChange?: () => void }) {
  return (
    <Form form={form} layout="vertical" onValuesChange={onChange} requiredMark={false}>
      <Row gutter={12}>
        {FIELDS.map((f) => (
          <Col key={f.name} xs={24} sm={f.name === 'review_note' ? 24 : 12}>
            <Form.Item
              name={f.name}
              label={f.label}
              style={{ marginBottom: 12 }}
              rules={f.name === 'full_name' ? [{ required: true, message: 'A member needs a name' }] : undefined}
            >
              {f.kind === 'number' ? (
                <InputNumber style={{ width: '100%' }} precision={0} />
              ) : f.kind === 'date' ? (
                <DatePicker style={{ width: '100%' }} />
              ) : f.kind === 'datetime' ? (
                <DatePicker showTime style={{ width: '100%' }} />
              ) : f.name === 'review_note' ? (
                <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} />
              ) : (
                <Input />
              )}
            </Form.Item>
          </Col>
        ))}
      </Row>
    </Form>
  );
}

export default function MembersPage() {
  const { me } = useAuth();
  const { token } = theme.useToken();
  const canEdit = can(me, 'members.edit');
  const [params, setParams] = useSearchParams();
  const openId = params.get('member') ? Number(params.get('member')) : null;

  const [rows, setRows] = useState<RosterMember[] | null>(null);
  const [stats, setStats] = useState<RosterStats | null>(null);
  const [q, setQ] = useState('');
  const [uni, setUni] = useState<string | undefined>();
  const [conf, setConf] = useState<string | undefined>();
  const [account, setAccount] = useState<string | undefined>();
  const [eventFilter, setEventFilter] = useState<string | undefined>();
  // accounts with no MTR ID aren't on the roster (admins, test logins, people
  // no longer in the member database) — hidden unless asked for
  const [showUnnumbered, setShowUnnumbered] = useState(false);

  const load = useCallback(() => {
    api.get<RosterMember[]>('/api/members').then(setRows).catch((e) => message.error(e.message));
    api.get<RosterStats>('/api/members/stats').then(setStats).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const universities = useMemo(
    () => Array.from(new Set((rows ?? []).map((r) => r.university).filter(Boolean) as string[])).sort(),
    [rows],
  );
  const eventCodes = useMemo(
    () => Array.from(new Set((rows ?? []).flatMap((r) => r.events))).sort(),
    [rows],
  );

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter((r) => {
      if (!showUnnumbered && !r.mtr_id) return false;
      if (uni && r.university !== uni) return false;
      if (conf && r.data_confidence !== conf) return false;
      if (account === 'claimed' && !r.claimed) return false;
      if (account === 'unclaimed' && r.claimed) return false;
      if (account === 'inactive' && r.is_active) return false;
      if (eventFilter && !r.events.includes(eventFilter)) return false;
      if (!needle) return true;
      return [r.name, r.mtr_id, r.email, r.phone, r.major, r.college, r.location]
        .some((v) => (v ?? '').toLowerCase().includes(needle));
    });
  }, [rows, q, uni, conf, account, eventFilter, showUnnumbered]);

  const [adding, setAdding] = useState(false);
  const t = stats?.totals;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <StatRow min={160}>
        <StatTile label="Members on roster" value={t ? String(t.members) : '—'} sub={t ? `${t.active_members} took part in an event` : undefined} />
        <StatTile label="Account set up" value={t ? String(t.claimed) : '—'} sub="Password or Google linked" />
        <StatTile label="Not set up yet" value={t ? String(t.unclaimed) : '—'} sub="Waiting for its owner to sign in" />
        <StatTile label="Participations" value={t ? String(t.participations) : '—'} sub="Member × event records" />
        <StatTile label="Needs review" value={t ? String(t.needs_review) : '—'} tone={t?.needs_review ? 'danger' : undefined} sub="Possible merge mistakes" />
      </StatRow>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <Input
          allowClear
          prefix={<SearchOutlined style={{ opacity: 0.5 }} />}
          placeholder="Search name, MTR ID, phone, Gmail…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ width: 280 }}
        />
        <Select allowClear placeholder="University" value={uni} onChange={setUni} style={{ minWidth: 150 }}
          options={universities.map((u) => ({ value: u, label: u }))} />
        <Select allowClear showSearch placeholder="Took part in" value={eventFilter} onChange={setEventFilter} style={{ minWidth: 150 }}
          options={eventCodes.map((c) => ({ value: c, label: c }))} />
        <Select allowClear placeholder="Data confidence" value={conf} onChange={setConf} style={{ minWidth: 150 }}
          options={Object.entries(CONFIDENCE).map(([value, c]) => ({ value, label: c.label }))} />
        <Select allowClear placeholder="Account" value={account} onChange={setAccount} style={{ minWidth: 140 }}
          options={[
            { value: 'claimed', label: 'Set up' },
            { value: 'unclaimed', label: 'Not set up yet' },
            { value: 'inactive', label: 'Deactivated' },
          ]} />
        {!!t?.unnumbered && (
          <Checkbox checked={showUnnumbered} onChange={(e) => setShowUnnumbered(e.target.checked)}>
            Include {t.unnumbered} {t.unnumbered === 1 ? 'person' : 'people'} without an MTR ID
          </Checkbox>
        )}
        <span style={{ flex: 1 }} />
        <Typography.Text type="secondary">{filtered.length} shown</Typography.Text>
        {canEdit && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAdding(true)}>
            Add member
          </Button>
        )}
      </div>

      <Table<RosterMember>
        size="small"
        rowKey="id"
        loading={rows === null}
        dataSource={filtered}
        className="circuit-table"
        onRow={(r) => ({ onClick: () => setParams({ member: String(r.id) }) })}
        pagination={{ defaultPageSize: 50, pageSizeOptions: [25, 50, 100, 400], showSizeChanger: true, size: 'small' }}
        scroll={{ x: 'max-content' }}
        columns={[
          {
            title: 'MTR ID', dataIndex: 'mtr_id', width: 96,
            sorter: (a, b) => (a.mtr_id ?? '~').localeCompare(b.mtr_id ?? '~'),
            defaultSortOrder: 'ascend',
            render: (v) => <span className="u-mono" style={{ fontSize: 12 }}>{dash(v)}</span>,
          },
          {
            title: 'Name', key: 'name', sorter: (a, b) => a.name.localeCompare(b.name),
            render: (_, r) => (
              <div>
                <div style={{ fontWeight: 500, color: token.colorText }}>
                  {r.name}
                  {r.data_confidence === 'review' && <WarningOutlined style={{ color: token.colorWarning, marginLeft: 6 }} />}
                </div>
                <div style={{ fontSize: 12, color: token.colorTextTertiary }}>{dash(r.email)}</div>
              </div>
            ),
          },
          { title: 'Phone', dataIndex: 'phone', render: (v) => <span className="u-mono" style={{ fontSize: 12 }}>{dash(v)}</span> },
          {
            title: 'Study', key: 'study',
            render: (_, r) => [r.university, r.major].filter(Boolean).join(' · ') || '—',
          },
          { title: 'Grad', dataIndex: 'graduating_year', width: 70, sorter: (a, b) => (a.graduating_year ?? 0) - (b.graduating_year ?? 0), render: dash },
          { title: 'Governorate', dataIndex: 'location', render: dash },
          {
            title: 'Events', key: 'events', width: 90, align: 'right',
            sorter: (a, b) => a.events.length - b.events.length,
            render: (_, r) => (r.events.length ? r.events.length : <span style={{ opacity: 0.35 }}>0</span>),
          },
          {
            title: 'Account', key: 'acct', width: 120,
            render: (_, r) =>
              !r.is_active ? <Tag>deactivated</Tag>
                : r.claimed ? <Tag color="processing">set up</Tag>
                  : <Tag>not set up</Tag>,
          },
        ]}
      />

      <MemberDrawer
        id={openId}
        canEdit={canEdit}
        onClose={() => setParams({})}
        onChanged={load}
      />
      {adding && (
        <AddMemberModal
          onClose={() => setAdding(false)}
          onCreated={(id) => {
            setAdding(false);
            load();
            setParams({ member: String(id) });
          }}
        />
      )}
    </div>
  );
}

function MemberDrawer({
  id,
  canEdit,
  onClose,
  onChanged,
}: {
  id: number | null;
  canEdit: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { token } = theme.useToken();
  const [m, setM] = useState<RosterMemberDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  useEffect(() => {
    setM(null);
    setEditing(false);
    if (id == null) return;
    api.get<RosterMemberDetail>(`/api/members/${id}`).then(setM).catch((e) => message.error(e.message));
  }, [id]);

  const startEdit = () => {
    form.setFieldsValue(toForm(m));
    setEditing(true);
  };

  const save = async () => {
    if (!m) return;
    const values = await form.validateFields();
    setSaving(true);
    try {
      const updated = await api.patch<RosterMemberDetail>(`/api/members/${m.id}`, toPayload(values));
      setM(updated);
      setEditing(false);
      onChanged();
      message.success('Saved');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!m) return;
    try {
      await api.delete(`/api/members/${m.id}`);
      message.success('Removed from the roster');
      onChanged();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not remove');
    }
  };

  return (
    <Drawer
      open={id != null}
      onClose={onClose}
      width={Math.min(720, window.innerWidth)}
      title={
        m ? (
          <Space direction="vertical" size={0}>
            <span>{m.name}</span>
            <span className="u-mono" style={{ fontSize: 12, fontWeight: 400, color: token.colorTextTertiary }}>
              {m.mtr_id ?? 'no MTR ID'} {m.claimed ? '· account set up' : m.email ? '· account not set up yet' : '· no email — can’t sign in yet'}
            </span>
          </Space>
        ) : (
          'Member'
        )
      }
      extra={
        canEdit && m && (
          editing ? (
            <Space>
              <Button onClick={() => setEditing(false)}>Cancel</Button>
              <Button type="primary" loading={saving} onClick={save}>Save</Button>
            </Space>
          ) : (
            <Space>
              {!m.claimed && (
                <Popconfirm title="Delete this member?" description="Only for duplicates or mistakes — their account and participations go with them." okText="Delete" okButtonProps={{ danger: true }} onConfirm={remove}>
                  <Button danger>Delete</Button>
                </Popconfirm>
              )}
              <Button type="primary" onClick={startEdit}>Edit</Button>
            </Space>
          )
        )
      }
    >
      {!m ? null : editing ? (
        <MemberForm form={form} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {m.review_note && <Alert type="warning" showIcon message="Flagged for review" description={m.review_note} />}
          <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
            <Descriptions.Item label="Gmail">{dash(m.email)}</Descriptions.Item>
            <Descriptions.Item label="Phone">{dash(m.phone)}</Descriptions.Item>
            <Descriptions.Item label="University">{dash(m.university)}</Descriptions.Item>
            <Descriptions.Item label="College">{dash(m.college)}</Descriptions.Item>
            <Descriptions.Item label="Major">{dash(m.major)}</Descriptions.Item>
            <Descriptions.Item label="College ID">{dash(m.uni_id)}</Descriptions.Item>
            <Descriptions.Item label="Graduating">{dash(m.graduating_year)}</Descriptions.Item>
            <Descriptions.Item label="Governorate">{dash(m.location)}</Descriptions.Item>
            <Descriptions.Item label="Birthday">{dash(m.birthday)}</Descriptions.Item>
            <Descriptions.Item label="National ID">{dash(m.national_id)}</Descriptions.Item>
            <Descriptions.Item label="Guardian">
              {dash(m.guardian_phone)}{m.guardian_kinship ? ` (${m.guardian_kinship})` : ''}
            </Descriptions.Item>
            <Descriptions.Item label="First registered">
              {m.joined_at ? dayjs(m.joined_at).format('D MMM YYYY') : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="Data confidence">
              {m.data_confidence ? (
                <Tag color={CONFIDENCE[m.data_confidence]?.color}>{CONFIDENCE[m.data_confidence]?.label ?? m.data_confidence}</Tag>
              ) : '—'}
              {m.source_records ? <span style={{ color: token.colorTextTertiary }}> · {m.source_records} source record(s)</span> : null}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Typography.Title level={5} style={{ marginTop: 0 }}>Events ({m.participations.length})</Typography.Title>
            {m.participations.length ? (
              <Table
                size="small"
                rowKey="id"
                pagination={false}
                dataSource={m.participations}
                columns={[
                  {
                    title: 'Event', key: 'e',
                    render: (_, p) => (
                      <div>
                        <div>{p.event_name}</div>
                        <div className="u-mono" style={{ fontSize: 11, color: token.colorTextTertiary }}>
                          {[p.event_code, p.event_kind].filter(Boolean).join(' · ')}
                        </div>
                      </div>
                    ),
                  },
                  { title: 'Role / field', dataIndex: 'role', render: dash },
                  { title: 'Team', dataIndex: 'team', render: dash },
                  { title: 'Mentor', dataIndex: 'mentor', render: dash },
                  { title: 'Rating', dataIndex: 'rating', align: 'right', render: dash },
                ]}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No participations recorded" />
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}

function AddMemberModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const [form] = Form.useForm<FormValues>();
  const [nextId, setNextId] = useState<string | null>(null);
  const [hits, setHits] = useState<DuplicateHit[]>([]);
  const [saving, setSaving] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    api.get<{ mtr_id: string }>('/api/members/next-id').then((r) => {
      setNextId(r.mtr_id);
      form.setFieldsValue({ mtr_id: r.mtr_id });
    }).catch(() => {});
  }, [form]);

  // the old "Add Members" sheet's duplicate column, live
  const check = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const v = form.getFieldsValue(['full_name', 'phone', 'email']);
      if (!v.full_name && !v.phone && !v.email) return setHits([]);
      api
        .post<DuplicateHit[]>('/api/members/check-duplicate', { name: v.full_name, phone: v.phone, email: v.email })
        .then(setHits)
        .catch(() => {});
    }, 400);
  };

  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const created = await api.post<RosterMemberDetail>('/api/members', toPayload(values));
      message.success(`Added ${created.name} as ${created.mtr_id}`);
      onCreated(created.id);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not add member');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      width={720}
      title={`Add member${nextId ? ` — next ID ${nextId}` : ''}`}
      okText={hits.length ? 'Add anyway' : 'Add member'}
      okButtonProps={{ danger: hits.length > 0, loading: saving }}
      onOk={submit}
      onCancel={onClose}
    >
      {hits.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 14 }}
          message="Possible duplicate — check before adding"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {hits.map((h) => (
                <li key={h.id}>
                  {h.mtr_id ?? '—'} {h.name} <span style={{ opacity: 0.7 }}>(same {h.matched_on.join(', ')})</span>
                </li>
              ))}
            </ul>
          }
        />
      )}
      <MemberForm form={form} onChange={check} />
    </Modal>
  );
}
