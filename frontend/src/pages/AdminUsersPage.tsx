import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Card, Checkbox, Collapse, Descriptions, Form, Input, List, Modal, Popconfirm, Select, Space, Switch, Table, Typography, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { AccessLevel, AdminUser, Privilege } from '../api/types';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

function Chip({ text, tone = 'muted' }: { text: string; tone?: 'accent' | 'gold' | 'muted' }) {
  const c = tone === 'accent' ? '#5cc6ff' : tone === 'gold' ? '#f5c451' : 'rgba(224,236,252,.5)';
  return <span style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: '.06em', textTransform: 'uppercase', color: c, border: `1px solid ${c}55`, background: `${c}14`, padding: '2px 8px', borderRadius: 5, whiteSpace: 'nowrap' }}>{text}</span>;
}

const dash = (v: string | number | null | undefined) =>
  v === null || v === undefined || v === '' ? <Typography.Text type="secondary">—</Typography.Text> : v;

interface ProfileFormValues {
  mtr_id?: string | null; national_id?: string | null; birthday?: string | null;
  university?: string | null; college?: string | null; major?: string | null;
  graduating_year?: number | string | null; phone?: string | null;
  father_phone?: string | null; mother_phone?: string | null;
  uni_id?: string | null; location?: string | null;
}
interface UserFormValues { email: string; full_name: string; password?: string; access_level_id?: number | null; profile?: ProfileFormValues }

// Roster fields rendered in the modal: [name, label, kind].
const PROFILE_FIELDS: [keyof ProfileFormValues, string, 'text' | 'number'][] = [
  ['mtr_id', 'MTR ID', 'text'], ['university', 'University', 'text'],
  ['college', 'College', 'text'], ['major', 'Major', 'text'],
  ['graduating_year', 'Grad year', 'number'], ['uni_id', 'UNI ID', 'text'],
  ['national_id', 'National ID', 'text'], ['birthday', 'Birthday (YYYY-MM-DD)', 'text'],
  ['phone', 'Phone', 'text'], ['location', 'Location', 'text'],
  ['father_phone', "Dad's number", 'text'], ['mother_phone', "Mom's number", 'text'],
];

// '' -> null so blank fields clear the profile column rather than 422 on typed ones.
const nn = (v: unknown) => (v === '' || v === undefined ? null : v);

function UserModal({ user, levels, open, onClose, onSaved }: { user: AdminUser | null; levels: AccessLevel[]; open: boolean; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm<UserFormValues>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      form.resetFields();
      if (user) form.setFieldsValue({ email: user.email, full_name: user.full_name, access_level_id: user.access_level_id, profile: user.profile ?? {} });
    }
  }, [open, user, form]);

  const submit = async (values: UserFormValues) => {
    setBusy(true);
    try {
      const p = values.profile ?? {};
      const profile = {
        mtr_id: nn(p.mtr_id), national_id: nn(p.national_id), birthday: nn(p.birthday),
        university: nn(p.university), college: nn(p.college), major: nn(p.major),
        graduating_year: p.graduating_year ? Number(p.graduating_year) : null,
        phone: nn(p.phone), father_phone: nn(p.father_phone), mother_phone: nn(p.mother_phone),
        uni_id: nn(p.uni_id), location: nn(p.location),
      };
      if (user) {
        await api.patch(`/api/users/${user.id}`, {
          full_name: values.full_name,
          ...(values.password ? { password: values.password } : {}),
          ...(values.access_level_id != null ? { access_level_id: values.access_level_id } : { clear_access_level: true }),
          profile,
        });
        message.success('User updated');
      } else {
        await api.post('/api/users', { email: values.email, full_name: values.full_name, password: values.password, access_level_id: values.access_level_id });
        message.success('User created');
      }
      onSaved();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title={user ? `Edit ${user.full_name}` : 'Create user'} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
          <Input disabled={!!user} />
        </Form.Item>
        <Form.Item name="full_name" label="Full name" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="password" label={user ? 'New password (leave blank to keep)' : 'Password'} rules={user ? [{ min: 8 }] : [{ required: true, min: 8 }]}>
          <Input.Password />
        </Form.Item>
        <Form.Item name="access_level_id" label="Access level override" extra="Power granted directly to the person, on top of whatever their org seats confer. Most people need none — their seats decide.">
          <Select allowClear placeholder="None — seats (or the bottom level) decide" options={levels.map((l) => ({ value: l.id, label: `${l.rank}. ${l.name}` }))} />
        </Form.Item>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Where this person sits (and who they report to, for task assignment) comes from the <strong>Organization</strong> chart — put them in a position there.
        </Typography.Paragraph>
        {user && (
          <>
            <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>Member profile</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: -2 }}>
              The roster record — biographical and contact details. Independent of access level. Leave a field blank to clear it.
            </Typography.Paragraph>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 12 }}>
              {PROFILE_FIELDS.map(([name, label, kind]) => (
                <Form.Item key={name} name={['profile', name]} label={label} style={{ marginBottom: 12 }}>
                  <Input type={kind === 'number' ? 'number' : 'text'} />
                </Form.Item>
              ))}
            </div>
          </>
        )}
        <Button type="primary" htmlType="submit" block loading={busy}>{user ? 'Save changes' : 'Create user'}</Button>
      </Form>
    </Modal>
  );
}

