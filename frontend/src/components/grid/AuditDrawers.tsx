import { RollbackOutlined } from '@ant-design/icons';
import { Button, Drawer, Empty, Spin, Tag, Timeline, Typography, message, theme } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../../api/client';
import { ColumnMeta, Option, displayText, optionsFor } from './sheet';

// The grid's two audit views: one row's change history, and the table's
// recycle bin of deleted rows (each restorable from the snapshot the delete
// left in the audit log).

interface Entry {
  id: number;
  action: 'create' | 'update' | 'delete' | 'restore';
  entity_id: number;
  actor: string | null;
  at: string | null;
  detail: {
    changes?: Record<string, [string, string]>;
    row?: Record<string, string>;
    policy?: string;
  };
}

interface Common {
  table: string;
  columns: ColumnMeta[];
  options: Record<string, Option[]> | undefined;
}

function useShow(columns: ColumnMeta[], options: Record<string, Option[]> | undefined) {
  return (name: string, value: string) => {
    const col = columns.find((c) => c.name === name);
    if (!col) return value;
    const text = displayText(col, value, optionsFor(col, options));
    return text === '' ? '∅' : text;
  };
}

const when = (at: string | null) => (at ? dayjs(at).format('YYYY-MM-DD HH:mm') : '');

export function RowHistory({ table, columns, options, rowId, onClose }: Common & { rowId: number | null; onClose: () => void }) {
  const { token } = theme.useToken();
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const show = useShow(columns, options);
  const label = (name: string) => columns.find((c) => c.name === name)?.label ?? name;

  useEffect(() => {
    if (rowId == null) return;
    setEntries(null);
    api
      .get<Entry[]>(`/api/bulk/${table}/${rowId}/history`)
      .then(setEntries)
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Could not load history'));
  }, [table, rowId]);

  return (
    <Drawer open={rowId != null} onClose={onClose} title={`History · row ${rowId ?? ''}`} width={440}>
      {!entries ? (
        <Spin />
      ) : !entries.length ? (
        <Empty description="No recorded changes yet (history starts with edits made after this feature shipped)." />
      ) : (
        <Timeline
          items={entries.map((e) => ({
            color: e.action === 'delete' ? 'red' : e.action === 'create' ? 'green' : e.action === 'restore' ? 'purple' : 'blue',
            children: (
              <div>
                <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                  {when(e.at)} · {e.actor ?? 'system'}
                </div>
                <div style={{ fontWeight: 600, textTransform: 'capitalize' }}>{e.action === 'create' ? 'Created' : e.action === 'update' ? 'Edited' : e.action === 'delete' ? 'Deleted' : 'Restored'}</div>
                {e.detail.changes &&
                  Object.entries(e.detail.changes).map(([col, [from, to]]) => (
                    <div key={col} style={{ fontSize: 13 }}>
                      <strong>{label(col)}</strong>: <span style={{ textDecoration: 'line-through', color: token.colorTextTertiary }}>{show(col, from)}</span> → {show(col, to)}
                    </div>
                  ))}
              </div>
            ),
          }))}
        />
      )}
    </Drawer>
  );
}

export function RecycleBin({ table, columns, options, open, onClose, onRestored }: Common & { open: boolean; onClose: () => void; onRestored: () => void }) {
  const { token } = theme.useToken();
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const show = useShow(columns, options);

  const load = () => {
    setEntries(null);
    api
      .get<Entry[]>(`/api/bulk/${table}/trash`)
      .then(setEntries)
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Could not load the recycle bin'));
  };
  useEffect(() => {
    if (open) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, table]);

  const restore = async (e: Entry) => {
    setBusy(e.id);
    try {
      await api.post(`/api/bulk/${table}/restore/${e.id}`, {});
      message.success(`Row ${e.entity_id} restored.`);
      onRestored();
      load();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : 'Restore failed');
    } finally {
      setBusy(null);
    }
  };

  // the first few meaningful columns make the row recognisable
  const preview = columns.filter((c) => c.editable).slice(0, 4);

  return (
    <Drawer open={open} onClose={onClose} title="Recycle bin" width={480}>
      <Typography.Paragraph type="secondary">Rows deleted from this table. Restoring puts the row back exactly as it was.</Typography.Paragraph>
      {!entries ? (
        <Spin />
      ) : !entries.length ? (
        <Empty description="Nothing deleted" />
      ) : (
        entries.map((e) => (
          <div key={e.id} style={{ border: `1px solid ${token.colorBorderSecondary}`, borderRadius: 8, padding: 10, marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                Row {e.entity_id} · {when(e.at)} · {e.actor ?? 'system'}
                {e.detail.policy && e.detail.policy !== 'hard' && <Tag style={{ marginLeft: 6 }}>{e.detail.policy === 'soft' ? 'archived' : 'deactivated'}</Tag>}
              </div>
              <Button size="small" icon={<RollbackOutlined />} loading={busy === e.id} onClick={() => void restore(e)}>
                Restore
              </Button>
            </div>
            <div style={{ fontSize: 13, marginTop: 4 }}>
              {preview.map((c) => (
                <div key={c.name} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  <span style={{ color: token.colorTextTertiary }}>{c.label}:</span> {show(c.name, e.detail.row?.[c.name] ?? '')}
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </Drawer>
  );
}
