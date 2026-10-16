import { Card, Empty, Tag, Typography, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../api/client';
import DataGrid from '../components/DataGrid';

interface TableSummary {
  key: string;
  label: string;
  row_count: number;
  append_only: boolean;
  read_only: boolean;
  group: string;
  description: string;
}

// Every table the signed-in user may edit, grouped by domain, each opening in
// the shared inline-editable grid (click a cell, it saves itself).
export default function BulkDataPage() {
  const [tables, setTables] = useState<TableSummary[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api
      .get<TableSummary[]>('/api/bulk/tables')
      .then((t) => {
        setTables(t);
        if (t.length) setActive((a) => a ?? t[0].key);
      })
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Failed to load tables'))
      .finally(() => setLoaded(true));
  }, []);

  const groups = useMemo(() => {
    const out: [string, TableSummary[]][] = [];
    for (const t of tables) {
      const g = out.find(([name]) => name === t.group);
      if (g) g[1].push(t);
      else out.push([t.group, [t]]);
    }
    return out;
  }, [tables]);

  const setCount = useCallback(
    (n: number) => setTables((ts) => ts.map((t) => (t.key === active ? { ...t, row_count: n } : t))),
    [active],
  );

  const current = tables.find((t) => t.key === active);

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <Card size="small" style={{ flex: '1 1 220px', minWidth: 200, maxWidth: 260 }} title="Data Tables"
        styles={{ body: { padding: 8, maxHeight: '75vh', overflowY: 'auto' } }}>
        {groups.map(([group, items]) => (
          <div key={group} style={{ marginBottom: 10 }}>
            <div className="u-label" style={{ padding: '6px 8px 4px', opacity: 0.6 }}>{group}</div>
            {items.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setActive(t.key)}
                style={{
                  all: 'unset',
                  boxSizing: 'border-box',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 6,
                  width: '100%',
                  cursor: 'pointer',
                  padding: '5px 8px',
                  borderRadius: 6,
                  fontWeight: t.key === active ? 600 : 400,
                  background: t.key === active ? 'rgba(92,198,255,0.12)' : undefined,
                }}
              >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.label}</span>
                <Tag style={{ marginInlineEnd: 0 }}>{t.row_count}</Tag>
              </button>
            ))}
          </div>
        ))}
      </Card>

      <Card style={{ flex: 1, minWidth: 0 }}>
        {current ? (
          <DataGrid
            key={current.key}
            table={current.key}
            allowUpload
            reloadOnSave
            onCount={setCount}
            title={<Typography.Text strong style={{ fontSize: 16 }}>{current.label}</Typography.Text>}
          />
        ) : (
          loaded && <Empty description="You have no editable tables." />
        )}
      </Card>
    </div>
  );
}