function LevelsEditor({ levels, privileges, onChanged }: { levels: AccessLevel[]; privileges: Privilege[]; onChanged: () => void }) {
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');

  const move = async (level: AccessLevel, dir: -1 | 1) => {
    try { await api.patch(`/api/access/levels/${level.id}`, { rank: level.rank + dir }); onChanged(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Move failed'); }
  };
  const rename = async (level: AccessLevel, name: string) => {
    if (!name || name === level.name) return;
    try { await api.patch(`/api/access/levels/${level.id}`, { name }); onChanged(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Rename failed'); }
  };
  const togglePrivilege = async (level: AccessLevel, key: string, on: boolean) => {
    const next = on ? [...level.privileges, key] : level.privileges.filter((k) => k !== key);
    try { await api.patch(`/api/access/levels/${level.id}`, { privileges: next }); onChanged(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Update failed'); }
  };
  const remove = async (level: AccessLevel) => {
    try { await api.delete(`/api/access/levels/${level.id}`); message.success('Level removed'); onChanged(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Delete failed'); }
  };
  const addLevel = async () => {
    if (!newName.trim()) return;
    try { await api.post('/api/access/levels', { name: newName.trim(), privileges: [] }); setNewName(''); setAdding(false); onChanged(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Create failed'); }
  };

  return (
    <Card size="small" style={{ marginTop: 24 }} title="Access levels" extra={<Button size="small" icon={<PlusOutlined />} onClick={() => setAdding((v) => !v)}>Add level</Button>}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        The ladder of power, strongest first. A person's effective level is the strongest of the seats they occupy plus their personal override; anyone with neither gets the bottom level. Level 1 always holds every privilege and can't be edited or deleted.
      </Typography.Paragraph>
      {adding && (
        <Space style={{ marginBottom: 12 }}>
          <Input size="small" placeholder="Level name" value={newName} onChange={(e) => setNewName(e.target.value)} onPressEnter={addLevel} />
          <Button size="small" type="primary" onClick={addLevel}>Add</Button>
        </Space>
      )}
      <Collapse size="small" items={levels.map((level, i) => ({
        key: String(level.id),
        label: (
          <Space size={6}>
            <Typography.Text strong>{level.rank}. {level.name}</Typography.Text>
            {level.is_top ? <Chip text="everything" tone="gold" /> : <Chip text={`${level.privileges.length} privileges`} />}
          </Space>
        ),
        extra: (
          <Space size={0} onClick={(e) => e.stopPropagation()}>
            <Button type="text" size="small" icon={<ArrowUpOutlined />} disabled={i === 0} onClick={() => move(level, -1)} />
            <Button type="text" size="small" icon={<ArrowDownOutlined />} disabled={i === levels.length - 1} onClick={() => move(level, 1)} />
            <Popconfirm title="Delete this level?" description="Seats and overrides using it fall back to no level." onConfirm={() => remove(level)} disabled={level.is_top}>
              <Button type="text" size="small" danger icon={<DeleteOutlined />} disabled={level.is_top} />
            </Popconfirm>
          </Space>
        ),
        children: (
          <>
            <Space style={{ marginBottom: 8 }}>
              <Typography.Text type="secondary">Name:</Typography.Text>
              <Typography.Text editable={{ onChange: (v) => rename(level, v) }}>{level.name}</Typography.Text>
            </Space>
            <List size="small" dataSource={privileges} renderItem={(p) => (
              <List.Item style={{ padding: '2px 0', border: 'none' }}>
                <Checkbox checked={level.is_top || level.privileges.includes(p.key)} disabled={level.is_top} onChange={(e) => togglePrivilege(level, p.key, e.target.checked)}>{p.label}</Checkbox>
              </List.Item>
            )} />
          </>
        ),
      }))} />
    </Card>
  );
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [levels, setLevels] = useState<AccessLevel[]>([]);
  const [privileges, setPrivileges] = useState<Privilege[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [query, setQuery] = useState('');

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.get<AdminUser[]>('/api/users'), api.get<AccessLevel[]>('/api/access/levels')])
      .then(([userRows, ladder]) => { setUsers(userRows); setLevels(ladder); })
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Load failed'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { api.get<Privilege[]>('/api/access/privileges').then(setPrivileges).catch(() => {}); }, []);
  useEffect(load, [load]);

  const levelById = useMemo(() => new Map(levels.map((l) => [l.id, l])), [levels]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return users;
    return users.filter((u) => {
      const p = u.profile;
      return [u.full_name, u.email, ...u.seats, u.effective_level,
        p?.mtr_id, p?.university, p?.college, p?.major, p?.location, p?.phone]
        .filter(Boolean).some((f) => String(f).toLowerCase().includes(q));
    });
  }, [users, query]);

  const universityFilters = useMemo(
    () => Array.from(new Set(users.map((u) => u.profile?.university).filter(Boolean) as string[])).sort(),
    [users],
  );

  const toggleActive = async (user: AdminUser, active: boolean) => {
    try { await api.patch(`/api/users/${user.id}`, { is_active: active }); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Failed'); }
  };

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <div style={{ maxWidth: 640 }}>
          <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>People &amp; Access</h2>
          <div style={{ fontSize: 13, color: 'rgba(224,236,252,.5)', marginTop: 6, lineHeight: 1.5 }}>
            The full directory and the management view in one: each person's seats come from the Organization chart, their power from the access ladder, their roster details from the member import. The only thing granted here directly is the override.
          </div>
          <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '.08em', color: 'rgba(224,236,252,.45)', marginTop: 8 }}>
            {users.length} ACCOUNT{users.length === 1 ? '' : 'S'}{query.trim() ? ` · ${filtered.length} SHOWN` : ''}
          </div>
        </div>
        <Space wrap>
          <Input.Search allowClear placeholder="Search name, email, MTR ID, major, university, seat…"
            onChange={(e) => setQuery(e.target.value)} style={{ width: 320, maxWidth: '100%' }} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setModalOpen(true); }}>Create user</Button>
        </Space>
      </div>
      <Table className="circuit-table" rowKey="id" loading={loading} dataSource={filtered}
        scroll={{ x: 'max-content' }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true, hideOnSinglePage: true, showTotal: (t) => `${t} shown` }}
        expandable={{
          expandedRowRender: (u) => (
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} bordered>
              <Descriptions.Item label="College">{dash(u.profile?.college)}</Descriptions.Item>
              <Descriptions.Item label="Major">{dash(u.profile?.major)}</Descriptions.Item>
              <Descriptions.Item label="Grad year">{dash(u.profile?.graduating_year)}</Descriptions.Item>
              <Descriptions.Item label="Phone">{dash(u.profile?.phone)}</Descriptions.Item>
              <Descriptions.Item label="Location">{dash(u.profile?.location)}</Descriptions.Item>
              <Descriptions.Item label="National ID">{dash(u.profile?.national_id)}</Descriptions.Item>
              <Descriptions.Item label="Birthday">{dash(u.profile?.birthday)}</Descriptions.Item>
              <Descriptions.Item label="UNI ID">{dash(u.profile?.uni_id)}</Descriptions.Item>
              <Descriptions.Item label="Dad's number">{dash(u.profile?.father_phone)}</Descriptions.Item>
              <Descriptions.Item label="Mom's number">{dash(u.profile?.mother_phone)}</Descriptions.Item>
              <Descriptions.Item label="Google-linked">{u.google_linked ? 'Yes' : 'No'}</Descriptions.Item>
            </Descriptions>
          ),
          rowExpandable: () => true,
        }}
        columns={[
          {
            title: 'MTR ID', dataIndex: ['profile', 'mtr_id'], width: 110,
            sorter: (a, b) => (a.profile?.mtr_id ?? '').localeCompare(b.profile?.mtr_id ?? ''),
            render: (v) => (v ? <span style={{ fontFamily: MONO, fontSize: 12, color: '#5cc6ff', letterSpacing: '.04em' }}>{v}</span> : dash(v)),
          },
          {
            title: 'Name', sorter: (a, b) => a.full_name.localeCompare(b.full_name),
            render: (_, u) => (
              <div style={{ lineHeight: 1.3 }}>
                <Space size={6}>
                  <span style={{ color: '#eaf2ff' }}>{u.full_name}</span>
                  {!u.is_active && <Chip text="deactivated" />}
                </Space>
                <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>{u.email}</Typography.Text></div>
              </div>
            ),
          },
          {
            title: 'University', dataIndex: ['profile', 'university'], width: 120, render: (v) => dash(v),
            filters: universityFilters.map((u) => ({ text: u, value: u })),
            onFilter: (value, u) => u.profile?.university === value,
          },
          {
            title: 'Seats (from the org chart)',
            render: (_, u) => u.seats.length ? (
              <Space size={4} wrap>{u.seats.map((s) => <Chip key={s} text={s} tone="accent" />)}</Space>
            ) : <Typography.Text type="secondary">—</Typography.Text>,
          },
          {
            title: 'Level', width: 190,
            render: (_, u) => (
              <Space size={4}>
                {u.effective_level ? <Chip text={u.effective_level} tone="gold" /> : '—'}
                {u.access_level_id != null && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>(override: {levelById.get(u.access_level_id)?.name ?? '?'})</Typography.Text>
                )}
              </Space>
            ),
          },
          { title: 'Active', width: 90, render: (_, u) => <Switch checked={u.is_active} onChange={(v) => toggleActive(u, v)} size="small" /> },
          { title: '', width: 90, render: (_, u) => <Button size="small" onClick={() => { setEditing(u); setModalOpen(true); }}>Edit</Button> },
        ]} />
      <LevelsEditor levels={levels} privileges={privileges} onChanged={load} />
      <UserModal user={editing} levels={levels} open={modalOpen} onClose={() => setModalOpen(false)} onSaved={load} />
    </>
  );
}
