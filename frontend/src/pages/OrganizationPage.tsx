import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Empty, Form, Input, Modal, Popconfirm, Select, Space, Switch, Tree, Typography, message } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { AccessLevel as AccessLevelT, EventKind as EventKindT, PositionNode, RoleEvent, RoleTemplate, UserBrief } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

// CIRCUIT hairline chip — replaces AntD preset <Tag> so tree chips match palette.
function Chip({ text, tone = 'muted' }: { text: string; tone?: 'accent' | 'violet' | 'gold' | 'muted' }) {
  const c = tone === 'accent' ? '#5cc6ff' : tone === 'violet' ? '#b892ff' : tone === 'gold' ? '#f5c451' : 'rgba(224,236,252,.5)';
  return (
    <span style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: '.06em', textTransform: 'uppercase', color: c, border: `1px solid ${c}55`, background: `${c}14`, padding: '2px 8px', borderRadius: 5, whiteSpace: 'nowrap' }}>{text}</span>
  );
}

interface EditTarget {
  mode: 'create-root' | 'create-child' | 'edit' | 'create-template-child' | 'edit-template';
  node?: PositionNode;
  template?: RoleTemplate;
}

const EVENT_LABELS: Record<RoleEvent, string> = {
  event_created: 'When a event is created',
  team_created: 'When a team is created',
  team_member_added: 'When a member is added to a team',
};

const EVENT_DEPTH: Record<RoleEvent, number> = { event_created: 0, team_created: 1, team_member_added: 2 };
const childEventOptions = (parent: RoleEvent) =>
  (Object.entries(EVENT_LABELS) as [RoleEvent, string][]).filter(([e]) => EVENT_DEPTH[e] >= EVENT_DEPTH[parent]).map(([value, label]) => ({ value, label }));

