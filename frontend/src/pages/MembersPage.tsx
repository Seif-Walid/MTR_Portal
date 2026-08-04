import { Descriptions, Input, Table, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useMemo, useState } from 'react';

import { api } from '../api/client';
import type { Member } from '../api/types';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

const dash = (v: string | number | null | undefined) =>
  v === null || v === undefined || v === '' ? <Typography.Text type="secondary">—</Typography.Text> : v;

export default function MembersPage() {
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  useEffect(() => {
    api.get<Member[]>('/api/users/members').then(setMembers).catch((e) => message.error(e.message)).finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return members;
    return members.filter((m) => {
      const p = m.profile;
      return [m.full_name, m.email, p?.mtr_id, p?.university, p?.college, p?.major, p?.location, p?.phone]
        .filter(Boolean).some((f) => String(f).toLowerCase().includes(q));
    });
  }, [members, query]);

  const columns: ColumnsType<Member> = [
    {
      title: 'MTR ID', dataIndex: ['profile', 'mtr_id'], width: 110,
      sorter: (a, b) => (a.profile?.mtr_id ?? '').localeCompare(b.profile?.mtr_id ?? ''),
      render: (v) => (v ? <span style={{ fontFamily: MONO, fontSize: 12, color: '#5cc6ff', letterSpacing: '.04em' }}>{v}</span> : dash(v)),
    },
    {
      title: 'Name', dataIndex: 'full_name', sorter: (a, b) => a.full_name.localeCompare(b.full_name),
      render: (v: string, m) => (
        <div style={{ lineHeight: 1.3 }}>
          <div style={{ color: '#eaf2ff' }}>{v}</div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{m.email}</Typography.Text>
        </div>
      ),
    },
    {
      title: 'University', dataIndex: ['profile', 'university'], width: 110, render: (v) => dash(v),
      filters: Array.from(new Set(members.map((m) => m.profile?.university).filter(Boolean) as string[])).sort().map((u) => ({ text: u, value: u })),
      onFilter: (value, m) => m.profile?.university === value,
    },
    { title: 'College', dataIndex: ['profile', 'college'], width: 130, render: (v) => dash(v) },
    { title: 'Major', dataIndex: ['profile', 'major'], width: 110, render: (v) => dash(v) },
    {
      title: 'Grad year', dataIndex: ['profile', 'graduating_year'], width: 100, align: 'center',
      sorter: (a, b) => (a.profile?.graduating_year ?? 0) - (b.profile?.graduating_year ?? 0), render: (v) => dash(v),
    },
    { title: 'Phone', dataIndex: ['profile', 'phone'], width: 130, render: (v) => dash(v) },
    { title: 'Location', dataIndex: ['profile', 'location'], width: 120, render: (v) => dash(v) },
    {
      title: 'Level', dataIndex: 'level', width: 110,
      render: (v: string | null) => (
        <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.06em', textTransform: 'uppercase', color: v ? '#5cc6ff' : 'rgba(224,236,252,.5)', border: `1px solid ${v ? 'rgba(92,198,255,.3)' : 'rgba(120,170,230,.18)'}`, background: v ? 'rgba(92,198,255,.08)' : 'transparent', padding: '3px 9px', borderRadius: 5 }}>{v ?? 'Guest'}</span>
      ),
      filters: Array.from(new Set(members.map((m) => m.level ?? 'Guest'))).sort().map((l) => ({ text: l, value: l })),
      onFilter: (value, m) => (m.level ?? 'Guest') === value,
    },
  ];

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <div>
          <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>Members</h2>
          <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: '.08em', color: 'rgba(224,236,252,.45)', marginTop: 6 }}>
            {members.length} MEMBER{members.length === 1 ? '' : 'S'} IN DIRECTORY
          </div>
        </div>
        <Input.Search allowClear placeholder="Search name, email, MTR ID, major, university…"
          onChange={(e) => setQuery(e.target.value)} style={{ width: 340, maxWidth: '100%' }} />
      </div>
      <div style={{ border: '1px solid rgba(120,170,230,.12)', borderRadius: 12, overflow: 'hidden', background: 'rgba(15,20,29,.5)' }}>
        <Table<Member> className="circuit-table" rowKey="id" size="small" loading={loading} columns={columns}
          dataSource={filtered} scroll={{ x: 'max-content' }}
          pagination={{ defaultPageSize: 20, showSizeChanger: true, showTotal: (t) => `${t} shown` }}
          expandable={{
            expandedRowRender: (m) => (
              <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} bordered>
                <Descriptions.Item label="National ID">{dash(m.profile?.national_id)}</Descriptions.Item>
                <Descriptions.Item label="Birthday">{dash(m.profile?.birthday)}</Descriptions.Item>
                <Descriptions.Item label="UNI ID">{dash(m.profile?.uni_id)}</Descriptions.Item>
                <Descriptions.Item label="Dad's number">{dash(m.profile?.father_phone)}</Descriptions.Item>
                <Descriptions.Item label="Mom's number">{dash(m.profile?.mother_phone)}</Descriptions.Item>
                <Descriptions.Item label="Active">{m.is_active ? 'Yes' : 'No'}</Descriptions.Item>
              </Descriptions>
            ),
            rowExpandable: (m) => m.profile !== null,
          }} />
      </div>
    </>
  );
}
