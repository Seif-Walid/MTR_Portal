import { PlusOutlined } from '@ant-design/icons';
import { Alert, Button, Input, Modal, Segmented, Select, Space, Table, Tabs, Tag, Tooltip, Typography, message, theme } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { DuesLedger, DuesRow, FinanceDashboard, FinanceSeasonBrief } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import DataGrid from '../components/DataGrid';
import FinanceOverview from '../components/FinanceOverview';
import { Panel, PanelGrid, StatRow, StatTile, egp } from '../components/charts';

const can = (privs: string[] | undefined, p: string) => !!privs?.includes(p);
const ALL = 'all';

const TABS = ['overview', 'budget', 'spendings', 'dues', 'funding', 'cash', 'setup'] as const;
type TabKey = (typeof TABS)[number];

export default function FinancePage() {
  const { me } = useAuth();
  const canEdit = can(me?.privileges, 'finance.edit');
  const [params, setParams] = useSearchParams();
  const tab = (TABS.includes(params.get('tab') as TabKey) ? params.get('tab') : 'overview') as TabKey;

  const [seasons, setSeasons] = useState<FinanceSeasonBrief[]>([]);
  const [season, setSeason] = useState<string>(ALL);
  const [dash, setDash] = useState<FinanceDashboard | null>(null);
  const [dues, setDues] = useState<DuesLedger | null>(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const [rollOpen, setRollOpen] = useState(false);
  const [rollFrom, setRollFrom] = useState<string>('');
  const [rollName, setRollName] = useState('');
  const [rolling, setRolling] = useState(false);

  const openRoll = () => {
    setRollFrom(season !== ALL ? season : String(seasons[seasons.length - 1]?.id ?? ''));
    setRollName('');
    setRollOpen(true);
  };
  const rollForward = async () => {
    setRolling(true);
    try {
      const res = await api.post<{ id: number; name: string; copied: Record<string, number> }>(
        `/api/finance/seasons/${rollFrom}/roll-forward`,
        { name: rollName.trim() },
      );
      message.success(
        `${res.name} started — ${res.copied.budget_lines} budget lines, ${res.copied.dues_tiers} dues tiers and ${res.copied.dues_discounts} discounts carried over.`,
      );
      setRollOpen(false);
      refresh();
      setSeason(String(res.id));
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not start the season');
    } finally {
      setRolling(false);
    }
  };

  useEffect(() => {
    api
      .get<{ seasons: FinanceSeasonBrief[]; current_id: number | null }>('/api/finance/seasons')
      .then((r) => {
        setSeasons(r.seasons);
        if (r.current_id != null) setSeason(String(r.current_id));
      })
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Failed to load seasons'));
  }, [tick]);

  useEffect(() => {
    const q = season === ALL ? '' : `?season_id=${season}`;
    api.get<FinanceDashboard>(`/api/finance/dashboard${q}`).then(setDash).catch(() => setDash(null));
    api.get<DuesLedger>(`/api/finance/dues${q}`).then(setDues).catch(() => setDues(null));
  }, [season, tick]);

  // grids show the selected season's rows; "all seasons" shows every row
  const seasonFilter = season === ALL ? undefined : { season_id: season };
  const setTab = (k: string) => setParams(k === 'overview' ? {} : { tab: k }, { replace: true });

  const grid = (table: string, opts: { fixed?: Record<string, string>; title?: string } = {}) =>
    canEdit ? (
      <DataGrid
        key={`${table}-${JSON.stringify(opts.fixed ?? {})}`}
        table={table}
        fixed={opts.fixed}
        reloadOnSave
        allowUpload
        onChanged={refresh}
        title={opts.title ? <Typography.Text strong>{opts.title}</Typography.Text> : undefined}
      />
    ) : (
      <Alert type="info" showIcon message="You can view the finance dashboard, but editing the books needs the “Edit finances” privilege." />
    );

  const items = [
    { key: 'overview', label: 'Overview', children: <FinanceOverview data={dash} /> },
    { key: 'budget', label: 'Budget', children: grid('budget_lines', { fixed: seasonFilter }) },
    { key: 'spendings', label: 'Spendings', children: grid('spendings', { fixed: seasonFilter }) },
    { key: 'dues', label: 'Dues', children: <DuesTab ledger={dues} canEdit={canEdit} grid={grid} seasonFilter={seasonFilter} /> },
    {
      key: 'funding',
      label: 'Funding & payables',
      children: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
          {grid('funding_lines', { fixed: seasonFilter, title: 'Funding in' })}
          {grid('payables', { title: 'Money we owe' })}
        </div>
      ),
    },
    {
      key: 'cash',
      label: 'Cash',
      children: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {dash && <CashTable data={dash} />}
          {grid('cash_transfers', { title: 'Transfers' })}
        </div>
      ),
    },
    { key: 'setup', label: 'Setup', children: <SetupTab grid={grid} /> },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Typography.Text type="secondary">
          The team's books — plan, spending, dues, funding and cash. Every grey column is computed; everything else
          is editable in place and saves itself.
        </Typography.Text>
        <Space>
          <span className="u-label" style={{ opacity: 0.6 }}>Season</span>
          <Select
            value={season}
            onChange={setSeason}
            style={{ minWidth: 220 }}
            options={[
              { value: ALL, label: 'All seasons' },
              ...seasons.map((s) => ({ value: String(s.id), label: s.status === 'closed' ? `${s.name} (closed)` : s.name })),
            ]}
          />
          {canEdit && seasons.length > 0 && (
            <Tooltip title="Start a new season from an existing one: its budget plan and dues fee schedule are copied; spending and payments are not.">
              <Button icon={<PlusOutlined />} onClick={openRoll}>
                New season
              </Button>
            </Tooltip>
          )}
        </Space>
      </div>
      <Tabs activeKey={tab} onChange={setTab} items={items} destroyOnHidden />
      <Modal
        open={rollOpen}
        title="Start a new season"
        okText="Start season"
        okButtonProps={{ disabled: !rollFrom || !rollName.trim(), loading: rolling }}
        onOk={() => void rollForward()}
        onCancel={() => setRollOpen(false)}
      >
        <Typography.Paragraph type="secondary">
          The new season starts as <strong>planning</strong> with the same USD rate. Budget lines, dues tiers and loyalty
          discounts are copied so you only adjust what changed. When the old season is done, set its status to
          <strong> closed</strong> on the Setup tab and its rows become read-only.
        </Typography.Paragraph>
        <Space direction="vertical" style={{ width: '100%' }}>
          <span className="u-label">Copy from</span>
          <Select
            value={rollFrom || undefined}
            onChange={setRollFrom}
            style={{ width: '100%' }}
            options={seasons.map((s) => ({ value: String(s.id), label: s.name }))}
          />
          <span className="u-label">New season name</span>
          <Input value={rollName} onChange={(e) => setRollName(e.target.value)} placeholder="e.g. Season 2027/2028 (S5)" onPressEnter={() => rollFrom && rollName.trim() && void rollForward()} />
        </Space>
      </Modal>
    </div>
  );
}

