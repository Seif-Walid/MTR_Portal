import { ReloadOutlined } from '@ant-design/icons';
import { Button, Segmented, Space, Table, Tag, Typography, message } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { AuditEntry } from '../api/types';

const DOMAIN_COLOR: Record<string, string> = {
  users: 'geekblue',
  inventory: 'gold',
  competitions: 'purple',
};

function detailSummary(detail: string): string {
  try {
    const d = JSON.parse(detail) as Record<string, unknown>;
    const parts = Object.entries(d).map(([k, v]) => `${k}: ${JSON.stringify(v)}`);
    return parts.join(' · ');
  } catch {
    return detail;
  }
}

export default function AuditLogPage() {
  const [domain, setDomain] = useState<'all' | 'users' | 'inventory' | 'competitions'>('all');
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    const params = domain === 'all' ? '' : `?domain=${domain}`;
    api
      .get<AuditEntry[]>(`/api/audit${params}`)
      .then(setEntries)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, [domain]);

  useEffect(load, [load]);

  return (
    <>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Audit Log
          </Typography.Title>
          <Typography.Text type="secondary">
            Every permission change, inventory quantity change, and competition-role change.
            Org-structure changes have their own log on the Organization page.
          </Typography.Text>
        </div>
        <Space>
          <Segmented
            value={domain}
            onChange={(v) => setDomain(v as typeof domain)}
            options={[
              { label: 'All', value: 'all' },
              { label: 'Users', value: 'users' },
              { label: 'Inventory', value: 'inventory' },
              { label: 'Competitions', value: 'competitions' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={load} />
        </Space>
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={entries}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        columns={[
          {
            title: 'When',
            dataIndex: 'created_at',
            width: 150,
            render: (d: string) => dayjs(d).format('DD MMM HH:mm'),
          },
          { title: 'Actor', dataIndex: 'actor', width: 160 },
          {
            title: 'Domain',
            dataIndex: 'domain',
            width: 130,
            render: (d: string) => <Tag color={DOMAIN_COLOR[d] ?? 'default'}>{d}</Tag>,
          },
          {
            title: 'Action',
            dataIndex: 'action',
            width: 160,
            render: (a: string) => a.replace(/_/g, ' '),
          },
          {
            title: 'Entity',
            width: 160,
            render: (_, r) => `${r.entity_type}${r.entity_id ? ` #${r.entity_id}` : ''}`,
          },
          {
            title: 'Detail',
            render: (_, r) => (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {detailSummary(r.detail)}
              </Typography.Text>
            ),
          },
        ]}
      />
    </>
  );
}
