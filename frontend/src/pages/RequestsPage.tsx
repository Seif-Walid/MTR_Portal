import { PlusOutlined } from '@ant-design/icons';
import {
  Button,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { ItemBrief, UserBrief, WorkRequest } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { PriorityTag, RequestStatusTag, StatusTag } from '../components/tags';

function NewRequestModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form] = Form.useForm();
  const [staff, setStaff] = useState<UserBrief[]>([]);
  const [items, setItems] = useState<ItemBrief[]>([]);
  const [busy, setBusy] = useState(false);
  const itemId = Form.useWatch('item_id', form) as number | undefined;

  useEffect(() => {
    if (open) {
      api.get<UserBrief[]>('/api/users/staff').then(setStaff).catch(() => {});
      api.get<ItemBrief[]>('/api/inventory/directory').then(setItems).catch(() => {});
    }
  }, [open]);

  const submit = async (values: {
    recipient_id: number;
    title: string;
    description?: string;
    priority: string;
    due_date?: Dayjs;
    item_id?: number;
    quantity?: number;
  }) => {
    setBusy(true);
    try {
      await api.post('/api/requests', {
        ...values,
        due_date: values.due_date?.format('YYYY-MM-DD') ?? null,
        item_id: values.item_id ?? null,
        quantity: values.item_id ? values.quantity ?? null : null,
      });
      message.success('Request sent');
      form.resetFields();
      onCreated();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to send request');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title="Send a request" footer={null} destroyOnHidden>
      <Typography.Paragraph type="secondary">
        Requests go to staff members you can't task directly — up the chain or across branches.
        They can accept (it becomes their task) or decline with a reason.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" onFinish={submit} initialValues={{ priority: 'medium' }}>
        <Form.Item name="recipient_id" label="To" rules={[{ required: true }]}>
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="Select a staff member"
            options={staff.map((u) => ({
              value: u.id,
              label: `${u.full_name} (${u.email})`,
            }))}
          />
        </Form.Item>
        <Space style={{ display: 'flex' }} align="start">
          <Form.Item
            name="item_id"
            label="Item (optional — search your inventory)"
            style={{ flex: 1, minWidth: 260 }}
          >
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="Type to search…"
              options={items.map((i) => ({ value: i.id, label: i.name }))}
              onChange={(v) => {
                if (v && !form.getFieldValue('title')) {
                  const picked = items.find((i) => i.id === v);
                  if (picked) form.setFieldValue('title', `${picked.name}`);
                }
              }}
            />
          </Form.Item>
          {itemId != null && (
            <Form.Item
              name="quantity"
              label="Quantity"
              rules={[{ required: true, message: 'How many?' }]}
              initialValue={1}
              style={{ width: 120 }}
            >
              <InputNumber min={1} style={{ width: '100%' }} />
            </Form.Item>
          )}
        </Space>
        <Form.Item name="title" label="Title" rules={[{ required: true, max: 255 }]}>
          <Input placeholder="What do you need?" />
        </Form.Item>
        <Form.Item name="description" label="Details">
          <Input.TextArea rows={4} />
        </Form.Item>
        <Space style={{ display: 'flex' }} align="start">
          <Form.Item name="priority" label="Priority">
            <Select
              style={{ width: 140 }}
              options={['low', 'medium', 'high', 'urgent'].map((p) => ({
                value: p,
                label: p.toUpperCase(),
              }))}
            />
          </Form.Item>
          <Form.Item name="due_date" label="Needed by">
            <DatePicker />
          </Form.Item>
        </Space>
        <Button type="primary" htmlType="submit" loading={busy} block>
          Send request
        </Button>
      </Form>
    </Modal>
  );
}

