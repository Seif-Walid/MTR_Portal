import { DollarOutlined, EnvironmentOutlined, ImportOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, SendOutlined, SyncOutlined } from '@ant-design/icons';
import { Button, Input, Popover, Space, Table, Typography, message } from 'antd';
import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { InventoryItem, SearchHit, ValueSummary } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import BulkAllocateModal from '../components/BulkAllocateModal';
import ImportFromFileModal from '../components/ImportFromFileModal';
import InventoryItemDrawer from '../components/InventoryItemDrawer';
import InventoryRequestsDrawer from '../components/InventoryRequestsDrawer';
import { PricingReviewModal, SOURCE_LABEL, ValueSourceTag, egp } from '../components/ItemValue';
import LocationsModal from '../components/LocationsModal';
import NewInventoryItemModal from '../components/NewInventoryItemModal';
import EmptyState from '../components/EmptyState';
import { ConditionTag } from '../components/tags';
import UsageBreakdown from '../components/UsageBreakdown';
import { openableRow } from '../components/a11y';
import { asButton } from '../components/a11y';

const MONO = 'var(--font-mono)';
const DISPLAY = 'var(--font-display)';
const DANGER = 'var(--error)';
const TEAL = '#4fd1b0';

const SIMILAR_MIN = 0.55; // cosine floor for a semantic-only match
const SIMILAR_BAND = 0.08; // ...and within this much of the best match

function Chip({ text, tone = 'muted' }: { text: string; tone?: 'accent' | 'danger' | 'muted' }) {
  const c = tone === 'accent' ? 'var(--brand-fg)' : tone === 'danger' ? DANGER : 'var(--text-tertiary)';
  return <span style={{ fontSize: 11.5, fontWeight: 500, color: c, background: c.startsWith('#') || c.startsWith('var(') ? `color-mix(in srgb, ${c} 12%, transparent)` : 'color-mix(in srgb, var(--text-primary) 6%, transparent)', padding: '2px 10px', borderRadius: 999, whiteSpace: 'nowrap' }}>{text}</span>;
}

