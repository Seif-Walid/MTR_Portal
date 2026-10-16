import { Skeleton, Table, Tag, Typography, theme } from 'antd';
import dayjs from 'dayjs';

import type { FinanceDashboard } from '../api/types';
import { BarList, Columns, Panel, PanelGrid, StatRow, StatTile, compact, egp } from './charts';

const STATUS_TAG: Record<string, { color: string; label: string }> = {
  over: { color: 'error', label: 'Over budget' },
  'on track': { color: 'processing', label: 'On track' },
  'not started': { color: 'default', label: 'Not started' },
  empty: { color: 'default', label: 'No plan' },
};

const monthLabel = (m: string) => dayjs(`${m}-01`).format('MMM YY');

/** The finance dashboard body — KPIs, where the plan goes, and money over time. */
export default function FinanceOverview({ data, compactView = false }: { data: FinanceDashboard | null; compactView?: boolean }) {
  const { token } = theme.useToken();
  if (!data) return <Skeleton active paragraph={{ rows: 8 }} />;
  const k = data.kpis;
  const collectedPct = k.projected_dues ? Math.round((k.dues_collected / k.projected_dues) * 100) : 0;
  const spentPct = k.plan_needed ? Math.round((k.spent / k.plan_needed) * 100) : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <StatRow>
        <StatTile label="Plan — still needed" value={egp(k.plan_needed)} unit="EGP" sub={`Full worth (FMV) ${compact(k.plan_fmv)}`} />
        <StatTile label="Actually spent" value={egp(k.spent)} unit="EGP" sub={`${spentPct}% of what's needed`} />
        <StatTile label="Dues collected" value={egp(k.dues_collected)} unit="EGP" sub={`${collectedPct}% of ${compact(k.projected_dues)} projected`} />
        <StatTile label="Funding secured" value={egp(k.funding_secured)} unit="EGP" sub={k.funding_expected ? `+ ${compact(k.funding_expected)} expected` : 'Grants, sponsors, carry-over'} />
        <StatTile label="Cash on hand" value={egp(k.cash_on_hand)} unit="EGP" sub="Across every holder" />
        <StatTile
          label="Gap"
          value={egp(k.gap)} unit="EGP"
          tone={k.gap > 0 ? 'danger' : 'good'}
          sub={k.gap > 0 ? 'Plan not yet covered by funding + projected dues' : 'Plan covered'}
        />
      </StatRow>

      <PanelGrid>
        <Panel title="Plan by subsystem" extra="Needed cost, over full worth">
          <BarList
            items={data.by_subsystem.map((r) => ({ name: r.name, value: r.needed, track: r.fmv }))}
            valueLabel="Still needed"
            trackLabel="Full worth (FMV)"
            empty="No budget lines yet"
          />
        </Panel>
        <Panel title="Spending against plan, by category" extra="Spent, over needed">
          <BarList
            items={data.by_category
              .filter((r) => r.needed || r.spent)
              .sort((a, b) => b.needed - a.needed)
              .map((r) => ({ name: r.name, value: r.spent, track: r.needed }))}
            valueLabel="Spent"
            trackLabel="Needed"
            empty="No budget lines yet"
          />
        </Panel>
      </PanelGrid>

      {!compactView && (
        <PanelGrid>
          <Panel title="Dues collected by month" extra="EGP">
            <Columns
              items={data.monthly.map((m) => ({ label: monthLabel(m.month), value: m.collected }))}
              empty="No payments yet"
            />
          </Panel>
          <Panel title="Spending by month" extra="EGP">
            <Columns
              items={data.monthly.map((m) => ({ label: monthLabel(m.month), value: m.spent }))}
              empty="Nothing spent yet"
            />
          </Panel>
        </PanelGrid>
      )}

      <PanelGrid min={420}>
        <Panel title="Seasons">
          <Table
            size="small"
            pagination={false}
            rowKey="season_id"
            dataSource={data.per_season}
            columns={[
              { title: 'Season', dataIndex: 'season' },
              { title: 'Needed', dataIndex: 'needed', align: 'right', render: egp },
              { title: 'Spent', dataIndex: 'spent', align: 'right', render: egp },
              { title: 'Left', dataIndex: 'left', align: 'right', render: egp },
              {
                title: 'Status',
                dataIndex: 'status',
                render: (s: string) => <Tag color={STATUS_TAG[s]?.color}>{STATUS_TAG[s]?.label ?? s}</Tag>,
              },
            ]}
          />
        </Panel>
        <Panel title="By event" extra="Needed vs spent">
          <Table
            size="small"
            pagination={false}
            rowKey="name"
            dataSource={data.by_event}
            locale={{ emptyText: 'No budget lines yet' }}
            columns={[
              { title: 'Event', dataIndex: 'name' },
              { title: 'Needed', dataIndex: 'needed', align: 'right', render: egp },
              { title: 'Spent', dataIndex: 'spent', align: 'right', render: egp },
            ]}
          />
        </Panel>
      </PanelGrid>

      {!compactView && (
        <PanelGrid min={420}>
          <Panel title="Funding pipeline">
            <Table
              size="small"
              pagination={false}
              rowKey={(r) => `${r.source}-${r.season_id}`}
              dataSource={[
                ...data.funding,
                { source: 'Member dues (projected, from the dues roster)', type: 'Member Dues', amount: k.projected_dues, status: 'expected', season_id: -1 },
              ]}
              columns={[
                { title: 'Source', dataIndex: 'source' },
                { title: 'Type', dataIndex: 'type', render: (v) => v ?? '—' },
                { title: 'Amount', dataIndex: 'amount', align: 'right', render: egp },
                {
                  title: 'Status',
                  dataIndex: 'status',
                  render: (s: string) => <Tag color={s === 'secured' ? 'success' : 'default'}>{s}</Tag>,
                },
              ]}
            />
          </Panel>
          <Panel title="Cash by holder" extra="EGP">
            {data.cash.rows.length ? (
              <Table
                size="small"
                pagination={false}
                rowKey="party_id"
                dataSource={data.cash.rows}
                columns={[
                  { title: 'Holder', dataIndex: 'name' },
                  ...data.cash.methods
                    .filter((m) => data.cash.totals[String(m.id)] !== 0)
                    .map((m) => ({
                      title: m.name,
                      key: String(m.id),
                      align: 'right' as const,
                      render: (_: unknown, r: (typeof data.cash.rows)[number]) => egp(r.cells[String(m.id)] ?? 0),
                    })),
                  { title: 'Total', dataIndex: 'total', align: 'right', render: (v: number) => <strong>{egp(v)}</strong> },
                ]}
              />
            ) : (
              <Typography.Text type="secondary">No cash holders yet.</Typography.Text>
            )}
            <div style={{ fontSize: 12, color: token.colorTextTertiary, marginTop: 8 }}>
              Transfers in − out − fees − spendings paid + dues received, per holder and method.
            </div>
          </Panel>
        </PanelGrid>
      )}
    </div>
  );
}
