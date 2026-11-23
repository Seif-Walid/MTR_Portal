/* The money feed: every dues payment, spending, received funding and
   hand-over as one readable list — who, what, how much, who holds it. A row
   opens a drawer where its holder (or a finance admin) can correct or delete it. */
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  RightOutlined,
  SwapOutlined,
} from '@ant-design/icons';
import {
  Button,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Segmented,
  Select,
  Skeleton,
  Space,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../../api/client';
import type { FinanceFormOptions, LedgerEntry, LedgerKind } from '../../api/types';
import { egp } from '../charts';
import EmptyState from '../EmptyState';

const TABLE: Record<LedgerKind, string> = {
  dues: 'dues_payments',
  funding: 'funding_lines',
  spending: 'spendings',
  handover: 'cash_transfers',
};

const KIND_LABEL: Record<LedgerKind, string> = {
  dues: 'Dues',
  funding: 'Funding',
  spending: 'Spending',
  handover: 'Hand-over',
};

const ICON = { in: <ArrowDownOutlined />, out: <ArrowUpOutlined />, move: <SwapOutlined /> };

type Filter = 'all' | 'mine' | LedgerKind;

export function Ledger({ seasonId, tick, opts, onChanged }: {
  seasonId: string | null; tick: number; opts: FinanceFormOptions | null; onChanged: () => void;
}) {
  const [filter, setFilter] = useState<Filter>('all');
  const [data, setData] = useState<{ entries: LedgerEntry[]; total: number } | null>(null);
  const [open, setOpen] = useState<LedgerEntry | null>(null);

  useEffect(() => {
    const q = new URLSearchParams();
    if (seasonId) q.set('season_id', seasonId);
    if (filter === 'mine') q.set('mine', 'true');
    else if (filter !== 'all') q.set('kind', filter);
    setData(null);
    api.get<{ entries: LedgerEntry[]; total: number }>(`/api/finance/ledger?${q}`)
      .then(setData)
      .catch((e) => {
        message.error(e instanceof ApiError ? e.message : 'Could not load the money feed');
        setData({ entries: [], total: 0 });
      });
  }, [seasonId, filter, tick]);

  // group by month so the feed reads like a statement
  const groups = useMemo(() => {
    const out: { month: string; rows: LedgerEntry[]; net: number }[] = [];
    for (const e of data?.entries ?? []) {
      const m = e.date ? dayjs(e.date).format('MMMM YYYY') : 'No date';
      let g = out[out.length - 1];
      if (!g || g.month !== m) out.push((g = { month: m, rows: [], net: 0 }));
      g.rows.push(e);
      g.net += e.direction === 'in' ? e.amount : e.direction === 'out' ? -e.amount : 0;
    }
    return out;
  }, [data]);

  return (
    <div className="fin-ledger">
      <div className="fin-ledger__bar">
        <Segmented
          value={filter}
          onChange={(v) => setFilter(v as Filter)}
          options={[
            { value: 'all', label: 'Everything' },
            ...(opts?.can_handle_cash ? [{ value: 'mine', label: 'Mine' }] : []),
            { value: 'dues', label: 'Dues' },
            { value: 'spending', label: 'Spending' },
            { value: 'funding', label: 'Funding' },
            { value: 'handover', label: 'Hand-overs' },
          ]}
        />
        {data && data.total > data.entries.length && (
          <Typography.Text type="secondary">Showing the latest {data.entries.length} of {data.total}</Typography.Text>
        )}
      </div>
      {!data && <Skeleton active paragraph={{ rows: 6 }} />}
      {data && !data.entries.length && (
        <EmptyState phrase={filter === 'mine' ? 'You haven’t logged any money yet.' : 'No money has moved here yet.'} />
      )}
      {groups.map((g) => (
        <section key={g.month} className="fin-month">
          <header className="fin-month__head">
            <h3>{g.month}</h3>
            <span className={`fin-amt ${g.net < 0 ? 'is-out' : 'is-in'}`}>
              {g.net < 0 ? '−' : '+'}{egp(Math.abs(g.net))}
            </span>
          </header>
          <div className="home-panel">
            {g.rows.map((e) => (
              <div
                key={`${e.kind}-${e.id}`}
                className="home-row fin-row"
                role="button"
                tabIndex={0}
                onClick={() => setOpen(e)}
                onKeyDown={(k) => (k.key === 'Enter' || k.key === ' ') && setOpen(e)}
              >
                <span className={`home-row__icon fin-row__icon is-${e.direction}`}>{ICON[e.direction]}</span>
                <div className="home-row__body">
                  <div className="home-row__title">{e.title}</div>
                  <div className="home-row__meta">
                    <span className="home-row__detail">
                      {[
                        KIND_LABEL[e.kind],
                        e.event && (e.team ? `${e.event} › ${e.team}` : e.event),
                        e.method,
                        e.holder && (e.mine ? 'you' : e.holder.name + (e.holder.legacy ? ' (legacy)' : '')),
                      ].filter(Boolean).join(' · ')}
                    </span>
                  </div>
                </div>
                <span className="home-row__due">{e.date ? dayjs(e.date).format('D MMM') : '—'}</span>
                <span className={`fin-amt is-${e.direction}`}>
                  {e.direction === 'in' ? '+' : e.direction === 'out' ? '−' : ''}{egp(e.amount)}
                </span>
                <RightOutlined className="home-row__chev" aria-hidden />
              </div>
            ))}
          </div>
        </section>
      ))}
      <EntryDrawer entry={open} opts={opts} onClose={() => setOpen(null)} onChanged={() => { setOpen(null); onChanged(); }} />
    </div>
  );
}

interface EditValues {
  amount?: number;
  method_id?: number;
  on?: Dayjs;
  note?: string;
  item?: string;
}

const DATE_FIELD: Record<LedgerKind, string> = {
  dues: 'paid_on', funding: 'received_on', spending: 'spent_on', handover: 'transferred_on',
};

function EntryDrawer({ entry, opts, onClose, onChanged }: {
  entry: LedgerEntry | null; opts: FinanceFormOptions | null; onClose: () => void; onChanged: () => void;
}) {
  const [form] = Form.useForm<EditValues>();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<{ id: number; action: string; actor: string | null; created_at: string }[] | null>(null);

  useEffect(() => {
    setEditing(false);
    setHistory(null);
    if (!entry) return;
    form.setFieldsValue({
      amount: entry.kind === 'spending' ? entry.unit_cost : entry.amount,
      method_id: entry.method_id ?? undefined,
      on: entry.date ? dayjs(entry.date) : undefined,
      note: entry.note ?? undefined,
      item: entry.title,
    });
    if (opts?.can_edit) {
      api.get<typeof history>(`/api/bulk/${TABLE[entry.kind]}/${entry.id}/history`).then(setHistory).catch(() => {});
    }
  }, [entry, form, opts]);

  if (!entry) return <Drawer open={false} onClose={onClose} />;

  const save = async (v: EditValues) => {
    const body: Record<string, unknown> = { note: v.note ?? null, [DATE_FIELD[entry.kind]]: v.on?.format('YYYY-MM-DD') };
    if (entry.kind === 'spending') {
      body.unit_cost = v.amount;
      body.item = v.item;
    } else body.amount = v.amount;
    if (entry.kind === 'handover') body.from_method_id = v.method_id;
    else body.method_id = v.method_id;
    setBusy(true);
    try {
      await api.patch(`/api/finance/entries/${entry.kind}/${entry.id}`, body);
      message.success('Corrected.');
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not save');
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    try {
      await api.delete(`/api/finance/entries/${entry.kind}/${entry.id}`);
      message.success('Deleted — a finance admin can restore it from the recycle bin.');
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not delete');
    }
  };

  const holder = entry.holder ? (entry.mine ? 'You' : entry.holder.name + (entry.holder.legacy ? ' (legacy holder)' : '')) : '—';
  return (
    <Drawer
      open
      width={440}
      onClose={onClose}
      title={<span>{KIND_LABEL[entry.kind]} · <span className={`fin-amt is-${entry.direction}`}>{egp(entry.amount)} EGP</span></span>}
      extra={entry.can_edit && !editing ? <Button onClick={() => setEditing(true)}>Correct</Button> : null}
    >
      {!editing ? (
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="What">{entry.title}</Descriptions.Item>
          <Descriptions.Item label="Date">{entry.date ? dayjs(entry.date).format('D MMM YYYY') : '—'}</Descriptions.Item>
          <Descriptions.Item label={entry.direction === 'out' ? 'Paid by' : entry.direction === 'in' ? 'Received by' : 'From'}>
            {holder}
          </Descriptions.Item>
          {entry.to && <Descriptions.Item label="To">{entry.to.name}{entry.to_method ? ` · ${entry.to_method}` : ''}</Descriptions.Item>}
          <Descriptions.Item label="Method">{entry.method ?? 'Unspecified'}</Descriptions.Item>
          {entry.fees ? <Descriptions.Item label="Fees">{egp(entry.fees)} EGP</Descriptions.Item> : null}
          {entry.event && <Descriptions.Item label="Event">{entry.team ? `${entry.event} › ${entry.team}` : entry.event}</Descriptions.Item>}
          {entry.category && <Descriptions.Item label="Category">{entry.category}</Descriptions.Item>}
          {entry.kind === 'spending' && (entry.count ?? 1) !== 1 && (
            <Descriptions.Item label="Count">{entry.count} × {egp(entry.unit_cost ?? 0)}</Descriptions.Item>
          )}
          {entry.payee && <Descriptions.Item label="Paid to">{entry.payee}</Descriptions.Item>}
          {entry.type && <Descriptions.Item label="Type">{entry.type}</Descriptions.Item>}
          {entry.receipt && (
            <Descriptions.Item label="Receipt">
              {/^https?:\/\//.test(entry.receipt) ? <a href={entry.receipt} target="_blank" rel="noreferrer">Open</a> : entry.receipt}
            </Descriptions.Item>
          )}
          {entry.note && <Descriptions.Item label="Note">{entry.note}</Descriptions.Item>}
        </Descriptions>
      ) : (
        <Form form={form} layout="vertical" onFinish={(v) => void save(v)} requiredMark={false}>
          {entry.kind === 'spending' && (
            <Form.Item name="item" label="What for" rules={[{ required: true }]}><Input /></Form.Item>
          )}
          <Form.Item name="amount" label={entry.kind === 'spending' && (entry.count ?? 1) !== 1 ? 'Each' : 'Amount'} rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} addonAfter="EGP" />
          </Form.Item>
          <Form.Item name="method_id" label="Method">
            <Select options={(opts?.methods ?? []).map((m) => ({ value: m.id, label: m.name }))} />
          </Form.Item>
          <Form.Item name="on" label="Date"><DatePicker style={{ width: '100%' }} allowClear={false} /></Form.Item>
          <Form.Item name="note" label="Note"><Input /></Form.Item>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Popconfirm title="Delete this entry?" description="It leaves the balances; a finance admin can restore it." onConfirm={() => void remove()} okText="Delete" okButtonProps={{ danger: true }}>
              <Button danger icon={<DeleteOutlined />}>Delete</Button>
            </Popconfirm>
            <Space>
              <Button onClick={() => setEditing(false)}>Cancel</Button>
              <Button type="primary" htmlType="submit" loading={busy}>Save</Button>
            </Space>
          </Space>
        </Form>
      )}
      {!entry.can_edit && (
        <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
          Only {holder === 'You' ? 'you' : holder} or a finance admin can correct this.
        </Typography.Paragraph>
      )}
      {history && history.length > 0 && (
        <>
          <Typography.Title level={5} style={{ marginTop: 24 }}>History</Typography.Title>
          <Timeline
            items={history.map((h) => ({
              children: (
                <span>
                  <Tag>{h.action}</Tag>{h.actor ?? 'someone'} · {dayjs(h.created_at).format('D MMM YYYY HH:mm')}
                </span>
              ),
            }))}
          />
        </>
      )}
    </Drawer>
  );
}