function useIsMobile(bp = 768) {
  const [mobile, setMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia(`(max-width: ${bp}px)`).matches);
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${bp}px)`);
    const apply = () => setMobile(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [bp]);
  return mobile;
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span className="mtr-label">{label}</span>
      <span style={{ fontFamily: MONO, fontSize: 13 }}>{children}</span>
    </div>
  );
}

function WorthBanner({ summary, onPrice }: { summary: ValueSummary; onPrice?: () => void }) {
  const sources = (['makers', 'future', 'manual'] as const).filter((k) => summary.by_source[k]);
  return (
    <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', alignItems: 'flex-end', borderRadius: 18, padding: '14px 18px', marginBottom: 18, background: 'color-mix(in srgb, var(--text-primary) 2.5%, transparent)' }}>
      <Stat label="Inventory worth"><span style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)' }}>{egp(summary.total, summary.currency)}</span></Stat>
      {sources.map((k) => (
        <Stat key={k} label={SOURCE_LABEL[k]}>
          <span style={{ color: k === 'manual' ? 'var(--warning-text)' : undefined }}>{egp(summary.by_source[k]!.total)}</span>
          <span style={{ color: 'var(--text-tertiary)' }}> · {summary.by_source[k]!.items} items</span>
        </Stat>
      ))}
      <Stat label="Unpriced">
        <span style={{ color: summary.unpriced_items ? 'var(--cat-amber)' : TEAL }}>{summary.unpriced_items} items · {summary.unpriced_units} units</span>
        {summary.unpriced_items > 0 && onPrice && (
          <button type="button" className="mtr-link-btn" onClick={onPrice} style={{ fontSize: 12.5, marginInlineStart: 10 }}>Price them →</button>
        )}
      </Stat>
      {summary.stale_items > 0 && <Stat label="Stale"><span style={{ color: DANGER }}>{summary.stale_items} refresh failed</span></Stat>}
      <Typography.Text type="secondary" style={{ fontSize: 11.5, flexBasis: '100%' }}>
        Unit value × total owned (allocated units included). Unpriced items are left out, not estimated.
      </Typography.Text>
    </div>
  );
}

function ItemCard({ item, onOpen }: { item: InventoryItem; onOpen: () => void }) {
  const low = item.quantity <= item.low_stock_threshold;
  return (
    <div
      {...asButton(onOpen, { label: `Open ${item.name}` })}
      className="mtr-card-btn"
      style={{
        border: '1px solid var(--c-hairline-row, color-mix(in srgb, var(--text-primary) 8%, transparent))', borderRadius: 10,
        background: 'color-mix(in srgb, var(--text-primary) 1.5%, transparent)', padding: '12px 14px', cursor: 'pointer',
        display: 'flex', flexDirection: 'column', gap: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <Typography.Text strong style={{ color: 'var(--text-primary)', fontSize: 15 }}>{item.name}</Typography.Text>
            {low && <Chip text="Low" tone="danger" />}
          </div>
          {item.category && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{item.category}{item.asset_tag ? ` · ${item.asset_tag}` : ''}</Typography.Text>
          )}
        </div>
        <ConditionTag condition={item.condition} />
      </div>
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
        <Stat label="Total">{item.quantity} {item.unit}</Stat>
        <Stat label="In use">{item.in_use}</Stat>
        <Stat label="Free"><span style={{ fontWeight: 600, color: item.free > 0 ? TEAL : DANGER }}>{item.free}</span></Stat>
        <Stat label="Value">{egp(item.total_value)}</Stat>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        {item.team_lead ? <Chip text={item.team_lead.full_name} tone="accent" /> : <Typography.Text type="secondary" style={{ fontSize: 12 }}>General</Typography.Text>}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{item.location || '—'}</Typography.Text>
      </div>
    </div>
  );
}

export default function InventoryPage() {
  const { me } = useAuth();
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [locationsOpen, setLocationsOpen] = useState(false);
  const [requestsOpen, setRequestsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [summary, setSummary] = useState<ValueSummary | null>(null);
  const [pricingOpen, setPricingOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  const canManage = can(me, 'inventory.edit');
  const isMobile = useIsMobile();
  const openItemId = searchParams.get('item') ? Number(searchParams.get('item')) : null;

  // Semantic matches: parts known by another name ("buck driver" finds the
  // step-down converters). Shown after the exact matches, tagged "similar".
  const [similar, setSimilar] = useState<Map<number, number>>(new Map());
  useEffect(() => {
    const q = query.trim();
    if (q.length < 3) { setSimilar(new Map()); return; }
    const t = setTimeout(() => {
      api.get<SearchHit[]>(`/api/ai/search?types=inventory&limit=25&q=${encodeURIComponent(q)}`)
        .then((hits) => {
          // cosine scales differ per query, so keep what is close to the best hit
          const best = Math.max(0, ...hits.map((h) => h.semantic));
          const keep = hits.filter((h) => h.semantic >= Math.max(SIMILAR_MIN, best - SIMILAR_BAND)).slice(0, 8);
          setSimilar(new Map(keep.map((h) => [h.id, h.score])));
        })
        .catch(() => setSimilar(new Map()));
    }, 350);
    return () => clearTimeout(t);
  }, [query]);

  const [filtered, similarIds] = useMemo((): [InventoryItem[], Set<number>] => {
    const q = query.trim().toLowerCase();
    if (!q) return [items, new Set()];
    const exact = items.filter((i) =>
      [i.name, i.aliases, i.category, i.asset_tag, i.location, i.team_lead?.full_name]
        .some((f) => f?.toLowerCase().includes(q)),
    );
    const seen = new Set(exact.map((i) => i.id));
    const extra = items
      .filter((i) => !seen.has(i.id) && similar.has(i.id))
      .sort((a, b) => (similar.get(b.id) ?? 0) - (similar.get(a.id) ?? 0));
    return [[...exact, ...extra], new Set(extra.map((i) => i.id))];
  }, [items, query, similar]);

  const empty = query.trim() ? (
    <EmptyState phrase={<>No components match “{query.trim()}”.</>} action={{ label: 'Clear the search', onClick: () => setQuery('') }} />
  ) : canManage ? (
    <EmptyState phrase="The shelves are empty." action={{ label: 'Add a component', onClick: () => setCreating(true) }} />
  ) : (
    <EmptyState phrase="The shelves are empty." action={{ label: 'See requests', to: '/requests' }} />
  );

  const selectedItems = useMemo(
    () => items.filter((i) => selectedIds.includes(i.id)),
    [items, selectedIds],
  );

  const load = useCallback(() => {
    setLoading(true);
    api.get<InventoryItem[]>('/api/inventory').then((rows) => { setItems(rows); setLoaded(true); }).catch((e) => message.error(e.message)).finally(() => setLoading(false));
    api.get<ValueSummary>('/api/inventory/value-summary').then(setSummary).catch(() => {});
  }, []);

  const refreshPrices = async () => {
    setRefreshing(true);
    try {
      const r = await api.post<{ checked: number; changed: number; failed: { name: string; error: string }[] }>('/api/inventory/values/refresh', {});
      const failed = r.failed.length ? `, ${r.failed.length} failed (previous price kept)` : '';
      message.info(`Checked ${r.checked} listings: ${r.changed} price change${r.changed === 1 ? '' : 's'}${failed}`);
      load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  const onPriced = (saved: InventoryItem) => {
    setItems((prev) => prev.map((i) => (i.id === saved.id ? saved : i)));
    api.get<ValueSummary>('/api/inventory/value-summary').then(setSummary).catch(() => {});
  };

  useEffect(load, [load]);

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <Space wrap align="center" size={12}>
          <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: 'var(--text-primary)' }}>Components</h2>
          <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>{loaded ? <><span style={{ fontFamily: MONO }}>{filtered.length}{query ? `/${items.length}` : ''}</span> component{filtered.length === 1 ? '' : 's'}</> : '—'}</span>
          {!canManage && <Chip text="Your team's equipment" tone="accent" />}
          <Button aria-label="Reload inventory" icon={<ReloadOutlined />} onClick={load} />
        </Space>
        <Input allowClear prefix={<SearchOutlined style={{ color: 'var(--text-tertiary)' }} />} placeholder="Search components…" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: isMobile ? '100%' : 240 }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <Space wrap>
          {canManage && selectedIds.length > 0 && (
            <Button type="primary" ghost icon={<PlusOutlined />} onClick={() => setBulkOpen(true)}>
              Allocate {selectedIds.length} selected
            </Button>
          )}
          <Button icon={<SendOutlined />} onClick={() => setRequestsOpen(true)}>Requests</Button>
          {canManage && <Button icon={<DollarOutlined />} onClick={() => setPricingOpen(true)}>Price items</Button>}
          {canManage && <Button icon={<SyncOutlined spin={refreshing} />} loading={refreshing} onClick={() => void refreshPrices()}>Refresh prices</Button>}
          {canManage && <Button icon={<EnvironmentOutlined />} onClick={() => setLocationsOpen(true)}>Locations</Button>}
          {canManage && <Button icon={<ImportOutlined />} onClick={() => setImporting(true)}>Import components</Button>}
          {canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>Add item</Button>}
        </Space>
      </div>

      {summary && <WorthBanner summary={summary} onPrice={canManage ? () => setPricingOpen(true) : undefined} />}

      {isMobile ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 280px), 1fr))', gap: 10 }}>
          {filtered.length === 0 && !loading && (
            <div style={{ gridColumn: '1 / -1' }}>{empty}</div>
          )}
          {filtered.map((i) => (
            <ItemCard key={i.id} item={i} onOpen={() => setSearchParams({ item: String(i.id) })} />
          ))}
        </div>
      ) : (
      <Table className="circuit-table" rowKey="id" loading={loading} dataSource={filtered} locale={{ emptyText: empty }}
        scroll={{ x: 'max-content' }}
        rowSelection={canManage ? { selectedRowKeys: selectedIds, onChange: (keys) => setSelectedIds(keys as number[]) } : undefined}
        onRow={(i) => openableRow(() => setSearchParams({ item: String(i.id) }))}
        pagination={{ defaultPageSize: 15, hideOnSinglePage: true }}
        columns={[
          {
            title: 'Item', dataIndex: 'name',
            render: (_, i) => (
              <div>
                <Space size={6}>
                  <Typography.Text strong style={{ color: 'var(--text-primary)' }}>{i.name}</Typography.Text>
                  {i.quantity <= i.low_stock_threshold && <Chip text="Low" tone="danger" />}
                  {similarIds.has(i.id) && <Chip text="similar" tone="accent" />}
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
          {
            title: 'Unit value', width: 130, align: 'right' as const,
            sorter: (a, b) => (a.unit_value ?? -1) - (b.unit_value ?? -1),
            render: (_, i) => <span style={{ fontFamily: MONO, fontSize: 12.5 }}>{egp(i.unit_value, i.value_currency ?? 'EGP')}</span>,
          },
          {
            title: 'Value', width: 150, align: 'right' as const,
            sorter: (a, b) => (a.total_value ?? -1) - (b.total_value ?? -1),
            render: (_, i) => (
              <div>
                {i.total_value !== null && <div style={{ fontFamily: MONO, fontSize: 12.5, fontWeight: 600 }}>{egp(i.total_value, i.value_currency ?? 'EGP')}</div>}
                <ValueSourceTag item={i} />
              </div>
            ),
          },
          { title: 'Condition', width: 120, render: (_, i) => <ConditionTag condition={i.condition} /> },
          { title: 'Location', dataIndex: 'location', ellipsis: true, render: (l: string | null) => l || '—' },
        ]} />
      )}

      <NewInventoryItemModal open={creating} onClose={() => setCreating(false)} onCreated={load} />
      <InventoryRequestsDrawer open={requestsOpen} onClose={() => setRequestsOpen(false)} />
      <ImportFromFileModal open={importing} onClose={() => setImporting(false)} onImported={load} />
      <LocationsModal open={locationsOpen} onClose={() => setLocationsOpen(false)} />
      <InventoryItemDrawer itemId={openItemId} onClose={() => setSearchParams({})} onChanged={load} />
      <PricingReviewModal open={pricingOpen} items={items} onClose={() => setPricingOpen(false)} onChanged={onPriced} />
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
