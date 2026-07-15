import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Input, List, Modal, Popconfirm, Select, Space, Tag, message } from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Location } from '../api/types';

const KINDS = ['room', 'shelf', 'box', 'other'];

export default function LocationsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [locations, setLocations] = useState<Location[]>([]);
  const [name, setName] = useState('');
  const [kind, setKind] = useState('shelf');

  const load = useCallback(() => {
    api.get<Location[]>('/api/inventory/locations').then(setLocations).catch(() => {});
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const add = async () => {
    if (!name.trim()) return;
    try {
      await api.post('/api/inventory/locations', { name: name.trim(), kind });
      setName('');
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };

  const remove = async (id: number) => {
    try {
      await api.delete(`/api/inventory/locations/${id}`);
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title="Storage locations" footer={null} destroyOnHidden>
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input placeholder="e.g. Lab A — Shelf 3" value={name} onChange={(e) => setName(e.target.value)} onPressEnter={add} />
        <Select value={kind} onChange={setKind} options={KINDS.map((k) => ({ value: k, label: k }))} style={{ width: 110 }} />
        <Button type="primary" icon={<PlusOutlined />} onClick={add}>Add</Button>
      </Space.Compact>
      <List
        size="small"
        locale={{ emptyText: 'No locations yet' }}
        dataSource={locations}
        renderItem={(l) => (
          <List.Item
            actions={[
              <Popconfirm key="d" title="Delete this location?" onConfirm={() => remove(l.id)}>
                <Button size="small" type="text" danger icon={<DeleteOutlined />} />
              </Popconfirm>,
            ]}
          >
            <Space>{l.name}<Tag>{l.kind}</Tag></Space>
          </List.Item>
        )}
      />
    </Modal>
  );
}
