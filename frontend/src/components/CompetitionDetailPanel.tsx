import { CrownOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Card, Divider, Empty, Input, Popconfirm, Select, Space, Tag, Typography, message } from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { CompetitionDetail, CompetitionTeam, UserBrief } from '../api/types';
import { useAuth } from '../auth/AuthContext';

function opts(users: UserBrief[]) {
  return users.map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` }));
}

async function run(p: Promise<unknown>, ok: string, after: () => void) {
  try {
    await p;
    message.success(ok);
    after();
  } catch (e) {
    message.error(e instanceof ApiError ? e.message : 'Failed');
  }
}

function TeamCard({ team, dir, canManageComp, isAdmin, onChanged }: {
  team: CompetitionTeam;
  dir: UserBrief[];
  canManageComp: boolean;
  isAdmin: boolean;
  onChanged: () => void;
}) {
  const [memberId, setMemberId] = useState<number>();
  const canMembers = team.can_manage_members;
  const taken = new Set([team.lead?.id, ...team.members.map((m) => m.user.id)]);

  return (
    <Card
      size="small"
      style={{ marginTop: 8 }}
      title={
        <Space wrap>
          <Typography.Text strong>{team.name}</Typography.Text>
          {team.lead ? (
            <Tag icon={<CrownOutlined />} color="gold">{team.lead.full_name}</Tag>
          ) : (
            <Tag>no lead</Tag>
          )}
        </Space>
      }
      extra={
        canManageComp && (
          <Space>
            <Select
              size="small" style={{ width: 150 }} placeholder="Appoint lead"
              value={team.lead?.id} options={opts(dir)}
              onChange={(v) => run(api.patch(`/api/competitions/teams/${team.id}`, { lead_id: v }), 'Lead appointed', onChanged)}
            />
            <Popconfirm
              title="Remove this team?"
              description="It's kept for history but hidden everywhere."
              onConfirm={() => run(api.delete(`/api/competitions/teams/${team.id}`), 'Team removed', onChanged)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
            {isAdmin && (
              <Popconfirm
                title="Permanently delete this team?"
                description="Really removes it and its member history. Admin-only."
                onConfirm={() => run(api.delete(`/api/competitions/teams/${team.id}?permanent=true`), 'Team permanently deleted', onChanged)}
              >
                <Button size="small" danger type="text" icon={<DeleteOutlined />} title="Permanently delete (admin)" />
              </Popconfirm>
            )}
          </Space>
        )
      }
    >
      <Space wrap size={[6, 6]}>
        {team.members.length === 0 && <Typography.Text type="secondary">No members yet.</Typography.Text>}
        {team.members.map((m) => (
          <Tag key={m.id} closable={canMembers}
            onClose={(e) => { e.preventDefault(); run(api.delete(`/api/competitions/teams/${team.id}/members/${m.user.id}`), 'Removed', onChanged); }}>
            {m.user.full_name}
          </Tag>
        ))}
      </Space>
      {canMembers && (
        <Space.Compact style={{ marginTop: 10, width: '100%', maxWidth: 420 }}>
          <Select
            showSearch optionFilterProp="label" style={{ width: '100%' }} placeholder="Add a member"
            value={memberId} options={opts(dir.filter((u) => !taken.has(u.id)))} onChange={setMemberId}
          />
          <Button icon={<PlusOutlined />} disabled={!memberId}
            onClick={() => run(api.post(`/api/competitions/teams/${team.id}/members`, { user_id: memberId }), 'Member added', () => { setMemberId(undefined); onChanged(); })}>
            Add
          </Button>
        </Space.Compact>
      )}
    </Card>
  );
}

export default function CompetitionDetailPanel({ competitionId, onChanged }: {
  competitionId: number;
  onChanged: () => void;
}) {
  const { me } = useAuth();
  const [detail, setDetail] = useState<CompetitionDetail | null>(null);
  const [dir, setDir] = useState<UserBrief[]>([]);
  const [newCat, setNewCat] = useState('');
  const [pmId, setPmId] = useState<number>();
  const [teamNames, setTeamNames] = useState<Record<number, string>>({});

  const isHighStaff = !!me?.is_high_staff;
  const isAdmin = !!me?.is_admin;

  const load = useCallback(() => {
    api.get<CompetitionDetail>(`/api/competitions/${competitionId}`).then(setDetail).catch(() => {});
  }, [competitionId]);

  useEffect(() => {
    load();
    api.get<UserBrief[]>('/api/users/directory').then(setDir).catch(() => {});
  }, [load]);

  const refresh = () => { load(); onChanged(); };

  if (!detail) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Loading…" />;
  const canManage = detail.can_manage;

  return (
    <div style={{ padding: '4px 8px' }}>
      {detail.description && <Typography.Paragraph type="secondary">{detail.description}</Typography.Paragraph>}

      <Space wrap align="center">
        <Typography.Text type="secondary">Project managers:</Typography.Text>
        {detail.pms.length === 0 && <Typography.Text type="secondary">none</Typography.Text>}
        {detail.pms.map((p) => (
          <Tag key={p.id} color="purple" closable={isHighStaff}
            onClose={(e) => { e.preventDefault(); run(api.delete(`/api/competitions/${competitionId}/pms/${p.id}`), 'PM removed', refresh); }}>
            {p.full_name}
          </Tag>
        ))}
        {isHighStaff && (
          <Space.Compact>
            <Select size="small" showSearch optionFilterProp="label" style={{ width: 180 }}
              placeholder="Add PM" value={pmId}
              options={opts(dir.filter((u) => !detail.pms.some((p) => p.id === u.id)))} onChange={setPmId} />
            <Button size="small" disabled={!pmId}
              onClick={() => run(api.post(`/api/competitions/${competitionId}/pms`, { user_id: pmId }), 'PM added', () => { setPmId(undefined); refresh(); })}>
              Add
            </Button>
          </Space.Compact>
        )}
      </Space>

      <Divider style={{ margin: '12px 0' }} />

      {detail.categories.length === 0 && (
        <Typography.Text type="secondary">No categories yet.</Typography.Text>
      )}
      {detail.categories.map((cat) => (
        <Card key={cat.id} size="small" style={{ marginBottom: 10 }}
          title={<Typography.Text strong>{cat.name}</Typography.Text>}
          extra={canManage && (
            <Button size="small" danger icon={<DeleteOutlined />}
              onClick={() => run(api.delete(`/api/competitions/categories/${cat.id}`), 'Category removed', refresh)} />
          )}
        >
          {cat.teams.map((t) => (
            <TeamCard key={t.id} team={t} dir={dir} canManageComp={canManage} isAdmin={isAdmin} onChanged={refresh} />
          ))}
          {canManage && (
            <Space.Compact style={{ marginTop: 10, width: '100%', maxWidth: 460 }}>
              <Input placeholder="New team name" value={teamNames[cat.id] ?? ''}
                onChange={(e) => setTeamNames((s) => ({ ...s, [cat.id]: e.target.value }))} />
              <Button type="primary" icon={<PlusOutlined />}
                disabled={!teamNames[cat.id]?.trim()}
                onClick={() => run(api.post(`/api/competitions/categories/${cat.id}/teams`, { name: teamNames[cat.id].trim() }), 'Team added', () => { setTeamNames((s) => ({ ...s, [cat.id]: '' })); refresh(); })}>
                Add team
              </Button>
            </Space.Compact>
          )}
        </Card>
      ))}

      {canManage && (
        <Space.Compact style={{ marginTop: 4, width: '100%', maxWidth: 460 }}>
          <Input placeholder="New category (division)" value={newCat}
            onChange={(e) => setNewCat(e.target.value)}
            onPressEnter={() => newCat.trim() && run(api.post(`/api/competitions/${competitionId}/categories`, { name: newCat.trim() }), 'Category added', () => { setNewCat(''); refresh(); })} />
          <Button type="primary" icon={<PlusOutlined />} disabled={!newCat.trim()}
            onClick={() => run(api.post(`/api/competitions/${competitionId}/categories`, { name: newCat.trim() }), 'Category added', () => { setNewCat(''); refresh(); })}>
            Add category
          </Button>
        </Space.Compact>
      )}
    </div>
  );
}
