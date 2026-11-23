import { CheckOutlined, LinkOutlined, SearchOutlined, WarningOutlined } from '@ant-design/icons';
import { Alert, Button, Input, InputNumber, Modal, Space, Spin, Tag, Tooltip, Typography, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api/client';
import type { InventoryItem, PriceCandidate, PriceCandidates, ValueSource } from '../api/types';
import EmptyState from './EmptyState';

const MONO = 'var(--font-mono)';

export const SOURCE_LABEL: Record<ValueSource, string> = {
  makers: 'Makers Electronics',
  future: 'Future Electronics',
  manual: 'Manual estimate',
};

export const MANUAL_WARNING =
  'Source not cited. This is our own estimate, so it does not follow market price changes and "Refresh prices" never updates it.';

export function egp(n: number | null | undefined, currency = 'EGP') {
  if (n === null || n === undefined) return '—';
  return `${n.toLocaleString('en-US', { maximumFractionDigits: 2 })} ${currency}`;
}

/** Where an item's value came from: a link to the pinned listing, or the
 *  uncited-estimate warning. */
export function ValueSourceTag({ item }: { item: InventoryItem }) {
  if (!item.value_source) return <Typography.Text type="secondary">Unpriced</Typography.Text>;
  if (item.value_source === 'manual') {
    return (
      <Tooltip title={MANUAL_WARNING}>
        <Tag color="warning" icon={<WarningOutlined />} style={{ marginInlineEnd: 0 }}>Manual · uncited</Tag>
      </Tooltip>
    );
  }
  const tag = (
    <Tag color={item.value_error ? 'error' : item.value_source === 'makers' ? 'blue' : 'purple'} style={{ marginInlineEnd: 0 }}>
      {item.value_source === 'makers' ? 'Makers' : 'Future'}{item.value_error ? ' · stale' : ''}
    </Tag>
  );
  return (
    <Tooltip title={item.value_error ? `Last refresh failed: ${item.value_error}. Showing the previous price.` : item.value_title}>
      <a href={item.value_url ?? undefined} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{tag}</a>
    </Tooltip>
  );
}

function CandidateRow({ c, pinned, busy, onPin }: { c: PriceCandidate; pinned: boolean; busy: boolean; onPin: () => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid color-mix(in srgb, var(--text-primary) 6%, transparent)' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <a href={c.url} target="_blank" rel="noreferrer" style={{ color: 'var(--text-primary)' }}>
          {c.title} <LinkOutlined style={{ fontSize: 11, opacity: 0.6 }} />
        </a>
        <div style={{ fontFamily: MONO, fontSize: 11, color: 'var(--text-tertiary)' }}>
          match {Math.round(c.score * 100)}%{c.in_stock ? '' : ' · out of stock'}
        </div>
      </div>
      <span style={{ fontFamily: MONO, fontSize: 13, whiteSpace: 'nowrap' }}>{egp(c.unit_price, c.currency)}</span>
      <Button size="small" type={pinned ? 'primary' : 'default'} icon={pinned ? <CheckOutlined /> : undefined} loading={busy} onClick={onPin}>
        {pinned ? 'Pinned' : 'Use'}
      </Button>
    </div>
  );
}

/** Find the item on Makers (preferred) or Future, pin a listing, or fall
 *  back to a manual estimate. Prices always come from the shop API on the
 *  server; the browser only says which listing. */
export function PriceItemPanel({ item, onSaved }: { item: InventoryItem; onSaved: (i: InventoryItem) => void }) {
  const [query, setQuery] = useState('');
  const [data, setData] = useState<PriceCandidates | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyRef, setBusyRef] = useState<string | null>(null);
  const [manual, setManual] = useState<number | null>(item.value_source === 'manual' ? item.unit_value : null);
  const [note, setNote] = useState(item.value_source === 'manual' ? item.value_note : '');

  const search = useCallback((q: string) => {
    setLoading(true);
    const qs = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
    api.get<PriceCandidates>(`/api/inventory/${item.id}/price-candidates${qs}`)
      .then(setData).catch((e) => message.error(e.message)).finally(() => setLoading(false));
  }, [item.id]);

  useEffect(() => {
    setQuery('');
    setData(null);
    setManual(item.value_source === 'manual' ? item.unit_value : null);
    setNote(item.value_source === 'manual' ? item.value_note : '');
    search('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  const save = async (body: { source: ValueSource; ref?: string; unit_value?: number; note?: string }) => {
    setBusyRef(body.ref ?? 'manual');
    try {
      const saved = await api.put<InventoryItem>(`/api/inventory/${item.id}/value`, body);
      message.success(`${item.name}: ${egp(saved.unit_value, saved.value_currency ?? 'EGP')} per ${saved.unit}`);
      onSaved(saved);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setBusyRef(null);
    }
  };

  const section = (source: 'makers' | 'future', hint: string) => {
    const list = data?.[source] ?? [];
    return (
      <div style={{ marginBottom: 16 }}>
        <Space size={8} style={{ marginBottom: 4 }}>
          <Typography.Text strong>{SOURCE_LABEL[source]}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{hint}</Typography.Text>
        </Space>
        {data?.errors[source] && <Alert type="error" showIcon message={`Could not search: ${data.errors[source]}`} style={{ marginBottom: 6 }} />}
        {data && data.query[source] && data.query[source] !== item.name && !query.trim() && (
          <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>Nothing for the full name. Showing results for “{data.query[source]}”</div>
        )}
        {data && !data.errors[source] && list.length === 0 && (
          <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>No listing found.</Typography.Text></div>
        )}
        {list.map((c) => (
          <CandidateRow key={c.ref} c={c} busy={busyRef === c.ref}
            pinned={item.value_source === source && item.value_ref === c.ref}
            onPin={() => void save({ source, ref: c.ref })} />
        ))}
      </div>
    );
  };

  return (
    <div>
      <Input.Search
        placeholder={`Search the shops (default: “${item.name}”)`}
        value={query} onChange={(e) => setQuery(e.target.value)}
        onSearch={(q) => search(q)} enterButton={<SearchOutlined />} allowClear
        style={{ marginBottom: 12 }}
      />
      <Spin spinning={loading}>
        {section('makers', 'use this when the item is listed here')}
        {section('future', 'only when Makers does not list it')}
      </Spin>
      <div style={{ borderTop: '1px solid color-mix(in srgb, var(--text-primary) 8%, transparent)', paddingTop: 12 }}>
        <Typography.Text strong>Neither shop has it</Typography.Text>
        <Alert type="warning" showIcon style={{ margin: '8px 0' }} message={MANUAL_WARNING} />
        <Space.Compact style={{ width: '100%' }}>
          <InputNumber min={0} value={manual} onChange={(v) => setManual(v)} placeholder="Unit value" suffix="EGP" style={{ width: 200 }} />
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why this value (optional)" />
          <Button disabled={manual === null} loading={busyRef === 'manual'}
            onClick={() => manual !== null && void save({ source: 'manual', unit_value: manual, note })}>
            Save estimate
          </Button>
        </Space.Compact>
      </div>
    </div>
  );
}

/** Walk through items one by one and price each. */
export function PricingReviewModal({ open, items, onClose, onChanged }: {
  open: boolean;
  items: InventoryItem[];
  onClose: () => void;
  onChanged: (i: InventoryItem) => void;
}) {
  const [onlyUnpriced, setOnlyUnpriced] = useState(true);
  const [queue, setQueue] = useState<number[]>([]);
  const [pos, setPos] = useState(0);

  useEffect(() => {
    if (!open) return;
    setQueue(items.filter((i) => !onlyUnpriced || i.unit_value === null).map((i) => i.id));
    setPos(0);
    // the queue is fixed when the modal opens so saving doesn't reshuffle it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, onlyUnpriced]);

  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);
  const current = queue[pos] !== undefined ? byId.get(queue[pos]) : undefined;
  const next = () => setPos((p) => Math.min(p + 1, queue.length));

  return (
    <Modal open={open} onCancel={onClose} width={760} destroyOnHidden
      title={
        <Space wrap>
          <span>Price items</span>
          <Button size="small" type={onlyUnpriced ? 'primary' : 'default'} onClick={() => setOnlyUnpriced(!onlyUnpriced)}>
            {onlyUnpriced ? 'Unpriced only' : 'All items'}
          </Button>
          {queue.length > 0 && <Typography.Text type="secondary" style={{ fontFamily: MONO, fontSize: 12 }}>{Math.min(pos + 1, queue.length)} / {queue.length}</Typography.Text>}
        </Space>
      }
      footer={
        <Space>
          <Button disabled={pos === 0} onClick={() => setPos(pos - 1)}>Back</Button>
          <Button type="primary" disabled={!current} onClick={next}>Skip / next</Button>
        </Space>
      }
    >
      {current ? (
        <>
          <div style={{ marginBottom: 12 }}>
            <Typography.Title level={5} style={{ margin: 0 }}>{current.name}</Typography.Title>
            <Space size={10} wrap>
              <Typography.Text type="secondary">{current.category ?? 'Uncategorised'} · {current.quantity} {current.unit}</Typography.Text>
              {current.unit_value !== null && <span style={{ fontFamily: MONO }}>{egp(current.unit_value)} / unit</span>}
              <ValueSourceTag item={current} />
            </Space>
          </div>
          <PriceItemPanel item={current} onSaved={(i) => { onChanged(i); next(); }} />
        </>
      ) : (
        <EmptyState compact phrase={queue.length ? 'All done. Every item in this list has been through review.' : 'Nothing to price.'} />
      )}
    </Modal>
  );
}
