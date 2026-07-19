import { DeleteOutlined, PlusOutlined, SendOutlined } from '@ant-design/icons';
import {
  Button,
  Col,
  Descriptions,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  message,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import type {
  AllocationPurpose,
  CompetitionBrief,
  InventoryItem,
  UserBrief,
} from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import HoldingsMatrix from './HoldingsMatrix';
import RequestUnitsModal from './RequestUnitsModal';
import { ConditionTag, PURPOSE_META, PurposeTag } from './tags';
import UsageBreakdown from './UsageBreakdown';
import WhereaboutsPanel from './WhereaboutsPanel';

const PURPOSES: AllocationPurpose[] = ['training', 'competition', 'research', 'borrowed', 'other'];

export default function InventoryItemDrawer({
  itemId,
  onClose,
  onChanged,
}: {
  itemId: number | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { me } = useAuth();
  const [item, setItem] = useState<InventoryItem | null>(null);
  const [holders, setHolders] = useState<UserBrief[]>([]);
  const [competitions, setCompetitions] = useState<CompetitionBrief[]>([]);
  const [allocForm] = Form.useForm();
  const allocPurpose = Form.useWatch('purpose', allocForm) as AllocationPurpose | undefined;
  const [busy, setBusy] = useState(false);
  const [requesting, setRequesting] = useState(false);

  const canManage = can(me, 'inventory.edit');

  const load = (id: number) =>
    api.get<InventoryItem>(`/api/inventory/${id}`).then(setItem).catch((e) => message.error(e.message));

  useEffect(() => {
    setItem(null);
    if (itemId !== null) void load(itemId);
  }, [itemId]);

  useEffect(() => {
    if (itemId !== null && canManage && holders.length === 0) {
      api.get<UserBrief[]>('/api/inventory/holders').then(setHolders).catch(() => {});
      api.get<CompetitionBrief[]>('/api/competitions').then(setCompetitions).catch(() => {});
    }
  }, [itemId, canManage, holders.length]);

  const holderOptions = useMemo(
    () => holders.map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` })),
    [holders],
  );

  const refresh = async (id: number) => {
    await load(id);
    onChanged();
  };

  const addAllocation = async (values: {
    quantity: number;
    purpose: AllocationPurpose;
    label?: string;
    competition_id?: number;
    holder_id?: number;
  }) => {
    if (!item) return;
    setBusy(true);
    try {
      const updated = await api.post<InventoryItem>(`/api/inventory/${item.id}/allocations`, values);
      setItem(updated);
      onChanged();
      allocForm.resetFields();
      message.success('Units allocated');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to allocate');
    } finally {
      setBusy(false);
    }
  };

  const removeAllocation = async (allocationId: number) => {
    if (!item) return;
    try {
      await api.delete(`/api/inventory/allocations/${allocationId}`);
      await refresh(item.id);
      message.success('Allocation removed');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to remove');
    }
  };

  const deleteItem = async (permanent = false) => {
    if (!item) return;
    try {
      await api.delete(`/api/inventory/${item.id}${permanent ? '?permanent=true' : ''}`);
      message.success(permanent ? 'Item permanently deleted' : 'Item deleted');
      onChanged();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to delete');
    }
  };

  return (
    <Drawer open={itemId !== null} onClose={onClose} width={600} title={item?.name ?? 'Item'}>
      {item && (
        <>
          <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space wrap>
              {item.category && <Tag>{item.category}</Tag>}
              <ConditionTag condition={item.condition} />
              <Tag color={item.team_lead ? 'geekblue' : 'default'}>
                {item.team_lead ? `Team: ${item.team_lead.full_name}` : 'General storage'}
              </Tag>
              {item.quantity <= item.low_stock_threshold && <Tag color="red">LOW STOCK</Tag>}
            </Space>
            <Button size="small" icon={<SendOutlined />} onClick={() => setRequesting(true)}>
              Request units
            </Button>
          </Space>

          <Row gutter={16} style={{ marginTop: 20 }}>
            <Col span={8}>
              <Statistic title="Total" value={item.quantity} suffix={item.unit} />
            </Col>
            <Col span={8}>
              <Statistic title="In use" value={item.in_use} />
            </Col>
            <Col span={8}>
              <Statistic
                title="Free"
                value={item.free}
                valueStyle={{ color: item.free > 0 ? '#3f8600' : '#cf1322' }}
              />
            </Col>
          </Row>

          <Divider plain>Usage breakdown</Divider>
          <UsageBreakdown item={item} unit />

          <Divider plain>Holdings — who has what, by activity</Divider>
          <HoldingsMatrix item={item} />

          <Divider plain>Whereabouts — where the stock physically is</Divider>
          <WhereaboutsPanel item={item} canManage={canManage} />

          <Descriptions column={1} size="small" style={{ marginTop: 16 }}>
            {item.asset_tag && (
              <Descriptions.Item label="Asset tag">{item.asset_tag}</Descriptions.Item>
            )}
            {item.location && <Descriptions.Item label="Location">{item.location}</Descriptions.Item>}
            {item.notes && <Descriptions.Item label="Notes">{item.notes}</Descriptions.Item>}
          </Descriptions>

          {canManage && (
            <>
              <Divider plain>Manage allocations</Divider>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {item.allocations.length === 0 && (
                  <Typography.Text type="secondary">No allocations yet.</Typography.Text>
                )}
                {item.allocations.map((a) => (
                  <div
                    key={a.id}
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}
                  >
                    <Space wrap>
                      <PurposeTag purpose={a.purpose} />
                      <Typography.Text strong>{a.quantity}</Typography.Text>
                      {a.competition ? (
                        <Tag color="gold">{a.competition.name}</Tag>
                      ) : (
                        a.display_label && (
                          <Typography.Text type="secondary">{a.display_label}</Typography.Text>
                        )
                      )}
                      {a.holder && <Tag color="geekblue">{a.holder.full_name}</Tag>}
                    </Space>
                    <Popconfirm title="Remove this allocation?" onConfirm={() => removeAllocation(a.id)}>
                      <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </div>
                ))}
              </Space>

              <Form
                form={allocForm}
                layout="vertical"
                onFinish={addAllocation}
                initialValues={{ purpose: 'training', quantity: 1 }}
                style={{ marginTop: 16 }}
              >
                <Row gutter={8}>
                  <Col span={8}>
                    <Form.Item name="quantity" label="Quantity" rules={[{ required: true }]}>
                      <InputNumber min={1} max={item.free} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={16}>
                    <Form.Item name="purpose" label="Purpose">
                      <Select options={PURPOSES.map((p) => ({ value: p, label: PURPOSE_META[p].label }))} />
                    </Form.Item>
                  </Col>
                </Row>
                {allocPurpose === 'competition' ? (
                  <Form.Item name="competition_id" label="Competition">
                    <Select
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      placeholder={competitions.length ? 'Pick a competition' : 'No competitions yet — add one first'}
                      options={competitions.map((c) => ({ value: c.id, label: c.name }))}
                      notFoundContent="Add competitions on the Competitions page"
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
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<PlusOutlined />}
                  loading={busy}
                  disabled={item.free <= 0}
                  block
                >
                  {item.free > 0 ? 'Allocate units' : 'No free units to allocate'}
                </Button>
              </Form>

              <Divider />
              <Popconfirm
                title="Delete this item?"
                description="It's kept for history (allocations, movements, past requests) but hidden everywhere."
                onConfirm={() => deleteItem(false)}
              >
                <Button danger icon={<DeleteOutlined />} block>
                  Delete item
                </Button>
              </Popconfirm>
              {me?.level?.rank === 1 && (
                <Popconfirm
                  title="Permanently delete this item?"
                  description="This really removes it, including all its allocation, movement and request history. Admin-only — use for genuine mistakes."
                  onConfirm={() => deleteItem(true)}
                >
                  <Button danger type="text" icon={<DeleteOutlined />} block style={{ marginTop: 4 }}>
                    Permanently delete (admin)
                  </Button>
                </Popconfirm>
              )}
            </>
          )}
        </>
      )}
      {item && (
        <RequestUnitsModal
          item={item}
          open={requesting}
          onClose={() => setRequesting(false)}
          onRequested={() => refresh(item.id)}
        />
      )}
    </Drawer>
  );
}
