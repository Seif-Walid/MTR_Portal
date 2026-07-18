import { PlusOutlined } from '@ant-design/icons';
import {
  Button,
  Form,
  Input,
  Modal,
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
import type { AdminUser, Role } from '../api/types';
import { RoleTags } from '../components/tags';

interface UserFormValues {
  email: string;
  full_name: string;
  password?: string;
  roles: string[];
  department?: string | null;
  manager_id?: number | null;
}

function UserModal({
  user,
  users,
  roles,
  departments,
  open,
  onClose,
  onSaved,
}: {
  user: AdminUser | null; // null = create
  users: AdminUser[];
  roles: Role[];
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
          roles: user.roles.map((r) => r.slug),
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
          roles: values.roles,
          ...(values.password ? { password: values.password } : {}),
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
        <Form.Item name="roles" label="Roles (permissions are the union)" rules={[{ required: true }]}>
          <Select
            mode="multiple"
            options={roles.map((r) => ({ value: r.slug, label: r.name }))}
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

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<AdminUser[]>('/api/users')
      .then(setUsers)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    api.get<Role[]>('/api/users/roles').then(setRoles).catch(() => {});
    api.get<string[]>('/api/users/departments').then(setDepartments).catch(() => {});
  }, []);

  useEffect(load, [load]);

  const byId = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);

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
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          User Management
        </Typography.Title>
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
          { title: 'Roles', render: (_, u) => <RoleTags roles={u.roles} /> },
          { title: 'Department', render: (_, u) => u.department ?? '—', width: 120 },
          {
            title: 'Reports to',
            width: 180,
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
      <UserModal
        user={editing}
        users={users}
        roles={roles}
        departments={departments}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={load}
      />
    </>
  );
}
