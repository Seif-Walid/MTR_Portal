export interface ExploreEntity {
  table: string;
  label: string;
  singular: string;
  group: string;
  count: number;
  summary: string[];
}

export interface ExploreSchema {
  groups: string[];
  entities: ExploreEntity[];
  links: { source: string; column: string; target: string; label: string }[];
}

export type Cell = string | number | boolean | null;

export interface ExploreRow {
  id: number;
  title: string;
  fields: Record<string, Cell>;
}

export interface RecordRef {
  table: string;
  id: number;
  title: string;
  entity: string;
  relation?: string;
  via?: string;
}

export interface RelatedGroup {
  key: string;
  label: string;
  table: string;
  relation: string;
  via: string | null;
  total: number;
  columns: { name: string; label: string }[];
  rows: ExploreRow[];
}

export interface ExploreRecord {
  table: string;
  entity: string;
  group: string;
  id: number;
  title: string;
  fields: { name: string; label: string; value: Cell; link?: RecordRef; computed?: boolean }[];
  outgoing: RecordRef[];
  incoming: RelatedGroup[];
}

export interface SearchGroup {
  table: string;
  label: string;
  group: string;
  rows: { id: number; title: string }[];
}

export const pretty = (col: string) => col.replace(/_id$/, '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

export function formatCell(v: Cell, name = ''): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  // years, ids and ranks read wrong with a thousands separator
  if (typeof v === 'number' && /year|(^|_)id$|rank|sort_order/.test(name)) return String(v);
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  if (/^\d{4}-\d{2}-\d{2}T/.test(v)) return v.slice(0, 16).replace('T', ' ');
  return v;
}
