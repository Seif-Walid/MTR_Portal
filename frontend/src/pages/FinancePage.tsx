import { ArrowDownOutlined, ArrowUpOutlined, PlusOutlined, SwapOutlined } from '@ant-design/icons';
import { Alert, Button, Input, Modal, Segmented, Select, Skeleton, Space, Table, Tabs, Tag, Tooltip, Typography, message, theme } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { DuesLedger, DuesRow, FinanceDashboard, FinanceFormOptions, FinanceSeasonBrief, MyCash } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import DataGrid from '../components/DataGrid';
import FinanceOverview from '../components/FinanceOverview';
import { Panel, PanelGrid, StatRow, StatTile, egp } from '../components/charts';
import EmptyState from '../components/EmptyState';
import { Ledger } from '../components/finance/Ledger';
import { HandoverModal, MoneyInModal, MoneyOutModal } from '../components/finance/MoneyForms';
import { OrbitButton } from '../components/fx';
import './home.css';
import './finance.css';

const can = (privs: string[] | undefined, p: string) => !!privs?.includes(p);
const ALL = 'all';

const TABS = ['activity', 'overview', 'dues', 'budget', 'funding', 'cash', 'advanced'] as const;
type TabKey = (typeof TABS)[number];

export default function FinancePage() {
  const { me } = useAuth();
  const canEdit = can(me?.privileges, 'finance.edit');
  const canHold = can(me?.privileges, 'finance.handle_cash');
  const [params, setParams] = useSearchParams();
  const tab = (TABS.includes(params.get('tab') as TabKey) ? params.get('tab') : 'activity') as TabKey;

  const [seasons, setSeasons] = useState<FinanceSeasonBrief[]>([]);
  const [season, setSeason] = useState<string>(ALL);
  const [dash, setDash] = useState<FinanceDashboard | null>(null);
  const [dues, setDues] = useState<DuesLedger | null>(null);
  const [opts, setOpts] = useState<FinanceFormOptions | null>(null);
  const [mine, setMine] = useState<MyCash | null>(null);
  const [acting, setActing] = useState<'in' | 'out' | 'hand' | null>(null);
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
        if (r.current_id != null) setSeason((cur) => (cur === ALL ? String(r.current_id) : cur));
      })
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Failed to load seasons'));
  }, [tick]);

  useEffect(() => {
    api.get<FinanceFormOptions>('/api/finance/form-options').then(setOpts).catch(() => setOpts(null));
    api.get<MyCash>('/api/finance/my-cash').then(setMine).catch(() => setMine(null));
  }, [tick]);

  useEffect(() => {
    const q = season === ALL ? '' : `?season_id=${season}`;
    api.get<FinanceDashboard>(`/api/finance/dashboard${q}`).then(setDash).catch(() => setDash(null));
    api.get<DuesLedger>(`/api/finance/dues${q}`).then(setDues).catch(() => setDues(null));
  }, [season, tick]);

  // grids show the selected season's rows; "all seasons" shows every row
  const seasonFilter = season === ALL ? undefined : { season_id: season };
  const setTab = (k: string) => setParams(k === 'activity' ? {} : { tab: k }, { replace: true });
  const done = () => { setActing(null); refresh(); };

  const grid = (table: string, opts: { fixed?: Record<string, string>; title?: string; note?: string } = {}) =>
    canEdit ? (
      <div>
        <DataGrid
          key={`${table}-${JSON.stringify(opts.fixed ?? {})}`}
          table={table}
          fixed={opts.fixed}
          reloadOnSave
          allowUpload
          onChanged={refresh}
          title={opts.title ? <Typography.Text strong>{opts.title}</Typography.Text> : undefined}
        />
        {opts.note && <Typography.Paragraph type="secondary" style={{ marginTop: 6 }}>{opts.note}</Typography.Paragraph>}
      </div>
    ) : null;

  const items = [
    {
      key: 'activity',
      label: 'Activity',
      children: <Ledger seasonId={season === ALL ? null : season} tick={tick} opts={opts} onChanged={refresh} />,
    },
    { key: 'overview', label: 'Overview', children: <FinanceOverview data={dash} /> },
    {
      key: 'dues',
      label: 'Dues',
      children: <DuesLedgerView ledger={dues} canEdit={canEdit} onChanged={refresh} />,
    },
    {
      key: 'budget',
      label: 'Budget',
      children: canEdit ? grid('budget_lines', { fixed: seasonFilter }) : <BudgetByEvent data={dash} />,
    },
    {
      key: 'funding',
      label: 'Funding & payables',
      children: canEdit ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
          {grid('funding_lines', {
            fixed: seasonFilter, title: 'Funding — planned and received',
            note: 'Plan funding here; when the money actually arrives, whoever takes it logs it with “Money in”.',
          })}
          {grid('payables', { title: 'Money we owe' })}
        </div>
      ) : <FundingList data={dash} />,
    },
    { key: 'cash', label: 'Who holds what', children: dash ? <CashTable data={dash} /> : <Skeleton active /> },
    ...(canEdit ? [{ key: 'advanced', label: 'Advanced', children: <AdvancedTab grid={grid} seasonFilter={seasonFilter} /> }] : []),
  ];

  const seasonName = seasons.find((s) => String(s.id) === season)?.name ?? 'All seasons';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <header className="home-hero fin-hero">
        <span className="home-hero__orb" aria-hidden />
        <div className="home-hero__text">
          <span className="home-hero__pill">{seasonName}</span>
          <h2 className="home-hero__greet">Money</h2>
          <p className="home-hero__sub">
            {canHold && mine
              ? <>You hold <strong>{egp(mine.total)} EGP</strong>{mine.methods.filter((m) => m.amount).length > 0 && (
                  <> — {mine.methods.filter((m) => m.amount).map((m) => `${egp(m.amount)} ${m.name}`).join(' · ')}</>
                )}</>
              : dash ? <>The team holds <strong>{egp(dash.cash.total)} EGP</strong> across {dash.cash.rows.filter((r) => r.total).length} holders.</> : '\u00a0'}
          </p>
        </div>
        {canHold && (
          <div className="fin-hero__actions">
            <OrbitButton icon={<ArrowDownOutlined />} label="Money in" onClick={() => setActing('in')} />
            <OrbitButton icon={<ArrowUpOutlined />} label="Money out" onClick={() => setActing('out')} />
            <OrbitButton icon={<SwapOutlined />} label="Hand over" onClick={() => setActing('hand')} />
          </div>
        )}
      </header>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Typography.Text type="secondary" style={{ maxWidth: 640 }}>
          {canHold
            ? 'Log money the moment it changes hands — it is recorded under your account.'
            : 'Only cash holders log money. Ask a finance admin if you should be one.'}
        </Typography.Text>
        <Space>
          <span className="u-label">Season</span>
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
      <MoneyInModal open={acting === 'in'} opts={opts} onClose={() => setActing(null)} onDone={done} />
      <MoneyOutModal open={acting === 'out'} opts={opts} onClose={() => setActing(null)} onDone={done} />
      <HandoverModal open={acting === 'hand'} opts={opts} mine={mine} onClose={() => setActing(null)} onDone={done} />
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
          <strong> closed</strong> under Advanced and its rows become read-only.
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

