import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Empty, Form, Input, Modal, Popconfirm, Select, Space, Switch, Tag, Tree, Typography, message } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { PositionNode, UserBrief } from '../api/types';
import { useAuth } from '../auth/AuthContext';

interface EditTarget {
  mode: 'create-root' | 'create-child' | 'edit';
  node?: PositionNode; // parent (create-child) or the position (edit)
}

function PositionModal({
  target,
  holders,
  open,
  onClose,
  onSaved,
}: {
  target: EditTarget | null;
  holders: UserBrief[];
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form] = Form.useForm<{ title: string; is_technical: boolean; occupant_id?: number }>();
  const [busy, setBusy] = useState(false);
  const isEdit = target?.mode === 'edit';

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (isEdit && target?.node) {
      form.setFieldsValue({
        title: target.node.title,
        is_technical: target.node.is_technical,
        occupant_id: target.node.occupant?.id,
      });
    } else {
      form.setFieldsValue({ is_technical: false });
    }
  }, [open, target, isEdit, form]);

  const submit = async (values: { title: string; is_technical: boolean; occupant_id?: number }) => {
    setBusy(true);
    try {
      if (isEdit && target?.node) {
        await api.patch(`/api/org/positions/${target.node.id}`, {
          title: values.title,
          is_technical: values.is_technical,
          ...(values.occupant_id != null ? { occupant_id: values.occupant_id } : { clear_occupant: true }),
        });
      } else {
        await api.post('/api/org/positions', {
          title: values.title,
          is_technical: values.is_technical,
          parent_id: target?.mode === 'create-child' ? target.node?.id : null,
          occupant_id: values.occupant_id ?? null,
        });
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
    target?.mode === 'edit'
      ? `Edit ${target.node?.title}`
      : target?.mode === 'create-child'
      ? `Add a position under ${target.node?.title}`
      : 'Add the top position';

  return (
    <Modal open={open} onCancel={onClose} title={title} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item name="title" label="Title" rules={[{ required: true, max: 255 }]}>
          <Input placeholder="e.g. Software Lead" />
        </Form.Item>
        <Form.Item name="occupant_id" label="Occupant (optional — a seat can be vacant)">
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Vacant"
            options={holders.map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` }))}
          />
        </Form.Item>
        <Form.Item name="is_technical" label="Technical position" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={busy}>
          {isEdit ? 'Save changes' : 'Add position'}
        </Button>
      </Form>
    </Modal>
  );
}

export default function OrganizationPage() {
  const { me } = useAuth();
  const [roots, setRoots] = useState<PositionNode[]>([]);
  const [holders, setHolders] = useState<UserBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [target, setTarget] = useState<EditTarget | null>(null);
  const [open, setOpen] = useState(false);

  const canManage = !!me && (me.is_admin || me.roles.some((r) => r.slug === 'ceo'));

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<PositionNode[]>('/api/org/tree')
      .then(setRoots)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    if (me && (me.is_staff || me.is_admin)) {
      api.get<UserBrief[]>('/api/inventory/holders').then(setHolders).catch(() => {});
    }
  }, [load, me]);

  const parentOf = useMemo(() => {
    const map = new Map<number, number | null>();
    const walk = (n: PositionNode, parent: number | null) => {
      map.set(n.id, parent);
      n.children.forEach((c) => walk(c, n.id));
    };
    roots.forEach((r) => walk(r, null));
    return map;
  }, [roots]);

  const openModal = (t: EditTarget) => {
    setTarget(t);
    setOpen(true);
  };

  const del = async (node: PositionNode) => {
    try {
      await api.delete(`/api/org/positions/${node.id}`);
      message.success('Position removed');
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Delete failed');
    }
  };

  const toTreeData = useCallback(
    (nodes: PositionNode[]): DataNode[] =>
      nodes.map((n) => ({
        key: String(n.id),
        title: (
          <Space size={6} wrap>
            <Typography.Text strong>{n.title}</Typography.Text>
            {n.occupant ? (
              <Typography.Text type="secondary">{n.occupant.full_name}</Typography.Text>
            ) : (
              <Tag>vacant</Tag>
            )}
            {n.is_technical && <Tag color="geekblue">technical</Tag>}
            {canManage && (
              <>
                <Button type="text" size="small" icon={<PlusOutlined />} title="Add under"
                  onClick={(e) => { e.stopPropagation(); openModal({ mode: 'create-child', node: n }); }} />
                <Button type="text" size="small" icon={<EditOutlined />} title="Edit"
                  onClick={(e) => { e.stopPropagation(); openModal({ mode: 'edit', node: n }); }} />
                <Popconfirm title="Remove this position?" onConfirm={() => del(n)}
                  onPopupClick={(e) => e.stopPropagation()}>
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} title="Remove"
                    onClick={(e) => e.stopPropagation()} />
                </Popconfirm>
              </>
            )}
          </Space>
        ),
        children: toTreeData(n.children),
      })),
    [canManage],
  );

  const onDrop = async (info: { dragNode: { key: React.Key }; node: { key: React.Key }; dropToGap: boolean }) => {
    const dragId = Number(info.dragNode.key);
    const targetId = Number(info.node.key);
    const newParent = info.dropToGap ? parentOf.get(targetId) ?? null : targetId;
    if (newParent === null) {
      message.info('There can be only one top position — drop onto a position to re-parent.');
      return;
    }
    if (newParent === dragId) return;
    try {
      await api.patch(`/api/org/positions/${dragId}`, { parent_id: newParent });
      message.success('Moved');
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Move failed');
    }
  };

  const treeData = useMemo(() => toTreeData(roots), [roots, toTreeData]);

  return (
    <>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }} align="start" wrap>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Organization
          </Typography.Title>
          <Typography.Text type="secondary">
            The chart of positions (jobs). A seat can be vacant. {canManage ? 'Add positions, assign occupants, or drag to re-parent.' : 'View only.'}
          </Typography.Text>
        </div>
        {canManage && roots.length === 0 && !loading && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal({ mode: 'create-root' })}>
            Add top position
          </Button>
        )}
      </Space>

      {!loading && treeData.length === 0 ? (
        <Empty description="No positions yet" />
      ) : (
        <Tree
          treeData={treeData}
          defaultExpandAll
          blockNode
          selectable={false}
          draggable={canManage ? { icon: false } : false}
          onDrop={onDrop}
        />
      )}

      <PositionModal
        target={target}
        holders={holders}
        open={open}
        onClose={() => setOpen(false)}
        onSaved={load}
      />
    </>
  );
}
