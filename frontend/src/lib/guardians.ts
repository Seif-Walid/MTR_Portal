// Guardian numbers live in the single `guardian_phone` roster cell as a
// comma-separated list, each entry optionally tagged with a kinship label in
// parentheses, e.g. `01000000000 (Father), 01111111111 (Uncle), 01222222222`.
// Keeping it one flat text cell means the bulk editor, Sheets mirror and roster
// importer still treat it as ordinary text.

export type GuardianKind = 'father' | 'mother' | 'other' | '';

export interface Guardian {
  number: string;
  kind: GuardianKind;
  other: string; // free-text label used only when kind === 'other'
}

export const KIND_OPTIONS = [
  { value: 'father', label: 'Father' },
  { value: 'mother', label: 'Mother' },
  { value: 'other', label: 'Other' },
] as const;

const CANON: Record<string, GuardianKind> = { father: 'father', mother: 'mother' };

/** Label written into the cell for a guardian, or '' when none should show. */
function labelFor(g: Guardian): string {
  if (g.kind === 'father') return 'Father';
  if (g.kind === 'mother') return 'Mother';
  if (g.kind === 'other') return g.other.trim();
  return '';
}

/** Encode rows back into the flat cell; blank-number rows are dropped. Returns
 *  null when nothing remains so the column clears instead of storing ''. */
export function encodeGuardians(rows: Guardian[]): string | null {
  const parts = rows
    .map((g) => {
      const number = g.number.trim();
      if (!number) return '';
      const label = labelFor(g);
      return label ? `${number} (${label})` : number;
    })
    .filter(Boolean);
  return parts.length ? parts.join(', ') : null;
}

/** Parse the flat cell into rows. A `(label)` maps to father/mother when it
 *  matches those, otherwise it's kept as an `other` free-text label. */
export function parseGuardians(raw: string | null | undefined): Guardian[] {
  if (!raw) return [];
  return raw
    .split(',')
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((entry) => {
      const m = entry.match(/^(.*?)(?:\s*\(([^)]*)\))?$/);
      const number = (m?.[1] ?? entry).trim();
      const label = (m?.[2] ?? '').trim();
      if (!label) return { number, kind: '' as GuardianKind, other: '' };
      const canon = CANON[label.toLowerCase()];
      if (canon) return { number, kind: canon, other: '' };
      return { number, kind: 'other' as GuardianKind, other: label };
    })
    .filter((g) => g.number);
}
