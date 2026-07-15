import { Button, DatePicker, Form, Input, InputNumber, Modal, message } from 'antd';
import type { Dayjs } from 'dayjs';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { InventoryItem, InventoryRequest } from '../api/types';

interface FormValues {
  quantity: number;
  reason?: string;
  needed_by?: Dayjs;
  return_by?: Dayjs;
}

export default function RequestUnitsModal({ item, open, onClose, onRequested }: {
  item: InventoryItem;
  open: boolean;
  onClose: () => void;
  onRequested: () => void;
}) {
  const [form] = Form.useForm<FormValues>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) form.resetFields();
  }, [open, form]);

  const submit = async (values: FormValues) => {
    setBusy(true);
    try {
      await api.post<InventoryRequest>('/api/inventory/requests', {
        item_id: item.id,
        quantity: values.quantity,
        reason: values.reason ?? '',
        needed_by: values.needed_by?.format('YYYY-MM-DD') ?? null,
        return_by: values.return_by?.format('YYYY-MM-DD') ?? null,
      });
      message.success('Request submitted');
      onRequested();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to submit request');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title={`Request ${item.name}`} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={submit} initialValues={{ quantity: 1 }}>
        <Form.Item name="quantity" label="Quantity" rules={[{ required: true }]}>
          <InputNumber min={1} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="reason" label="Reason">
          <Input.TextArea rows={2} placeholder="What do you need it for?" />
        </Form.Item>
        <Form.Item name="needed_by" label="Needed by">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="return_by" label="Return by (leave blank if not returning)">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={busy} block>
          Submit request
        </Button>
      </Form>
    </Modal>
  );
}
