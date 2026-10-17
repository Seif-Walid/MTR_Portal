import {
  CheckCircleFilled,
  DeleteOutlined,
  RestOutlined,
  DownloadOutlined,
  ExclamationCircleFilled,
  ExportOutlined,
  LoadingOutlined,
  LockOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  RedoOutlined,
  ReloadOutlined,
  SearchOutlined,
  UndoOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { Alert, Button, Input, Modal, Popover, Space, Switch, Tag, Tooltip, Typography, message, theme } from 'antd';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { api, ApiError } from '../api/client';
import { RecycleBin, RowHistory } from './grid/AuditDrawers';
import CellEditor, { Commit, EditorRect, Move } from './grid/CellEditor';
import {
  ApplyResult,
  TablePayload,
  copyText,
  defaultWidth,
  displayText,
  isNumeric,
  isPick,
  optionsFor,
  parseInput,
  parseTSV,
  toTSV,
} from './grid/sheet';

export type { ColumnMeta, TablePayload } from './grid/sheet';

// The spreadsheet every editable table in the portal is entered through (Data
// Tables, Finance, the Dashboard's record views). It behaves like Google
// Sheets: click or arrow to a cell and type, Enter/Tab to move on, drag or
// shift-select a range, copy/paste blocks to and from Sheets or Excel, fill
// down (Ctrl+D or the fill handle), undo/redo, and a blank row at the bottom
// that becomes a new record as soon as you type in it. Every change saves
// itself (debounced) through POST /api/bulk/{table}; a row that the server
// rejects is marked in place and never holds back the others.

interface Row {
  key: string; // stable client id (survives the row getting its server id)
  isNew: boolean; // not inserted yet
  saving: boolean; // insert in flight
  v: Record<string, string>; // column -> stored value ('' = blank); includes id
}

interface Change {
  key: string;
  col: string;
  before: string;
  after: string;
}

interface Pos {
  r: number;
  c: number;
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

const ROW_H = 32;
const HEAD_H = 36;
const ROW_HEAD_W = 56;
const OVERSCAN = 10;
let SEQ = 0;

interface Props {
  table: string;
  /** Show only rows whose column equals this value; new rows start with it.
   *  Those columns are hidden (they'd be the same on every row). */
  fixed?: Record<string, string>;
  /** Kept for callers; the grid always refreshes computed columns after a save. */
  reloadOnSave?: boolean;
  /** Offer the Excel upload round-trip (download is always offered). */
  allowUpload?: boolean;
  /** Called after any successful write (e.g. to refresh a summary above). */
  onChanged?: () => void;
  /** Show the table's own description line. */
  showDescription?: boolean;
  /** Called with the row count after each load (e.g. for a sidebar badge). */
  onCount?: (n: number) => void;
  /** Max height of the sheet; it shrinks to fit fewer rows. */
  height?: string;
  title?: React.ReactNode;
  /** Adds "open record" to each saved row. */
  onOpenRow?: (id: number) => void;
  /** Leaner toolbar for sheets embedded in another page. */
  compact?: boolean;
}

export default function DataGrid({
  table,
  fixed,
  allowUpload = false,
  onChanged,
  showDescription = true,
  onCount,
  height = '62vh',
  title,
  onOpenRow,
  compact = false,
}: Props) {
  const { token } = theme.useToken();
  const [payload, setPayload] = useState<TablePayload | null>(null);
  const [rows, setRowsState] = useState<Row[]>([]);
  const rowsRef = useRef<Row[]>([]);
  const setRows = useCallback((next: Row[]) => {
    rowsRef.current = next;
    setRowsState(next);
  }, []);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<{ col: string; dir: 1 | -1 } | null>(null);

  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [cellErrors, setCellErrors] = useState<Record<string, string>>({});
  const [tableErrors, setTableErrors] = useState<string[]>([]);
  const pending = useRef<Map<string, Set<string>>>(new Map()); // row key -> columns changed since last send
  const inflight = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout>>();

  const [anchor, setAnchor] = useState<Pos>({ r: 0, c: 0 });
  const [focus, setFocus] = useState<Pos>({ r: 0, c: 0 });
  const [editing, setEditing] = useState<{ r: number; c: number; seed: string | null; rect: EditorRect; hidden?: boolean } | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [fillTo, setFillTo] = useState<number | null>(null);
  const drag = useRef<null | 'cells' | 'rows' | 'fill'>(null);
  const undoStack = useRef<Change[][]>([]);
  const redoStack = useRef<Change[][]>([]);
  const [, bumpHistory] = useState(0);

  const scrollRef = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState({ top: 0, left: 0 });
  const [viewH, setViewH] = useState(600);

  const widthKey = `grid-widths:${table}`;
  const [widths, setWidths] = useState<Record<string, number>>(() => {
    try {
      return JSON.parse(localStorage.getItem(widthKey) ?? '{}');
    } catch {
      return {};
    }
  });

  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const pendingFile = useRef<File | null>(null);
  const [alsoDelete, setAlsoDelete] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [historyOf, setHistoryOf] = useState<number | null>(null);
  const [binOpen, setBinOpen] = useState(false);

  const fixedKey = JSON.stringify(fixed ?? {});
  const fixedRef = useRef(fixed);
  fixedRef.current = fixed;
  const matchesFixed = useCallback(
    (r: Record<string, string>) =>
      Object.entries(fixedRef.current ?? {}).every(([k, v]) => String(r[k] ?? '') === String(v)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fixedKey],
  );
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;
  const onCountRef = useRef(onCount);
  onCountRef.current = onCount;

  // --- columns --------------------------------------------------------------
  const columns = useMemo(
    () => (payload?.columns ?? []).filter((c) => c.name !== 'id' && !(fixed && c.name in fixed)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [payload, fixedKey],
  );
  const colOpts = useMemo(() => columns.map((c) => optionsFor(c, payload?.options)), [columns, payload]);
  const colW = useMemo(() => columns.map((c) => widths[c.name] ?? defaultWidth(c)), [columns, widths]);
  const colLeft = useMemo(() => {
    const out = [ROW_HEAD_W];
    for (const w of colW) out.push(out[out.length - 1] + w);
    return out;
  }, [colW]);
  const totalW = colLeft[colLeft.length - 1];

  const readOnly = !!payload?.read_only;
  const locked = useCallback(
    (row: Row | undefined, c: number) => {
      const col = columns[c];
      if (!col || !col.editable || readOnly) return true;
      return !!(payload?.append_only && row && !row.isNew);
    },
    [columns, readOnly, payload],
  );
  const requiredCols = useMemo(() => columns.filter((c) => c.editable && c.required).map((c) => c.name), [columns]);
  const complete = useCallback(
    (r: Row) => requiredCols.every((c) => (r.v[c] ?? '').trim() !== ''),
    [requiredCols],
  );

  // --- load / merge -----------------------------------------------------------
  const toRow = (v: Record<string, string>): Row => ({ key: `id-${v.id}`, isNew: false, saving: false, v });

  /** Fold fresh server rows in without losing anything typed since the last send. */
  const merge = useCallback(
    (server: Record<string, string>[], idUpdates: Record<string, string> = {}) => {
      const shown = server.filter(matchesFixed);
      const byId = new Map(shown.map((s) => [String(s.id), s]));
      const seen = new Set<string>();
      const out: Row[] = [];
      for (const r0 of rowsRef.current) {
        let r = r0;
        if (idUpdates[r.key]) r = { ...r, isNew: false, saving: false, v: { ...r.v, id: idUpdates[r.key] } };
        if (r.isNew) {
          out.push(r);
          continue;
        }
        const s = byId.get(String(r.v.id));
        if (!s) continue; // deleted (or moved out of this view) elsewhere
        seen.add(String(r.v.id));
        const mine = pending.current.get(r.key);
        const v = { ...s };
        if (mine) for (const c of mine) v[c] = r.v[c];
        out.push({ ...r, v });
      }
      const fresh = shown.filter((s) => !seen.has(String(s.id))).map(toRow);
      const firstNew = out.findIndex((r) => r.isNew);
      if (firstNew < 0) out.push(...fresh);
      else out.splice(firstNew, 0, ...fresh);
      setRows(out);
      onCountRef.current?.(out.filter((r) => !r.isNew).length);
    },
    [matchesFixed, setRows],
  );

  const load = useCallback(
    async (fresh = false) => {
      try {
        const p = await api.get<TablePayload>(`/api/bulk/${table}`);
        setPayload(p);
        if (fresh) {
          const shown = p.rows.filter(matchesFixed).map(toRow);
          setRows(shown);
          onCountRef.current?.(shown.length);
        } else merge(p.rows);
      } catch (e) {
        message.error(e instanceof ApiError ? e.message : 'Failed to load table');
      }
    },
    [table, matchesFixed, merge, setRows],
  );

  useEffect(() => {
    setLoading(true);
    pending.current.clear();
    undoStack.current = [];
    redoStack.current = [];
    setCellErrors({});
    setTableErrors([]);
    setEditing(null);
    setSaveState('idle');
    setSearch('');
    setSort(null);
    setAnchor({ r: 0, c: 0 });
    setFocus({ r: 0, c: 0 });
    load(true).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table, fixedKey]);

  // --- the visible order ------------------------------------------------------
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    let saved = rows.filter((r) => !r.isNew);
    const drafts = rows.filter((r) => r.isNew);
    if (q) {
      saved = saved.filter((r) =>
        columns.some((c, i) => displayText(c, r.v[c.name] ?? '', colOpts[i]).toLowerCase().includes(q)),
      );
    }
    if (sort) {
      const i = columns.findIndex((c) => c.name === sort.col);
      const c = columns[i];
      if (c) {
        const key = (r: Row) => {
          const raw = r.v[c.name] ?? '';
          if (isNumeric(c)) return raw === '' ? Number.NEGATIVE_INFINITY : Number(raw);
          return displayText(c, raw, colOpts[i]).toLowerCase();
        };
        saved = [...saved].sort((a, b) => {
          const x = key(a);
          const y = key(b);
          return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
        });
      }
    }
    return [...saved, ...drafts];
  }, [rows, search, sort, columns, colOpts]);
  const visibleRef = useRef(visible);
  visibleRef.current = visible;
  const ghost = !readOnly && !!payload;
  const nRows = visible.length + (ghost ? 1 : 0);
  const nCols = columns.length;

  const r1 = Math.min(anchor.r, focus.r);
  const r2 = Math.max(anchor.r, focus.r);
  const c1 = Math.min(anchor.c, focus.c);
  const c2 = Math.max(anchor.c, focus.c);

  // keep the selection inside the sheet when rows/columns come and go
  useEffect(() => {
    const clampR = (r: number) => Math.max(0, Math.min(r, Math.max(0, nRows - 1)));
    const clampC = (c: number) => Math.max(0, Math.min(c, Math.max(0, nCols - 1)));
    if (anchor.r !== clampR(anchor.r) || anchor.c !== clampC(anchor.c)) setAnchor({ r: clampR(anchor.r), c: clampC(anchor.c) });
    if (focus.r !== clampR(focus.r) || focus.c !== clampC(focus.c)) setFocus({ r: clampR(focus.r), c: clampC(focus.c) });
  }, [nRows, nCols, anchor, focus]);

  // --- saving -----------------------------------------------------------------
  const doSaveRef = useRef<() => Promise<void>>(async () => {});
  const scheduleSave = useCallback((ms = 600) => {
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void doSaveRef.current(), ms);
  }, []);

  const sendable = useCallback(
    (r: Row) => {
      const p = pending.current.get(r.key);
      if (!p?.size) return false;
      return r.isNew ? !r.saving && complete(r) : true;
    },
    [complete],
  );

  doSaveRef.current = async () => {
    if (!payload) return;
    if (inflight.current) {
      scheduleSave(300);
      return;
    }
    const current = rowsRef.current;
    const batch = current.filter(sendable);
    if (!batch.length) {
      setSaveState((s) => (s === 'saving' ? 'saved' : s));
      return;
    }
    const editableCols = columns.filter((c) => c.editable).map((c) => c.name);
    const sent: { key: string; isNew: boolean; cols: string[] }[] = [];
    const body = batch.map((r) => {
      const cols = r.isNew ? editableCols : [...(pending.current.get(r.key) ?? [])];
      pending.current.delete(r.key);
      sent.push({ key: r.key, isNew: r.isNew, cols });
      const out: Record<string, string> = { id: r.isNew ? '' : r.v.id };
      for (const c of cols) out[c] = r.v[c] ?? '';
      return r.isNew ? { ...out, ...fixedRef.current } : out;
    });
    const newKeys = new Set(sent.filter((s) => s.isNew).map((s) => s.key));
    if (newKeys.size) setRows(rowsRef.current.map((r) => (newKeys.has(r.key) ? { ...r, saving: true } : r)));

    inflight.current = true;
    setSaveState('saving');
    try {
      const res = await api.post<ApplyResult>(`/api/bulk/${table}`, {
        rows: body,
        deletes: [],
        partial: true,
        return_rows: true,
      });
      const idUpdates: Record<string, string> = {};
      for (const [i, id] of Object.entries(res.ids ?? {})) {
        const s = sent[Number(i)];
        if (s?.isNew) idUpdates[s.key] = String(id);
      }
      // rejected new rows stop "saving" and stay drafts
      setRows(rowsRef.current.map((r) => (newKeys.has(r.key) && !idUpdates[r.key] ? { ...r, saving: false } : r)));
      const errs: Record<string, string> = {};
      const te: string[] = [];
      for (const e of res.errors) {
        const s = e.row != null ? sent[e.row] : undefined;
        if (s) errs[`${s.key}:${e.column && s.cols.includes(e.column) ? e.column : '*'}`] = e.message;
        else te.push(e.message);
      }
      setCellErrors((ce) => {
        const next = { ...ce };
        for (const s of sent) {
          delete next[`${s.key}:*`];
          for (const c of s.cols) delete next[`${s.key}:${c}`];
        }
        return { ...next, ...errs };
      });
      setTableErrors(te);
      if (res.rows) merge(res.rows, idUpdates);
      else if (Object.keys(idUpdates).length) merge([], idUpdates);
      setSaveState(res.errors.length ? 'error' : 'saved');
      if (Object.keys(res.ids ?? {}).length) onChangedRef.current?.();
    } catch (e) {
      // network / server failure: put everything back in the queue
      for (const s of sent) {
        const set = pending.current.get(s.key) ?? new Set<string>();
        s.cols.forEach((c) => set.add(c));
        pending.current.set(s.key, set);
      }
      setRows(rowsRef.current.map((r) => (newKeys.has(r.key) ? { ...r, saving: false } : r)));
      setTableErrors([e instanceof ApiError ? e.message : 'Could not reach the server — your changes are kept and will retry.']);
      setSaveState('error');
      inflight.current = false;
      scheduleSave(5000);
      return;
    }
    inflight.current = false;
    if (rowsRef.current.some(sendable)) scheduleSave(150);
  };

  // flush on unmount / tab close
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (inflight.current || rowsRef.current.some((r) => pending.current.get(r.key)?.size && !r.isNew)) {
        e.preventDefault();
      }
    };
    window.addEventListener('beforeunload', warn);
    return () => {
      window.removeEventListener('beforeunload', warn);
      clearTimeout(saveTimer.current);
      void doSaveRef.current();
    };
  }, []);

  // --- writing cells ------------------------------------------------------------
  const newDraft = useCallback((): Row => {
    const v: Record<string, string> = { id: '' };
    for (const c of payload?.columns ?? []) if (c.editable) v[c.name] = c.type === 'bool' ? 'false' : '';
    return { key: `new-${++SEQ}`, isNew: true, saving: false, v };
  }, [payload]);

  /** Apply changes by (row key, column). Records undo history unless replaying. */
  const applyChanges = useCallback(
    (changes: Change[], record: boolean) => {
      if (!changes.length) return;
      const byKey = new Map<string, Change[]>();
      for (const ch of changes) byKey.set(ch.key, [...(byKey.get(ch.key) ?? []), ch]);
      setRows(
        rowsRef.current.map((r) => {
          const mine = byKey.get(r.key);
          if (!mine) return r;
          const v = { ...r.v };
          const set = pending.current.get(r.key) ?? new Set<string>();
          for (const ch of mine) {
            v[ch.col] = ch.after;
            set.add(ch.col);
          }
          pending.current.set(r.key, set);
          return { ...r, v };
        }),
      );
      setCellErrors((ce) => {
        const next = { ...ce };
        for (const ch of changes) {
          delete next[`${ch.key}:${ch.col}`];
          delete next[`${ch.key}:*`];
        }
        return next;
      });
      if (record) {
        undoStack.current.push(changes);
        if (undoStack.current.length > 200) undoStack.current.shift();
        redoStack.current = [];
        bumpHistory((n) => n + 1);
      }
      scheduleSave();
    },
    [setRows, scheduleSave],
  );

  /** Write values at visible positions; positions past the end become new rows. */
  const setCells = useCallback(
    (cells: { r: number; c: number; value?: string; error?: string }[]) => {
      const vis = visibleRef.current;
      let all = rowsRef.current;
      const created: Row[] = [];
      const rowAt = (r: number): Row | undefined => {
        if (r < vis.length) return vis[r];
        if (readOnly) return undefined;
        while (created.length <= r - vis.length) created.push(newDraft());
        return created[r - vis.length];
      };
      const changes: Change[] = [];
      const errs: Record<string, string> = {};
      const touched = new Set<string>();
      for (const cell of cells) {
        const col = columns[cell.c];
        const row = rowAt(cell.r);
        if (!col || !row || locked(row, cell.c)) continue;
        touched.add(row.key);
        if (cell.error) {
          errs[`${row.key}:${col.name}`] = cell.error;
          continue;
        }
        const before = row.v[col.name] ?? '';
        if (cell.value === undefined || before === cell.value) continue;
        changes.push({ key: row.key, col: col.name, before, after: cell.value });
      }
      const needed = created.filter((r) => touched.has(r.key) || changes.some((ch) => ch.key === r.key));
      if (needed.length) {
        all = [...all, ...created.slice(0, created.indexOf(needed[needed.length - 1]) + 1)];
        setRows(all);
      }
      applyChanges(changes, true);
      if (Object.keys(errs).length) setCellErrors((ce) => ({ ...ce, ...errs }));
      return changes.length;
    },
    [columns, locked, newDraft, readOnly, setRows, applyChanges],
  );

  const pruneEmptyDrafts = useCallback(() => {
    const blank = (r: Row) => r.isNew && !r.saving && columns.every((c) => !c.editable || c.type === 'bool' || !(r.v[c.name] ?? '').trim());
    if (rowsRef.current.some(blank)) {
      const keep = rowsRef.current.filter((r) => !blank(r));
      rowsRef.current.filter(blank).forEach((r) => pending.current.delete(r.key));
      setRows(keep);
    }
  }, [columns, setRows]);

  const undo = useCallback(() => {
    const batch = undoStack.current.pop();
    if (!batch) return;
    applyChanges(batch.map((c) => ({ ...c, before: c.after, after: c.before })), false);
    redoStack.current.push(batch);
    bumpHistory((n) => n + 1);
    pruneEmptyDrafts();
  }, [applyChanges, pruneEmptyDrafts]);

  const redo = useCallback(() => {
    const batch = redoStack.current.pop();
    if (!batch) return;
    applyChanges(batch, false);
    undoStack.current.push(batch);
    bumpHistory((n) => n + 1);
  }, [applyChanges]);

  // --- selection helpers ---------------------------------------------------------
  const scrollIntoView = useCallback(
    (p: Pos) => {
      const el = scrollRef.current;
      if (!el) return;
      const top = p.r * ROW_H;
      const bodyH = el.clientHeight - HEAD_H;
      if (top < el.scrollTop) el.scrollTop = top;
      else if (top + ROW_H > el.scrollTop + bodyH) el.scrollTop = top + ROW_H - bodyH;
      const left = colLeft[p.c] ?? 0;
      const right = colLeft[p.c + 1] ?? left;
      if (left - ROW_HEAD_W < el.scrollLeft) el.scrollLeft = left - ROW_HEAD_W;
      else if (right > el.scrollLeft + el.clientWidth) el.scrollLeft = right - el.clientWidth;
    },
    [colLeft],
  );

  const select = useCallback(
    (p: Pos, extend = false) => {
      const q = { r: Math.max(0, Math.min(p.r, nRows - 1)), c: Math.max(0, Math.min(p.c, nCols - 1)) };
      setFocus(q);
      if (!extend) setAnchor(q);
      scrollIntoView(q);
    },
    [nRows, nCols, scrollIntoView],
  );

  const refocus = () => scrollRef.current?.focus({ preventScroll: true });

  const cellRect = (p: Pos): EditorRect | null => {
    const td = scrollRef.current?.querySelector<HTMLElement>(`[data-cell="${p.r}:${p.c}"]`);
    if (!td) return null;
    const b = td.getBoundingClientRect();
    return { left: b.left, top: b.top, width: b.width, height: b.height };
  };

  const startEdit = useCallback(
    (p: Pos, seed: string | null) => {
      const row = visibleRef.current[p.r];
      if (locked(row, p.c) || columns[p.c]?.type === 'bool') return;
      scrollIntoView(p);
      const open = () => {
        const rect = cellRect(p);
        if (rect) setEditing({ r: p.r, c: p.c, seed, rect });
        return !!rect;
      };
      // the cell may only render after the scroll above repaints the window of rows
      if (!open()) setTimeout(open, 30);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [locked, columns, scrollIntoView],
  );

  const commitEdit = (commit: Commit, move: Move) => {
    if (!editing) return;
    const { r, c } = editing;
    const col = columns[c];
    if (commit.kind === 'value') setCells([{ r, c, value: commit.value }]);
    else {
      const parsed = parseInput(col, commit.text, colOpts[c]);
      if (parsed.ok) setCells([{ r, c, value: parsed.value }]);
      else {
        setCells([{ r, c, error: parsed.error }]);
        message.warning(parsed.error);
      }
    }
    setEditing(null);
    if (move === 'down') select({ r: r + 1, c });
    else if (move === 'up') select({ r: r - 1, c });
    else if (move === 'right') select({ r, c: c + 1 });
    else if (move === 'left') select({ r, c: c - 1 });
    refocus();
  };

  const toggleBool = (p: Pos) => {
    const row = visibleRef.current[p.r];
    const col = columns[p.c];
    if (!col || col.type !== 'bool' || locked(row, p.c)) return;
    setCells([{ r: p.r, c: p.c, value: row?.v[col.name] === 'true' ? 'false' : 'true' }]);
  };

  // --- clipboard / bulk ops ---------------------------------------------------------
  const rangeGrid = (): string[][] => {
    const out: string[][] = [];
    for (let r = r1; r <= Math.min(r2, visible.length - 1); r++) {
      const line: string[] = [];
      for (let c = c1; c <= c2; c++) line.push(copyText(columns[c], visible[r].v[columns[c].name] ?? '', colOpts[c]));
      out.push(line);
    }
    return out;
  };

  const clearRange = () => {
    const cells = [];
    for (let r = r1; r <= Math.min(r2, visible.length - 1); r++)
      for (let c = c1; c <= c2; c++) cells.push({ r, c, value: columns[c].type === 'bool' ? 'false' : '' });
    setCells(cells);
  };

  const pasteText = (text: string) => {
    if (readOnly) return;
    let clip = parseTSV(text);
    if (clip.length > 1 && clip[clip.length - 1].every((x) => x === '')) clip = clip.slice(0, -1);
    if (!clip.length) return;
    const h = clip.length;
    const w = Math.max(...clip.map((l) => l.length));
    const selH = r2 - r1 + 1;
    const selW = c2 - c1 + 1;
    // a selection that's a whole multiple of the copied block gets it tiled (1 cell -> fill all)
    const tile = selH % h === 0 && selW % w === 0 && (selH > h || selW > w);
    const rows = tile ? selH : h;
    const cols = tile ? selW : w;
    const cells: { r: number; c: number; value?: string; error?: string }[] = [];
    const bad: string[] = [];
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const c = c1 + j;
        if (c >= nCols) continue;
        const raw = clip[i % h][j % w] ?? '';
        const parsed = parseInput(columns[c], raw, colOpts[c]);
        if (parsed.ok) cells.push({ r: r1 + i, c, value: parsed.value });
        else {
          cells.push({ r: r1 + i, c, error: parsed.error });
          bad.push(`${columns[c].label}: ${parsed.error}`);
        }
      }
    }
    setCells(cells);
    setAnchor({ r: r1, c: c1 });
    setFocus({ r: r1 + rows - 1, c: Math.min(nCols - 1, c1 + cols - 1) });
    if (bad.length) message.warning(`${bad.length} pasted value(s) didn't fit and were skipped — e.g. ${bad[0]}`);
  };

  const fillDown = () => {
    const from = r1 === r2 ? r1 - 1 : r1;
    if (from < 0 || from >= visible.length) return;
    const cells = [];
    for (let r = from + 1; r <= r2; r++)
      for (let c = c1; c <= c2; c++) cells.push({ r, c, value: visible[from].v[columns[c].name] ?? '' });
    setCells(cells);
  };

  const fillRight = () => {
    const from = c1 === c2 ? c1 - 1 : c1;
    if (from < 0) return;
    const cells = [];
    for (let r = r1; r <= Math.min(r2, visible.length - 1); r++) {
      const src = columns[from];
      for (let c = from + 1; c <= c2; c++) {
        const parsed = parseInput(columns[c], copyText(src, visible[r].v[src.name] ?? '', colOpts[from]), colOpts[c]);
        if (parsed.ok) cells.push({ r, c, value: parsed.value });
      }
    }
    setCells(cells);
  };

  /** Fill-handle drag: repeat the selected block (or continue a number series) up to `to`. */
  const fillHandle = (to: number) => {
    if (to >= r1 && to <= r2) return;
    const srcH = Math.min(r2, visible.length - 1) - r1 + 1;
    if (srcH <= 0) return;
    const cells = [];
    const targets = to > r2 ? range(r2 + 1, to) : range(to, r1 - 1);
    for (let c = c1; c <= c2; c++) {
      const col = columns[c];
      const src = range(r1, r1 + srcH - 1).map((r) => visible[r].v[col.name] ?? '');
      const nums = src.map(Number);
      const series = isNumeric(col) && srcH >= 2 && src.every((x) => x !== '' && !Number.isNaN(Number(x)));
      const step = series ? nums[nums.length - 1] - nums[nums.length - 2] : 0;
      for (const r of targets) {
        let value: string;
        if (series) {
          value = String(to > r2 ? nums[nums.length - 1] + step * (r - (r1 + srcH - 1)) : nums[0] - step * (r1 - r));
        } else {
          value = src[(((r - r1) % srcH) + srcH) % srcH];
        }
        cells.push({ r, c, value });
      }
    }
    setCells(cells);
    if (to > r2) {
      setAnchor({ r: r1, c: c1 });
      setFocus({ r: to, c: c2 });
    } else {
      setAnchor({ r: r2, c: c1 });
      setFocus({ r: to, c: c2 });
    }
  };

  // --- deleting rows -------------------------------------------------------------------
  const selectedRows = useMemo(
    () => visible.slice(r1, Math.min(r2, visible.length - 1) + 1),
    [visible, r1, r2],
  );
  const canDelete = !readOnly && !payload?.append_only && payload?.delete !== 'none';

  const deleteRows = (targets: Row[]) => {
    const drafts = targets.filter((r) => r.isNew);
    const saved = targets.filter((r) => !r.isNew && canDelete);
    const dropDrafts = () => {
      if (!drafts.length) return;
      const gone = new Set(drafts.map((r) => r.key));
      drafts.forEach((r) => pending.current.delete(r.key));
      setRows(rowsRef.current.filter((r) => !gone.has(r.key)));
    };
    if (!saved.length) {
      dropDrafts();
      return;
    }
    const how =
      payload?.delete === 'deactivate'
        ? `${saved.length > 1 ? 'They' : 'It'} will be deactivated.`
        : payload?.delete === 'soft'
          ? `${saved.length > 1 ? 'They' : 'It'} will be archived.`
          : `This permanently removes ${saved.length > 1 ? 'them' : 'it'} and cannot be undone.`;
    Modal.confirm({
      title: `Delete ${saved.length} row${saved.length > 1 ? 's' : ''}?`,
      content: how,
      okText: 'Delete',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await api.post<ApplyResult>(`/api/bulk/${table}`, {
            rows: [],
            deletes: saved.map((r) => Number(r.v.id)),
            return_rows: true,
          });
          if (!res.ok) {
            message.error(res.errors[0]?.message ?? 'Could not delete those rows.');
            return;
          }
          dropDrafts();
          saved.forEach((r) => pending.current.delete(r.key));
          if (res.rows) merge(res.rows);
          message.success(`${saved.length} row${saved.length > 1 ? 's' : ''} deleted.`);
          onChangedRef.current?.();
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : 'Delete failed');
        } finally {
          refocus();
        }
      },
      onCancel: refocus,
    });
  };

  // --- keyboard -----------------------------------------------------------------------
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (editing) return;
    const mod = e.ctrlKey || e.metaKey;
    const k = e.key;
    const page = Math.max(1, Math.floor((viewH - HEAD_H) / ROW_H) - 1);
    const move = (dr: number, dc: number) => {
      e.preventDefault();
      setMenu(null);
      let r = focus.r + dr;
      let c = focus.c + dc;
      if (mod && dr) r = dr > 0 ? nRows - 1 : 0;
      if (mod && dc) c = dc > 0 ? nCols - 1 : 0;
      select({ r, c }, e.shiftKey);
    };
    if (k === 'ArrowDown') return move(1, 0);
    if (k === 'ArrowUp') return move(-1, 0);
    if (k === 'ArrowRight') return move(0, 1);
    if (k === 'ArrowLeft') return move(0, -1);
    if (k === 'PageDown') return move(page, 0);
    if (k === 'PageUp') return move(-page, 0);
    if (k === 'Home') {
      e.preventDefault();
      return select({ r: mod ? 0 : focus.r, c: 0 }, e.shiftKey);
    }
    if (k === 'End') {
      e.preventDefault();
      return select({ r: mod ? nRows - 1 : focus.r, c: nCols - 1 }, e.shiftKey);
    }
    if (k === 'Tab') {
      e.preventDefault();
      return select({ r: focus.r, c: focus.c + (e.shiftKey ? -1 : 1) });
    }
    if (k === 'Escape') {
      setMenu(null);
      return select(focus);
    }
    if (mod && (k === 'z' || k === 'Z')) {
      e.preventDefault();
      return e.shiftKey ? redo() : undo();
    }
    if (mod && (k === 'y' || k === 'Y')) {
      e.preventDefault();
      return redo();
    }
    if (mod && (k === 'd' || k === 'D')) {
      e.preventDefault();
      return fillDown();
    }
    if (mod && (k === 'r' || k === 'R')) {
      e.preventDefault();
      return fillRight();
    }
    if (mod && (k === 'a' || k === 'A')) {
      e.preventDefault();
      setAnchor({ r: 0, c: 0 });
      setFocus({ r: Math.max(0, visible.length - 1), c: nCols - 1 });
      return;
    }
    if (mod) return; // let copy / cut / paste through to the clipboard events
    if (k === 'Enter' || k === 'F2') {
      e.preventDefault();
      if (columns[focus.c]?.type === 'bool') return toggleBool(focus);
      return startEdit(focus, null);
    }
    if (k === ' ' && columns[focus.c]?.type === 'bool') {
      e.preventDefault();
      return toggleBool(focus);
    }
    if (k === 'Delete' || k === 'Backspace') {
      e.preventDefault();
      return clearRange();
    }
    if (k.length === 1 && !e.altKey) {
      e.preventDefault();
      select(focus);
      startEdit(focus, k);
    }
  };

  // --- mouse --------------------------------------------------------------------------
  useEffect(() => {
    const up = () => {
      if (drag.current === 'fill' && fillTo != null) fillHandle(fillTo);
      drag.current = null;
      setFillTo(null);
    };
    window.addEventListener('mouseup', up);
    return () => window.removeEventListener('mouseup', up);
  });

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener('mousedown', close);
    window.addEventListener('blur', close);
    return () => {
      window.removeEventListener('mousedown', close);
      window.removeEventListener('blur', close);
    };
  }, [menu]);

  const cellDown = (e: React.MouseEvent, p: Pos) => {
    if (e.button === 2) {
      if (p.r < r1 || p.r > r2 || p.c < c1 || p.c > c2) select(p);
      return;
    }
    if (e.button !== 0) return;
    setMenu(null);
    select(p, e.shiftKey);
    drag.current = 'cells';
    scrollRef.current?.focus({ preventScroll: true });
  };
  const cellEnter = (p: Pos) => {
    if (drag.current === 'cells') {
      setFocus(p);
    } else if (drag.current === 'rows') {
      setFocus({ r: p.r, c: nCols - 1 });
    } else if (drag.current === 'fill') setFillTo(p.r);
  };
  const rowHeadDown = (e: React.MouseEvent, r: number) => {
    if (e.button === 2) {
      if (r < r1 || r > r2) {
        setAnchor({ r, c: 0 });
        setFocus({ r, c: nCols - 1 });
      }
      return;
    }
    if (e.shiftKey) setAnchor((a) => ({ r: a.r, c: 0 }));
    else setAnchor({ r, c: 0 });
    setFocus({ r, c: nCols - 1 });
    drag.current = 'rows';
    scrollRef.current?.focus({ preventScroll: true });
  };
  const colHeadDown = (e: React.MouseEvent, c: number) => {
    if (e.shiftKey) {
      setAnchor((a) => ({ r: 0, c: a.c }));
      setFocus({ r: Math.max(0, visible.length - 1), c });
    } else {
      setAnchor({ r: 0, c });
      setFocus({ r: Math.max(0, visible.length - 1), c });
    }
    scrollRef.current?.focus({ preventScroll: true });
  };

  const startResize = (e: React.MouseEvent, c: number) => {
    e.preventDefault();
    e.stopPropagation();
    const name = columns[c].name;
    const x0 = e.clientX;
    const w0 = colW[c];
    const mv = (ev: MouseEvent) => setWidths((w) => ({ ...w, [name]: Math.max(60, w0 + ev.clientX - x0) }));
    const up = () => {
      window.removeEventListener('mousemove', mv);
      window.removeEventListener('mouseup', up);
      setWidths((w) => {
        try {
          localStorage.setItem(widthKey, JSON.stringify(w));
        } catch {
          /* storage unavailable */
        }
        return w;
      });
    };
    window.addEventListener('mousemove', mv);
    window.addEventListener('mouseup', up);
  };

  // --- viewport -------------------------------------------------------------------------
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setViewH(el.clientHeight));
    ro.observe(el);
    setViewH(el.clientHeight);
    return () => ro.disconnect();
  }, [payload]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setScroll({ top: el.scrollTop, left: el.scrollLeft });
    if (editing) {
      // keep the editor glued to its cell; hide it (keeping what's typed) while the cell is scrolled away
      const rect = cellRect(editing);
      const box = el.getBoundingClientRect();
      const inView =
        !!rect && rect.top >= box.top + HEAD_H - 4 && rect.top + rect.height <= box.bottom + 4 &&
        rect.left >= box.left + ROW_HEAD_W - 4 && rect.left < box.right;
      setEditing({ ...editing, rect: rect ?? editing.rect, hidden: !inView });
    }
  };

  const start = Math.max(0, Math.floor(scroll.top / ROW_H) - OVERSCAN);
  const end = Math.min(nRows, Math.ceil((scroll.top + viewH) / ROW_H) + OVERSCAN);

  // --- Excel download / upload -----------------------------------------------------------
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

  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    pendingFile.current = file;
    setAlsoDelete(false);
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    api
      .upload<UploadPreview>(`/api/bulk/${table}/upload`, form)
      .then(setPreview)
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
        message.success(`Applied: ${res.new} added, ${res.changed} updated${res.will_delete ? `, ${res.will_delete} deleted` : ''}.`);
        setPreview(null);
        pendingFile.current = null;
        await load();
        onChangedRef.current?.();
      } else {
        message.error(res.errors?.[0]?.message ?? 'The file has invalid data — fix it and re-upload.');
      }
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  // --- render ----------------------------------------------------------------------------
  const activeRow = visible[focus.r];
  const activeCol = columns[focus.c];
  const activeErr = activeRow
    ? cellErrors[`${activeRow.key}:${activeCol?.name}`] ?? cellErrors[`${activeRow.key}:*`]
    : undefined;
  const draftCount = rows.filter((r) => r.isNew && !r.saving).length;
  const errorCount = Object.keys(cellErrors).length;

  const stats = useMemo(() => {
    if (r1 === r2 && c1 === c2) return null;
    let count = 0;
    let n = 0;
    let sum = 0;
    for (let r = r1; r <= Math.min(r2, visible.length - 1); r++)
      for (let c = c1; c <= c2; c++) {
        const raw = visible[r].v[columns[c]?.name] ?? '';
        if (raw === '') continue;
        count++;
        if (columns[c] && isNumeric(columns[c])) {
          n++;
          sum += Number(raw);
        }
      }
    return { count, n, sum };
  }, [r1, r2, c1, c2, visible, columns]);

  const saveTag = () => {
    if (saveState === 'saving') return <Tag icon={<LoadingOutlined />} color="processing">Saving…</Tag>;
    if (saveState === 'saved' && !errorCount) return <Tag icon={<CheckCircleFilled />} color="success">Saved</Tag>;
    if (saveState === 'error' || errorCount)
      return (
        <Tag icon={<ExclamationCircleFilled />} color="error">
          {errorCount ? `${errorCount} cell${errorCount > 1 ? 's need' : ' needs'} fixing` : 'Not saved'}
        </Tag>
      );
    return null;
  };

  // selection tints mixed from the primary colour (the theme's own *Bg tokens are light in dark mode)
  const tint = (pct: number) => `color-mix(in srgb, ${token.colorPrimary} ${pct}%, transparent)`;
  const css = `
    .sg-wrap:focus { outline: none; }
    .sg-table { border-collapse: separate; border-spacing: 0; table-layout: fixed; font-size: 13px; }
    .sg-table td, .sg-table th { border-right: 1px solid ${token.colorBorderSecondary}; border-bottom: 1px solid ${token.colorBorderSecondary}; }
    .sg-th { position: sticky; top: 0; z-index: 3; height: ${HEAD_H}px; font-weight: 600; text-align: left; padding: 0 8px; user-select: none; cursor: default; }
    .sg-th-inner { display: flex; align-items: center; gap: 4px; height: 100%; overflow: hidden; white-space: nowrap; }
    .sg-th-label { overflow: hidden; text-overflow: ellipsis; flex: 1; }
    .sg-sort { opacity: 0; cursor: pointer; padding: 0 2px; color: ${token.colorTextTertiary}; }
    .sg-th:hover .sg-sort, .sg-sort.on { opacity: 1; }
    .sg-sort.on { color: ${token.colorPrimary}; }
    .sg-resize { position: absolute; right: -3px; top: 0; bottom: 0; width: 6px; cursor: col-resize; z-index: 4; }
    .sg-resize:hover { background: ${token.colorPrimary}; opacity: .5; }
    .sg-rh { position: sticky; left: 0; z-index: 2; background: ${token.colorBgContainer}; color: ${token.colorTextTertiary}; text-align: center; font-size: 11px; user-select: none; cursor: default; font-variant-numeric: tabular-nums; }
    .sg-rh.sel { color: ${token.colorPrimary}; font-weight: 600; background: linear-gradient(${tint(16)}, ${tint(16)}), ${token.colorBgContainer}; }
    .sg-corner { left: 0; z-index: 5; }
    .sg-td { position: relative; height: ${ROW_H}px; padding: 0 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: cell; user-select: none; }
    .sg-td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .sg-td.lock { background: ${token.colorFillQuaternary}; color: ${token.colorTextSecondary}; }
    .sg-td.inr { background: ${tint(14)}; }
    .sg-td.err { background: ${token.colorErrorBg}; box-shadow: inset 0 0 0 1px ${token.colorErrorBorder}; }
    .sg-td.miss { background: ${token.colorWarningBg}; }
    .sg-td.act { box-shadow: inset 0 0 0 2px ${token.colorPrimary}; }
    .sg-td.act.err { box-shadow: inset 0 0 0 2px ${token.colorError}; }
    .sg-td.fill { box-shadow: inset 0 0 0 1px ${token.colorPrimary}; background: ${tint(22)}; }
    .sg-handle { position: absolute; right: 0; bottom: 0; width: 7px; height: 7px; background: ${token.colorPrimary}; border: 1px solid ${token.colorBgContainer}; cursor: crosshair; z-index: 1; }
    .sg-ghost .sg-td { color: ${token.colorTextQuaternary}; }
    .sg-open { display: none; cursor: pointer; color: ${token.colorPrimary}; }
    .sg-row:hover .sg-open { display: inline; }
    .sg-row:hover .sg-num.can-open { display: none; }
    .sg-row.draft .sg-rh { color: ${token.colorWarning}; }
    .sg-dim { color: ${token.colorTextQuaternary}; }
    .sg-menu { position: fixed; z-index: 1200; background: ${token.colorBgElevated}; box-shadow: ${token.boxShadowSecondary}; border-radius: 8px; padding: 4px; min-width: 200px; font-size: 13px; }
    .sg-menu button { all: unset; box-sizing: border-box; display: flex; justify-content: space-between; gap: 16px; width: 100%; padding: 6px 10px; border-radius: 4px; cursor: pointer; }
    .sg-menu button:hover { background: ${token.controlItemBgHover}; }
    .sg-menu button[disabled] { opacity: .4; cursor: default; }
    .sg-menu kbd { font-family: inherit; color: ${token.colorTextTertiary}; font-size: 12px; }
    .sg-menu hr { border: 0; border-top: 1px solid ${token.colorSplit}; margin: 4px 0; }
  `;

  const renderCell = (row: Row | undefined, r: number, c: number) => {
    const col = columns[c];
    const value = row?.v[col.name] ?? '';
    const isLocked = locked(row, c);
    const err = row ? cellErrors[`${row.key}:${col.name}`] : undefined;
    const inRange = r >= r1 && r <= r2 && c >= c1 && c <= c2;
    const active = r === focus.r && c === focus.c;
    const inFill =
      fillTo != null && c >= c1 && c <= c2 && ((fillTo > r2 && r > r2 && r <= fillTo) || (fillTo < r1 && r >= fillTo && r < r1));
    const missing = !!row?.isNew && col.required && col.editable && value.trim() === '';
    const cls = [
      'sg-td',
      isNumeric(col) ? 'num' : '',
      isLocked && row ? 'lock' : '',
      inRange && !active ? 'inr' : '',
      inFill ? 'fill' : '',
      err ? 'err' : missing ? 'miss' : '',
      active ? 'act' : '',
    ].join(' ');
    let content: React.ReactNode;
    if (!row) content = c === 0 && ghost ? <span className="sg-dim">{visible.length ? 'Type to add a row…' : 'Type here to add the first row…'}</span> : null;
    else if (col.type === 'bool')
      content = (
        <input
          type="checkbox"
          checked={value === 'true'}
          disabled={isLocked}
          readOnly
          tabIndex={-1}
          onMouseDown={(e) => {
            if (e.button !== 0 || isLocked) return;
            e.stopPropagation();
            select({ r, c });
            toggleBool({ r, c });
            scrollRef.current?.focus({ preventScroll: true });
          }}
          style={{ cursor: isLocked ? 'default' : 'pointer', margin: 0, verticalAlign: 'middle' }}
        />
      );
    else content = displayText(col, value, colOpts[c]);
    const showHandle = !readOnly && r === r2 && c === c2 && !editing && r < visible.length;
    return (
      <td
        key={col.name}
        data-cell={`${r}:${c}`}
        className={cls}
        title={err ?? (typeof content === 'string' && content.length > 18 ? content : undefined)}
        onMouseDown={(e) => cellDown(e, { r, c })}
        onMouseEnter={() => cellEnter({ r, c })}
        onDoubleClick={() => startEdit({ r, c }, null)}
        onContextMenu={(e) => {
          e.preventDefault();
          setMenu({ x: e.clientX, y: e.clientY });
        }}
      >
        {content}
        {showHandle && (
          <div
            className="sg-handle"
            title="Drag to fill"
            onMouseDown={(e) => {
              e.stopPropagation();
              e.preventDefault();
              drag.current = 'fill';
              setFillTo(r2);
            }}
          />
        )}
      </td>
    );
  };

  const shortcuts = (
    <div style={{ fontSize: 13, display: 'grid', gridTemplateColumns: 'auto auto', gap: '4px 16px' }}>
      {[
        ['Type', 'Replace the cell'],
        ['Enter / F2 / double-click', 'Edit the cell'],
        ['Enter · Tab', 'Save and move down · right'],
        ['Alt+Enter', 'New line in a cell'],
        ['Esc', 'Cancel editing'],
        ['Arrows · Shift+Arrows', 'Move · extend selection'],
        ['Ctrl+Arrows', 'Jump to the edge'],
        ['Ctrl+C / X / V', 'Copy / cut / paste (works with Sheets & Excel)'],
        ['Delete', 'Clear the selected cells'],
        ['Ctrl+D · Ctrl+R', 'Fill down · right'],
        ['Drag the corner square', 'Fill (continues number series)'],
        ['Ctrl+Z · Ctrl+Y', 'Undo · redo'],
        ['Space', 'Tick / untick a checkbox'],
        ['Last row', 'Type in it to add a record'],
        ['Right-click', 'More (delete rows, open…)'],
      ].map(([k, v]) => (
        <span key={k} style={{ display: 'contents' }}>
          <strong style={{ whiteSpace: 'nowrap' }}>{k}</strong>
          <span>{v}</span>
        </span>
      ))}
    </div>
  );

  const menuItem = (label: string, onClick: () => void, kbd?: string, disabled = false) => (
    <button
      type="button"
      disabled={disabled}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={() => {
        setMenu(null);
        onClick();
        refocus();
      }}
    >
      <span>{label}</span>
      {kbd && <kbd>{kbd}</kbd>}
    </button>
  );

  const nSel = selectedRows.length;
  const savedSel = selectedRows.filter((r) => !r.isNew);
  const deletable = nSel > 0 && (savedSel.length === 0 || canDelete);

  return (
    <div>
      <style>{css}</style>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
        <Space size={8} wrap style={{ flex: 1, minWidth: 180 }}>
          {title}
          {saveTag()}
          {draftCount > 0 && (
            <Tooltip title="New rows save as soon as every * column is filled in">
              <Tag color="warning">{draftCount} unsaved new row{draftCount > 1 ? 's' : ''}</Tag>
            </Tooltip>
          )}
        </Space>
        <Space wrap size={6}>
          <Input
            allowClear
            prefix={<SearchOutlined style={{ opacity: 0.5 }} />}
            placeholder="Filter rows"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: compact ? 160 : 200 }}
          />
          {readOnly ? (
            <Tag icon={<LockOutlined />}>Read-only</Tag>
          ) : (
            <>
              <Button
                icon={<PlusOutlined />}
                type="primary"
                disabled={!payload}
                onClick={() => {
                  const p = { r: visible.length, c: Math.max(0, columns.findIndex((c) => c.editable)) };
                  select(p);
                  startEdit(p, null);
                }}
              >
                Add row
              </Button>
              {nSel > 0 && deletable && (r1 !== r2 || (c1 === 0 && c2 === nCols - 1)) && (
                <Button danger icon={<DeleteOutlined />} onClick={() => deleteRows(selectedRows)}>
                  Delete {nSel} row{nSel > 1 ? 's' : ''}
                </Button>
              )}
              <Tooltip title="Undo (Ctrl+Z)">
                <Button icon={<UndoOutlined />} disabled={!undoStack.current.length} onClick={undo} />
              </Tooltip>
              <Tooltip title="Redo (Ctrl+Y)">
                <Button icon={<RedoOutlined />} disabled={!redoStack.current.length} onClick={redo} />
              </Tooltip>
            </>
          )}
          {canDelete && !compact && (
            <Tooltip title="Recycle bin — restore deleted rows">
              <Button icon={<RestOutlined />} onClick={() => setBinOpen(true)} />
            </Tooltip>
          )}
          <Tooltip title="Refresh from the server (keeps unsaved edits)">
            <Button icon={<ReloadOutlined />} onClick={() => void load()} />
          </Tooltip>
          {!compact && (
            <Tooltip title="Download as Excel">
              <Button icon={<DownloadOutlined />} loading={downloading} onClick={download} />
            </Tooltip>
          )}
          {allowUpload && !compact && payload && !readOnly && (
            <Tooltip title="Upload an edited .xlsx/.csv — diffed against the table, you confirm before anything changes. (For a few rows, just paste them into the sheet.)">
              <Button icon={<UploadOutlined />} loading={uploading} onClick={() => fileInput.current?.click()} />
            </Tooltip>
          )}
          <Popover content={shortcuts} title="Working in the sheet" placement="bottomRight" trigger="click">
            <Button icon={<QuestionCircleOutlined />} />
          </Popover>
          <input ref={fileInput} type="file" accept=".xlsx,.xlsm,.csv" style={{ display: 'none' }} onChange={onPickFile} />
        </Space>
      </div>

      {showDescription && payload?.description && (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          {payload.description}
        </Typography.Paragraph>
      )}

      {tableErrors.length > 0 && (
        <Alert
          type="error"
          showIcon
          closable
          onClose={() => setTableErrors([])}
          style={{ marginBottom: 8 }}
          message={tableErrors.length === 1 ? tableErrors[0] : 'Some changes couldn’t be saved'}
          description={
            tableErrors.length > 1 ? (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {tableErrors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            ) : undefined
          }
        />
      )}

      <div
        style={{
          border: `1px solid ${token.colorBorderSecondary}`,
          borderRadius: token.borderRadiusLG,
          overflow: 'hidden',
          background: token.colorBgContainer,
        }}
      >
        <div
          ref={scrollRef}
          className="sg-wrap"
          tabIndex={0}
          onKeyDown={onKeyDown}
          onScroll={onScroll}
          onCopy={(e) => {
            if (editing || (e.target as HTMLElement) !== scrollRef.current) return;
            e.preventDefault();
            e.clipboardData.setData('text/plain', toTSV(rangeGrid()));
          }}
          onCut={(e) => {
            if (editing || readOnly || (e.target as HTMLElement) !== scrollRef.current) return;
            e.preventDefault();
            e.clipboardData.setData('text/plain', toTSV(rangeGrid()));
            clearRange();
          }}
          onPaste={(e) => {
            if (editing || (e.target as HTMLElement) !== scrollRef.current) return;
            e.preventDefault();
            pasteText(e.clipboardData.getData('text/plain'));
          }}
          style={{ maxHeight: height, minHeight: ROW_H * 3 + HEAD_H, overflow: 'auto', position: 'relative' }}
        >
          {loading && !payload ? (
            <div style={{ padding: 24, color: token.colorTextTertiary }}>
              <LoadingOutlined /> Loading…
            </div>
          ) : (
            <table className="sg-table" style={{ width: totalW }}>
              <colgroup>
                <col style={{ width: ROW_HEAD_W }} />
                {colW.map((w, i) => (
                  <col key={columns[i].name} style={{ width: w }} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  <th className="sg-th sg-rh sg-corner" style={{ position: 'sticky', top: 0 }} />
                  {columns.map((c, i) => {
                    const on = sort?.col === c.name;
                    return (
                      <th
                        key={c.name}
                        className="sg-th"
                        style={{ background: i >= c1 && i <= c2 ? `linear-gradient(${tint(18)}, ${tint(18)}), ${token.colorBgContainer}` : token.colorBgContainer }}
                        onMouseDown={(e) => colHeadDown(e, i)}
                      >
                        <div className="sg-th-inner" title={c.editable ? c.label : `${c.label} — computed, not editable`}>
                          {!c.editable && <LockOutlined style={{ fontSize: 10, opacity: 0.5 }} />}
                          <span className="sg-th-label" style={{ textAlign: isNumeric(c) ? 'right' : 'left', opacity: c.editable ? 1 : 0.7 }}>
                            {c.label}
                            {c.required && c.editable && <span style={{ color: token.colorError }}> *</span>}
                          </span>
                          <span
                            className={`sg-sort${on ? ' on' : ''}`}
                            title="Sort"
                            onMouseDown={(e) => {
                              e.stopPropagation();
                              setSort(!on ? { col: c.name, dir: 1 } : sort!.dir === 1 ? { col: c.name, dir: -1 } : null);
                            }}
                          >
                            {on ? (sort!.dir === 1 ? '▲' : '▼') : '⇅'}
                          </span>
                        </div>
                        <div className="sg-resize" onMouseDown={(e) => startResize(e, i)} />
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {start > 0 && (
                  <tr style={{ height: start * ROW_H }}>
                    <td colSpan={nCols + 1} style={{ padding: 0, border: 0 }} />
                  </tr>
                )}
                {range(start, end - 1).map((r) => {
                  const row = visible[r];
                  const rowErr = row ? cellErrors[`${row.key}:*`] : undefined;
                  const inRows = r >= r1 && r <= r2;
                  return (
                    <tr key={row?.key ?? 'ghost'} className={`sg-row${row?.isNew ? ' draft' : ''}${row ? '' : ' sg-ghost'}`}>
                      <td
                        className={`sg-rh${inRows ? ' sel' : ''}`}
                        style={rowErr ? { background: token.colorErrorBg, color: token.colorError } : undefined}
                        title={rowErr ?? (row?.isNew ? (row.saving ? 'Saving…' : 'New row — fill the * columns to save it') : row ? `ID ${row.v.id}` : 'New row')}
                        onMouseDown={(e) => rowHeadDown(e, r)}
                        onMouseEnter={() => cellEnter({ r, c: 0 })}
                        onContextMenu={(e) => {
                          e.preventDefault();
                          setMenu({ x: e.clientX, y: e.clientY });
                        }}
                        onDoubleClick={() => row && !row.isNew && onOpenRow?.(Number(row.v.id))}
                      >
                        {!row ? (
                          <PlusOutlined style={{ fontSize: 10 }} />
                        ) : row.isNew ? (
                          row.saving ? <LoadingOutlined style={{ fontSize: 10 }} /> : '•'
                        ) : (
                          <>
                            <span className={`sg-num${onOpenRow ? ' can-open' : ''}`}>{rowErr ? '!' : r + 1}</span>
                            {onOpenRow && (
                              <ExportOutlined
                                className="sg-open"
                                title="Open this record"
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={() => onOpenRow(Number(row.v.id))}
                              />
                            )}
                          </>
                        )}
                      </td>
                      {columns.map((_, c) => renderCell(row, r, c))}
                    </tr>
                  );
                })}
                {end < nRows && (
                  <tr style={{ height: (nRows - end) * ROW_H }}>
                    <td colSpan={nCols + 1} style={{ padding: 0, border: 0 }} />
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
        <div
          style={{
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            padding: '5px 10px',
            borderTop: `1px solid ${token.colorBorderSecondary}`,
            fontSize: 12,
            color: token.colorTextSecondary,
            minHeight: 30,
            background: token.colorFillQuaternary,
          }}
        >
          <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {activeErr ? (
              <span style={{ color: token.colorError }}>
                <ExclamationCircleFilled /> {activeErr}
              </span>
            ) : activeCol ? (
              <>
                <strong>{activeCol.label}</strong>
                {focus.r >= visible.length
                  ? ' · new row'
                  : activeRow?.isNew
                    ? ` · new row${requiredCols.length ? ' — fill the * columns to save' : ''}`
                    : ` · row ${focus.r + 1}`}
                {activeCol && isPick(activeCol) && !locked(activeRow, focus.c) && ' · type to search the list'}
                {activeCol && !activeCol.editable && ' · computed'}
              </>
            ) : null}
          </span>
          {stats && (
            <span style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
              Count {stats.count}
              {stats.n > 0 && (
                <>
                  {' · '}Sum {stats.sum.toLocaleString('en-US', { maximumFractionDigits: 2 })}
                  {' · '}Avg {(stats.sum / stats.n).toLocaleString('en-US', { maximumFractionDigits: 2 })}
                </>
              )}
            </span>
          )}
          <span style={{ whiteSpace: 'nowrap' }}>
            {visible.filter((r) => !r.isNew).length}
            {search ? ` of ${rows.filter((r) => !r.isNew).length}` : ''} rows
          </span>
        </div>
      </div>

      {editing && columns[editing.c] && (
        <CellEditor
          col={columns[editing.c]}
          opts={colOpts[editing.c]}
          value={visible[editing.r]?.v[columns[editing.c].name] ?? ''}
          seed={editing.seed}
          rect={editing.rect}
          hidden={editing.hidden}
          onCommit={commitEdit}
          onCancel={() => {
            setEditing(null);
            refocus();
          }}
        />
      )}

      {menu && (
        <div className="sg-menu" style={{ left: Math.min(menu.x, window.innerWidth - 220), top: Math.min(menu.y, window.innerHeight - 320) }}>
          {menuItem('Copy', () => document.execCommand('copy'), 'Ctrl+C')}
          {!readOnly && menuItem('Cut', () => document.execCommand('cut'), 'Ctrl+X')}
          {!readOnly &&
            menuItem(
              'Paste',
              () =>
                navigator.clipboard
                  ?.readText()
                  .then(pasteText)
                  .catch(() => message.info('Use Ctrl+V to paste — the browser blocked menu access to the clipboard.')),
              'Ctrl+V',
            )}
          {!readOnly && <hr />}
          {!readOnly && menuItem('Clear cells', clearRange, 'Delete')}
          {!readOnly && menuItem('Fill down', fillDown, 'Ctrl+D')}
          {!readOnly && <hr />}
          {!readOnly &&
            menuItem(
              nSel > 1 ? `Delete ${nSel} rows` : 'Delete row',
              () => deleteRows(selectedRows),
              undefined,
              !nSel || !deletable,
            )}
          {activeRow && !activeRow.isNew && (
            <>
              <hr />
              {menuItem('Row history', () => setHistoryOf(Number(activeRow.v.id)))}
              {onOpenRow && menuItem('Open record', () => onOpenRow(Number(activeRow.v.id)))}
            </>
          )}
        </div>
      )}

      {payload && (
        <>
          <RowHistory table={table} columns={payload.columns} options={payload.options} rowId={historyOf} onClose={() => setHistoryOf(null)} />
          <RecycleBin
            table={table}
            columns={payload.columns}
            options={payload.options}
            open={binOpen}
            onClose={() => setBinOpen(false)}
            onRestored={() => {
              void load();
              onChangedRef.current?.();
            }}
          />
        </>
      )}

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
                  <span>Also delete the {preview.missing_ids.length} row(s) that are in the table but missing from this file.</span>
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

function range(a: number, b: number): number[] {
  const out: number[] = [];
  for (let i = a; i <= b; i++) out.push(i);
  return out;
}
