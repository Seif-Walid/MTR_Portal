import { PlusOutlined } from '@ant-design/icons';
import {
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Typography,
  message,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import type {
  AllocationPurpose,
  EventBrief,
  InventoryItem,
  UserBrief,
} from '../api/types';
import { PURPOSE_META } from './tags';

const PURPOSES: AllocationPurpose[] = ['training', 'event', 'research', 'borrowed', 'other'];

export default function BulkAllocateModal({
  items,
  open,
  onClose,
  onAllocated,
}: {
  items: InventoryItem[];
  open: boolean;
  onClose: () => void;
  onAllocated: () => void;
}) {
  const [form] = Form.useForm();
  const purpose = Form.useWatch('purpose', form) as AllocationPurpose | undefined;
  const [holders, setHolders] = useState<UserBrief[]>([]);
  const [events, setEvents] = useState<EventBrief[]>([]);
  const [qty, setQty] = useState<Record<number, number>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.get<UserBrief[]>('/api/inventory/holders').then(setHolders).catch(() => {});
    api.get<EventBrief[]>('/api/events').then(setEvents).catch(() => {});
  }, [open]);

  // seed each selected item with 1 unit (clamped to what's free)
  useEffect(() => {
    if (open) setQty(Object.fromEntries(items.map((i) => [i.id, Math.min(1, i.free)])));
  }, [open, items]);

  const holderOptions = useMemo(
    () => holders.map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` })),
    [holders],
  );

  const submit = async () => {
    const values = await form.validateFields();
    const lines = items
      .map((i) => ({ item_id: i.id, quantity: qty[i.id] ?? 0 }))
      .filter((l) => l.quantity > 0);
    if (lines.length === 0) {
      message.warning('Set a quantity above 0 for at least one item');
      return;
    }
    setBusy(true);
    try {
      await api.post('/api/inventory/allocations/bulk', {
        lines,
        purpose: values.purpose,
        label: values.label ?? '',
        event_id: values.event_id ?? null,
        holder_id: values.holder_id ?? null,
      });
      message.success(`Allocated ${lines.length} item${lines.length === 1 ? '' : 's'}`);
      onAllocated();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to allocate');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={submit}
      okText="Allocate all"
      okButtonProps={{ icon: <PlusOutlined />, loading: busy }}
      title={`Allocate ${items.length} item${items.length === 1 ? '' : 's'}`}
      width={560}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" initialValues={{ purpose: 'training' }}>
        <Form.Item name="purpose" label="Purpose">
          <Select options={PURPOSES.map((p) => ({ value: p, label: PURPOSE_META[p].label }))} />
        </Form.Item>
        {purpose === 'event' ? (
          <Form.Item name="event_id" label="Event">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={events.length ? 'Pick an event' : 'No events yet — add one first'}
              options={events.map((c) => ({ value: c.id, label: c.name }))}
            />
          </Form.Item>
        ) : (
          <Form.Item name="label" label="Label (project / activity name)">
            <Input placeholder="Optional — e.g. Line-follower R&D" />
          </Form.Item>
        )}
        <Form.Item name="holder_id" label="Holder (who has it)">
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Unassigned pool"
            options={holderOptions}
          />
        </Form.Item>
      </Form>

      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Quantity per item (free stock shown)
      </Typography.Text>
      <Space direction="vertical" size={6} style={{ width: '100%', marginTop: 8 }}>
        {items.map((i) => (
          <div
            key={i.id}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}
          >
            <Typography.Text style={{ flex: 1 }}>
              {i.name}{' '}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {i.free} free
              </Typography.Text>
            </Typography.Text>
            <InputNumber
              min={0}
              max={i.free}
              value={qty[i.id] ?? 0}
              onChange={(v) => setQty((q) => ({ ...q, [i.id]: Number(v ?? 0) }))}
              disabled={i.free <= 0}
              style={{ width: 90 }}
            />
          </div>
        ))}
      </Space>
    </Modal>
  );
}