function PositionModal({ target, holders, levels, kinds, open, onClose, onSaved }: {
  target: EditTarget | null; holders: UserBrief[]; levels: AccessLevelT[]; kinds: EventKindT[];
  open: boolean; onClose: () => void; onSaved: () => void;
}) {
  const [form] = Form.useForm<{ title: string; is_technical: boolean; occupant_ids?: number[]; title_template: string; event: RoleEvent; access_level_id: number | null; event_kind_id: number | null }>();
  const [busy, setBusy] = useState(false);
  const [automatic, setAutomatic] = useState(false);

  const underTemplate = target?.mode === 'create-template-child';
  const isTemplateForm = target?.mode === 'edit-template' || (automatic && (target?.mode === 'create-child' || target?.mode === 'create-root'));
  const showWhenField = isTemplateForm;
  const showAutomaticSwitch = target?.mode === 'create-child' || target?.mode === 'create-root' || underTemplate;

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    setAutomatic(false);
    if (target?.mode === 'edit' && target.node) {
      form.setFieldsValue({ title: target.node.title, is_technical: target.node.is_technical, occupant_ids: target.node.occupants.map((u) => u.id), access_level_id: target.node.access_level_id });
    } else if (target?.mode === 'edit-template' && target.template) {
      form.setFieldsValue({ title_template: target.template.title_template, event: target.template.event, access_level_id: target.template.access_level_id, event_kind_id: target.template.event_kind_id });
    } else if (target?.mode === 'create-template-child') {
      form.setFieldsValue({ event: target.template?.event, access_level_id: null, event_kind_id: target.template?.event_kind_id ?? null });
    } else {
      form.setFieldsValue({ is_technical: false, event: 'event_created', access_level_id: null, event_kind_id: null });
    }
  }, [open, target, form]);

  const submit = async (values: { title: string; is_technical: boolean; occupant_ids?: number[]; title_template: string; event: RoleEvent; access_level_id?: number | null; event_kind_id?: number | null }) => {
    setBusy(true);
    try {
      if (target?.mode === 'edit' && target.node) {
        await api.patch(`/api/org/positions/${target.node.id}`, { title: values.title, is_technical: values.is_technical, occupant_ids: values.occupant_ids ?? [], access_level_id: values.access_level_id ?? null, clear_access_level: values.access_level_id == null });
      } else if (target?.mode === 'edit-template' && target.template) {
        await api.patch(`/api/org/roles/templates/${target.template.id}`, { title_template: values.title_template, event: values.event, access_level_id: values.access_level_id ?? null, clear_access_level: values.access_level_id == null, event_kind_id: values.event_kind_id ?? null, set_event_kind: true });
      } else if (target?.mode === 'create-template-child' && target.template) {
        await api.post('/api/org/roles/templates', { title_template: values.title_template, event: automatic && values.event ? values.event : target.template.event, access_level_id: automatic ? values.access_level_id ?? null : null, event_kind_id: automatic ? values.event_kind_id ?? null : null, insert_after_id: target.template.id });
      } else if (automatic) {
        await api.post('/api/org/roles/templates', { title_template: values.title_template, event: values.event, access_level_id: values.access_level_id ?? null, event_kind_id: values.event_kind_id ?? null });
      } else {
        await api.post('/api/org/positions', { title: values.title, is_technical: values.is_technical, parent_id: target?.mode === 'create-child' ? target.node?.id : null, occupant_ids: values.occupant_ids ?? [], access_level_id: values.access_level_id ?? null });
      }
      message.success('Saved');
      onSaved();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  const title =
    target?.mode === 'edit' ? `Edit ${target.node?.title}`
      : target?.mode === 'edit-template' ? `Edit ${target.template?.title_template}`
      : target?.mode === 'create-template-child' ? `Add a role under ${target.template?.title_template}`
      : target?.mode === 'create-child' ? `Add a position under ${target.node?.title}`
      : 'Add the top position';
  const isEditing = target?.mode === 'edit' || target?.mode === 'edit-template';

  return (
    <Modal open={open} onCancel={onClose} title={title} footer={null} destroyOnHidden>
      {showAutomaticSwitch && (
        <Space align="center" style={{ marginBottom: 16 }}>
          <Switch checked={automatic} onChange={setAutomatic} />
          <Typography.Text>
            {underTemplate
              ? `Automatic role — pick this role's own condition instead of inheriting "${target?.template?.title_template}"'s.`
              : 'Automatic role — seats itself when a event/team/member event happens, chained together with any other automatic roles for the same event, instead of a position you assign by hand.'}
          </Typography.Text>
        </Space>
      )}
      <Form form={form} layout="vertical" onFinish={submit}>
        {underTemplate && target?.template ? (
          <>
            <Form.Item name="title_template" label="Title" rules={[{ required: true, max: 255 }]} extra="Use {event}, {team}, or {member} as placeholders">
              <Input placeholder="e.g. Team Lead" />
            </Form.Item>
            {automatic ? (
              <>
                <Form.Item name="event" label="When" rules={[{ required: true }]}>
                  <Select options={childEventOptions(target.template.event)} />
                </Form.Item>
                <Form.Item name="event_kind_id" label="Fires for" extra="Which kind of event triggers this role — or every kind">
                  <Select allowClear placeholder="Every event kind" options={kinds.map((k) => ({ value: k.id, label: k.name }))} />
                </Form.Item>
                <Form.Item name="access_level_id" label="Access level" extra="The power this seat gives whoever occupies it — none by default">
                  <Select allowClear placeholder="No level — confers nothing" options={levels.map((l) => ({ value: l.id, label: `${l.rank}. ${l.name}` }))} />
                </Form.Item>
              </>
            ) : (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                Appears under "{target.template.title_template}" with the same condition — {EVENT_LABELS[target.template.event]}.
              </Typography.Paragraph>
            )}
          </>
        ) : isTemplateForm ? (
          <>
            <Form.Item name="title_template" label="Title" rules={[{ required: true, max: 255 }]} extra="Use {event}, {team}, or {member} as placeholders">
              <Input placeholder="e.g. {event} PM" />
            </Form.Item>
            {showWhenField && (
              <Form.Item name="event" label="When" rules={[{ required: true }]}>
                <Select options={Object.entries(EVENT_LABELS).map(([value, label]) => ({ value, label }))} />
              </Form.Item>
            )}
            <Form.Item name="event_kind_id" label="Fires for" extra="Which kind of event triggers this role — or every kind">
              <Select allowClear placeholder="Every event kind" options={kinds.map((k) => ({ value: k.id, label: k.name }))} />
            </Form.Item>
            <Form.Item name="access_level_id" label="Access level" extra="The power this seat gives whoever occupies it — none by default">
              <Select allowClear placeholder="No level — confers nothing" options={levels.map((l) => ({ value: l.id, label: `${l.rank}. ${l.name}` }))} />
            </Form.Item>
          </>
        ) : (
          <>
            <Form.Item name="title" label="Title" rules={[{ required: true, max: 255 }]}>
              <Input placeholder="e.g. Software Lead" />
            </Form.Item>
            <Form.Item name="occupant_ids" label="Occupants (optional — a seat can be vacant, or shared)">
              <Select mode="multiple" allowClear showSearch optionFilterProp="label" placeholder="Vacant" options={holders.map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` }))} />
            </Form.Item>
            <Form.Item name="access_level_id" label="Access level" extra="The power this seat gives whoever occupies it — none by default">
              <Select allowClear placeholder="No level — confers nothing" options={levels.map((l) => ({ value: l.id, label: `${l.rank}. ${l.name}` }))} />
            </Form.Item>
            <Form.Item name="is_technical" label="Technical position" valuePropName="checked">
              <Switch />
            </Form.Item>
          </>
        )}
        <Button type="primary" htmlType="submit" block loading={busy}>
          {isEditing ? 'Save changes' : isTemplateForm || underTemplate ? 'Add role' : 'Add position'}
        </Button>
      </Form>
    </Modal>
  );
}

export default function OrganizationPage() {
  const { me } = useAuth();
  const [roots, setRoots] = useState<PositionNode[]>([]);
  const [templates, setTemplates] = useState<RoleTemplate[]>([]);
  const [levels, setLevels] = useState<AccessLevelT[]>([]);
  const [kinds, setKinds] = useState<EventKindT[]>([]);
  const [holders, setHolders] = useState<UserBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [target, setTarget] = useState<EditTarget | null>(null);
  const [open, setOpen] = useState(false);
  const [showAutomatic, setShowAutomatic] = useState(false);

  const canManage = can(me, 'org.edit');

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get<PositionNode[]>('/api/org/tree'),
      api.get<RoleTemplate[]>('/api/org/roles/templates'),
      api.get<AccessLevelT[]>('/api/access/levels'),
      api.get<EventKindT[]>('/api/events/kinds'),
    ])
      .then(([positions, roleTemplates, ladder, eventKinds]) => { setRoots(positions); setTemplates(roleTemplates); setLevels(ladder); setKinds(eventKinds); })
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    if (can(me, 'people.view')) api.get<UserBrief[]>('/api/inventory/holders').then(setHolders).catch(() => {});
  }, [load, me]);

  const parentOf = useMemo(() => {
    const map = new Map<number, number | null>();
    const walk = (n: PositionNode, parent: number | null) => { map.set(n.id, parent); n.children.forEach((c) => walk(c, n.id)); };
    roots.forEach((r) => walk(r, null));
    return map;
  }, [roots]);

  const templatesByParent = useMemo(() => {
    const map = new Map<number | null, RoleTemplate[]>();
    for (const t of templates) { const key = t.parent_template_id; if (!map.has(key)) map.set(key, []); map.get(key)!.push(t); }
    for (const list of map.values()) list.sort((a, b) => a.sort_order - b.sort_order);
    return map;
  }, [templates]);

  const templatesOrdered = useMemo(() => [...templates].sort((a, b) => a.sort_order - b.sort_order), [templates]);
  const levelName = useCallback((id: number) => levels.find((l) => l.id === id)?.name ?? '?', [levels]);
  const kindName = useCallback((id: number) => kinds.find((k) => k.id === id)?.name ?? '?', [kinds]);
  const openModal = (t: EditTarget) => { setTarget(t); setOpen(true); };

  const del = async (node: PositionNode) => {
    try { await api.delete(`/api/org/positions/${node.id}`); message.success('Position removed'); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Delete failed'); }
  };
  const removeTemplate = async (t: RoleTemplate) => {
    try { await api.delete(`/api/org/roles/templates/${t.id}`); message.success('Role removed'); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Delete failed'); }
  };

  const templateActions = useCallback((t: RoleTemplate) =>
    canManage ? [
      <Button key="add" type="text" size="small" icon={<PlusOutlined />} title="Add role under" onClick={(e: React.MouseEvent) => { e.stopPropagation(); openModal({ mode: 'create-template-child', template: t }); }} />,
      <Button key="edit" type="text" size="small" icon={<EditOutlined />} title="Edit" onClick={(e: React.MouseEvent) => { e.stopPropagation(); openModal({ mode: 'edit-template', template: t }); }} />,
      <Popconfirm key="del" title="Remove this role?" description="Stops seating future events. People already in this role keep their seats." onConfirm={() => removeTemplate(t)} onPopupClick={(e) => e.stopPropagation()}>
        <Button type="text" size="small" danger icon={<DeleteOutlined />} title="Remove" onClick={(e) => e.stopPropagation()} />
      </Popconfirm>,
    ] : [], [canManage]);

  const toTemplateTreeData = useCallback((parentId: number | null): DataNode[] =>
    (templatesByParent.get(parentId) ?? []).map((t) => ({
      key: `tpl-${t.id}`,
      title: (
        <Space size={6} wrap>
          <Typography.Text strong italic style={{ color: '#eaf2ff' }}>{t.title_template}</Typography.Text>
          <Chip text="automatic" tone="violet" />
          <Chip text={EVENT_LABELS[t.event]} />
          <Chip text={t.event_kind_id != null ? kindName(t.event_kind_id) : 'all kinds'} tone={t.event_kind_id != null ? 'accent' : 'muted'} />
          {t.access_level_id != null && <Chip text={levelName(t.access_level_id)} tone="gold" />}
          {templateActions(t)}
        </Space>
      ),
      children: toTemplateTreeData(t.id),
    })), [templatesByParent, templateActions, levelName, kindName]);

  const toTreeData = useCallback((nodes: PositionNode[]): DataNode[] =>
    nodes.map((n) => ({
      key: String(n.id),
      title: (
        <Space size={6} wrap>
          <Typography.Text strong style={{ color: '#eaf2ff' }}>{n.title}</Typography.Text>
          {n.occupants.length > 0 ? (
            <Typography.Text type="secondary">{n.occupants.map((u) => u.full_name).join(', ')}</Typography.Text>
          ) : (
            <Chip text="vacant" />
          )}
          {n.is_technical && <Chip text="technical" tone="accent" />}
          {n.role_template_id != null && <Chip text="automatic" tone="violet" />}
          {canManage && (
            <>
              <Button type="text" size="small" icon={<PlusOutlined />} title="Add under" onClick={(e) => { e.stopPropagation(); openModal({ mode: 'create-child', node: n }); }} />
              <Button type="text" size="small" icon={<EditOutlined />} title="Edit" onClick={(e) => { e.stopPropagation(); openModal({ mode: 'edit', node: n }); }} />
              <Popconfirm title="Remove this position?" onConfirm={() => del(n)} onPopupClick={(e) => e.stopPropagation()}>
                <Button type="text" size="small" danger icon={<DeleteOutlined />} title="Remove" onClick={(e) => e.stopPropagation()} />
              </Popconfirm>
            </>
          )}
        </Space>
      ),
      children: [...toTreeData(n.children), ...(showAutomatic && n.parent_id === null ? toTemplateTreeData(null) : [])],
    })), [canManage, showAutomatic, toTemplateTreeData]);

  const onDrop = async (info: { dragNode: { key: React.Key }; node: { key: React.Key }; dropToGap: boolean }) => {
    const dragKey = String(info.dragNode.key);
    const targetKey = String(info.node.key);
    const dragIsTemplate = dragKey.startsWith('tpl-');
    const targetIsTemplate = targetKey.startsWith('tpl-');
    if (dragIsTemplate || targetIsTemplate) {
      if (!dragIsTemplate || !targetIsTemplate) { message.info('Automatic roles can only be reordered against other automatic roles.'); return; }
      const dragId = Number(dragKey.slice(4));
      const targetId = Number(targetKey.slice(4));
      const targetIdx = templatesOrdered.findIndex((t) => t.id === targetId);
      if (targetIdx === -1 || dragId === targetId) return;
      const newRank = (info.dropToGap ? targetIdx : targetIdx + 1) + 1;
      try { await api.patch(`/api/org/roles/templates/${dragId}`, { sort_order: newRank }); message.success('Reordered'); load(); }
      catch (e) { message.error(e instanceof ApiError ? e.message : 'Move failed'); }
      return;
    }
    const dragId = Number(dragKey);
    const targetId = Number(targetKey);
    const newParent = info.dropToGap ? parentOf.get(targetId) ?? null : targetId;
    if (newParent === null) { message.info('There can be only one top position — drop onto a position to re-parent.'); return; }
    if (newParent === dragId) return;
    try { await api.patch(`/api/org/positions/${dragId}`, { parent_id: newParent }); message.success('Moved'); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Move failed'); }
  };

  const treeData = useMemo(() => {
    const positionNodes = toTreeData(roots);
    const extraTopLevelTemplates = showAutomatic && roots.length === 0 ? toTemplateTreeData(null) : [];
    return [...positionNodes, ...extraTopLevelTemplates];
  }, [roots, toTreeData, showAutomatic, toTemplateTreeData]);

  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([]);
  useEffect(() => {
    const keys: React.Key[] = [];
    const walk = (nodes: DataNode[]) => { nodes.forEach((n) => { keys.push(n.key); if (n.children) walk(n.children); }); };
    walk(treeData);
    setExpandedKeys(keys);
  }, [treeData]);

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <div style={{ maxWidth: 620 }}>
          <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>Organization</h2>
          <div style={{ fontSize: 13, color: 'rgba(224,236,252,.5)', marginTop: 6, lineHeight: 1.5 }}>
            The chart of positions (jobs). A seat can be vacant, or shared by more than one person.{' '}
            {canManage ? 'Add positions, assign occupants, or drag to re-parent.' : 'View only.'}
          </div>
        </div>
        <Space direction="vertical" align="end" size={8}>
          {canManage && roots.length === 0 && !loading && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal({ mode: 'create-root' })}>Add top position</Button>
          )}
          <Space>
            <Switch checked={showAutomatic} onChange={setShowAutomatic} />
            <Typography.Text>Show automatic roles</Typography.Text>
          </Space>
        </Space>
      </div>

      {!loading && treeData.length === 0 ? (
        <Empty description="No positions yet" />
      ) : (
        <div style={{ border: '1px solid rgba(120,170,230,.12)', borderRadius: 12, background: 'rgba(15,20,29,.5)', padding: '16px 18px' }}>
          <Tree treeData={treeData} expandedKeys={expandedKeys} onExpand={setExpandedKeys} blockNode selectable={false} draggable={canManage ? { icon: false } : false} onDrop={onDrop} />
        </div>
      )}

      <PositionModal target={target} holders={holders} levels={levels} kinds={kinds} open={open} onClose={() => setOpen(false)} onSaved={load} />
    </>
  );
}
