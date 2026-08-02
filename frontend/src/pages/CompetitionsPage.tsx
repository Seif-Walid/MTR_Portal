import { DeleteOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons';
import {
  Button, DatePicker, Empty, Form, Input, List, Modal, Popconfirm, Space, Table, Tag, Typography, message,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useState } from 'react';
import { Navigate, useParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { Competition, EventKind, RoleRoot } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import CompetitionDetailPanel from '../components/CompetitionDetailPanel';
import PositionPicker from '../components/PositionPicker';

interface FormValues {
  name: string;
  description?: string;
  dates?: [Dayjs, Dayjs];
  role_root_position_id?: number;
}

function EventModal({ kind, event, open, onClose, onSaved }: {
  kind: EventKind;
  event: Competition | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form] = Form.useForm<FormValues>();
  const [busy, setBusy] = useState(false);
  const [needsRoot, setNeedsRoot] = useState(false);
  const label = kind.event_label;

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (event) {
      form.setFieldsValue({
        name: event.name,
        description: event.description,
        dates: event.start_date && event.end_date
          ? [dayjs(event.start_date), dayjs(event.end_date)] : undefined,
      });
    } else {
      api.get<RoleRoot>('/api/org/roles/root')
        .then((r) => setNeedsRoot(r.has_templates && r.root_position_id === null))
        .catch(() => setNeedsRoot(false));
    }
  }, [open, event, form]);

  const submit = async (values: FormValues) => {
    setBusy(true);
    const body = {
      name: values.name,
      description: values.description ?? '',
      start_date: values.dates?.[0]?.format('YYYY-MM-DD') ?? null,
      end_date: values.dates?.[1]?.format('YYYY-MM-DD') ?? null,
      ...(event ? {} : { kind_id: kind.id, role_root_position_id: values.role_root_position_id ?? null }),
    };
    try {
      if (event) await api.patch(`/api/competitions/${event.id}`, body);
      else await api.post('/api/competitions', body);
      message.success('Saved');
      onSaved();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title={event ? `Edit ${event.name}` : `Add ${label}`} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item name="name" label="Name" rules={[{ required: true, max: 255 }]}>
          <Input placeholder={`e.g. ${kind.slug === 'training' ? 'Summer Bootcamp' : kind.slug === 'rnd' ? 'Line-follower R&D' : 'RoboCup 2026'}`} />
        </Form.Item>
        <Form.Item name="dates" label="Dates">
          <DatePicker.RangePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="description" label="Description">
          <Input.TextArea rows={2} />
        </Form.Item>
        {!event && needsRoot && (
          <Form.Item
            name="role_root_position_id"
            label="Where does the first automatic role go in the org chart?"
            rules={[{ required: true, message: 'Pick a position — this is only asked once' }]}
            extra="Asked once, ever — every later automatic role reuses this or chains under an earlier one."
          >
            <PositionPicker />
          </Form.Item>
        )}
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Add {kind.category_label.toLowerCase()}, {kind.team_label.toLowerCase()}s, and members after creating — expand the row.
        </Typography.Paragraph>
        <Button type="primary" htmlType="submit" block loading={busy}>
          {event ? 'Save changes' : `Add ${label.toLowerCase()}`}
        </Button>
      </Form>
    </Modal>
  );
}

function EventsList({ kind, canCreate }: { kind: EventKind; canCreate: boolean }) {
  const [events, setEvents] = useState<Competition[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Competition | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.get<Competition[]>(`/api/competitions?include_archived=true&kind_id=${kind.id}`)
      .then(setEvents)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, [kind.id]);

  useEffect(load, [load]);

  const setStatus = async (c: Competition, status: 'active' | 'archived') => {
    try { await api.patch(`/api/competitions/${c.id}`, { status }); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Failed'); }
  };
  const remove = async (c: Competition) => {
    try { await api.delete(`/api/competitions/${c.id}`); message.success('Deleted'); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Delete failed'); }
  };

  return (
    <>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'flex-end' }}>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true); }}>
            Add {kind.event_label.toLowerCase()}
          </Button>
        )}
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={events}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        expandable={{ expandedRowRender: (c) => <CompetitionDetailPanel competitionId={c.id} onChanged={load} /> }}
        columns={[
          { title: 'Name', dataIndex: 'name', render: (v) => <Typography.Text strong>{v}</Typography.Text> },
          {
            title: 'Dates', width: 170,
            render: (_, c) => c.start_date && c.end_date
              ? `${dayjs(c.start_date).format('DD MMM')} – ${dayjs(c.end_date).format('DD MMM YY')}` : '—',
          },
          {
            title: 'Roles', width: 180,
            render: (_, c) => c.roles.flatMap((r) => r.occupants.map((u) => u.full_name)).join(', ') || '—',
          },
          { title: kind.category_label, dataIndex: 'category_count', width: 110, render: (n: number) => n || '—' },
          { title: `${kind.team_label}s`, dataIndex: 'team_count', width: 90, render: (n: number) => n || '—' },
          { title: 'Members', dataIndex: 'member_count', width: 90, render: (n: number) => n || '—' },
          {
            title: 'Status', dataIndex: 'status', width: 100,
            render: (s: string) => <Tag color={s === 'active' ? 'green' : 'default'}>{s.toUpperCase()}</Tag>,
          },
          {
            title: '', width: 240,
            render: (_, c) => c.can_manage ? (
              <Space>
                <Button size="small" onClick={() => { setEditing(c); setOpen(true); }}>Edit</Button>
                {c.status === 'active'
                  ? <Button size="small" onClick={() => setStatus(c, 'archived')}>Archive</Button>
                  : <Button size="small" onClick={() => setStatus(c, 'active')}>Reactivate</Button>}
                <Popconfirm
                  title={c.allocation_count ? 'In use — archive it instead.' : 'Delete this?'}
                  onConfirm={() => remove(c)} disabled={!!c.allocation_count}>
                  <Button size="small" danger disabled={!!c.allocation_count}>Delete</Button>
                </Popconfirm>
              </Space>
            ) : null,
          },
        ]}
      />
      <EventModal kind={kind} event={editing} open={open} onClose={() => setOpen(false)} onSaved={load} />
    </>
  );
}

