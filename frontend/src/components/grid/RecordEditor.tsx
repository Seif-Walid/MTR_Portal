import { ExclamationCircleFilled, LoadingOutlined, LockOutlined } from '@ant-design/icons';
import { Skeleton, message, theme } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';

import { api, ApiError } from '../../api/client';
import CellEditor, { Commit, EditorRect, Move } from './CellEditor';
import { ApplyResult, TablePayload, displayText, isNumeric, optionsFor, parseInput } from './sheet';

// One record's fields as editable cells — the same editors and keyboard as the
// sheet (type to replace, Enter/F2 to edit, Tab to move on, Delete to clear),
// laid out as a form. Each change saves on its own.

export default function RecordEditor({ table, id, onSaved }: { table: string; id: number; onSaved?: () => void }) {
  const { token } = theme.useToken();
  const [payload, setPayload] = useState<TablePayload | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<{ c: number; seed: string | null; rect: EditorRect } | null>(null);
  const boxes = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    api
      .get<TablePayload>(`/api/bulk/${table}`)
      .then(setPayload)
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Failed to load'));
  }, [table]);

  const row = payload?.rows.find((r) => String(r.id) === String(id));
  const cols = (payload?.columns ?? []).filter((c) => c.name !== 'id');
  const lockedAt = (i: number) => !cols[i]?.editable || !!payload?.read_only || !!payload?.append_only;

  const save = useCallback(
    async (col: string, value: string) => {
      if (!payload || !row || (row[col] ?? '') === value) return;
      setPayload({ ...payload, rows: payload.rows.map((r) => (r === row ? { ...r, [col]: value } : r)) });
      setSaving((s) => new Set(s).add(col));
      try {
        const res = await api.post<ApplyResult>(`/api/bulk/${table}`, {
          rows: [{ id: String(id), [col]: value, _base: { [col]: row[col] ?? '' } }],
          deletes: [],
          partial: true,
          return_rows: true,
        });
        setErrors((e) => {
          const next = { ...e };
          delete next[col];
          for (const er of res.errors)
            next[er.column ?? col] =
              er.code === 'conflict' ? `${er.by ?? 'Someone'} changed this meanwhile — now showing their value; edit again to overwrite.` : er.message;
          return next;
        });
        if (res.rows) setPayload((p) => (p ? { ...p, rows: res.rows! } : p));
        if (!res.errors.length) onSaved?.();
      } catch (e) {
        setErrors((er) => ({ ...er, [col]: e instanceof ApiError ? e.message : 'Save failed' }));
      } finally {
        setSaving((s) => {
          const next = new Set(s);
          next.delete(col);
          return next;
        });
      }
    },
    [payload, row, table, id, onSaved],
  );

  if (!payload) return <Skeleton active paragraph={{ rows: 4 }} />;
  if (!row) return <div style={{ color: token.colorTextTertiary }}>This record isn’t in the editable table.</div>;

  const start = (i: number, seed: string | null) => {
    if (lockedAt(i)) return;
    const col = cols[i];
    if (col.type === 'bool') {
      void save(col.name, row[col.name] === 'true' ? 'false' : 'true');
      return;
    }
    const b = boxes.current[i]?.getBoundingClientRect();
    if (b) setEditing({ c: i, seed, rect: { left: b.left, top: b.top, width: b.width, height: b.height } });
  };

  const commit = (c: Commit, move: Move) => {
    if (!editing) return;
    const col = cols[editing.c];
    if (c.kind === 'value') void save(col.name, c.value);
    else {
      const p = parseInput(col, c.text, optionsFor(col, payload.options));
      if (p.ok) void save(col.name, p.value);
      else setErrors((e) => ({ ...e, [col.name]: p.error }));
    }
    const i = editing.c;
    setEditing(null);
    const next = move === 'right' || move === 'down' ? i + 1 : move === 'left' || move === 'up' ? i - 1 : i;
    setTimeout(() => boxes.current[Math.max(0, Math.min(cols.length - 1, next))]?.focus(), 0);
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(240px, 100%), 1fr))', gap: '10px 14px' }}>
      {cols.map((col, i) => {
        const value = row[col.name] ?? '';
        const err = errors[col.name];
        const isLocked = lockedAt(i);
        const opts = optionsFor(col, payload.options);
        return (
          <div key={col.name} style={{ minWidth: 0 }}>
            <div style={{ fontSize: 12, color: token.colorTextSecondary, marginBottom: 3, display: 'flex', gap: 4, alignItems: 'center' }}>
              {isLocked && <LockOutlined style={{ fontSize: 10, opacity: 0.6 }} />}
              <span>{col.label}</span>
              {col.required && !isLocked && <span style={{ color: token.colorError }}>*</span>}
              {saving.has(col.name) && <LoadingOutlined style={{ fontSize: 10 }} />}
            </div>
            <div
              ref={(el) => (boxes.current[i] = el)}
              tabIndex={0}
              title={err}
              onClick={() => start(i, null)}
              onKeyDown={(e) => {
                if (editing) return;
                if (e.key === 'Enter' || e.key === 'F2' || (e.key === ' ' && col.type === 'bool')) {
                  e.preventDefault();
                  start(i, null);
                } else if ((e.key === 'Delete' || e.key === 'Backspace') && !isLocked) {
                  e.preventDefault();
                  void save(col.name, col.type === 'bool' ? 'false' : '');
                } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && col.type !== 'bool') {
                  e.preventDefault();
                  start(i, e.key);
                }
              }}
              style={{
                minHeight: 32,
                padding: '5px 8px',
                borderRadius: 6,
                border: `1px solid ${err ? token.colorError : token.colorBorderSecondary}`,
                background: err ? token.colorErrorBg : isLocked ? token.colorFillQuaternary : token.colorBgContainer,
                color: isLocked ? token.colorTextSecondary : token.colorText,
                cursor: isLocked ? 'default' : col.type === 'bool' ? 'pointer' : 'text',
                textAlign: isNumeric(col) ? 'right' : 'left',
                fontVariantNumeric: 'tabular-nums',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                outlineColor: token.colorPrimary,
              }}
            >
              {col.type === 'bool' ? (
                <input type="checkbox" checked={value === 'true'} readOnly tabIndex={-1} disabled={isLocked} style={{ margin: 0, pointerEvents: 'none' }} />
              ) : value === '' ? (
                <span style={{ color: token.colorTextQuaternary }}>—</span>
              ) : (
                displayText(col, value, opts)
              )}
            </div>
            {err && (
              <div style={{ fontSize: 12, color: token.colorError, marginTop: 2 }}>
                <ExclamationCircleFilled /> {err}
              </div>
            )}
          </div>
        );
      })}
      {editing && (
        <CellEditor
          col={cols[editing.c]}
          opts={optionsFor(cols[editing.c], payload.options)}
          value={row[cols[editing.c].name] ?? ''}
          seed={editing.seed}
          rect={editing.rect}
          onCommit={commit}
          onCancel={() => {
            const i = editing.c;
            setEditing(null);
            setTimeout(() => boxes.current[i]?.focus(), 0);
          }}
        />
      )}
    </div>
  );
}
