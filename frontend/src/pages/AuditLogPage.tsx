import { ReloadOutlined, RobotOutlined } from '@ant-design/icons';
import { Button, Checkbox, Select, Space, Table, Tag, Typography, message } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { AuditEntry, AuditPage } from '../api/types';

const DOMAIN_COLOR: Record<string, string> = {
  users: 'geekblue',
  inventory: 'gold',
  events: 'purple',
};

/** How the AI reached the portal, in words. */
export function channelLabel(via: string): string {
  if (via === 'assistant') return 'portal assistant';
  if (via === 'mcp') return 'MCP / script';
  if (via.startsWith('agent:')) return `${via.slice(6) || 'agent'} (connected agent)`;
  return via;
}

function ActorCell({ entry }: { entry: AuditEntry }) {
  if (!entry.via) return <>{entry.actor}</>;
  return (
    <Space direction="vertical" size={0}>
      <span>
        <Tag icon={<RobotOutlined />} color="cyan" style={{ marginInlineEnd: 6 }}>AI</Tag>
        via {entry.actor}
      </span>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {channelLabel(entry.via)}
        {/* approval by the account owner goes without saying; name anyone else */}
        {!entry.approved_by
          ? ' · ran directly, no approval'
          : entry.approved_by !== entry.actor && ` · approved by ${entry.approved_by}`}
      </Typography.Text>
    </Space>
  );
}

function detailSummary(detail: string): string {
  try {
    const d = JSON.parse(detail) as Record<string, unknown>;
    const show = (v: unknown) => (typeof v === 'string' ? `"${v}"` : JSON.stringify(v));
    const parts: string[] = [];
    for (const [k, v] of Object.entries(d)) {
      // automatic entries: {changes: {field: [before, after]}} and {values: {field: value}}
      if (k === 'changes' && v && typeof v === 'object') {
        for (const [f, pair] of Object.entries(v as Record<string, unknown>)) {
          const [before, after] = Array.isArray(pair) ? pair : [undefined, pair];
          parts.push(`${f}: ${show(before)} → ${show(after)}`);
        }
      } else if (k === 'values' && v && typeof v === 'object') {
        for (const [f, val] of Object.entries(v as Record<string, unknown>)) parts.push(`${f}: ${show(val)}`);
      } else {
        parts.push(`${k}: ${show(v)}`);
      }
    }
    return parts.join(' · ');
  } catch {
    return detail;
  }
}

export default function AuditLogPage() {
  const [domain, setDomain] = useState<string>('all');
  const [aiOnly, setAiOnly] = useState(false);
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
    if (aiOnly) params.set('ai', 'true');
    api
      .get<AuditPage>(`/api/audit?${params}`)
      .then((r) => {
        setEntries(r.items);
        setTotal(r.total);
        setDomains(r.domains);
      })
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, [domain, aiOnly, page, pageSize]);

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
          <Checkbox
            checked={aiOnly}
            onChange={(e) => {
              setAiOnly(e.target.checked);
              setPage(1);
            }}
          >
            Made by AI
          </Checkbox>
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
          <Button aria-label="Reload audit log" icon={<ReloadOutlined />} onClick={load} />
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
          { title: 'Actor', width: 220, render: (_, r) => <ActorCell entry={r} /> },
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
