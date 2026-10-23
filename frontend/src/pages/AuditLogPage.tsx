import { ReloadOutlined } from '@ant-design/icons';
import { Button, Select, Space, Table, Tag, Typography, message } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { AuditEntry, AuditPage } from '../api/types';

const DOMAIN_COLOR: Record<string, string> = {
  users: 'geekblue',
  inventory: 'gold',
  events: 'purple',
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
  const [domain, setDomain] = useState<string>('all');
  const [domains, setDomains] = useState<string[]>([]);
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  // Paged server-side so "All" reaches every entry, not just the newest batch.
  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({
      limit: String(pageSize),
      offset: String((page - 1) * pageSize),
    });
    if (domain !== 'all') params.set('domain', domain);
    api
      .get<AuditPage>(`/api/audit?${params}`)
      .then((r) => {
        setEntries(r.items);
        setTotal(r.total);
        setDomains(r.domains);
      })
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, [domain, page, pageSize]);

  useEffect(load, [load]);

  return (
    <>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }} wrap>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Audit Log
          </Typography.Title>
          <Typography.Text type="secondary">
            Every recorded change across the portal, newest first.
            Org-structure changes have their own log on the Organization page.
          </Typography.Text>
        </div>
        <Space>
          <Select
            style={{ minWidth: 160 }}
            value={domain}
            onChange={(v) => {
              setDomain(v as string);
              setPage(1);
            }}
            options={[
              { label: 'All', value: 'all' },
              ...domains.map((d) => ({ label: d.charAt(0).toUpperCase() + d.slice(1), value: d })),
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={load} />
        </Space>
      </Space>

      <Table className="circuit-table"
        rowKey="id"
        loading={loading}
        dataSource={entries}
        pagination={{
          current: page,
          pageSize,
          total,
          hideOnSinglePage: true,
          showSizeChanger: true,
          showTotal: (t) => `${t} entries`,
          onChange: (p, s) => {
            setPage(s !== pageSize ? 1 : p);
            setPageSize(s);
          },
        }} scroll={{ x: 'max-content' }}
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