type GridFn = (table: string, opts?: { fixed?: Record<string, string>; title?: string }) => React.ReactNode;

function DuesTab({
  ledger,
  canEdit,
  grid,
  seasonFilter,
}: {
  ledger: DuesLedger | null;
  canEdit: boolean;
  grid: GridFn;
  seasonFilter?: Record<string, string>;
}) {
  const [view, setView] = useState<'ledger' | 'roster' | 'collection' | 'schedule'>('ledger');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Segmented
        value={view}
        onChange={(v) => setView(v as typeof view)}
        options={[
          { value: 'ledger', label: 'Who paid what' },
          ...(canEdit
            ? [
                { value: 'collection', label: 'Log payments' },
                { value: 'roster', label: 'Dues roster' },
                { value: 'schedule', label: 'Fees & discounts' },
              ]
            : []),
        ]}
        style={{ alignSelf: 'flex-start' }}
      />
      {view === 'ledger' && <DuesLedgerView ledger={ledger} />}
      {view === 'collection' && grid('dues_payments', { fixed: seasonFilter })}
      {view === 'roster' && grid('dues_enrollments', { fixed: seasonFilter })}
      {view === 'schedule' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
          {grid('dues_tiers', { fixed: seasonFilter, title: 'Tiers' })}
          {grid('dues_discounts', { fixed: seasonFilter, title: 'Loyalty discounts' })}
        </div>
      )}
    </div>
  );
}

