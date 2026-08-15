import { GoogleOutlined, LockOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Me, MemberProfile } from '../api/types';
import { useAuth } from '../auth/AuthContext';

// Roster fields the member can edit about themselves. `mtr_id` is shown
// read-only (org-assigned) and intentionally absent here.
const EDITABLE_FIELDS: {
  key: keyof MemberProfile;
  label: string;
  type?: 'number';
}[] = [
  { key: 'university', label: 'University' },
  { key: 'college', label: 'College' },
  { key: 'major', label: 'Major' },
  { key: 'graduating_year', label: 'Graduating year', type: 'number' },
  { key: 'phone', label: 'Phone' },
  { key: 'location', label: 'Location' },
];

export default function ProfilePage() {
  const { me, applyMe } = useAuth();
  const [form] = Form.useForm();
  const [profileForm] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);

  useEffect(() => {
    if (!me?.profile) return;
    profileForm.setFieldsValue(
      Object.fromEntries(EDITABLE_FIELDS.map((f) => [f.key, me.profile![f.key] ?? undefined])),
    );
  }, [me, profileForm]);

  useEffect(() => {
    api
      .get<{ google_enabled: boolean }>('/api/auth/config')
      .then((c) => setGoogleEnabled(c.google_enabled))
      .catch(() => {});
  }, []);

  if (!me) return null;

  const changePassword = async (values: {
    current_password: string;
    new_password: string;
    confirm: string;
  }) => {
    setSaving(true);
    try {
      await api.post('/api/auth/change-password', {
        current_password: values.current_password,
        new_password: values.new_password,
      });
      message.success('Password changed.');
      form.resetFields();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not change password');
    } finally {
      setSaving(false);
    }
  };

  const saveProfile = async (values: Record<string, string | number | undefined>) => {
    setSavingProfile(true);
    try {
      const payload = Object.fromEntries(
        EDITABLE_FIELDS.map((f) => {
          const v = values[f.key];
          return [f.key, v === '' || v === undefined ? null : v];
        }),
      );
      const updated = await api.put<Me>('/api/auth/me/profile', payload);
      applyMe(updated);
      message.success('Profile saved.');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not save profile');
    } finally {
      setSavingProfile(false);
    }
  };

  return (
    <div style={{ maxWidth: 720 }}>
      <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 4 }}>
        My Profile
      </Typography.Title>
      <Typography.Text type="secondary">
        Your account details and personal data. Change your password below.
      </Typography.Text>

      <Card title="Account" style={{ marginTop: 20 }}>
        <Descriptions column={1} size="small">
          <Descriptions.Item label="Name">{me.full_name}</Descriptions.Item>
          <Descriptions.Item label="Email">{me.email}</Descriptions.Item>
          <Descriptions.Item label="Access level">
            {me.level ? <Tag color="blue">{me.level.name}</Tag> : <Typography.Text type="secondary">No level</Typography.Text>}
          </Descriptions.Item>
          {me.seats.length > 0 && (
            <Descriptions.Item label="Positions">
              <Space size={[4, 4]} wrap>
                {me.seats.map((s) => (
                  <Tag key={s}>{s}</Tag>
                ))}
              </Space>
            </Descriptions.Item>
          )}
          {me.department && <Descriptions.Item label="Department">{me.department}</Descriptions.Item>}
          <Descriptions.Item label="Google">
            {me.google_linked ? (
              <Tag icon={<GoogleOutlined />} color="green">Linked</Tag>
            ) : (
              <Typography.Text type="secondary">Not linked</Typography.Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Member since">
            {dayjs(me.created_at).format('DD MMM YYYY')}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="Personal data" style={{ marginTop: 16 }}>
        {me.profile?.mtr_id && (
          <Descriptions column={1} size="small" style={{ marginBottom: 8 }}>
            <Descriptions.Item label="MTR ID">{me.profile.mtr_id}</Descriptions.Item>
          </Descriptions>
        )}
        <Form
          form={profileForm}
          layout="vertical"
          onFinish={saveProfile}
          style={{ maxWidth: 380 }}
        >
          {EDITABLE_FIELDS.map((f) => (
            <Form.Item key={f.key} name={f.key} label={f.label} style={{ marginBottom: 12 }}>
              {f.type === 'number' ? (
                <InputNumber style={{ width: '100%' }} controls={false} />
              ) : (
                <Input />
              )}
            </Form.Item>
          ))}
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" loading={savingProfile}>
              Save changes
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card title="Change password" style={{ marginTop: 16 }}>
        <Form form={form} layout="vertical" onFinish={changePassword} style={{ maxWidth: 380 }}>
          <Form.Item
            name="current_password"
            label="Current password"
            rules={[{ required: true, message: 'Enter your current password' }]}
          >
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="New password"
            rules={[
              { required: true, message: 'Enter a new password' },
              { min: 8, message: 'At least 8 characters' },
            ]}
          >
            <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="Confirm new password"
            dependencies={['new_password']}
            rules={[
              { required: true, message: 'Confirm your new password' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) return Promise.resolve();
                  return Promise.reject(new Error('Passwords do not match'));
                },
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" loading={saving}>
              Update password
            </Button>
          </Form.Item>
        </Form>
        {googleEnabled && me.google_linked && (
          <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
            You can also sign in with your linked Google account.
          </Typography.Text>
        )}
      </Card>
    </div>
  );
}
