import dayjs from 'dayjs';
import customParseFormat from 'dayjs/plugin/customParseFormat';

dayjs.extend(customParseFormat);

// Shared types and pure helpers of the spreadsheet grid: how a typed or pasted
// value becomes a cell value, how a cell value is shown, and TSV clipboard I/O
// compatible with Google Sheets / Excel.

export interface ColumnMeta {
  name: string;
  label: string;
  type: string; // int | number | str | bool | date | datetime
  editable: boolean;
  required: boolean;
  ref: string | null;
  choices: string[] | null;
}

export type Option = { value: string | number; label: string };

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

export interface ApplyError {
  row: number | null;
  column: string | null;
  message: string;
  /** 'conflict': the cell changed under the editor; `current` is what the database holds now */
  code?: string | null;
  current?: string | null;
  by?: string | null;
}

export interface ApplyResult {
  ok: boolean;
  errors: ApplyError[];
  summary: { adds: number; updates: number; deletes: number };
  ids: Record<string, number>;
  rows: Record<string, string>[] | null;
}

export const NUMBER_FMT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

export const isPick = (c: ColumnMeta) => !!(c.ref || c.choices);
/** a plain number column (a reference stored as an id is a pick-list, not a number) */
export const isNumeric = (c: ColumnMeta) => (c.type === 'number' || c.type === 'int') && !isPick(c);

export function optionsFor(col: ColumnMeta, options: Record<string, Option[]> | undefined): Option[] {
  if (col.ref) return options?.[col.name] ?? [];
  if (col.choices) return col.choices.map((c) => ({ value: c, label: c }));
  return [];
}

/** What a stored cell value reads as (ref ids become their label). */
export function displayText(col: ColumnMeta, value: string, opts: Option[]): string {
  if (value === '' || value == null) return '';
  if (isPick(col)) {
    const o = opts.find((x) => String(x.value) === value);
    return o ? o.label : value;
  }
  if (isNumeric(col) && value.trim() !== '' && !Number.isNaN(Number(value))) {
    return col.type === 'int' ? String(Number(value)) : NUMBER_FMT.format(Number(value));
  }
  if (col.type === 'datetime') {
    const d = dayjs(value);
    return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : value;
  }
  if (col.type === 'bool') return value === 'true' ? 'TRUE' : 'FALSE';
  return value;
}

/** The text a cell copies as — what someone pasting it elsewhere expects. */
export function copyText(col: ColumnMeta, value: string, opts: Option[]): string {
  if (isNumeric(col)) return value;
  return displayText(col, value, opts);
}

const DATE_FORMATS = [
  'YYYY-MM-DD', 'YYYY/MM/DD', 'D/M/YYYY', 'DD/MM/YYYY', 'D-M-YYYY', 'DD-MM-YYYY', 'D.M.YYYY',
  'D MMM YYYY', 'DD MMM YYYY', 'MMM D, YYYY', 'MMM D YYYY', 'D MMMM YYYY', 'MMMM D, YYYY', 'YYYY-MM-DDTHH:mm:ss',
];

function parseDate(raw: string): dayjs.Dayjs | null {
  const s = raw.trim();
  // spreadsheet serial day number (Excel / Sheets epoch 1899-12-30)
  if (/^\d{5}(\.\d+)?$/.test(s)) return dayjs('1899-12-30').add(Math.floor(Number(s)), 'day');
  for (const f of DATE_FORMATS) {
    const d = dayjs(s, f, true);
    if (d.isValid()) return d;
  }
  const loose = dayjs(s);
  return loose.isValid() ? loose : null;
}

export type Parsed = { ok: true; value: string } | { ok: false; error: string };

/** Turn typed / pasted text into a stored cell value, or say why it can't be. */
export function parseInput(col: ColumnMeta, raw: string, opts: Option[]): Parsed {
  const s = (raw ?? '').replace(/\r/g, '').trim();
  if (s === '') return { ok: true, value: '' };
  if (isPick(col)) {
    const low = s.toLowerCase();
    const exact =
      opts.find((o) => String(o.value) === s) ??
      opts.find((o) => o.label.toLowerCase() === low) ??
      opts.find((o) => String(o.value).toLowerCase() === low);
    if (exact) return { ok: true, value: String(exact.value) };
    const starts = opts.filter((o) => o.label.toLowerCase().startsWith(low));
    if (starts.length === 1) return { ok: true, value: String(starts[0].value) };
    const has = opts.filter((o) => o.label.toLowerCase().includes(low));
    if (has.length === 1) return { ok: true, value: String(has[0].value) };
    return {
      ok: false,
      error: has.length > 1 ? `“${s}” matches ${has.length} options — be more specific` : `“${s}” is not one of the options`,
    };
  }
  if (isNumeric(col)) {
    let t = s.replace(/[,\s]|EGP|USD|\$|£|€/gi, '');
    if (/^\(.*\)$/.test(t)) t = `-${t.slice(1, -1)}`; // accounting negatives
    const pct = t.endsWith('%');
    if (pct) t = t.slice(0, -1);
    let n = Number(t);
    if (t === '' || Number.isNaN(n)) return { ok: false, error: `“${s}” is not a number` };
    if (pct) n = n / 100;
    if (col.type === 'int') {
      if (!Number.isInteger(n)) return { ok: false, error: `“${s}” must be a whole number` };
      return { ok: true, value: String(n) };
    }
    return { ok: true, value: String(Math.round(n * 1e6) / 1e6) };
  }
  if (col.type === 'bool') {
    const low = s.toLowerCase();
    if (['true', 'yes', 'y', '1', '✓', 'x', 'on', 'checked'].includes(low)) return { ok: true, value: 'true' };
    if (['false', 'no', 'n', '0', 'off', 'unchecked', '-'].includes(low)) return { ok: true, value: 'false' };
    return { ok: false, error: `“${s}” is not yes/no` };
  }
  if (col.type === 'date') {
    const d = parseDate(s);
    return d ? { ok: true, value: d.format('YYYY-MM-DD') } : { ok: false, error: `“${s}” is not a date` };
  }
  if (col.type === 'datetime') {
    const d = parseDate(s);
    return d ? { ok: true, value: d.format('YYYY-MM-DDTHH:mm:ss') } : { ok: false, error: `“${s}” is not a date` };
  }
  return { ok: true, value: raw.replace(/\r/g, '') };
}

/** Parse clipboard TSV (quoted cells may hold tabs, newlines and "" escapes). */
export function parseTSV(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let i = 0;
  let quoted = false;
  const t = text.replace(/\r\n?/g, '\n');
  while (i < t.length) {
    const ch = t[i];
    if (quoted) {
      if (ch === '"' && t[i + 1] === '"') {
        cell += '"';
        i += 2;
        continue;
      }
      if (ch === '"') {
        quoted = false;
        i++;
        continue;
      }
      cell += ch;
      i++;
      continue;
    }
    if (ch === '"' && cell === '') {
      quoted = true;
      i++;
      continue;
    }
    if (ch === '\t') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else cell += ch;
    i++;
  }
  if (cell !== '' || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

export function toTSV(grid: string[][]): string {
  return grid
    .map((r) => r.map((c) => (/[\t\n"]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join('\t'))
    .join('\n');
}

export function defaultWidth(c: ColumnMeta): number {
  if (c.type === 'bool') return 84;
  if (c.type === 'int') return 90;
  if (c.type === 'number') return 120;
  if (c.type === 'date') return 124;
  if (c.type === 'datetime') return 150;
  if (c.ref) return 210;
  if (c.choices) return 140;
  return 180;
}
