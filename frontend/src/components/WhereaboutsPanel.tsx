import { SwapOutlined } from '@ant-design/icons';
import { Button, Col, Divider, Empty, Form, Input, InputNumber, List, Row, Select, Space, Statistic, Tag, Typography, message } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { InventoryItem, Location, StockMovement, UserBrief, Whereabouts } from '../api/types';

function placeLabel(m: StockMovement, dir: 'from' | 'to'): string {
  const loc = dir === 'from' ? m.from_location : m.to_location;
  const holder = dir === 'from' ? m.from_holder : m.to_holder;
  if (loc) return loc.name;
  if (holder) return holder.full_name;
  return dir === 'from' ? 'stock-in' : 'consumed';
}

export default function WhereaboutsPanel({ item, canManage }: { item: InventoryItem; canManage: boolean }) {
  const [w, setW] = useState<Whereabouts | null>(null);
  const [locations, setLocations] = useState<Location[]>([]);
  const [holders, setHolders] = useState<UserBrief[]>([]);
  const [movements, setMovements] = useState<StockMovement[]>([]);
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<Whereabouts>(`/api/inventory/${item.id}/whereabouts`).then(setW).catch(() => {});
    api.get<StockMovement[]>(`/api/inventory/${item.id}/movements`).then(setMovements).catch(() => {});
  }, [item.id]);

  useEffect(() => {
    load();
    if (canManage) {
      api.get<Location[]>('/api/inventory/locations').then(setLocations).catch(() => {});
      api.get<UserBrief[]>('/api/inventory/holders').then(setHolders).catch(() => {});
    }
  }, [load, canManage]);

  const placeOptions = [
    { label: 'Nowhere (stock-in / consume)', options: [{ value: 'none', label: '— nowhere —' }] },
    { label: 'Locations', options: locations.map((l) => ({ value: `loc:${l.id}`, label: l.name })) },
    { label: 'Holders', options: holders.map((h) => ({ value: `usr:${h.id}`, label: h.full_name })) },
  ];

  const parse = (v: string | undefined) => {
    if (!v || v === 'none') return {};
    const [k, id] = v.split(':');
    return k === 'loc' ? { location_id: Number(id) } : { holder_id: Number(id) };
  };

  const submit = async (values: { quantity: number; from?: string; to?: string; reason?: string }) => {
    const from = parse(values.from);
    const to = parse(values.to);
    setBusy(true);
    try {
      const res = await api.post<Whereabouts>(`/api/inventory/${item.id}/movements`, {
        quantity: values.quantity,
        from_location_id: from.location_id ?? null,
        from_holder_id: from.holder_id ?? null,
        to_location_id: to.location_id ?? null,
        to_holder_id: to.holder_id ?? null,
        reason: values.reason ?? '',
      });
      setW(res);
      load();
      form.resetFields();
      message.success('Movement recorded');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to record movement');
    } finally {
      setBusy(false);
    }
  };

  if (!w) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Loading…" />;

  return (
    <>
      <Row gutter={16}>
        <Col span={8}><Statistic title="Owned" value={w.owned} suffix={item.unit} /></Col>
        <Col span={8}><Statistic title="Tracked in ledger" value={w.tracked} /></Col>
        <Col span={8}>
          <Statistic title="Low stock" valueRender={() => (w.low_stock ? <Tag color="red">LOW</Tag> : <Tag color="green">OK</Tag>)} value={0} />
        </Col>
      </Row>

      <Divider plain>On hand</Divider>
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        {w.by_location.length === 0 && w.by_holder.length === 0 && (
          <Typography.Text type="secondary">Nothing placed yet — record a stock-in below.</Typography.Text>
        )}
        {w.by_location.map((p) => (
          <div key={`l${p.location?.id}`} style={{ display: 'flex', justifyContent: 'space-between' }}>
            <Space><Tag>location</Tag>{p.location?.name}</Space>
            <Typography.Text strong>{p.quantity}</Typography.Text>
          </div>
        ))}
        {w.by_holder.map((p) => (
          <div key={`h${p.holder?.id}`} style={{ display: 'flex', justifyContent: 'space-between' }}>
            <Space><Tag color="geekblue">holder</Tag>{p.holder?.full_name}</Space>
            <Typography.Text strong>{p.quantity}</Typography.Text>
          </div>
        ))}
      </Space>

      {canManage && (
        <>
          <Divider plain>Record a movement</Divider>
          <Form form={form} layout="vertical" onFinish={submit} initialValues={{ from: 'none', to: 'none' }}>
            <Row gutter={8}>
              <Col span={6}>
                <Form.Item name="quantity" label="Qty" rules={[{ required: true }]}>
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={9}>
                <Form.Item name="from" label="From">
                  <Select options={placeOptions} showSearch optionFilterProp="label" />
                </Form.Item>
              </Col>
              <Col span={9}>
                <Form.Item name="to" label="To">
                  <Select options={placeOptions} showSearch optionFilterProp="label" />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="reason" label="Reason">
              <Input placeholder="e.g. Initial stock-in, issued for R&D, returned" />
            </Form.Item>
            <Button type="primary" htmlType="submit" icon={<SwapOutlined />} loading={busy} block>
              Record movement
            </Button>
          </Form>
        </>
      )}

      <Divider plain>Movement history</Divider>
      <List
        size="small"
        locale={{ emptyText: 'No movements yet' }}
        dataSource={movements}
        renderItem={(m) => (
          <List.Item>
            <Space size={6} wrap>
              <Typography.Text strong>{m.quantity}</Typography.Text>
              <Typography.Text type="secondary">{placeLabel(m, 'from')}</Typography.Text>
              <SwapOutlined style={{ fontSize: 11 }} />
              <Typography.Text type="secondary">{placeLabel(m, 'to')}</Typography.Text>
              {m.reason && <Tag>{m.reason}</Tag>}
            </Space>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {dayjs(m.created_at).format('DD MMM HH:mm')}
            </Typography.Text>
          </List.Item>
        )}
      />
    </>
  );
}
