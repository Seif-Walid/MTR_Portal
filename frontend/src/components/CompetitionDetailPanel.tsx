import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Card, Divider, Empty, Input, Popconfirm, Select, Space, Tag, Typography, message } from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { CompetitionDetail, EntityRole, RoleRoot, UserBrief } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import PositionPicker from './PositionPicker';

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

function RolesEditor({ roles, dir, canManage, onChanged }: {
  roles: EntityRole[];
  dir: UserBrief[];
  canManage: boolean;
  onChanged: () => void;
}) {
  const [adding, setAdding] = useState<Record<number, number | undefined>>({});
  if (roles.length === 0) return null;

  const setOccupants = (role: EntityRole, userIds: number[]) => {
    if (!role.position_id) return;
    run(
      api.put(`/api/org/roles/positions/${role.position_id}/occupants`, { user_ids: userIds }),
      'Roles updated',
      onChanged,
    );
  };

  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      {roles.map((r) => (
        <Space key={r.template_id} wrap size={4} align="center">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{r.title}:</Typography.Text>
          {r.occupants.length === 0 && <Tag>vacant</Tag>}
          {r.occupants.map((u) => (
            <Tag
              key={u.id}
              closable={canManage && !!r.position_id}
              onClose={(e) => {
                e.preventDefault();
                setOccupants(r, r.occupants.filter((o) => o.id !== u.id).map((o) => o.id));
              }}
            >
              {u.full_name}
            </Tag>
          ))}
          {canManage && r.position_id && (
            <Select
              size="small" style={{ width: 160 }} showSearch optionFilterProp="label" placeholder="Add someone"
              value={adding[r.template_id]}
              options={opts(dir.filter((u) => !r.occupants.some((o) => o.id === u.id)))}
              onChange={(v) => {
                setOccupants(r, [...r.occupants.map((o) => o.id), v]);
                setAdding((s) => ({ ...s, [r.template_id]: undefined }));
              }}
            />
          )}
        </Space>
      ))}
    </Space>
  );
}

function TeamCard({ team, dir, canManageComp, isAdmin, onChanged }: {
  team: CompetitionDetail['categories'][number]['teams'][number];
  dir: UserBrief[];
  canManageComp: boolean;
  isAdmin: boolean;
  onChanged: () => void;
}) {
  const [memberId, setMemberId] = useState<number>();
  const canMembers = team.can_manage_members;
  const taken = new Set([...team.roles.flatMap((r) => r.occupants.map((o) => o.id)), ...team.members.map((m) => m.user.id)]);

  return (
    <Card
      size="small"
      style={{ marginTop: 8 }}
      title={<Typography.Text strong>{team.name}</Typography.Text>}
      extra={
        canManageComp && (
          <Space>
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
      <RolesEditor roles={team.roles} dir={dir} canManage={canManageComp} onChanged={onChanged} />
      <Divider style={{ margin: '8px 0' }} />
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
  const [teamNames, setTeamNames] = useState<Record<number, string>>({});
  const [roleRootParent, setRoleRootParent] = useState<Record<number, number | undefined>>({});
  const [roleRoot, setRoleRoot] = useState<RoleRoot | null>(null);

  const isAdmin = !!me?.is_admin;

  const load = useCallback(() => {
    api.get<CompetitionDetail>(`/api/competitions/${competitionId}`).then(setDetail).catch(() => {});
  }, [competitionId]);

  useEffect(() => {
    load();
    api.get<UserBrief[]>('/api/users/directory').then(setDir).catch(() => {});
    api.get<RoleRoot>('/api/org/roles/root').then(setRoleRoot).catch(() => {});
  }, [load]);

  const needsRoot = !!roleRoot && roleRoot.has_templates && roleRoot.root_position_id === null;

  const addTeam = (catId: number) => {
    const name = teamNames[catId]?.trim();
    if (!name) return;
    const body: Record<string, unknown> = { name };
    if (needsRoot) body.role_root_position_id = roleRootParent[catId];
    run(
      api.post(`/api/competitions/categories/${catId}/teams`, body),
      'Team added',
      () => {
        setTeamNames((s) => ({ ...s, [catId]: '' }));
        setRoleRootParent((s) => ({ ...s, [catId]: undefined }));
        api.get<RoleRoot>('/api/org/roles/root').then(setRoleRoot).catch(() => {});
        refresh();
      },
    );
  };

  const refresh = () => { load(); onChanged(); };

  if (!detail) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Loading…" />;
  const canManage = detail.can_manage;

  return (
    <div style={{ padding: '4px 8px' }}>
      {detail.description && <Typography.Paragraph type="secondary">{detail.description}</Typography.Paragraph>}

      <RolesEditor roles={detail.roles} dir={dir} canManage={canManage} onChanged={refresh} />

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
            <Space direction="vertical" size={6} style={{ marginTop: 10, width: '100%', maxWidth: 460 }}>
              {needsRoot && (
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    Where does the first automatic role go? (asked once, ever)
                  </Typography.Text>
                  <PositionPicker
                    value={roleRootParent[cat.id]}
                    onChange={(v) => setRoleRootParent((s) => ({ ...s, [cat.id]: v }))}
                  />
                </div>
              )}
              <Space.Compact style={{ width: '100%' }}>
                <Input placeholder="New team name" value={teamNames[cat.id] ?? ''}
                  onChange={(e) => setTeamNames((s) => ({ ...s, [cat.id]: e.target.value }))} />
                <Button type="primary" icon={<PlusOutlined />}
                  disabled={!teamNames[cat.id]?.trim() || (needsRoot && !roleRootParent[cat.id])}
                  onClick={() => addTeam(cat.id)}>
                  Add team
                </Button>
              </Space.Compact>
            </Space>
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
