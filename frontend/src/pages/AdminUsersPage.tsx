import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Checkbox,
  Collapse,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { AccessLevel, AdminUser, Privilege } from '../api/types';

interface UserFormValues {
  email: string;
  full_name: string;
  password?: string;
  access_level_id?: number | null;
  department?: string | null;
  manager_id?: number | null;
}

function UserModal({
  user,
  users,
  levels,
  departments,
  open,
  onClose,
  onSaved,
}: {
  user: AdminUser | null; // null = create
  users: AdminUser[];
  levels: AccessLevel[];
  departments: string[];
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form] = Form.useForm<UserFormValues>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      form.resetFields();
      if (user) {
        form.setFieldsValue({
          email: user.email,
          full_name: user.full_name,
          access_level_id: user.access_level_id,
          department: user.department,
          manager_id: user.manager_id,
        });
      }
    }
  }, [open, user, form]);

  const managerOptions = useMemo(
    () =>
      users
        .filter((u) => u.id !== user?.id && u.is_active)
        .map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` })),
    [users, user],
  );

  const submit = async (values: UserFormValues) => {
    setBusy(true);
    try {
      if (user) {
        await api.patch(`/api/users/${user.id}`, {
          full_name: values.full_name,
          ...(values.password ? { password: values.password } : {}),
          ...(values.access_level_id != null
            ? { access_level_id: values.access_level_id }
            : { clear_access_level: true }),
          ...(values.department
            ? { department: values.department }
            : { clear_department: true }),
          ...(values.manager_id != null
            ? { manager_id: values.manager_id }
            : { clear_manager: true }),
        });
        message.success('User updated');
      } else {
        await api.post('/api/users', values);
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
    <Modal
      open={open}
      onCancel={onClose}
      title={user ? `Edit ${user.full_name}` : 'Create user'}
      footer={null}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}>
          <Input disabled={!!user} />
        </Form.Item>
        <Form.Item name="full_name" label="Full name" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item
          name="password"
          label={user ? 'New password (leave blank to keep)' : 'Password'}
          rules={user ? [{ min: 8 }] : [{ required: true, min: 8 }]}
        >
          <Input.Password />
        </Form.Item>
        <Form.Item
          name="access_level_id"
          label="Access level override"
          extra="Power granted directly to the person, on top of whatever their org seats confer. Most people need none — their seats decide."
        >
          <Select
            allowClear
            placeholder="None — seats (or the bottom level) decide"
            options={levels.map((l) => ({ value: l.id, label: `${l.rank}. ${l.name}` }))}
          />
        </Form.Item>
        <Form.Item name="department" label="Department">
          <Select allowClear options={departments.map((d) => ({ value: d, label: d }))} />
        </Form.Item>
        <Form.Item
          name="manager_id"
          label="Reports to (drives task assignment & visibility)"
        >
          <Select allowClear showSearch optionFilterProp="label" options={managerOptions} />
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={busy}>
          {user ? 'Save changes' : 'Create user'}
        </Button>
      </Form>
    </Modal>
  );
}

function LevelsEditor({
  levels,
  privileges,
  onChanged,
}: {
  levels: AccessLevel[];
  privileges: Privilege[];
  onChanged: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');

  const move = async (level: AccessLevel, dir: -1 | 1) => {
    try {
      await api.patch(`/api/access/levels/${level.id}`, { rank: level.rank + dir });
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Move failed');
    }
  };

  const rename = async (level: AccessLevel, name: string) => {
    if (!name || name === level.name) return;
    try {
      await api.patch(`/api/access/levels/${level.id}`, { name });
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Rename failed');
    }
  };

  const togglePrivilege = async (level: AccessLevel, key: string, on: boolean) => {
    const next = on
      ? [...level.privileges, key]
      : level.privileges.filter((k) => k !== key);
    try {
      await api.patch(`/api/access/levels/${level.id}`, { privileges: next });
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Update failed');
    }
  };

  const remove = async (level: AccessLevel) => {
    try {
      await api.delete(`/api/access/levels/${level.id}`);
      message.success('Level removed');
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Delete failed');
    }
  };

  const addLevel = async () => {
    if (!newName.trim()) return;
    try {
      await api.post('/api/access/levels', { name: newName.trim(), privileges: [] });
      setNewName('');
      setAdding(false);
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Create failed');
    }
  };

  return (
    <Card
      size="small"
      style={{ marginTop: 24 }}
      title="Access levels"
      extra={
        <Button size="small" icon={<PlusOutlined />} onClick={() => setAdding((v) => !v)}>
          Add level
        </Button>
      }
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        The ladder of power, strongest first. A person's effective level is the strongest of the
        seats they occupy plus their personal override; anyone with neither gets the bottom level.
        Level 1 always holds every privilege and can't be edited or deleted.
      </Typography.Paragraph>
      {adding && (
        <Space style={{ marginBottom: 12 }}>
          <Input
            size="small"
            placeholder="Level name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onPressEnter={addLevel}
          />
          <Button size="small" type="primary" onClick={addLevel}>
            Add
          </Button>
        </Space>
      )}
      <Collapse
        size="small"
        items={levels.map((level, i) => ({
          key: String(level.id),
          label: (
            <Space size={6}>
              <Typography.Text strong>
                {level.rank}. {level.name}
              </Typography.Text>
              {level.is_top ? (
                <Tag color="gold">everything</Tag>
              ) : (
                <Tag>{level.privileges.length} privileges</Tag>
              )}
            </Space>
          ),
          extra: (
            <Space size={0} onClick={(e) => e.stopPropagation()}>
              <Button
                type="text" size="small" icon={<ArrowUpOutlined />}
                disabled={i === 0} onClick={() => move(level, -1)}
              />
              <Button
                type="text" size="small" icon={<ArrowDownOutlined />}
                disabled={i === levels.length - 1} onClick={() => move(level, 1)}
              />
              <Popconfirm
                title="Delete this level?"
                description="Seats and overrides using it fall back to no level."
                onConfirm={() => remove(level)}
                disabled={level.is_top}
              >
                <Button type="text" size="small" danger icon={<DeleteOutlined />} disabled={level.is_top} />
              </Popconfirm>
            </Space>
          ),
          children: (
            <>
              <Space style={{ marginBottom: 8 }}>
                <Typography.Text type="secondary">Name:</Typography.Text>
                <Typography.Text
                  editable={{ onChange: (v) => rename(level, v) }}
                >
                  {level.name}
                </Typography.Text>
              </Space>
              <List
                size="small"
                dataSource={privileges}
                renderItem={(p) => (
                  <List.Item style={{ padding: '2px 0', border: 'none' }}>
                    <Checkbox
                      checked={level.is_top || level.privileges.includes(p.key)}
                      disabled={level.is_top}
                      onChange={(e) => togglePrivilege(level, p.key, e.target.checked)}
                    >
                      {p.label}
                    </Checkbox>
                  </List.Item>
                )}
              />
            </>
          ),
        }))}
      />
    </Card>
  );
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [levels, setLevels] = useState<AccessLevel[]>([]);
  const [privileges, setPrivileges] = useState<Privilege[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get<AdminUser[]>('/api/users'),
      api.get<AccessLevel[]>('/api/access/levels'),
    ])
      .then(([userRows, ladder]) => {
        setUsers(userRows);
        setLevels(ladder);
      })
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Load failed'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    api.get<Privilege[]>('/api/access/privileges').then(setPrivileges).catch(() => {});
    api.get<string[]>('/api/users/departments').then(setDepartments).catch(() => {});
  }, []);

  useEffect(load, [load]);

  const byId = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);
  const levelById = useMemo(() => new Map(levels.map((l) => [l.id, l])), [levels]);

  const toggleActive = async (user: AdminUser, active: boolean) => {
    try {
      await api.patch(`/api/users/${user.id}`, { is_active: active });
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };

  return (
    <>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} align="start" wrap>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            People &amp; Access
          </Typography.Title>
          <Typography.Text type="secondary">
            A reflection of the org: each person's seats come from the Organization chart, their
            power from the access ladder. The only thing granted here directly is the override.
          </Typography.Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
        >
          Create user
        </Button>
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={users}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        columns={[
          {
            title: 'Name',
            render: (_, u) => (
              <Space>
                {u.full_name}
                {!u.is_active && <Tag>deactivated</Tag>}
              </Space>
            ),
          },
          { title: 'Email', dataIndex: 'email', width: 220 },
          {
            title: 'Seats (from the org chart)',
            render: (_, u) =>
              u.seats.length ? (
                <Space size={4} wrap>
                  {u.seats.map((s) => (
                    <Tag key={s}>{s}</Tag>
                  ))}
                </Space>
              ) : (
                <Typography.Text type="secondary">—</Typography.Text>
              ),
          },
          {
            title: 'Level',
            width: 170,
            render: (_, u) => (
              <Space size={4}>
                {u.effective_level ? <Tag color="gold">{u.effective_level}</Tag> : '—'}
                {u.access_level_id != null && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    (override: {levelById.get(u.access_level_id)?.name ?? '?'})
                  </Typography.Text>
                )}
              </Space>
            ),
          },
          {
            title: 'Reports to',
            width: 160,
            render: (_, u) => (u.manager_id ? byId.get(u.manager_id)?.full_name ?? '—' : '—'),
          },
          {
            title: 'Active',
            width: 90,
            render: (_, u) => (
              <Switch checked={u.is_active} onChange={(v) => toggleActive(u, v)} size="small" />
            ),
          },
          {
            title: '',
            width: 90,
            render: (_, u) => (
              <Button
                size="small"
                onClick={() => {
                  setEditing(u);
                  setModalOpen(true);
                }}
              >
                Edit
              </Button>
            ),
          },
        ]}
      />
      <LevelsEditor levels={levels} privileges={privileges} onChanged={load} />
      <UserModal
        user={editing}
        users={users}
        levels={levels}
        departments={departments}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={load}
      />
    </>
  );
}