function DuesLedgerView({ ledger }: { ledger: DuesLedger | null }) {
  const { token } = theme.useToken();
  const [filter, setFilter] = useState<'all' | 'owing' | 'paid'>('all');
  const rows = useMemo(() => {
    if (!ledger) return [];
    if (filter === 'owing') return ledger.rows.filter((r) => r.balance > 0);
    if (filter === 'paid') return ledger.rows.filter((r) => r.paid > 0);
    return ledger.rows;
  }, [ledger, filter]);
  if (!ledger) return <Typography.Text type="secondary">No dues season set up yet.</Typography.Text>;
  const t = ledger.totals;

  const monthCols = ledger.months.map((m) => ({
    title: dayjs(`${m}-01`).format('MMM'),
    key: m,
    width: 64,
    align: 'right' as const,
    render: (_: unknown, r: DuesRow) => {
      const v = r.monthly[m] ?? 0;
      return v ? (
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{egp(v)}</span>
      ) : (
        <span style={{ color: token.colorTextQuaternary }}>·</span>
      );
    },
  }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <StatRow>
        <StatTile label="Enrolled" value={String(t.members)} sub={`${t.active} active`} />
        <StatTile label="Projected this season" value={egp(t.projected)} unit="EGP" sub="Active members × fee × months" />
        <StatTile label="Collected" value={egp(t.collected)} unit="EGP" />
        <StatTile label="Still owed" value={egp(t.balance)} unit="EGP" tone={t.balance > 0 ? 'danger' : undefined} />
      </StatRow>
      {t.unenrolled_paid !== 0 && (
        <Alert
          type="warning"
          showIcon
          message={`${egp(t.unenrolled_paid)} EGP was logged for members who aren't on this season's dues roster — add them to the roster.`}
        />
      )}
      <PanelGrid min={520}>
        <Panel title="Projection by segment">
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => `${r.tier}-${r.discount}`}
            dataSource={ledger.projection}
            locale={{ emptyText: 'No active enrolments' }}
            columns={[
              { title: 'Segment', key: 's', render: (_, r) => `${r.tier} — ${r.discount ? `${Math.round(r.discount * 100)}% off` : 'full fee'}` },
              { title: 'Members', dataIndex: 'members', align: 'right' },
              { title: 'Monthly fee', dataIndex: 'monthly_fee', align: 'right', render: egp },
              { title: 'Months', dataIndex: 'months', align: 'right' },
              { title: 'Projected', dataIndex: 'projected', align: 'right', render: (v: number) => <strong>{egp(v)}</strong> },
            ]}
          />
        </Panel>
      </PanelGrid>
      <Panel
        title="Monthly dues — who paid what"
        extra={
          <Segmented
            size="small"
            value={filter}
            onChange={(v) => setFilter(v as typeof filter)}
            options={[
              { value: 'all', label: 'Everyone' },
              { value: 'owing', label: 'Owing' },
              { value: 'paid', label: 'Paid something' },
            ]}
          />
        }
      >
        <Table<DuesRow>
          size="small"
          rowKey="enrollment_id"
          dataSource={rows}
          pagination={{ defaultPageSize: 50, size: 'small', hideOnSinglePage: true }}
          scroll={{ x: 'max-content' }}
          columns={[
            {
              title: 'Member',
              key: 'name',
              fixed: 'left',
              width: 220,
              render: (_, r) => (
                <div>
                  <div style={{ fontWeight: 500 }}>{r.name}</div>
                  <div className="u-mono" style={{ fontSize: 11, color: token.colorTextTertiary }}>
                    {r.mtr_id ?? '—'} · {r.tier}
                    {r.status === 'withdrawn' && <Tag style={{ marginLeft: 6 }}>withdrawn</Tag>}
                  </div>
                </div>
              ),
            },
            {
              title: 'Years',
              dataIndex: 'maturity',
              align: 'right',
              width: 64,
              render: (v: number, r) =>
                r.maturity_overridden ? <Tooltip title="Set by hand (overrides the join date)">{v}*</Tooltip> : v,
            },
            { title: 'Fee/mo', dataIndex: 'monthly_fee', align: 'right', width: 76, render: egp },
            ...monthCols,
            { title: 'Paid', dataIndex: 'paid', align: 'right', width: 80, render: egp },
            { title: 'Expected', dataIndex: 'expected', align: 'right', width: 86, render: egp },
            {
              title: 'Balance',
              dataIndex: 'balance',
              align: 'right',
              width: 86,
              fixed: 'right',
              render: (v: number) => (
                <span style={{ color: v > 0 ? token.colorError : token.colorSuccess, fontVariantNumeric: 'tabular-nums' }}>
                  {egp(v)}
                </span>
              ),
            },
          ]}
          summary={() => (
            <Table.Summary fixed>
              <Table.Summary.Row>
                <Table.Summary.Cell index={0} colSpan={3}><strong>Total</strong></Table.Summary.Cell>
                {ledger.months.map((m, i) => (
                  <Table.Summary.Cell key={m} index={3 + i} align="right">{egp(t.by_month[m] ?? 0)}</Table.Summary.Cell>
                ))}
                <Table.Summary.Cell index={3 + ledger.months.length} align="right">{egp(t.collected - t.unenrolled_paid)}</Table.Summary.Cell>
                <Table.Summary.Cell index={4 + ledger.months.length} align="right">{egp(t.expected)}</Table.Summary.Cell>
                <Table.Summary.Cell index={5 + ledger.months.length} align="right"><strong>{egp(t.balance)}</strong></Table.Summary.Cell>
              </Table.Summary.Row>
            </Table.Summary>
          )}
        />
      </Panel>
    </div>
  );
}

