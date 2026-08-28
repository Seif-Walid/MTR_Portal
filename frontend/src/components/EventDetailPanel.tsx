import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Card, Divider, Empty, Input, Popconfirm, Select, Space, Tag, Typography, message } from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { EventDetail, EntityRole, RoleRoot, UserBrief } from '../api/types';
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

/** The official long-form title (event.full_name) the public Hall of Fame heads
 * this record with — "MATE ROV Competition" for an event named "MATE ROV 2026". */
function FullNameField({ value, canManage, onSave }: {
  value: string | null | undefined;
  canManage: boolean;
  onSave: (fullName: string) => void;
}) {
  if (!canManage) {
    return value ? <Typography.Paragraph type="secondary">{value}</Typography.Paragraph> : null;
  }
  return (
    <div style={{ marginBottom: 10 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Official full name
      </Typography.Text>
      <div>
        <Typography.Text
          type={value ? undefined : 'secondary'}
          style={{ fontSize: 13 }}
          editable={{
            tooltip: 'Set the official full name',
            text: value ?? '',
            onChange: (val) => onSave(val.trim()),
          }}
        >
          {value || 'e.g. MATE ROV Competition'}
        </Typography.Text>
      </div>
    </div>
  );
}

/** Competition-wide placements (event.awards) shown in the public Hall of Fame.
 * Free-form chips — type a placement and press enter; ✕ removes one. */
function AwardsEditor({ awards, canManage, onSave }: {
  awards: string[] | null | undefined;
  canManage: boolean;
  onSave: (awards: string[]) => void;
}) {
  const list = awards ?? [];
  if (!canManage) {
    if (list.length === 0) return null;
    return (
      <Space wrap size={4} style={{ marginBottom: 8 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>Awards:</Typography.Text>
        {list.map((a) => <Tag key={a} color="gold">{a}</Tag>)}
      </Space>
    );
  }
  return (
    <div style={{ marginBottom: 10 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Hall of Fame — competition awards
      </Typography.Text>
      <Select
        mode="tags"
        style={{ width: '100%', maxWidth: 560, marginTop: 4 }}
        placeholder="e.g. 🥇 1st Place — Sumo, Best Documentation"
        value={list}
        open={false}
        tokenSeparators={[',']}
        onChange={(v: string[]) => onSave(v.map((s) => s.trim()).filter(Boolean))}
      />
    </div>
  );
}

/** A single per-team placement (team.award), inline-editable. */
function AwardField({ value, canManage, onSave }: {
  value: string | null | undefined;
  canManage: boolean;
  onSave: (award: string) => void;
}) {
  if (!canManage) {
    return value ? <Tag color="gold" style={{ marginBottom: 6 }}>{value}</Tag> : null;
  }
  return (
    <div style={{ marginBottom: 6 }}>
      <Typography.Text
        type={value ? undefined : 'secondary'}
        style={{ fontSize: 13 }}
        editable={{ tooltip: 'Set placement', text: value ?? '', onChange: (val) => onSave(val.trim()) }}
      >
        {value || '🏆 Add placement'}
      </Typography.Text>
    </div>
  );
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
  team: EventDetail['categories'][number]['teams'][number];
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
      title={
        <Typography.Text
          strong
          editable={canManageComp ? {
            tooltip: 'Rename',
            onChange: (val) => {
              const name = val.trim();
              if (!name || name === team.name) return;
              run(api.patch(`/api/events/teams/${team.id}`, { name }), 'Team renamed', onChanged);
            },
          } : false}
        >
          {team.name}
        </Typography.Text>
      }
      extra={
        canManageComp && (
          <Space>
            <Popconfirm
              title="Remove this team?"
              description="It's kept for history but hidden everywhere."
              onConfirm={() => run(api.delete(`/api/events/teams/${team.id}`), 'Team removed', onChanged)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
            {isAdmin && (
              <Popconfirm
                title="Permanently delete this team?"
                description="Really removes it and its member history. Admin-only."
                onConfirm={() => run(api.delete(`/api/events/teams/${team.id}?permanent=true`), 'Team permanently deleted', onChanged)}
              >
                <Button size="small" danger type="text" icon={<DeleteOutlined />} title="Permanently delete (admin)" />
              </Popconfirm>
            )}
          </Space>
        )
      }
    >
      <AwardField
        value={team.award}
        canManage={canManageComp}
        onSave={(award) =>
          run(
            api.patch(`/api/events/teams/${team.id}`, award ? { award } : { clear_award: true }),
            'Placement updated',
            onChanged,
          )
        }
      />
      <RolesEditor roles={team.roles} dir={dir} canManage={canManageComp} onChanged={onChanged} />
      <Divider style={{ margin: '8px 0' }} />
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        {team.members.length === 0 && <Typography.Text type="secondary">No members yet.</Typography.Text>}
        {team.members.map((m) => (
          <Space key={m.id} size={6} align="center" wrap>
            <Typography.Text>{m.user.full_name}</Typography.Text>
            {/* Competition role shown in the public Hall of Fame — inline editable. */}
            <Typography.Text
              type={m.role ? 'secondary' : undefined}
              style={{ fontSize: 12 }}
              editable={canMembers ? {
                tooltip: 'Set role',
                text: m.role ?? '',
                onChange: (val) => {
                  const role = val.trim();
                  run(
                    api.patch(
                      `/api/events/teams/${team.id}/members/${m.user.id}`,
                      role ? { role } : { clear_role: true },
                    ),
                    'Role updated',
                    onChanged,
                  );
                },
              } : false}
            >
              {m.role ? `· ${m.role}` : (canMembers ? '· add role' : '')}
            </Typography.Text>
            {canMembers && (
              <Button
                size="small" type="text" danger icon={<DeleteOutlined />}
                onClick={() => run(api.delete(`/api/events/teams/${team.id}/members/${m.user.id}`), 'Removed', onChanged)}
              />
            )}
          </Space>
        ))}
      </Space>
      {canMembers && (
        <Space.Compact style={{ marginTop: 10, width: '100%', maxWidth: 420 }}>
          <Select
            showSearch optionFilterProp="label" style={{ width: '100%' }} placeholder="Add a member"
            value={memberId} options={opts(dir.filter((u) => !taken.has(u.id)))} onChange={setMemberId}
          />
          <Button icon={<PlusOutlined />} disabled={!memberId}
            onClick={() => run(api.post(`/api/events/teams/${team.id}/members`, { user_id: memberId }), 'Member added', () => { setMemberId(undefined); onChanged(); })}>
            Add
          </Button>
        </Space.Compact>
      )}
    </Card>
  );
}

export default function EventDetailPanel({ eventId, onChanged }: {
  eventId: number;
  onChanged: () => void;
}) {
  const { me } = useAuth();
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [dir, setDir] = useState<UserBrief[]>([]);
  const [newCat, setNewCat] = useState('');
  const [teamNames, setTeamNames] = useState<Record<number, string>>({});
  const [roleRootParent, setRoleRootParent] = useState<Record<number, number | undefined>>({});
  const [roleRoot, setRoleRoot] = useState<RoleRoot | null>(null);

  const isAdmin = me?.level?.rank === 1;

  const load = useCallback(() => {
    api.get<EventDetail>(`/api/events/${eventId}`).then(setDetail).catch(() => {});
  }, [eventId]);

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
      api.post(`/api/events/categories/${catId}/teams`, body),
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
  const teamLabel = detail.kind?.team_label ?? 'Team';
  const categoryLabel = detail.kind?.category_label ?? 'Category';

  return (
    <div style={{ padding: '4px 8px' }}>
      {detail.description && <Typography.Paragraph type="secondary">{detail.description}</Typography.Paragraph>}

      <FullNameField
        value={detail.full_name}
        canManage={canManage}
        onSave={(fullName) => {
          if (fullName === (detail.full_name ?? '')) return;
          run(
            api.patch(`/api/events/${eventId}`, fullName ? { full_name: fullName } : { clear_full_name: true }),
            'Full name updated',
            refresh,
          );
        }}
      />

      <AwardsEditor
        awards={detail.awards}
        canManage={canManage}
        onSave={(awards) =>
          run(
            api.patch(`/api/events/${eventId}`, awards.length ? { awards } : { clear_awards: true }),
            'Awards updated',
            refresh,
          )
        }
      />

      <RolesEditor roles={detail.roles} dir={dir} canManage={canManage} onChanged={refresh} />

      <Divider style={{ margin: '12px 0' }} />

      {detail.categories.length === 0 && (
        <Typography.Text type="secondary">No {categoryLabel.toLowerCase()} yet.</Typography.Text>
      )}
      {detail.categories.map((cat) => (
        <Card key={cat.id} size="small" style={{ marginBottom: 10 }}
          title={
            <Typography.Text
              strong
              editable={canManage ? {
                tooltip: 'Rename',
                onChange: (val) => {
                  const name = val.trim();
                  if (!name || name === cat.name) return;
                  run(api.patch(`/api/events/categories/${cat.id}`, { name }), 'Category renamed', refresh);
                },
              } : false}
            >
              {cat.name}
            </Typography.Text>
          }
          extra={canManage && (
            <Button size="small" danger icon={<DeleteOutlined />}
              onClick={() => run(api.delete(`/api/events/categories/${cat.id}`), 'Category removed', refresh)} />
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
                <Input placeholder={`New ${teamLabel.toLowerCase()} name`} value={teamNames[cat.id] ?? ''}
                  onChange={(e) => setTeamNames((s) => ({ ...s, [cat.id]: e.target.value }))} />
                <Button type="primary" icon={<PlusOutlined />}
                  disabled={!teamNames[cat.id]?.trim() || (needsRoot && !roleRootParent[cat.id])}
                  onClick={() => addTeam(cat.id)}>
                  Add {teamLabel.toLowerCase()}
                </Button>
              </Space.Compact>
            </Space>
          )}
        </Card>
      ))}

      {canManage && (
        <Space.Compact style={{ marginTop: 4, width: '100%', maxWidth: 460 }}>
          <Input placeholder={`New ${categoryLabel.toLowerCase()}`} value={newCat}
            onChange={(e) => setNewCat(e.target.value)}
            onPressEnter={() => newCat.trim() && run(api.post(`/api/events/${eventId}/categories`, { name: newCat.trim() }), 'Category added', () => { setNewCat(''); refresh(); })} />
          <Button type="primary" icon={<PlusOutlined />} disabled={!newCat.trim()}
            onClick={() => run(api.post(`/api/events/${eventId}/categories`, { name: newCat.trim() }), 'Category added', () => { setNewCat(''); refresh(); })}>
            Add {categoryLabel.toLowerCase()}
          </Button>
        </Space.Compact>
      )}
    </div>
  );
}
