import { Button, DatePicker, Form, Input, InputNumber, Modal, Select, Typography, message } from 'antd';
import type { Dayjs } from 'dayjs';
import { useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { InventoryItem, InventoryRequest, Whereabouts } from '../api/types';

interface FormValues {
  item_id: number;
  quantity: number;
  reason?: string;
  needed_by?: Dayjs;
  return_by?: Dayjs;
}

/** If `item` is given, the item is fixed (opened from that item's drawer).
 *  Otherwise a searchable dropdown lets the user pick from the whole
 *  inventory they can see — used by the general "New request" entry point. */
export default function RequestUnitsModal({ item, open, onClose, onRequested }: {
  item?: InventoryItem;
  open: boolean;
  onClose: () => void;
  onRequested: () => void;
}) {
  const [form] = Form.useForm<FormValues>();
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | undefined>(item?.id);
  const [available, setAvailable] = useState<number | null>(null);
  const quantity = Form.useWatch('quantity', form) as number | undefined;

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    setSelectedId(item?.id);
    setAvailable(null);
    if (item) {
      form.setFieldValue('item_id', item.id);
    } else {
      api.get<InventoryItem[]>('/api/inventory').then(setItems).catch(() => {});
    }
  }, [open, item, form]);

  useEffect(() => {
    if (!open || selectedId == null) {
      setAvailable(null);
      return;
    }
    api
      .get<Whereabouts>(`/api/inventory/${selectedId}/whereabouts`)
      .then((w) => setAvailable(w.by_location.reduce((sum, p) => sum + p.quantity, 0)))
      .catch(() => setAvailable(null));
  }, [open, selectedId]);

  const selectedItem = useMemo(
    () => item ?? items.find((i) => i.id === selectedId),
    [item, items, selectedId],
  );
  const overStock = available != null && (quantity ?? 0) > available;

  const submit = async (values: FormValues) => {
    setBusy(true);
    try {
      await api.post<InventoryRequest>('/api/inventory/requests', {
        item_id: values.item_id,
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
    <Modal
      open={open}
      onCancel={onClose}
      title={item ? `Request ${item.name}` : 'Request inventory'}
      footer={null}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={submit} initialValues={{ quantity: 1 }}>
        {!item && (
          <Form.Item name="item_id" label="Item" rules={[{ required: true, message: 'Pick an item' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="Search inventory…"
              onChange={setSelectedId}
              options={items.map((i) => ({ value: i.id, label: `${i.name}${i.category ? ` (${i.category})` : ''}` }))}
            />
          </Form.Item>
        )}
        <Form.Item
          name="quantity"
          label="Quantity"
          rules={[{ required: true }]}
          help={
            overStock ? (
              <Typography.Text type="danger">
                Only {available} {selectedItem?.unit ?? 'unit'}(s) currently in stock — you can still
                send this request, it just flags that more needs to be bought.
              </Typography.Text>
            ) : undefined
          }
        >
          <InputNumber min={1} status={overStock ? 'error' : undefined} style={{ width: '100%' }} />
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