function KindsManagerModal({ kinds, open, onClose, onChanged }: {
  kinds: EventKind[];
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [form] = Form.useForm();

  const add = async (v: { name: string; event_label: string; category_label?: string; team_label?: string; member_label?: string }) => {
    try {
      await api.post('/api/competitions/kinds', {
        name: v.name,
        event_label: v.event_label,
        category_label: v.category_label || 'Category',
        team_label: v.team_label || 'Team',
        member_label: v.member_label || 'Member',
      });
      form.resetFields();
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };
  const patch = async (k: EventKind, field: keyof EventKind, value: string) => {
    if (!value || value === k[field]) return;
    try { await api.patch(`/api/competitions/kinds/${k.id}`, { [field]: value }); onChanged(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Failed'); }
  };
  const remove = async (k: EventKind) => {
    try { await api.delete(`/api/competitions/kinds/${k.id}`); message.success('Removed'); onChanged(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Delete failed'); }
  };

  return (
    <Modal open={open} onCancel={onClose} title="Event types" footer={null} destroyOnHidden width={620}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Each type is a tab. It reuses the same structure — only the labels for its top level, {' '}
        divisions, teams and members differ. Automatic roles can target one type or all.
      </Typography.Paragraph>
      <List
        size="small"
        dataSource={kinds}
        renderItem={(k) => (
          <List.Item
            actions={[
              <Popconfirm key="d" title={`Delete "${k.name}"?`} description="Only if it has no events or roles." onConfirm={() => remove(k)}>
                <Button type="text" size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>,
            ]}
          >
            <Space wrap size={6}>
              <Typography.Text editable={{ onChange: (v) => patch(k, 'name', v) }} strong>{k.name}</Typography.Text>
              <Tag>one is a <Typography.Text editable={{ onChange: (v) => patch(k, 'event_label', v) }}>{k.event_label}</Typography.Text></Tag>
              <Tag>team = <Typography.Text editable={{ onChange: (v) => patch(k, 'team_label', v) }}>{k.team_label}</Typography.Text></Tag>
              <Tag>division = <Typography.Text editable={{ onChange: (v) => patch(k, 'category_label', v) }}>{k.category_label}</Typography.Text></Tag>
            </Space>
          </List.Item>
        )}
      />
      <Form form={form} layout="vertical" onFinish={add} style={{ marginTop: 12 }}>
        <Space align="end" wrap>
          <Form.Item name="name" label="New type" rules={[{ required: true }]} style={{ marginBottom: 8 }}>
            <Input placeholder="e.g. Workshop" />
          </Form.Item>
          <Form.Item name="event_label" label="One is called" rules={[{ required: true }]} style={{ marginBottom: 8 }}>
            <Input placeholder="e.g. Session" />
          </Form.Item>
          <Form.Item name="team_label" label="Team label" style={{ marginBottom: 8 }}>
            <Input placeholder="Team" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" icon={<PlusOutlined />}>Add type</Button>
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}

export default function EventsPage() {
  const { me } = useAuth();
  const { slug } = useParams<{ slug: string }>();
  const [kinds, setKinds] = useState<EventKind[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [managing, setManaging] = useState(false);
  const canCreate = can(me, 'competitions.create');
  const canManageKinds = can(me, 'org.edit');

  const loadKinds = useCallback(() => {
    api.get<EventKind[]>('/api/competitions/kinds')
      .then(setKinds)
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);
  useEffect(loadKinds, [loadKinds]);

  // no slug in the URL → land on the first kind (the nav sub-items link here)
  if (loaded && !slug && kinds.length) return <Navigate to={`/events/${kinds[0].slug}`} replace />;

  const kind = kinds.find((k) => k.slug === slug);

  return (
    <>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }} align="start" wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {kind ? kind.name : 'Events'}
        </Typography.Title>
        {canManageKinds && (
          <Button icon={<SettingOutlined />} onClick={() => setManaging(true)}>Event types</Button>
        )}
      </Space>
      {kind ? (
        <EventsList key={kind.id} kind={kind} canCreate={canCreate} />
      ) : loaded && kinds.length === 0 ? (
        <Empty
          description={
            canManageKinds
              ? 'No event types yet. Use "Event types" to add one (e.g. Competition, Training, R&D).'
              : 'No event types have been set up yet.'
          }
        />
      ) : loaded ? (
        <Empty description="No such event type" />
      ) : null}
      <KindsManagerModal kinds={kinds} open={managing} onClose={() => setManaging(false)} onChanged={loadKinds} />
    </>
  );
}
