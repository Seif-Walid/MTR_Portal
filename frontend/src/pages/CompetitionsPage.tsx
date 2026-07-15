import { AppstoreOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import {
  Button,
  DatePicker,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type {
  Competition,
  CompetitionCategory,
  CompetitionDetail,
  UserBrief,
} from '../api/types';

interface FormValues {
  name: string;
  category_id?: number;
  dates?: [Dayjs, Dayjs];
  team_name?: string;
  team_lead_id?: number;
  member_ids?: number[];
}

function CategoriesModal({
  open,
  categories,
  onClose,
  onChanged,
}: {
  open: boolean;
  categories: CompetitionCategory[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [name, setName] = useState('');
  const add = async () => {
    if (!name.trim()) return;
    try {
      await api.post('/api/competitions/categories', { name: name.trim() });
      setName('');
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };
  const remove = async (id: number) => {
    try {
      await api.delete(`/api/competitions/categories/${id}`);
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };
  return (
    <Modal open={open} onCancel={onClose} title="Categories (divisions)" footer={null} destroyOnHidden>
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input
          placeholder="e.g. Senior, Junior, Line-follower"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onPressEnter={add}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={add}>
          Add
        </Button>
      </Space.Compact>
      <List
        size="small"
        locale={{ emptyText: 'No categories yet' }}
        dataSource={categories}
        renderItem={(c) => (
          <List.Item
            actions={[
              <Popconfirm key="d" title="Delete this category?" onConfirm={() => remove(c.id)}>
                <Button size="small" type="text" danger icon={<DeleteOutlined />} />
              </Popconfirm>,
            ]}
          >
            {c.name}
          </List.Item>
        )}
      />
    </Modal>
  );
}

function CompetitionModal({
  competition,
  categories,
  holders,
  open,
  onClose,
  onSaved,
}: {
  competition: Competition | null;
  categories: CompetitionCategory[];
  holders: UserBrief[];
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form] = Form.useForm<FormValues>();
  const [busy, setBusy] = useState(false);
  const [initialMembers, setInitialMembers] = useState<number[]>([]);

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    setInitialMembers([]);
    if (competition) {
      // fetch detail for the current member list
      api
        .get<CompetitionDetail>(`/api/competitions/${competition.id}`)
        .then((d) => {
          const memberIds = d.members.map((m) => m.user.id);
          setInitialMembers(memberIds);
          form.setFieldsValue({
            name: d.name,
            category_id: d.category?.id,
            team_name: d.team_name ?? undefined,
            team_lead_id: d.team_lead?.id,
            member_ids: memberIds,
            dates:
              d.start_date && d.end_date ? [dayjs(d.start_date), dayjs(d.end_date)] : undefined,
          });
        })
        .catch(() => {});
    }
  }, [open, competition, form]);

  const submit = async (values: FormValues) => {
    setBusy(true);
    const body = {
      name: values.name,
      category_id: values.category_id ?? null,
      clear_category: values.category_id == null,
      team_name: values.team_name ?? null,
      team_lead_id: values.team_lead_id ?? null,
      clear_team_lead: values.team_lead_id == null,
      start_date: values.dates?.[0]?.format('YYYY-MM-DD') ?? null,
      end_date: values.dates?.[1]?.format('YYYY-MM-DD') ?? null,
    };
    try {
      const comp = competition
        ? await api.patch<Competition>(`/api/competitions/${competition.id}`, body)
        : await api.post<Competition>('/api/competitions', body);
      // reconcile members
      const selected = new Set(values.member_ids ?? []);
      const current = new Set(initialMembers);
      const toAdd = [...selected].filter((id) => !current.has(id));
      const toRemove = [...current].filter((id) => !selected.has(id));
      await Promise.all([
        ...toAdd.map((id) => api.post(`/api/competitions/${comp.id}/members`, { user_id: id })),
        ...toRemove.map((id) => api.delete(`/api/competitions/${comp.id}/members/${id}`)),
      ]);
      message.success(competition ? 'Competition updated' : 'Competition added');
      onSaved();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  const userOptions = holders.map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` }));

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={competition ? `Edit ${competition.name}` : 'Add competition'}
      footer={null}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item name="name" label="Name" rules={[{ required: true, max: 255 }]}>
          <Input placeholder="e.g. RoboCup 2026" />
        </Form.Item>
        <Form.Item name="category_id" label="Category (division)">
          <Select
            allowClear
            placeholder="None"
            options={categories.map((c) => ({ value: c.id, label: c.name }))}
          />
        </Form.Item>
        <Form.Item name="dates" label="Dates">
          <DatePicker.RangePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="team_name" label="Team">
          <Input placeholder="Team name" />
        </Form.Item>
        <Form.Item name="team_lead_id" label="Team lead">
          <Select allowClear showSearch optionFilterProp="label" placeholder="Pick a lead" options={userOptions} />
        </Form.Item>
        <Form.Item name="member_ids" label="Team members">
          <Select
            mode="multiple"
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Add members"
            options={userOptions}
          />
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={busy}>
          {competition ? 'Save changes' : 'Add competition'}
        </Button>
      </Form>
    </Modal>
  );
}

export default function CompetitionsPage() {
  const [competitions, setCompetitions] = useState<Competition[]>([]);
  const [categories, setCategories] = useState<CompetitionCategory[]>([]);
  const [holders, setHolders] = useState<UserBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Competition | null>(null);
  const [open, setOpen] = useState(false);
  const [catsOpen, setCatsOpen] = useState(false);

  const loadCategories = useCallback(() => {
    api.get<CompetitionCategory[]>('/api/competitions/categories').then(setCategories).catch(() => {});
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<Competition[]>('/api/competitions?include_archived=true')
      .then(setCompetitions)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    loadCategories();
    api.get<UserBrief[]>('/api/inventory/holders').then(setHolders).catch(() => {});
  }, [load, loadCategories]);

  const setStatus = async (c: Competition, status: 'active' | 'archived') => {
    try {
      await api.patch(`/api/competitions/${c.id}`, { status });
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };

  const remove = async (c: Competition) => {
    try {
      await api.delete(`/api/competitions/${c.id}`);
      message.success('Competition deleted');
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Delete failed');
    }
  };

  return (
    <>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          Competitions
        </Typography.Title>
        <Space wrap>
          <Button icon={<AppstoreOutlined />} onClick={() => setCatsOpen(true)}>
            Categories
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            Add competition
          </Button>
        </Space>
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={competitions}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        columns={[
          { title: 'Name', dataIndex: 'name', render: (v) => <Typography.Text strong>{v}</Typography.Text> },
          {
            title: 'Category',
            width: 130,
            render: (_, c) => (c.category ? <Tag color="purple">{c.category.name}</Tag> : '—'),
          },
          {
            title: 'Dates',
            width: 170,
            render: (_, c) =>
              c.start_date && c.end_date
                ? `${dayjs(c.start_date).format('DD MMM')} – ${dayjs(c.end_date).format('DD MMM YY')}`
                : '—',
          },
          { title: 'Team', dataIndex: 'team_name', width: 130, render: (v) => v || '—' },
          { title: 'Lead', width: 150, render: (_, c) => c.team_lead?.full_name ?? '—' },
          {
            title: 'Members',
            dataIndex: 'member_count',
            width: 100,
            render: (n: number) => n || '—',
          },
          {
            title: 'Status',
            dataIndex: 'status',
            width: 110,
            render: (s: string) => (
              <Tag color={s === 'active' ? 'green' : 'default'}>{s.toUpperCase()}</Tag>
            ),
          },
          {
            title: '',
            width: 250,
            render: (_, c) => (
              <Space>
                <Button size="small" onClick={() => { setEditing(c); setOpen(true); }}>
                  Edit
                </Button>
                {c.status === 'active' ? (
                  <Button size="small" onClick={() => setStatus(c, 'archived')}>
                    Archive
                  </Button>
                ) : (
                  <Button size="small" onClick={() => setStatus(c, 'active')}>
                    Reactivate
                  </Button>
                )}
                <Popconfirm
                  title={c.allocation_count ? 'In use — archive it instead.' : 'Delete this competition?'}
                  onConfirm={() => remove(c)}
                  disabled={!!c.allocation_count}
                >
                  <Button size="small" danger disabled={!!c.allocation_count}>
                    Delete
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <CompetitionModal
        competition={editing}
        categories={categories}
        holders={holders}
        open={open}
        onClose={() => setOpen(false)}
        onSaved={load}
      />
      <CategoriesModal
        open={catsOpen}
        categories={categories}
        onClose={() => setCatsOpen(false)}
        onChanged={loadCategories}
      />
    </>
  );
}
