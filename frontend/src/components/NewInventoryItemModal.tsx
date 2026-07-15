import { Button, Form, Input, InputNumber, Modal, Select, message } from 'antd';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Condition, InventoryItem, UserBrief } from '../api/types';

interface FormValues {
  name: string;
  category?: string;
  asset_tag?: string;
  sku?: string;
  quantity: number;
  low_stock_threshold?: number;
  unit: string;
  location?: string;
  condition: Condition;
  team_lead_id?: number;
  notes?: string;
}

const CONDITIONS: Condition[] = ['new', 'good', 'fair', 'poor', 'damaged'];

export default function NewInventoryItemModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form] = Form.useForm<FormValues>();
  const [holders, setHolders] = useState<UserBrief[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      api.get<UserBrief[]>('/api/inventory/holders').then(setHolders).catch(() => {});
    }
  }, [open]);

  const submit = async (values: FormValues) => {
    setBusy(true);
    try {
      await api.post<InventoryItem>('/api/inventory', values);
      message.success('Item added');
      form.resetFields();
      onCreated();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to add item');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title="Add inventory item" footer={null} destroyOnHidden>
      <Form
        form={form}
        layout="vertical"
        onFinish={submit}
        initialValues={{ quantity: 1, low_stock_threshold: 0, unit: 'unit', condition: 'good' }}
      >
        <Form.Item name="name" label="Name" rules={[{ required: true, max: 255 }]}>
          <Input placeholder="e.g. Arduino Uno R3" />
        </Form.Item>
        <Form.Item name="category" label="Category">
          <Input placeholder="e.g. Microcontrollers" />
        </Form.Item>
        <Form.Item name="quantity" label="Total quantity" rules={[{ required: true }]}>
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="low_stock_threshold" label="Low-stock threshold" tooltip="Flag the item as low when owned quantity drops to this or below.">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="sku" label="SKU">
          <Input placeholder="Optional" />
        </Form.Item>
        <Form.Item name="unit" label="Unit">
          <Input placeholder="unit, board, roll…" />
        </Form.Item>
        <Form.Item name="condition" label="Condition">
          <Select options={CONDITIONS.map((c) => ({ value: c, label: c.toUpperCase() }))} />
        </Form.Item>
        <Form.Item name="asset_tag" label="Asset tag">
          <Input placeholder="Optional" />
        </Form.Item>
        <Form.Item name="location" label="Location">
          <Input placeholder="e.g. Lab A — Shelf 3" />
        </Form.Item>
        <Form.Item
          name="team_lead_id"
          label="Dedicate to team (optional)"
          tooltip="Leave empty for general storage (staff-only). Choosing a team lead makes it visible to that team's members."
        >
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="General storage"
            options={holders.map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` }))}
          />
        </Form.Item>
        <Form.Item name="notes" label="Notes">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={busy} block>
          Add item
        </Button>
      </Form>
    </Modal>
  );
}
