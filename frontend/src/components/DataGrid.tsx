import {
  CheckCircleFilled,
  DeleteOutlined,
  DownloadOutlined,
  ExclamationCircleFilled,
  LoadingOutlined,
  LockOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  DatePicker,
  Input,
  InputNumber,
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

// The inline-editable grid behind every bulk-editor table: click a cell to edit
// it, changes autosave (debounced) through POST /api/bulk/{table}. Used by the
// Data Tables page and embedded in feature pages (Finance) for one table each.

export interface ColumnMeta {
  name: string;
  label: string;
  type: string;
  editable: boolean;
  required: boolean;
  ref: string | null;
  choices: string[] | null;
}

type Option = { value: string | number; label: string };

export interface TablePayload {
  key: string;
  label: string;
  columns: ColumnMeta[];
  rows: Record<string, string>[];
  options: Record<string, Option[]>;
  append_only: boolean;
  delete: string;
  read_only: boolean;
  group: string;
  description: string;
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

const NUMBER_FMT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

interface Props {
  table: string;
  /** Show only rows whose column equals this value; new rows start with it.
   *  Those columns are hidden (they'd be the same on every row). */
  fixed?: Record<string, string>;
  /** Reload after every save — for tables with computed columns. */
  reloadOnSave?: boolean;
  /** Offer the Excel upload round-trip (download is always offered). */
  allowUpload?: boolean;
  /** Called after any successful write (e.g. to refresh a summary above). */
  onChanged?: () => void;
  /** Show the table's own description line. */
  showDescription?: boolean;
  /** Called with the row count after each load (e.g. for a sidebar badge). */
  onCount?: (n: number) => void;
  height?: string;
  title?: React.ReactNode;
}

export default function DataGrid({
  table,
  fixed,
  reloadOnSave = false,
  allowUpload = false,
  onChanged,
  showDescription = true,
  onCount,
  height = '58vh',
  title,
}: Props) {
  const [payload, setPayload] = useState<TablePayload | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [search, setSearch] = useState('');

  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [cellErrors, setCellErrors] = useState<Record<string, string>>({});
  const [tableErrors, setTableErrors] = useState<string[]>([]);
  const dirty = useRef<Set<string>>(new Set()); // _keys of edited existing rows
  const saveTimer = useRef<ReturnType<typeof setTimeout>>();
  const [editing, setEditing] = useState<{ key: string; col: string } | null>(null);

  const [uploading, setUploading] = useState(false);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const pendingFile = useRef<File | null>(null);
  const [alsoDelete, setAlsoDelete] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);

  const fixedKey = JSON.stringify(fixed ?? {});
  const matchesFixed = useCallback(
    (r: Record<string, unknown>) =>
      Object.entries(fixed ?? {}).every(([k, v]) => String(r[k] ?? '') === String(v)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fixedKey],
  );

  const applyPayload = useCallback(
    (p: TablePayload, keepDrafts: Row[] = []) => {
      setPayload(p);
      const shown = p.rows.filter(matchesFixed);
      setRows([...shown.map((r) => ({ ...r, _key: `id-${r.id}` }) as Row), ...keepDrafts]);
      onCount?.(shown.length);
    },
    [matchesFixed, onCount],
  );

  const load = useCallback(
    (keepDrafts: Row[] = []) =>
      api
        .get<TablePayload>(`/api/bulk/${table}`)
        .then((p) => applyPayload(p, keepDrafts))
        .catch((e) => message.error(e instanceof ApiError ? e.message : 'Failed to load table')),
    [table, applyPayload],
  );

  useEffect(() => {
    setLoading(true);
    dirty.current.clear();
    setCellErrors({});
    setTableErrors([]);
    setEditing(null);
    setSaveState('idle');
    setSearch('');
    load().finally(() => setLoading(false));
  }, [load]);

  const columns = useMemo(
    () => (payload?.columns ?? []).filter((c) => !(fixed && c.name in fixed)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [payload, fixedKey],
  );
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
    if (!payload) return;
    const toSend: Row[] = [];
    const sentKeys: string[] = [];
    for (const r of rows) {
      if (r._new ? rowComplete(r) : dirty.current.has(r._key)) {
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
      const res = await api.post<ApplyResult>(`/api/bulk/${table}`, {
        rows: toSend.map((r) => ({ ...stripMeta(r), ...(r._new ? fixed : {}) })),
        deletes: [],
      });
      if (res.ok) {
        sentKeys.forEach((k) => dirty.current.delete(k));
        setCellErrors({});
        setTableErrors([]);
        setSaveState('saved');
        // Adds get server-assigned ids (and computed columns recompute) —
        // reload, keeping any still-incomplete draft rows mid-typing.
        if (reloadOnSave || toSend.some((r) => r._new)) {
          await load(rows.filter((r) => r._new && !sentKeys.includes(r._key)));
        }
        onChanged?.();
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
  }, [payload, rows, rowComplete, table, fixed, reloadOnSave, load, onChanged]);

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
      if ((record[col.name] ?? '') === value) {
        setEditing(null);
        return;
      }
      setRows((rs) => rs.map((r) => (r._key === record._key ? { ...r, [col.name]: value } : r)));
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
    setSearch('');
    setSaveState('idle');
  }, [columns]);

  const removeNewRow = useCallback((key: string) => {
    setRows((rs) => rs.filter((r) => r._key !== key));
    dirty.current.delete(key);
  }, []);

  const deleteExisting = useCallback(
    async (record: Row) => {
      try {
        const res = await api.post<ApplyResult>(`/api/bulk/${table}`, {
          rows: [],
          deletes: [Number(record.id)],
        });
        if (res.ok) {
          setRows((rs) => rs.filter((r) => r._key !== record._key));
          message.success('Row deleted.');
          onChanged?.();
        } else {
          message.error(res.errors[0]?.message ?? 'Could not delete that row.');
        }
      } catch (e) {
        message.error(e instanceof ApiError ? e.message : 'Delete failed');
      }
    },
    [table, onChanged],
  );

  // --- Excel round-trip -----------------------------------------------------
  const download = () => {
    setDownloading(true);
    fetch(`/api/bulk/${table}/export.xlsx`, { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error('Download failed');
        return r.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${table}.xlsx`;
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
    if (!file) return;
    pendingFile.current = file;
    setAlsoDelete(false);
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    api
      .upload<UploadPreview>(`/api/bulk/${table}/upload`, form)
      .then((p) => setPreview(p))
      .catch((err) => message.error(err instanceof ApiError ? err.message : 'Could not read that file'))
      .finally(() => setUploading(false));
  };

  const applyUpload = async () => {
    const file = pendingFile.current;
    if (!file) return;
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await api.upload<UploadPreview>(
        `/api/bulk/${table}/upload?apply=true&delete_missing=${alsoDelete}`,
        form,
      );
      if (res.applied) {
        message.success(
          `Applied: ${res.new} added, ${res.changed} updated${res.will_delete ? `, ${res.will_delete} deleted` : ''}.`,
        );
        setPreview(null);
        pendingFile.current = null;
        await load();
        onChanged?.();
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

  const labelFor = useCallback(
    (col: ColumnMeta, value: string): string => {
      if (col.ref || col.choices) {
        const opt = optionsFor(col).find((o) => String(o.value) === String(value));
        return opt ? opt.label : value;
      }
      return value;
    },
    [optionsFor],
  );

  const displayValue = (col: ColumnMeta, value: string) => {
    if (value === '' || value == null) return <span style={{ opacity: 0.3 }}>—</span>;
    if (col.type === 'number' && !Number.isNaN(Number(value))) {
      return <span style={{ fontVariantNumeric: 'tabular-nums' }}>{NUMBER_FMT.format(Number(value))}</span>;
    }
    if (col.type === 'datetime') return dayjs(value).isValid() ? dayjs(value).format('YYYY-MM-DD HH:mm') : value;
    return labelFor(col, value);
  };

  const renderCell = (col: ColumnMeta, record: Row) => {
    const value = String(record[col.name] ?? '');
    const cellKey = `${record._key}:${col.name}`;
    const err = cellErrors[cellKey];
    const locked = !col.editable || (payload?.append_only && !record._new) || payload?.read_only;

    if (col.editable && !locked && col.type === 'bool') {
      return (
        <Switch
          size="small"
          checked={value === 'true' || value === '1'}
          onChange={(v) => commit(record, col, v ? 'true' : 'false')}
        />
      );
    }

    if (locked) {
      return (
        <div style={{ minHeight: 22, opacity: col.editable ? 1 : 0.75 }}>{displayValue(col, value)}</div>
      );
    }

    if (editing?.key === record._key && editing?.col === col.name) {
      if (col.ref || col.choices) {
        return (
          <Select
            autoFocus
            defaultOpen
            showSearch
            allowClear={!col.required}
            size="small"
            style={{ width: '100%', minWidth: 160 }}
            defaultValue={value === '' ? undefined : value}
            optionFilterProp="label"
            options={optionsFor(col).map((o) => ({ value: String(o.value), label: o.label }))}
            onChange={(v) => commit(record, col, v ?? '')}
            onBlur={() => setEditing(null)}
          />
        );
      }
      if (col.type === 'int' || col.type === 'number') {
        return (
          <InputNumber
            autoFocus
            size="small"
            style={{ width: '100%', minWidth: 90 }}
            precision={col.type === 'int' ? 0 : undefined}
            defaultValue={value === '' ? undefined : Number(value)}
            onBlur={(e) => commit(record, col, e.target.value.replace(/,/g, '').trim())}
            onPressEnter={(e) =>
              commit(record, col, (e.target as HTMLInputElement).value.replace(/,/g, '').trim())
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
            onOpenChange={(o) => !o && setEditing(null)}
          />
        );
      }
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
          {c.label} <span style={{ color: '#ff4d4f' }}>*</span>
        </span>
      ) : c.editable ? (
        c.label
      ) : (
        <Tooltip title="Computed — not editable">
          <span style={{ opacity: 0.7 }}>{c.label}</span>
        </Tooltip>
      ),
      dataIndex: c.name,
      key: c.name,
      width: c.name === 'id' ? 64 : c.type === 'bool' ? 80 : undefined,
      align: (c.type === 'number' || c.type === 'int') && c.name !== 'id' ? ('right' as const) : undefined,
      ellipsis: true,
      render: (_: unknown, record: Row) => renderCell(c, record),
    })),
    ...(payload?.read_only
      ? []
      : [
          {
            title: '',
            key: '_actions',
            width: 48,
            fixed: 'right' as const,
            render: (_: unknown, record: Row) => {
              if (record._new)
                return (
                  <Tooltip title="Discard this new row">
                    <Button type="text" size="small" icon={<DeleteOutlined />} onClick={() => removeNewRow(record._key)} />
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
        ]),
  ];

  const visibleRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r._new ||
        columns.some((c) => labelFor(c, String(r[c.name] ?? '')).toLowerCase().includes(q)),
    );
  }, [rows, search, columns, labelFor]);

  const draftCount = rows.filter((r) => r._new && !rowComplete(r)).length;

  const saveIndicator = () => {
    if (saveState === 'saving') return <Tag icon={<LoadingOutlined />} color="processing">Saving…</Tag>;
    if (saveState === 'saved') return <Tag icon={<CheckCircleFilled />} color="success">All changes saved</Tag>;
    if (saveState === 'error') return <Tag icon={<ExclamationCircleFilled />} color="error">Fix the highlighted cells</Tag>;
    return null;
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
        <Space size={8} wrap style={{ flex: 1, minWidth: 200 }}>
          {title}
          {saveIndicator()}
          {draftCount > 0 && <Tag color="warning">{draftCount} draft row(s) — fill the * cells to save</Tag>}
        </Space>
        <Space wrap>
          <Input
            allowClear
            size="middle"
            prefix={<SearchOutlined style={{ opacity: 0.5 }} />}
            placeholder="Search rows"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: 200 }}
          />
          {payload?.read_only ? (
            <Tag icon={<LockOutlined />}>Read-only</Tag>
          ) : (
            <Button icon={<PlusOutlined />} type="primary" onClick={addRow} disabled={!payload}>
              Add row
            </Button>
          )}
          <Tooltip title="Reload from the server">
            <Button icon={<ReloadOutlined />} onClick={() => void load()} />
          </Tooltip>
          <Tooltip title="Download as Excel">
            <Button icon={<DownloadOutlined />} loading={downloading} onClick={download} />
          </Tooltip>
          {allowUpload && payload && !payload.read_only && (
            <Tooltip title="Upload an edited .xlsx/.csv — it's diffed against the table and you confirm before anything changes">
              <Button icon={<UploadOutlined />} loading={uploading} onClick={() => fileInput.current?.click()}>
                Upload
              </Button>
            </Tooltip>
          )}
          <input ref={fileInput} type="file" accept=".xlsx,.xlsm,.csv" style={{ display: 'none' }} onChange={onPickFile} />
        </Space>
      </div>

      {showDescription && payload?.description && (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 10 }}>
          {payload.description}
        </Typography.Paragraph>
      )}

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
        loading={loading}
        columns={antdColumns}
        dataSource={visibleRows}
        rowKey="_key"
        rowClassName={(r) => (r._new ? 'bulk-new-row' : '')}
        scroll={{ x: 'max-content', y: height }}
        pagination={{
          defaultPageSize: 50,
          pageSizeOptions: [20, 50, 100, 200],
          showSizeChanger: true,
          size: 'small',
          showTotal: (n) => `${n} rows`,
        }}
      />

      <Modal
        open={preview != null}
        title="Review upload"
        okText={preview?.ok ? 'Apply changes' : 'OK'}
        okButtonProps={{ disabled: !preview?.ok, loading: uploading }}
        onOk={() => (preview?.ok ? applyUpload() : setPreview(null))}
        onCancel={() => setPreview(null)}
        confirmLoading={uploading}
      >
        {preview &&
          (preview.ok ? (
            <>
              <Typography.Paragraph>This file, diffed against the table:</Typography.Paragraph>
              <Space size={8} wrap style={{ marginBottom: 12 }}>
                <Tag color="success">{preview.new} new</Tag>
                <Tag color="processing">{preview.changed} changed</Tag>
                <Tag>{preview.unchanged} unchanged</Tag>
                {preview.can_delete && <Tag color="error">{preview.missing_ids.length} missing from file</Tag>}
              </Space>
              {preview.can_delete && preview.missing_ids.length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Switch checked={alsoDelete} onChange={setAlsoDelete} />
                  <span>
                    Also delete the {preview.missing_ids.length} row(s) that are in the table but missing from this file.
                  </span>
                </div>
              )}
              {preview.new === 0 && preview.changed === 0 && !alsoDelete && (
                <Alert type="info" showIcon style={{ marginTop: 12 }} message="Nothing to apply — the file matches the table." />
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
          ))}
      </Modal>
    </div>
  );
}
