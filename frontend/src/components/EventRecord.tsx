import { Button, Descriptions, Table, Typography, theme } from 'antd';
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { EventDetail, EventMoney, EventParticipant } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import { egp } from './charts';

const LABELS: Record<string, string> = {
  level: 'Level',
  organizer: 'Organizer',
  location: 'Location',
  tracks: 'Categories / tracks',
  result: 'Result',
  registered_count: 'Registered',
  participants_count: 'Participants',
  teams_count: 'Teams',
  mentors: 'Mentors / coaches',
  captains: 'Captain(s)',
  contact: 'MTR contact',
  budget_total: 'Budget (recorded)',
  actual_spend: 'Actual spend (recorded)',
  currency: 'Currency',
  funding_source: 'Funding / sponsor',
  prep_date: 'Prep date',
  competition_days: 'Competition day(s)',
  registration_form: 'Registration form',
  roster_source: 'Roster source',
  notes: 'Notes',
};
const MONEY = new Set(['budget_total', 'actual_spend']);

/** The event's record from the member database — its facts, its money from the
 *  books, and everyone who took part. Edited in Data Tables → Events. */
export default function EventRecord({ detail }: { detail: EventDetail }) {
  const { me } = useAuth();
  const { token } = theme.useToken();
  const [money, setMoney] = useState<EventMoney | null>(null);
  const [people, setPeople] = useState<EventParticipant[] | null>(null);
  const [showPeople, setShowPeople] = useState(false);
  const seeFinance = can(me, 'finance.view');
  const seeMembers = can(me, 'members.view');
  const record = detail.record ?? {};
  const count = detail.participation_count ?? 0;

  useEffect(() => {
    setMoney(null);
    setPeople(null);
    setShowPeople(false);
    if (seeFinance) api.get<EventMoney>(`/api/finance/events/${detail.id}`).then(setMoney).catch(() => {});
  }, [detail.id, seeFinance]);

  useEffect(() => {
    if (showPeople && people === null)
      api.get<EventParticipant[]>(`/api/events/${detail.id}/participations`).then(setPeople).catch(() => setPeople([]));
  }, [showPeople, people, detail.id]);

  const entries = Object.entries(record);
  if (!entries.length && !detail.code && !count && !money?.has_books) return null;

  return (
    <div style={{ margin: '12px 0' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
        <Typography.Text strong>Event record</Typography.Text>
        {detail.code && <span className="u-mono" style={{ fontSize: 12, color: token.colorTextTertiary }}>{detail.code}</span>}
      </div>
      {entries.length > 0 && (
        <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
          {entries.map(([k, v]) => (
            <Descriptions.Item key={k} label={LABELS[k] ?? k} span={k === 'result' || k === 'notes' ? 2 : 1}>
              {MONEY.has(k) ? egp(Number(v)) : String(v)}
            </Descriptions.Item>
          ))}
        </Descriptions>
      )}
      {money?.has_books && (
        <div style={{ marginTop: 8, fontSize: 13, color: token.colorTextSecondary }}>
          From the books: {egp(money.planned_needed)} EGP still needed of {egp(money.planned_fmv)} planned
          ({money.budget_lines} budget lines) · {egp(money.spent)} EGP spent
        </div>
      )}
      {seeMembers && count > 0 && (
        <div style={{ marginTop: 10 }}>
          <Button size="small" onClick={() => setShowPeople((s) => !s)}>
            {showPeople ? 'Hide' : 'Show'} the {count} participant{count === 1 ? '' : 's'}
          </Button>
          {showPeople && (
            <Table
              size="small"
              style={{ marginTop: 8 }}
              rowKey="id"
              loading={people === null}
              dataSource={people ?? []}
              pagination={{ defaultPageSize: 20, hideOnSinglePage: true, size: 'small' }}
              columns={[
                { title: 'MTR ID', dataIndex: 'mtr_id', width: 90, render: (v) => <span className="u-mono" style={{ fontSize: 12 }}>{v ?? '—'}</span> },
                { title: 'Name', dataIndex: 'name' },
                { title: 'Role / field', dataIndex: 'role', render: (v) => v ?? '—' },
                { title: 'Team', dataIndex: 'team', render: (v) => v ?? '—' },
                { title: 'Mentor', dataIndex: 'mentor', render: (v) => v ?? '—' },
                { title: 'Rating', dataIndex: 'rating', align: 'right', render: (v) => v ?? '—' },
              ]}
            />
          )}
        </div>
      )}
    </div>
  );
}
