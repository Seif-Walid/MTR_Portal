import { C, hexA } from '../theme/circuitTokens';
import type {
  AllocationPurpose,
  Condition,
  Priority,
  RequestStatus,
  TaskStatus,
} from '../api/types';

/* CIRCUIT status / priority / request chips. Mono, uppercase, hairline-bordered
   over a faint tint of the meaning colour. Export names/signatures match what
   the pages already import. */

// tint a colour (hex or rgb/rgba) to the given alpha — for chip border/fill.
const tint = (color: string, a: number): string => {
  if (color.startsWith('#')) return hexA(color, a);
  const m = color.match(/rgba?\(([^)]+)\)/);
  if (m) {
    const [r, g, b] = m[1].split(',').map((v) => v.trim());
    return `rgba(${r},${g},${b},${a})`;
  }
  return color;
};

const chip = (text: string, color: string) => (
  <span
    style={{
      fontFamily: C.mono,
      fontSize: 10,
      letterSpacing: '.06em',
      textTransform: 'uppercase',
      color,
      border: `1px solid ${tint(color, 0.35)}`,
      background: tint(color, 0.08),
      padding: '3px 9px',
      borderRadius: 5,
      whiteSpace: 'nowrap',
    }}
  >
    {text}
  </span>
);

// Kept for the Tasks status filter <Select> (reads .label per key). Colours
// mirror the chip meanings; every backend status is present, incl. approved.
export const STATUS_META: Record<TaskStatus, { label: string; color: string }> = {
  todo: { label: 'To do', color: C.textMuted },
  in_progress: { label: 'In progress', color: C.accent },
  submitted: { label: 'Submitted', color: C.violet },
  approved: { label: 'Approved', color: C.teal },
  revision_requested: { label: 'Needs revision', color: C.amber },
};

export function StatusTag({ status }: { status: TaskStatus }) {
  const meta = STATUS_META[status] ?? { label: status, color: C.textMuted };
  return chip(meta.label, meta.color);
}

const REQ_STATUS: Record<RequestStatus, { label: string; color: string }> = {
  pending: { label: 'Pending', color: C.amber },
  accepted: { label: 'Accepted', color: C.teal },
  declined: { label: 'Declined', color: C.danger },
};

export function RequestStatusTag({ status }: { status: RequestStatus }) {
  const meta = REQ_STATUS[status] ?? { label: status, color: C.textMuted };
  return chip(meta.label, meta.color);
}

const PRIORITY: Record<Priority, { label: string; color: string }> = {
  low: { label: 'Low', color: C.textMuted },
  medium: { label: 'Medium', color: C.accent },
  high: { label: 'High', color: C.amber },
  urgent: { label: 'Urgent', color: C.danger },
};

export function PriorityTag({ priority }: { priority: Priority }) {
  const m = PRIORITY[priority] ?? { label: priority, color: C.textMuted };
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: C.mono, fontSize: 11, color: m.color }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: m.color }} />
      {m.label}
    </span>
  );
}

export function BlockedTag() {
  return (
    <span
      style={{
        fontFamily: C.mono,
        fontSize: 9,
        fontWeight: 600,
        letterSpacing: '.08em',
        color: C.danger,
        border: `1px solid ${hexA(C.danger, 0.4)}`,
        background: hexA(C.danger, 0.1),
        padding: '3px 7px',
        borderRadius: 4,
      }}
    >
      BLOCKED
    </span>
  );
}

// ---- Inventory chips (unchanged callers) — restyled to CIRCUIT ------------
export const PURPOSE_META: Record<AllocationPurpose, { label: string; color: string }> = {
  training: { label: 'Training', color: C.accent },
  competition: { label: 'Competition', color: C.amber },
  research: { label: 'R&D', color: C.violet },
  borrowed: { label: 'Borrowed', color: C.steel },
  other: { label: 'Other', color: C.textMuted },
};

const CONDITION_META: Record<Condition, { label: string; color: string }> = {
  new: { label: 'New', color: C.teal },
  good: { label: 'Good', color: C.accent },
  fair: { label: 'Fair', color: C.amber },
  poor: { label: 'Poor', color: C.amber },
  damaged: { label: 'Damaged', color: C.danger },
};

export function ConditionTag({ condition }: { condition: Condition }) {
  const meta = CONDITION_META[condition] ?? { label: condition, color: C.textMuted };
  return chip(meta.label, meta.color);
}

export function PurposeTag({ purpose }: { purpose: AllocationPurpose }) {
  const meta = PURPOSE_META[purpose] ?? { label: purpose, color: C.textMuted };
  return chip(meta.label, meta.color);
}