function AcceptModal({
  request,
  onClose,
  onDone,
}: {
  request: WorkRequest | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [mode, setMode] = useState<'self' | 'delegate'>('self');
  const [assignee, setAssignee] = useState<number | undefined>();
  const [team, setTeam] = useState<UserBrief[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (request) {
      setMode('self');
      setAssignee(undefined);
      api.get<UserBrief[]>('/api/users/assignable').then(setTeam).catch(() => {});
    }
  }, [request]);

  const accept = async () => {
    if (!request) return;
    setBusy(true);
    try {
      await api.post(`/api/requests/${request.id}/accept`, {
        assignee_id: mode === 'delegate' ? assignee : null,
      });
      message.success('Request accepted — task created');
      onDone();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to accept');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={request !== null}
      onCancel={onClose}
      title={`Accept: ${request?.title ?? ''}`}
      onOk={accept}
      okText="Accept"
      confirmLoading={busy}
      okButtonProps={{ disabled: mode === 'delegate' && assignee === undefined }}
    >
      {request?.item && (
        <Typography.Paragraph>
          Requesting <Typography.Text strong>{request.quantity}</Typography.Text> x{' '}
          <Typography.Text strong>{request.item.name}</Typography.Text>
        </Typography.Paragraph>
      )}
      <Radio.Group
        value={mode}
        onChange={(e) => setMode(e.target.value)}
        options={[
          { value: 'self', label: 'Take it myself' },
          { value: 'delegate', label: 'Delegate into my team', disabled: team.length === 0 },
        ]}
      />
      {mode === 'delegate' && (
        <Select
          style={{ width: '100%', marginTop: 12 }}
          showSearch
          optionFilterProp="label"
          placeholder="Choose a team member"
          value={assignee}
          onChange={setAssignee}
          options={team.map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` }))}
        />
      )}
    </Modal>
  );
}

export default function RequestsPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [box, setBox] = useState<'received' | 'sent'>('received');
  const [rows, setRows] = useState<WorkRequest[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [accepting, setAccepting] = useState<WorkRequest | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<WorkRequest[]>(`/api/requests?box=${box}`)
      .then(setRows)
      .finally(() => setLoading(false));
  }, [box]);

  useEffect(load, [load]);

  const decline = (req: WorkRequest) => {
    let reason = '';
    Modal.confirm({
      title: `Decline: ${req.title}`,
      content: (
        <Input.TextArea
          rows={3}
          placeholder="Reason (required, shared with the requester)"
          onChange={(e) => (reason = e.target.value)}
        />
      ),
      okText: 'Decline',
      okButtonProps: { danger: true },
      onOk: async () => {
        if (!reason.trim()) {
          message.warning('A reason is required');
          return Promise.reject();
        }
        try {
          await api.post(`/api/requests/${req.id}/decline`, { reason });
          message.success('Request declined');
          load();
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : 'Failed to decline');
        }
      },
    });
  };

  return (
    <>
      <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          Requests
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
          New request
        </Button>
      </Space>
      <Tabs
        activeKey={box}
        onChange={(k) => setBox(k as 'received' | 'sent')}
        items={[
          { key: 'received', label: 'Received' },
          { key: 'sent', label: 'Sent' },
        ]}
      />
      <Table
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 15, hideOnSinglePage: true }}
        columns={[
          {
            title: 'Title',
            dataIndex: 'title',
            ellipsis: true,
            render: (title: string, r) => (
              <Space size={6}>
                <span>{title}</span>
                {r.item && (
                  <Tag color="geekblue">
                    {r.quantity} x {r.item.name}
                  </Tag>
                )}
              </Space>
            ),
          },
          {
            title: box === 'received' ? 'From' : 'To',
            width: 180,
            render: (_, r) =>
              box === 'received' ? r.requester.full_name : r.recipient.full_name,
          },
          {
            title: 'Priority',
            dataIndex: 'priority',
            width: 110,
            render: (p: WorkRequest['priority']) => <PriorityTag priority={p} />,
          },
          {
            title: 'Status',
            width: 220,
            render: (_, r) => (
              <Space size={4}>
                <RequestStatusTag status={r.status} />
                {r.status === 'accepted' && r.created_task_status && (
                  <Tooltip title="Status of the task this request spawned">
                    <span>
                      <StatusTag status={r.created_task_status} />
                    </span>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          {
            title: 'Sent',
            dataIndex: 'created_at',
            width: 120,
            render: (d: string) => dayjs(d).format('DD MMM'),
          },
          {
            title: '',
            width: 220,
            render: (_, r) => (
              <Space>
                {box === 'received' && r.status === 'pending' && r.recipient.id === me?.id && (
                  <>
                    <Button size="small" type="primary" onClick={() => setAccepting(r)}>
                      Accept
                    </Button>
                    <Button size="small" danger onClick={() => decline(r)}>
                      Decline
                    </Button>
                  </>
                )}
                {r.created_task_id && (
                  <Button size="small" onClick={() => navigate(`/tasks?task=${r.created_task_id}`)}>
                    View task
                  </Button>
                )}
                {r.status === 'declined' && r.decline_reason && (
                  <Tooltip title={r.decline_reason}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      why?
                    </Typography.Text>
                  </Tooltip>
                )}
              </Space>
            ),
          },
        ]}
      />
      <NewRequestModal open={creating} onClose={() => setCreating(false)} onCreated={load} />
      <AcceptModal request={accepting} onClose={() => setAccepting(null)} onDone={load} />
    </>
  );
}
