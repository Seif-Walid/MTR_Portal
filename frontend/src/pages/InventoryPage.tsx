import { EnvironmentOutlined, ImportOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, SendOutlined } from '@ant-design/icons';
import { Button, Input, Popover, Space, Table, Typography, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { InventoryItem } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import BulkAllocateModal from '../components/BulkAllocateModal';
import ImportFromSheetModal from '../components/ImportFromSheetModal';
import InventoryItemDrawer from '../components/InventoryItemDrawer';
import InventoryRequestsDrawer from '../components/InventoryRequestsDrawer';
import LocationsModal from '../components/LocationsModal';
import NewInventoryItemModal from '../components/NewInventoryItemModal';
import { ConditionTag } from '../components/tags';
import UsageBreakdown from '../components/UsageBreakdown';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";
const DANGER = '#ff5a6e';
const TEAL = '#4fd1b0';

function Chip({ text, tone = 'muted' }: { text: string; tone?: 'accent' | 'danger' | 'muted' }) {
  const c = tone === 'accent' ? '#5cc6ff' : tone === 'danger' ? DANGER : 'rgba(224,236,252,.5)';
  return <span style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: '.06em', textTransform: 'uppercase', color: c, border: `1px solid ${c}55`, background: `${c}14`, padding: '2px 8px', borderRadius: 5, whiteSpace: 'nowrap' }}>{text}</span>;
}

export default function InventoryPage() {
  const { me } = useAuth();
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [locationsOpen, setLocationsOpen] = useState(false);
  const [requestsOpen, setRequestsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  const canManage = can(me, 'inventory.edit');
  const openItemId = searchParams.get('item') ? Number(searchParams.get('item')) : null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((i) =>
      [i.name, i.category, i.asset_tag, i.location, i.team_lead?.full_name]
        .some((f) => f?.toLowerCase().includes(q)),
    );
  }, [items, query]);

  const selectedItems = useMemo(
    () => items.filter((i) => selectedIds.includes(i.id)),
    [items, selectedIds],
  );

  const load = useCallback(() => {
    setLoading(true);
    api.get<InventoryItem[]>('/api/inventory').then(setItems).catch((e) => message.error(e.message)).finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <Space wrap align="center" size={12}>
          <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>Components</h2>
          <span style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '.08em', color: 'rgba(224,236,252,.45)' }}>{filtered.length}{query ? `/${items.length}` : ''} SKU{filtered.length === 1 ? '' : 'S'}</span>
          {!canManage && <Chip text="Your team's equipment" tone="accent" />}
          <Button icon={<ReloadOutlined />} onClick={load} />
        </Space>
        <Input allowClear prefix={<SearchOutlined style={{ color: 'rgba(224,236,252,.4)' }} />} placeholder="Search components…" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: 240 }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <Space wrap>
          {canManage && selectedIds.length > 0 && (
            <Button type="primary" ghost icon={<PlusOutlined />} onClick={() => setBulkOpen(true)}>
              Allocate {selectedIds.length} selected
            </Button>
          )}
          <Button icon={<SendOutlined />} onClick={() => setRequestsOpen(true)}>Requests</Button>
          {canManage && <Button icon={<EnvironmentOutlined />} onClick={() => setLocationsOpen(true)}>Locations</Button>}
          {canManage && <Button icon={<ImportOutlined />} onClick={() => setImporting(true)}>Import components</Button>}
          {canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>Add item</Button>}
        </Space>
      </div>

      <Table className="circuit-table" rowKey="id" loading={loading} dataSource={filtered}
        rowSelection={canManage ? { selectedRowKeys: selectedIds, onChange: (keys) => setSelectedIds(keys as number[]) } : undefined}
        onRow={(i) => ({ onClick: () => setSearchParams({ item: String(i.id) }), style: { cursor: 'pointer' } })}
        pagination={{ defaultPageSize: 15, hideOnSinglePage: true }}
        columns={[
          {
            title: 'Item', dataIndex: 'name',
            render: (_, i) => (
              <div>
                <Space size={6}>
                  <Typography.Text strong style={{ color: '#eaf2ff' }}>{i.name}</Typography.Text>
                  {i.quantity <= i.low_stock_threshold && <Chip text="Low" tone="danger" />}
                </Space>
                {i.category && (
                  <div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>{i.category}{i.asset_tag ? ` · ${i.asset_tag}` : ''}</Typography.Text>
                  </div>
                )}
              </div>
            ),
          },
          { title: 'Total', width: 110, render: (_, i) => <span style={{ fontFamily: MONO, fontSize: 12.5 }}>{i.quantity} {i.unit}</span> },
          {
            title: 'In use', width: 110,
            render: (_, i) => (
              <Popover title="Usage breakdown" content={<UsageBreakdown item={i} unit />} trigger="hover">
                <Typography.Text strong onClick={(e) => e.stopPropagation()} style={{ cursor: 'help', borderBottom: '1px dashed currentColor', fontFamily: MONO }}>{i.in_use}</Typography.Text>
              </Popover>
            ),
          },
          {
            title: 'Free', width: 90,
            render: (_, i) => <span style={{ fontFamily: MONO, fontWeight: 600, fontSize: 13, color: i.free > 0 ? TEAL : DANGER }}>{i.free}</span>,
          },
          {
            title: 'Team', width: 160,
            render: (_, i) => i.team_lead ? <Chip text={i.team_lead.full_name} tone="accent" /> : <Typography.Text type="secondary">General</Typography.Text>,
          },
          { title: 'Condition', width: 120, render: (_, i) => <ConditionTag condition={i.condition} /> },
          { title: 'Location', dataIndex: 'location', ellipsis: true, render: (l: string | null) => l || '—' },
        ]} />

      <NewInventoryItemModal open={creating} onClose={() => setCreating(false)} onCreated={load} />
      <InventoryRequestsDrawer open={requestsOpen} onClose={() => setRequestsOpen(false)} />
      <ImportFromSheetModal open={importing} onClose={() => setImporting(false)} onImported={load} />
      <LocationsModal open={locationsOpen} onClose={() => setLocationsOpen(false)} />
      <InventoryItemDrawer itemId={openItemId} onClose={() => setSearchParams({})} onChanged={load} />
      <BulkAllocateModal
        items={selectedItems}
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        onAllocated={() => {
          setSelectedIds([]);
          load();
        }}
      />
    </>
  );
}