function CashTable({ data }: { data: FinanceDashboard }) {
  const cash = data.cash;
  return (
    <Panel title="Cash balances" extra={`Total ${egp(cash.total)} EGP`}>
      <Table
        size="small"
        pagination={false}
        rowKey="party_id"
        dataSource={cash.rows}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: 'No holders yet — add people of type “Cash Holder” or “CFO” in Setup' }}
        columns={[
          { title: 'Holder', dataIndex: 'name', fixed: 'left' },
          ...cash.methods.map((m) => ({
            title: m.name,
            key: String(m.id),
            align: 'right' as const,
            render: (_: unknown, r: (typeof cash.rows)[number]) => egp(r.cells[String(m.id)] ?? 0),
          })),
          { title: 'Total', dataIndex: 'total', align: 'right', render: (v: number) => <strong>{egp(v)}</strong> },
        ]}
      />
    </Panel>
  );
}

const PICKLISTS: [string, string][] = [
  ['options_payment_method', 'Payment methods'],
  ['options_category', 'Categories'],
  ['options_subcategory', 'Sub-categories'],
  ['options_subsystem', 'Subsystems'],
  ['options_funding_type', 'Funding types'],
  ['options_party_type', 'Entity / role types'],
];

function SetupTab({ grid }: { grid: GridFn }) {
  const [list, setList] = useState(PICKLISTS[0][0]);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      {grid('finance_seasons', { title: 'Seasons' })}
      {grid('finance_parties', { title: 'People & entities' })}
      <div>
        <Space style={{ marginBottom: 10 }} wrap>
          <Typography.Text strong>Pick-lists</Typography.Text>
          <Segmented size="small" value={list} onChange={(v) => setList(String(v))} options={PICKLISTS.map(([value, label]) => ({ value, label }))} />
        </Space>
        {grid(list)}
      </div>
    </div>
  );
}
