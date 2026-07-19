import {
  CloudUploadOutlined,
  EnvironmentOutlined,
  ImportOutlined,
  PlusOutlined,
  ReloadOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { Button, Popover, Space, Table, Tag, Tooltip, Typography, message } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { InventoryItem, SheetsStatus } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import ImportFromSheetModal from '../components/ImportFromSheetModal';
import InventoryItemDrawer from '../components/InventoryItemDrawer';
import InventoryRequestsDrawer from '../components/InventoryRequestsDrawer';
import LocationsModal from '../components/LocationsModal';
import NewInventoryItemModal from '../components/NewInventoryItemModal';
import { ConditionTag } from '../components/tags';
import UsageBreakdown from '../components/UsageBreakdown';

export default function InventoryPage() {
  const { me } = useAuth();
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [locationsOpen, setLocationsOpen] = useState(false);
  const [requestsOpen, setRequestsOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [sheets, setSheets] = useState<SheetsStatus | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const canManage = can(me, 'inventory.edit');
  const openItemId = searchParams.get('item') ? Number(searchParams.get('item')) : null;

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<InventoryItem[]>('/api/inventory')
      .then(setItems)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    if (canManage) {
      api.get<SheetsStatus>('/api/inventory/sheets/status').then(setSheets).catch(() => {});
    }
  }, [canManage]);

  const sync = async () => {
    setSyncing(true);
    try {
      const res = await api.post<{ synced: number }>('/api/inventory/sync');
      message.success(`Synced ${res.synced} items to Google Sheets`);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <Space wrap align="center">
          <Typography.Title level={4} style={{ margin: 0 }}>
            Inventory
          </Typography.Title>
          {!canManage && <Tag color="geekblue">Your team's equipment</Tag>}
          <Button icon={<ReloadOutlined />} onClick={load} />
        </Space>
        <Space wrap>
          <Button icon={<SendOutlined />} onClick={() => setRequestsOpen(true)}>
            Requests
          </Button>
          {canManage && (
            <Button icon={<EnvironmentOutlined />} onClick={() => setLocationsOpen(true)}>
              Locations
            </Button>
          )}
          {canManage && (
            <Button icon={<ImportOutlined />} onClick={() => setImporting(true)}>
              Import components
            </Button>
          )}
          {canManage && (
            <Tooltip
              title={
                sheets && !sheets.configured
                  ? 'Google Sheets sync is not configured on the server'
                  : 'Push the whole inventory into the linked Google Sheet (overwrites it)'
              }
            >
              <Button
                icon={<CloudUploadOutlined />}
                loading={syncing}
                disabled={!sheets?.configured}
                onClick={sync}
              >
                Sync to Sheets
              </Button>
            </Tooltip>
          )}
          {canManage && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
              Add item
            </Button>
          )}
        </Space>
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        onRow={(i) => ({
          onClick: () => setSearchParams({ item: String(i.id) }),
          style: { cursor: 'pointer' },
        })}
        pagination={{ pageSize: 15, hideOnSinglePage: true }}
        columns={[
          {
            title: 'Item',
            dataIndex: 'name',
            render: (_, i) => (
              <div>
                <Space size={6}>
                  <Typography.Text strong>{i.name}</Typography.Text>
                  {i.quantity <= i.low_stock_threshold && <Tag color="red">LOW</Tag>}
                </Space>
                {i.category && (
                  <div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {i.category}
                      {i.asset_tag ? ` · ${i.asset_tag}` : ''}
                    </Typography.Text>
                  </div>
                )}
              </div>
            ),
          },
          {
            title: 'Total',
            width: 110,
            render: (_, i) => `${i.quantity} ${i.unit}`,
          },
          {
            title: 'In use',
            width: 110,
            render: (_, i) => (
              <Popover
                title="Usage breakdown"
                content={<UsageBreakdown item={i} unit />}
                trigger="hover"
              >
                <Typography.Text
                  strong
                  onClick={(e) => e.stopPropagation()}
                  style={{ cursor: 'help', borderBottom: '1px dashed currentColor' }}
                >
                  {i.in_use}
                </Typography.Text>
              </Popover>
            ),
          },
          {
            title: 'Free',
            width: 90,
            render: (_, i) => (
              <Typography.Text strong style={{ color: i.free > 0 ? '#3f8600' : '#cf1322' }}>
                {i.free}
              </Typography.Text>
            ),
          },
          {
            title: 'Team',
            width: 160,
            render: (_, i) =>
              i.team_lead ? (
                <Tag color="geekblue">{i.team_lead.full_name}</Tag>
              ) : (
                <Typography.Text type="secondary">General</Typography.Text>
              ),
          },
          {
            title: 'Condition',
            width: 120,
            render: (_, i) => <ConditionTag condition={i.condition} />,
          },
          {
            title: 'Location',
            dataIndex: 'location',
            ellipsis: true,
            render: (l: string | null) => l || '—',
          },
        ]}
      />

      <NewInventoryItemModal open={creating} onClose={() => setCreating(false)} onCreated={load} />
      <InventoryRequestsDrawer open={requestsOpen} onClose={() => setRequestsOpen(false)} />
      <ImportFromSheetModal
        open={importing}
        onClose={() => setImporting(false)}
        onImported={load}
      />
      <LocationsModal open={locationsOpen} onClose={() => setLocationsOpen(false)} />
      <InventoryItemDrawer
        itemId={openItemId}
        onClose={() => setSearchParams({})}
        onChanged={load}
      />
    </>
  );
}
