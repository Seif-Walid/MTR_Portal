import { PlusOutlined } from '@ant-design/icons';
import { Button, DatePicker, Form, Input, Modal, Popconfirm, Space, Table, Tag, Typography, message } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Competition, RoleRoot } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import CompetitionDetailPanel from '../components/CompetitionDetailPanel';
import PositionPicker from '../components/PositionPicker';

interface FormValues {
  name: string;
  description?: string;
  dates?: [Dayjs, Dayjs];
  role_root_position_id?: number;
}

function CompetitionModal({ competition, open, onClose, onSaved }: {
  competition: Competition | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form] = Form.useForm<FormValues>();
  const [busy, setBusy] = useState(false);
  const [needsRoot, setNeedsRoot] = useState(false);

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (competition) {
      form.setFieldsValue({
        name: competition.name,
        description: competition.description,
        dates: competition.start_date && competition.end_date
          ? [dayjs(competition.start_date), dayjs(competition.end_date)] : undefined,
      });
    } else {
      api.get<RoleRoot>('/api/org/roles/root')
        .then((r) => setNeedsRoot(r.has_templates && r.root_position_id === null))
        .catch(() => setNeedsRoot(false));
    }
  }, [open, competition, form]);

  const submit = async (values: FormValues) => {
    setBusy(true);
    const body = {
      name: values.name,
      description: values.description ?? '',
      start_date: values.dates?.[0]?.format('YYYY-MM-DD') ?? null,
      end_date: values.dates?.[1]?.format('YYYY-MM-DD') ?? null,
      ...(competition ? {} : { role_root_position_id: values.role_root_position_id ?? null }),
    };
    try {
      if (competition) await api.patch(`/api/competitions/${competition.id}`, body);
      else await api.post('/api/competitions', body);
      message.success(competition ? 'Competition updated' : 'Competition added');
      onSaved();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title={competition ? `Edit ${competition.name}` : 'Add competition'} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item name="name" label="Name" rules={[{ required: true, max: 255 }]}>
          <Input placeholder="e.g. RoboCup 2026" />
        </Form.Item>
        <Form.Item name="dates" label="Dates">
          <DatePicker.RangePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="description" label="Description">
          <Input.TextArea rows={2} />
        </Form.Item>
        {!competition && needsRoot && (
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
          Add categories, teams, and members after creating — expand the competition row.
        </Typography.Paragraph>
        <Button type="primary" htmlType="submit" block loading={busy}>
          {competition ? 'Save changes' : 'Add competition'}
        </Button>
      </Form>
    </Modal>
  );
}

export default function CompetitionsPage() {
  const { me } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Competition | null>(null);
  const [open, setOpen] = useState(false);

  const canCreate = can(me, 'competitions.create');

  const load = useCallback(() => {
    setLoading(true);
    api.get<Competition[]>('/api/competitions?include_archived=true')
      .then(setCompetitions)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const setStatus = async (c: Competition, status: 'active' | 'archived') => {
    try { await api.patch(`/api/competitions/${c.id}`, { status }); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Failed'); }
  };

  const remove = async (c: Competition) => {
    try { await api.delete(`/api/competitions/${c.id}`); message.success('Competition deleted'); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Delete failed'); }
  };

  return (
    <>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>Competitions</Typography.Title>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true); }}>
            Add competition
          </Button>
        )}
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={competitions}
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
          { title: 'Categories', dataIndex: 'category_count', width: 100, render: (n: number) => n || '—' },
          { title: 'Teams', dataIndex: 'team_count', width: 80, render: (n: number) => n || '—' },
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
                  title={c.allocation_count ? 'In use — archive it instead.' : 'Delete this competition?'}
                  onConfirm={() => remove(c)} disabled={!!c.allocation_count}>
                  <Button size="small" danger disabled={!!c.allocation_count}>Delete</Button>
                </Popconfirm>
              </Space>
            ) : null,
          },
        ]}
      />

      <CompetitionModal competition={editing} open={open} onClose={() => setOpen(false)} onSaved={load} />
    </>
  );
}
