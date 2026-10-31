import { ArrowRightOutlined } from '@ant-design/icons';
import { Button, Segmented, Skeleton, Table, Tag, Typography, theme } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { FinanceDashboard, RosterStats } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import FinanceOverview from '../components/FinanceOverview';
import { BarList, Columns, Panel, PanelGrid, StatRow, StatTile } from '../components/charts';

const count = (n: number) => n.toLocaleString('en-US');

/** One page that shows the team at a glance: the roster, what members took
 *  part in, and — for those who may see it — the money. */
export default function InsightsPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const seeMembers = can(me, 'members.view');
  const seeFinance = can(me, 'finance.view');

  const [stats, setStats] = useState<RosterStats | null>(null);
  const [finance, setFinance] = useState<FinanceDashboard | null>(null);
  const [joinsBy, setJoinsBy] = useState<'year' | 'month'>('year');

  useEffect(() => {
    if (seeMembers) api.get<RosterStats>('/api/members/stats').then(setStats).catch(() => {});
    if (seeFinance) {
      api
        .get<{ current_id: number | null }>('/api/finance/seasons')
        .then((s) => api.get<FinanceDashboard>(`/api/finance/dashboard${s.current_id ? `?season_id=${s.current_id}` : ''}`))
        .then(setFinance)
        .catch(() => {});
    }
  }, [seeMembers, seeFinance]);

  const joins = useMemo(() => {
    if (!stats) return [];
    if (joinsBy === 'month') {
      return stats.joins_by_month.map((j) => ({ label: dayjs(`${j.month}-01`).format('MMM YY'), value: j.count }));
    }
    const byYear = new Map<string, number>();
    for (const j of stats.joins_by_month) byYear.set(j.month.slice(0, 4), (byYear.get(j.month.slice(0, 4)) ?? 0) + j.count);
    return Array.from(byYear, ([label, value]) => ({ label, value }));
  }, [stats, joinsBy]);

  const t = stats?.totals;
  const seasonName = finance?.seasons.find((s) => s.id === finance.season_id)?.name;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
      {seeMembers && (
        <section style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <SectionHead title="Members" onOpen={() => navigate('/members')} openLabel="Open roster" />
          {!stats ? (
            <Skeleton active paragraph={{ rows: 6 }} />
          ) : (
            <>
              <StatRow min={170}>
                <StatTile label="On the roster" value={count(t!.members)} sub={`${count(t!.claimed)} with their account set up`} />
                <StatTile label="Took part in an event" value={count(t!.active_members)} sub={`${Math.round((t!.active_members / Math.max(t!.members, 1)) * 100)}% of the roster`} />
                <StatTile label="Participations" value={count(t!.participations)} sub={`across ${stats.events.length} events`} />
                <StatTile label="Graduating within a year" value={count(t!.graduating_soon)} />
                <StatTile label="Records to review" value={count(t!.needs_review)} tone={t!.needs_review ? 'danger' : undefined} />
              </StatRow>
              <PanelGrid>
                <Panel
                  title="New members"
                  extra={
                    <Segmented size="small" value={joinsBy} onChange={(v) => setJoinsBy(v as 'year' | 'month')}
                      options={[{ value: 'year', label: 'By year' }, { value: 'month', label: 'By month' }]} />
                  }
                >
                  <Columns items={joins} format={count} empty="No registration dates" />
                </Panel>
                <Panel title="Participants per event">
                  <BarList
                    items={stats.events.map((e) => ({ name: e.code ? `${e.name}` : e.name, value: e.participants }))}
                    format={count}
                    empty="No participations yet"
                  />
                </Panel>
              </PanelGrid>
              <PanelGrid min={280}>
                <Panel title="University">
                  <BarList items={stats.by_university.map((r) => ({ name: r.name, value: r.count }))} format={count} />
                </Panel>
                <Panel title="Major">
                  <BarList items={stats.by_major.map((r) => ({ name: r.name, value: r.count }))} format={count} />
                </Panel>
                <Panel title="Governorate">
                  <BarList items={stats.by_location.map((r) => ({ name: r.name, value: r.count }))} format={count} />
                </Panel>
              </PanelGrid>
              <PanelGrid>
                <Panel title="Graduating year">
                  <Columns items={stats.by_graduating_year.map((r) => ({ label: r.name, value: r.count }))} format={count} every={1} />
                </Panel>
                <Panel title="How many events each member did" extra="members">
                  <Columns
                    items={stats.activity.map((a) => ({ label: String(a.events), value: a.members, title: `${a.events} event${a.events === 1 ? '' : 's'}` }))}
                    format={count}
                    every={1}
                  />
                </Panel>
              </PanelGrid>
              <Panel title="Event record">
                <Table
                  size="small"
                  rowKey="id"
                  pagination={false}
                  dataSource={stats.events}
                  scroll={{ x: 'max-content' }}
                  columns={[
                    { title: 'Event', dataIndex: 'name' },
                    { title: 'ID', dataIndex: 'code', render: (v) => <span className="u-mono" style={{ fontSize: 12 }}>{v ?? '—'}</span> },
                    { title: 'Kind', dataIndex: 'kind', render: (v) => v ?? '—' },
                    { title: 'Participants', dataIndex: 'participants', align: 'right' },
                    { title: 'Result', dataIndex: 'result', render: (v) => <span style={{ color: token.colorTextSecondary }}>{v ?? '—'}</span> },
                    {
                      title: 'Status', dataIndex: 'status',
                      render: (s: string) => <Tag color={s === 'archived' ? 'default' : 'processing'}>{s === 'archived' ? 'archived' : 'active'}</Tag>,
                    },
                  ]}
                />
              </Panel>
            </>
          )}
        </section>
      )}

      {seeFinance && (
        <section style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <SectionHead
            title={`Finance${seasonName ? ` — ${seasonName}` : ''}`}
            onOpen={() => navigate('/finance')}
            openLabel="Open the books"
          />
          <FinanceOverview data={finance} compactView />
        </section>
      )}

      {!seeMembers && !seeFinance && (
        <Typography.Text type="secondary">Nothing to show — your access level doesn't include the roster or the books.</Typography.Text>
      )}
    </div>
  );
}

function SectionHead({ title, onOpen, openLabel }: { title: string; onOpen: () => void; openLabel: string }) {
  const { token } = theme.useToken();
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: token.colorText }}>{title}</h2>
      <Button type="link" onClick={onOpen} style={{ paddingInline: 0 }}>
        {openLabel} <ArrowRightOutlined />
      </Button>
    </div>
  );
}