type GridFn = (table: string, opts?: { fixed?: Record<string, string>; title?: string; note?: string }) => React.ReactNode;

function DuesLedgerView({ ledger, canEdit, onChanged }: {
  ledger: DuesLedger | null; canEdit: boolean; onChanged: () => void;
}) {
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
        <StatTile label="Owe dues" value={String(t.members)} sub={`${t.active} active · from event teams`} />
        <StatTile label="Projected this season" value={egp(t.projected)} unit="EGP" sub="Active members × fee × months" />
        <StatTile label="Collected" value={egp(t.collected)} unit="EGP" />
        <StatTile label="Still owed" value={egp(t.balance)} unit="EGP" tone={t.balance > 0 ? 'danger' : undefined} />
      </StatRow>
      {ledger.unlisted_payers.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message={`${egp(t.unenrolled_paid)} EGP was paid by people who aren't on any of this season's event teams`}
          description={`${ledger.unlisted_payers.map((u) => u.name).join(', ')}. Put them on an event team, or add them under Advanced › Dues exceptions.`}
        />
      )}
      {canEdit && <EventTiers ledger={ledger} onChanged={onChanged} />}
      <PanelGrid min={520}>
        <Panel title="Projection by segment">
          <Table
            size="small"
            pagination={false}
            rowKey={(r) => `${r.tier}-${r.discount}`}
            dataSource={ledger.projection}
            locale={{ emptyText: <EmptyState compact phrase="No active enrolments." /> }}
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
          rowKey="member_id"
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
                    {r.mtr_id ?? '—'} · {r.tier ?? 'no tier'}
                    {r.status === 'withdrawn' && <Tag style={{ marginLeft: 6 }}>withdrawn</Tag>}
                    {r.source === 'manual' && <Tooltip title="Not on an event team — added by hand under Dues exceptions"><Tag style={{ marginLeft: 6 }}>added</Tag></Tooltip>}
                    {r.tier_overridden && <Tooltip title="Tier changed by hand from what the event gives"><Tag style={{ marginLeft: 6 }}>tier set</Tag></Tooltip>}
                  </div>
                  <div style={{ fontSize: 11, color: token.colorTextTertiary }}>
                    {r.events.join(' · ')}
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
    <Panel title="Who holds the team's money" extra={`Total ${egp(cash.total)} EGP`}>
      <Table
        size="small"
        pagination={false}
        rowKey={(r) => `${r.holder?.kind}-${r.holder?.id}`}
        dataSource={cash.rows}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyState compact phrase="No cash holders yet. Give a seat or level the “Hold & log the team’s money” privilege." /> }}
        columns={[
          { title: 'Holder', dataIndex: 'name', fixed: 'left' },
          ...cash.methods.map((m) => ({
            title: m.name,
            key: m.key,
            align: 'right' as const,
            render: (_: unknown, r: (typeof cash.rows)[number]) => egp(r.cells[m.key] ?? 0),
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
  ['options_party_type', 'Contact types'],
];

const SHEETS: [string, string][] = [
  ['dues_payments', 'Dues payments'],
  ['spendings', 'Spendings'],
  ['funding_lines', 'Funding'],
  ['cash_transfers', 'Hand-overs & opening balances'],
];

/** Finance admins only: the season setup and the raw sheets for corrections. */
function AdvancedTab({ grid, seasonFilter }: { grid: GridFn; seasonFilter?: Record<string, string> }) {
  const [view, setView] = useState<'setup' | 'dues' | 'contacts' | 'lists' | 'sheets'>('setup');
  const [list, setList] = useState(PICKLISTS[0][0]);
  const [sheet, setSheet] = useState(SHEETS[0][0]);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <Segmented
        value={view}
        onChange={(v) => setView(v as typeof view)}
        style={{ alignSelf: 'flex-start' }}
        options={[
          { value: 'setup', label: 'Seasons' },
          { value: 'dues', label: 'Dues fees & exceptions' },
          { value: 'contacts', label: 'Contacts' },
          { value: 'lists', label: 'Lists' },
          { value: 'sheets', label: 'Raw sheets' },
        ]}
      />
      {view === 'setup' && grid('finance_seasons', { title: 'Seasons' })}
      {view === 'dues' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
          {grid('dues_tiers', { fixed: seasonFilter, title: 'Tiers' })}
          {grid('dues_discounts', { fixed: seasonFilter, title: 'Loyalty discounts' })}
          {grid('dues_enrollments', {
            fixed: seasonFilter, title: 'Exceptions',
            note: 'Everyone on a team of an event with a dues tier owes it automatically (set the tier per event on the Dues tab). Add a row only to add someone who is not on a team, change their tier or maturity, or mark them withdrawn.',
          })}
        </div>
      )}
      {view === 'contacts' && grid('finance_parties', {
        title: 'Contacts',
        note: 'Suppliers, sponsors and organizers. A row marked as a former cash holder only needs its portal account set — its old money then moves to that account.',
      })}
      {view === 'lists' && (
        <div>
          <Segmented size="small" value={list} onChange={(v) => setList(String(v))} style={{ marginBottom: 10 }}
            options={PICKLISTS.map(([value, label]) => ({ value, label }))} />
          {grid(list)}
        </div>
      )}
      {view === 'sheets' && (
        <div>
          <Alert type="info" showIcon style={{ marginBottom: 12 }}
            message="For corrections. New money is logged with Money in / Money out / Hand over, so it is always recorded under the account that handled it. Rows you add here are recorded under your account." />
          <Segmented size="small" value={sheet} onChange={(v) => setSheet(String(v))} style={{ marginBottom: 10 }}
            options={SHEETS.map(([value, label]) => ({ value, label }))} />
          {grid(sheet, sheet === 'cash_transfers' ? {} : { fixed: seasonFilter })}
        </div>
      )}
    </div>
  );
}

/** Which dues tier each live event's team members owe. */
function EventTiers({ ledger, onChanged }: { ledger: DuesLedger; onChanged: () => void }) {
  const [tiers, setTiers] = useState<{ id: number; name: string }[]>([]);
  useEffect(() => {
    api.get<{ rows: Record<string, string>[] }>('/api/bulk/dues_tiers')
      .then((r) => setTiers(r.rows.filter((t) => t.season_id === String(ledger.season.id)).map((t) => ({ id: Number(t.id), name: t.name }))))
      .catch(() => setTiers([]));
  }, [ledger.season.id]);
  const ownTier = new Set(tiers.map((t) => t.id));
  const setTier = async (eventId: number, tierId: number | null) => {
    try {
      await api.put(`/api/finance/events/${eventId}/dues-tier`, { tier_id: tierId });
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not set the tier');
    }
  };
  return (
    <Panel title="Who owes dues" extra="Everyone on an event's teams owes its tier">
      {!tiers.length ? (
        <Typography.Text type="secondary">No tiers for {ledger.season.name} yet — add them under Advanced › Dues fees.</Typography.Text>
      ) : (
        <div className="fin-tiers">
          {ledger.events.map((ev) => (
            <div key={ev.id} className="fin-tiers__row">
              <span>{ev.name}</span>
              <Select
                size="small"
                style={{ minWidth: 170 }}
                value={ev.tier_id != null && ownTier.has(ev.tier_id) ? ev.tier_id : 0}
                onChange={(v: number) => void setTier(ev.id, v || null)}
                options={[{ value: 0, label: 'No dues' }, ...tiers.map((t) => ({ value: t.id, label: t.name }))]}
              />
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function BudgetByEvent({ data }: { data: FinanceDashboard | null }) {
  if (!data) return <Skeleton active />;
  return (
    <Panel title="Plan vs spent, by event">
      <Table
        size="small"
        pagination={false}
        rowKey="name"
        dataSource={data.by_event}
        locale={{ emptyText: <EmptyState compact phrase="No budget yet." /> }}
        columns={[
          { title: 'Event', dataIndex: 'name' },
          { title: 'Still to buy', dataIndex: 'needed', align: 'right', render: egp },
          { title: 'Spent', dataIndex: 'spent', align: 'right', render: egp },
        ]}
      />
    </Panel>
  );
}

function FundingList({ data }: { data: FinanceDashboard | null }) {
  if (!data) return <Skeleton active />;
  return (
    <Panel title="Funding">
      <Table
        size="small"
        pagination={false}
        rowKey="id"
        dataSource={data.funding}
        locale={{ emptyText: <EmptyState compact phrase="No funding recorded." /> }}
        columns={[
          { title: 'From', dataIndex: 'source' },
          { title: 'Type', dataIndex: 'type' },
          { title: 'Amount', dataIndex: 'amount', align: 'right', render: egp },
          { title: 'Status', key: 's', render: (_, f) => (f.received_on ? `received ${dayjs(f.received_on).format('D MMM')}` : f.status) },
        ]}
      />
    </Panel>
  );
}
