import {
  CheckCircleFilled,
  DeleteOutlined,
  DownloadOutlined,
  ExclamationCircleFilled,
  LoadingOutlined,
  LockOutlined,
  PlusOutlined,
  ReloadOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { api, ApiError } from '../api/client';

interface ColumnMeta {
  name: string;
  type: string;
  editable: boolean;
  required: boolean;
  ref: string | null;
  choices: string[] | null;
}

interface TableSummary {
  key: string;
  label: string;
  row_count: number;
  append_only: boolean;
  read_only: boolean;
}

type Option = { value: string | number; label: string };

interface TablePayload {
  key: string;
  label: string;
  columns: ColumnMeta[];
  rows: Record<string, string>[];
  options: Record<string, Option[]>;
  append_only: boolean;
  delete: string;
  read_only: boolean;
}

interface ApplyResult {
  ok: boolean;
  errors: { row: number | null; column: string | null; message: string }[];
  summary: { adds: number; updates: number; deletes: number };
}

interface UploadPreview {
  applied: boolean;
  ok: boolean;
  errors: { row: number | null; column: string | null; message: string }[];
  new: number;
  changed: number;
  unchanged: number;
  missing_ids: number[];
  can_delete: boolean;
  will_delete: number;
}

// One editable grid row. `_key` is a stable client id; `_new` marks a row that
// hasn't been inserted yet (id blank). Column cells are always stored as strings.
interface Row {
  _key: string;
  _new?: boolean;
  [col: string]: string | boolean | undefined;
}

let NEW_SEQ = 0;

const stripMeta = (r: Row): Record<string, string> => {
  const { _key, _new, ...rest } = r;
  void _key;
  void _new;
  return rest as Record<string, string>;
};

export default function BulkDataPage() {
  const [tables, setTables] = useState<TableSummary[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [payload, setPayload] = useState<TablePayload | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  // save state
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [cellErrors, setCellErrors] = useState<Record<string, string>>({});
  const [tableErrors, setTableErrors] = useState<string[]>([]);
  const dirty = useRef<Set<string>>(new Set()); // _keys of edited existing rows
  const saveTimer = useRef<ReturnType<typeof setTimeout>>();

  // one-cell-at-a-time editing
  const [editing, setEditing] = useState<{ key: string; col: string } | null>(null);

  // Excel upload (download → edit → upload, diffed against the DB)
  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const pendingFile = useRef<File | null>(null);
  const [alsoDelete, setAlsoDelete] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    api
      .get<TableSummary[]>('/api/bulk/tables')
      .then((t) => {
        setTables(t);
        if (t.length) setActive((a) => a ?? t[0].key);
      })
      .catch((e) => message.error(e instanceof ApiError ? e.message : 'Failed to load tables'));
  }, []);

  const applyPayload = useCallback((p: TablePayload, keepDrafts: Row[] = []) => {
    setPayload(p);
    setRows([
      ...p.rows.map((r) => ({ ...r, _key: `id-${r.id}` }) as Row),
      ...keepDrafts,
    ]);
  }, []);

  const loadTable = useCallback(
    (key: string) => {
      setLoading(true);
      dirty.current.clear();
      setCellErrors({});
      setTableErrors([]);
      setEditing(null);
      setSaveState('idle');
      api
        .get<TablePayload>(`/api/bulk/${key}`)
        .then((p) => applyPayload(p))
        .catch((e) => message.error(e instanceof ApiError ? e.message : 'Failed to load table'))
        .finally(() => setLoading(false));
    },
    [applyPayload],
  );

  useEffect(() => {
    if (active) loadTable(active);
  }, [active, loadTable]);

  const columns = payload?.columns ?? [];
  const requiredCols = useMemo(
    () => columns.filter((c) => c.editable && c.required).map((c) => c.name),
    [columns],
  );
  const rowComplete = useCallback(
    (r: Row) => requiredCols.every((c) => (r[c] ?? '').toString().trim() !== ''),
    [requiredCols],
  );

  // --- saving ---------------------------------------------------------------
  const doSave = useCallback(async () => {
    if (!active || !payload) return;
    const toSend: Row[] = [];
    const sentKeys: string[] = [];
    for (const r of rows) {
      if (r._new) {
        if (rowComplete(r)) {
          toSend.push(r);
          sentKeys.push(r._key);
        }
      } else if (dirty.current.has(r._key)) {
        toSend.push(r);
        sentKeys.push(r._key);
      }
    }
    if (!toSend.length) {
      setSaveState('idle');
      return;
    }

    setSaveState('saving');
    try {
      const res = await api.post<ApplyResult>(`/api/bulk/${active}`, {
        rows: toSend.map(stripMeta),
        deletes: [],
      });
      if (res.ok) {
        sentKeys.forEach((k) => dirty.current.delete(k));
        setCellErrors({});
        setTableErrors([]);
        setSaveState('saved');
        // Adds get server-assigned ids — reload to pick them up, but keep any
        // still-incomplete draft rows the user is mid-typing.
        const drafts = rows.filter((r) => r._new && !sentKeys.includes(r._key));
        const hadAdds = toSend.some((r) => r._new);
        if (hadAdds) {
          const p = await api.get<TablePayload>(`/api/bulk/${active}`);
          applyPayload(p, drafts);
          setTables((ts) =>
            ts.map((t) => (t.key === active ? { ...t, row_count: p.rows.length } : t)),
          );
        }
      } else {
        const ce: Record<string, string> = {};
        const te: string[] = [];
        for (const e of res.errors) {
          if (e.row != null && e.column) ce[`${sentKeys[e.row]}:${e.column}`] = e.message;
          else te.push(e.message);
        }
        setCellErrors(ce);
        setTableErrors(te);
        setSaveState('error');
      }
    } catch (e) {
      setTableErrors([e instanceof ApiError ? e.message : 'Save failed']);
      setSaveState('error');
    }
  }, [active, payload, rows, rowComplete, applyPayload]);

  // Keep the debounce timer pointed at the freshest doSave (it closes over the
  // current `rows`), while scheduleSave itself stays a stable callback.
  const doSaveRef = useRef(doSave);
  doSaveRef.current = doSave;
  const scheduleSave = useCallback(() => {
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void doSaveRef.current(), 800);
  }, []);

  const commit = useCallback(
    (record: Row, col: ColumnMeta, value: string) => {
      // No-op if the value didn't change (e.g. click a cell then click away).
      // Don't mark dirty or schedule a save for that.
      if ((record[col.name] ?? '') === value) {
        setEditing(null);
        return;
      }
      setRows((rs) =>
        rs.map((r) => (r._key === record._key ? { ...r, [col.name]: value } : r)),
      );
      if (!record._new) dirty.current.add(record._key);
      setCellErrors((ce) => {
        const k = `${record._key}:${col.name}`;
        if (!ce[k]) return ce;
        const next = { ...ce };
        delete next[k];
        return next;
      });
      setEditing(null);
      scheduleSave();
    },
    [scheduleSave],
  );

  const addRow = useCallback(() => {
    const blank: Row = { _key: `new-${++NEW_SEQ}`, _new: true, id: '' };
    for (const c of columns) if (c.editable) blank[c.name] = c.type === 'bool' ? 'false' : '';
    setRows((rs) => [...rs, blank]);
    setSaveState('idle');
  }, [columns]);

  const removeNewRow = useCallback((key: string) => {
    setRows((rs) => rs.filter((r) => r._key !== key));
    dirty.current.delete(key);
  }, []);

  const deleteExisting = useCallback(
    async (record: Row) => {
      if (!active) return;
      try {
        const res = await api.post<ApplyResult>(`/api/bulk/${active}`, {
          rows: [],
          deletes: [Number(record.id)],
        });
        if (res.ok) {
          setRows((rs) => rs.filter((r) => r._key !== record._key));
          setTables((ts) =>
            ts.map((t) => (t.key === active ? { ...t, row_count: Math.max(0, t.row_count - 1) } : t)),
          );
          message.success('Row deleted.');
        } else {
          message.error(res.errors[0]?.message ?? 'Could not delete that row.');
        }
      } catch (e) {
        message.error(e instanceof ApiError ? e.message : 'Delete failed');
      }
    },
    [active],
  );

  // --- Excel / Sheets escape hatch ------------------------------------------
  const download = () => {
    if (!active) return;
    setDownloading(true);
    fetch(`/api/bulk/${active}/export.xlsx`, { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error('Download failed');
        return r.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${active}.xlsx`;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => message.error(e.message))
      .finally(() => setDownloading(false));
  };

  // Upload an edited .xlsx/.csv: first previews the diff against the DB
  // (apply=false), then a confirm step commits it (apply=true).
  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // let the same file be re-picked later
    if (!file || !active) return;
    pendingFile.current = file;
    setAlsoDelete(false);
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    api
      .upload<UploadPreview>(`/api/bulk/${active}/upload`, form)
      .then((p) => setPreview(p))
      .catch((err) => message.error(err instanceof ApiError ? err.message : 'Could not read that file'))
      .finally(() => setUploading(false));
  };

  const applyUpload = async () => {
    const file = pendingFile.current;
    if (!active || !file) return;
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await api.upload<UploadPreview>(
        `/api/bulk/${active}/upload?apply=true&delete_missing=${alsoDelete}`,
        form,
      );
      if (res.applied) {
        message.success(
          `Applied: ${res.new} added, ${res.changed} updated${res.will_delete ? `, ${res.will_delete} deleted` : ''}.`,
        );
        setPreview(null);
        pendingFile.current = null;
        loadTable(active);
      } else {
        message.error(res.errors?.[0]?.message ?? 'The file has invalid data — fix it and re-upload.');
      }
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  // --- cell rendering -------------------------------------------------------
  const optionsFor = useCallback(
    (col: ColumnMeta): Option[] => {
      if (col.ref) return payload?.options[col.name] ?? [];
      if (col.choices) return col.choices.map((c) => ({ value: c, label: c }));
      return [];
    },
    [payload],
  );

  const displayValue = useCallback(
    (col: ColumnMeta, value: string) => {
      if (value === '' || value == null)
        return <span style={{ opacity: 0.3 }}>—</span>;
      if (col.ref || col.choices) {
        const opt = optionsFor(col).find((o) => String(o.value) === String(value));
        return opt ? opt.label : value;
      }
      return value;
    },
    [optionsFor],
  );

  const renderCell = (col: ColumnMeta, record: Row) => {
    const value = String(record[col.name] ?? '');
    const cellKey = `${record._key}:${col.name}`;
    const err = cellErrors[cellKey];
    const locked = !col.editable || (payload?.append_only && !record._new);

    // bool -> always-on switch
    if (col.editable && !locked && col.type === 'bool') {
      return (
        <Switch
          size="small"
          checked={value === 'true' || value === '1'}
          onChange={(v) => commit(record, col, v ? 'true' : 'false')}
        />
      );
    }

    const isEditing = editing?.key === record._key && editing?.col === col.name;

    if (locked) {
      return <div style={{ minHeight: 22 }}>{displayValue(col, value)}</div>;
    }

    if (isEditing) {
      // select (ref or fixed choices)
      if (col.ref || col.choices) {
        return (
          <Select
            autoFocus
            defaultOpen
            showSearch
            allowClear={!col.required}
            size="small"
            style={{ width: '100%', minWidth: 140 }}
            defaultValue={value === '' ? undefined : value}
            optionFilterProp="label"
            options={optionsFor(col).map((o) => ({ value: String(o.value), label: o.label }))}
            onChange={(v) => commit(record, col, v ?? '')}
            onBlur={() => setEditing(null)}
          />
        );
      }
      if (col.type === 'int') {
        return (
          <InputNumber
            autoFocus
            size="small"
            style={{ width: '100%' }}
            defaultValue={value === '' ? undefined : Number(value)}
            onBlur={(e) => commit(record, col, e.target.value.trim())}
            onPressEnter={(e) =>
              commit(record, col, (e.target as HTMLInputElement).value.trim())
            }
          />
        );
      }
      if (col.type === 'date') {
        return (
          <DatePicker
            autoFocus
            open
            size="small"
            style={{ width: '100%' }}
            defaultValue={value ? dayjs(value) : undefined}
            onChange={(d) => commit(record, col, d ? d.format('YYYY-MM-DD') : '')}
          />
        );
      }
      // plain text
      return (
        <Input
          autoFocus
          size="small"
          defaultValue={value}
          onBlur={(e) => commit(record, col, e.target.value)}
          onPressEnter={(e) => commit(record, col, (e.target as HTMLInputElement).value)}
        />
      );
    }

    // resting cell — click to edit
    return (
      <Tooltip title={err} open={err ? undefined : false}>
        <div
          onClick={() => setEditing({ key: record._key, col: col.name })}
          style={{
            minHeight: 22,
            cursor: 'text',
            padding: '1px 4px',
            borderRadius: 4,
            border: err ? '1px solid #ff4d4f' : '1px solid transparent',
            background: err ? 'rgba(255,77,79,0.08)' : undefined,
          }}
        >
          {displayValue(col, value)}
        </div>
      </Tooltip>
    );
  };

  const antdColumns = [
    ...columns.map((c) => ({
      title: c.required ? (
        <span>
          {c.name} <span style={{ color: '#ff4d4f' }}>*</span>
        </span>
      ) : (
        c.name
      ),
      dataIndex: c.name,
      key: c.name,
      width: c.name === 'id' ? 70 : c.type === 'bool' ? 90 : undefined,
      ellipsis: true,
      render: (_: unknown, record: Row) => renderCell(c, record),
    })),
    {
      title: '',
      key: '_actions',
      width: 48,
      fixed: 'right' as const,
      render: (_: unknown, record: Row) => {
        if (record._new)
          return (
            <Tooltip title="Discard this new row">
              <Button
                type="text"
                size="small"
                icon={<DeleteOutlined />}
                onClick={() => removeNewRow(record._key)}
              />
            </Tooltip>
          );
        if (payload?.delete === 'none' || payload?.append_only) return null;
        return (
          <Popconfirm
            title="Delete this row?"
            description={
              payload?.delete === 'deactivate'
                ? 'It will be deactivated.'
                : payload?.delete === 'soft'
                  ? 'It will be archived (soft-deleted).'
                  : 'This permanently removes the row.'
            }
            okText="Delete"
            okButtonProps={{ danger: true }}
            onConfirm={() => deleteExisting(record)}
          >
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        );
      },
    },
  ];

  const draftCount = rows.filter((r) => r._new && !rowComplete(r)).length;

  const saveIndicator = () => {
    if (saveState === 'saving')
      return (
        <Tag icon={<LoadingOutlined />} color="processing">
          Saving…
        </Tag>
      );
    if (saveState === 'saved')
      return (
        <Tag icon={<CheckCircleFilled />} color="success">
          All changes saved
        </Tag>
      );
    if (saveState === 'error')
      return (
        <Tag icon={<ExclamationCircleFilled />} color="error">
          Fix the highlighted cells
        </Tag>
      );
    return null;
  };

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      <Card size="small" style={{ width: 240, flexShrink: 0 }} title="Data Tables">
        <List
          size="small"
          dataSource={tables}
          renderItem={(t) => (
            <List.Item
              onClick={() => setActive(t.key)}
              style={{
                cursor: 'pointer',
                fontWeight: t.key === active ? 600 : 400,
                background: t.key === active ? 'rgba(92,198,255,0.12)' : undefined,
                borderRadius: 6,
                paddingInline: 8,
              }}
            >
              <Space size={4} style={{ justifyContent: 'space-between', width: '100%' }}>
                <span>{t.label}</span>
                <Tag>{t.row_count}</Tag>
              </Space>
            </List.Item>
          )}
        />
      </Card>

      <Card
        style={{ flex: 1, minWidth: 0 }}
        loading={loading}
        title={
          <Space>
            {payload?.label ?? 'Select a table'}
            {saveIndicator()}
          </Space>
        }
        extra={
          payload && (
            <Space wrap>
              {payload.read_only ? (
                <Tag icon={<LockOutlined />} color="default">
                  Read-only
                </Tag>
              ) : (
                <Button icon={<PlusOutlined />} type="primary" onClick={addRow}>
                  Add row
                </Button>
              )}
              <Button icon={<ReloadOutlined />} onClick={() => active && loadTable(active)}>
                Refresh
              </Button>
              <Button icon={<DownloadOutlined />} loading={downloading} onClick={download}>
                Download Excel
              </Button>
              {!payload.read_only && (
                <Tooltip title="Upload an edited .xlsx/.csv — it's diffed against the table and you confirm before anything changes">
                  <Button
                    icon={<UploadOutlined />}
                    loading={uploading}
                    onClick={() => fileInput.current?.click()}
                  >
                    Upload Excel
                  </Button>
                </Tooltip>
              )}
              <input
                ref={fileInput}
                type="file"
                accept=".xlsx,.xlsm,.csv"
                style={{ display: 'none' }}
                onChange={onPickFile}
              />
            </Space>
          )
        }
      >
        {payload ? (
          <>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              {payload.read_only ? (
                <>
                  Read-only view of the <code>{payload.key}</code> table — shown
                  for inspection only (no editing). Download Excel to export it.
                  Showing up to 2000 rows.
                </>
              ) : (
                <>
                  Click any cell to edit it — changes save automatically. Or
                  Download Excel, edit it offline, and Upload it back: the file is
                  diffed against the table and you confirm the adds, updates and
                  deletes before anything is written.
                </>
              )}
              {!payload.read_only && payload.append_only && (
                <> This is an append-only ledger: you can add rows, but existing rows are locked.</>
              )}
              {draftCount > 0 && (
                <>
                  {' '}
                  <Tag color="warning" style={{ marginLeft: 4 }}>
                    {draftCount} draft row(s) — fill the required (*) cells to save
                  </Tag>
                </>
              )}
            </Typography.Paragraph>

            {tableErrors.length > 0 && (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 12 }}
                message="Some changes couldn't be saved"
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {tableErrors.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                }
              />
            )}

            <Table<Row>
              size="small"
              columns={antdColumns}
              dataSource={rows}
              rowKey="_key"
              rowClassName={(r) => (r._new ? 'bulk-new-row' : '')}
              scroll={{ x: 'max-content', y: '58vh' }}
              pagination={{
                defaultPageSize: 50,
                pageSizeOptions: [10, 20, 50, 100, 200],
                showSizeChanger: true,
                size: 'small',
              }}
            />
          </>
        ) : (
          !loading && <Empty description="You have no editable tables." />
        )}
      </Card>

      <Modal
        open={preview != null}
        title="Review upload"
        okText={preview?.ok ? 'Apply changes' : 'OK'}
        okButtonProps={{ disabled: !preview?.ok, loading: uploading }}
        onOk={() => (preview?.ok ? applyUpload() : setPreview(null))}
        onCancel={() => setPreview(null)}
        confirmLoading={uploading}
      >
        {preview && (
          <>
            {preview.ok ? (
              <>
                <Typography.Paragraph>
                  This file, diffed against the table:
                </Typography.Paragraph>
                <Space size={8} wrap style={{ marginBottom: 12 }}>
                  <Tag color="success">{preview.new} new</Tag>
                  <Tag color="processing">{preview.changed} changed</Tag>
                  <Tag>{preview.unchanged} unchanged</Tag>
                  {preview.can_delete && (
                    <Tag color="error">{preview.missing_ids.length} missing from file</Tag>
                  )}
                </Space>
                {preview.can_delete && preview.missing_ids.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Switch checked={alsoDelete} onChange={setAlsoDelete} />
                    <span>
                      Also delete the {preview.missing_ids.length} row(s) that are in the table
                      but missing from this file.
                    </span>
                  </div>
                )}
                {preview.new === 0 && preview.changed === 0 && !alsoDelete && (
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginTop: 12 }}
                    message="Nothing to apply — the file matches the table."
                  />
                )}
              </>
            ) : (
              <Alert
                type="error"
                showIcon
                message="The file has problems — nothing will be written"
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {preview.errors.slice(0, 20).map((e, i) => (
                      <li key={i}>
                        {e.row != null ? `Row ${e.row + 1}: ` : ''}
                        {e.column ? `${e.column} — ` : ''}
                        {e.message}
                      </li>
                    ))}
                  </ul>
                }
              />
            )}
          </>
        )}
      </Modal>
    </div>
  );
}
