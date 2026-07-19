import { Tag } from 'antd';

import type {
  AllocationPurpose,
  Condition,
  Priority,
  RequestStatus,
  TaskStatus,
} from '../api/types';

export const STATUS_META: Record<TaskStatus, { label: string; color: string }> = {
  todo: { label: 'To Do', color: 'default' },
  in_progress: { label: 'In Progress', color: 'processing' },
  submitted: { label: 'Submitted for Review', color: 'warning' },
  approved: { label: 'Approved', color: 'success' },
  revision_requested: { label: 'Revision Requested', color: 'error' },
};

const PRIORITY_COLOR: Record<Priority, string> = {
  low: 'default',
  medium: 'blue',
  high: 'orange',
  urgent: 'red',
};

const REQUEST_COLOR: Record<RequestStatus, string> = {
  pending: 'processing',
  accepted: 'success',
  declined: 'error',
};

export function StatusTag({ status }: { status: TaskStatus }) {
  const meta = STATUS_META[status] ?? { label: status, color: 'default' };
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

export function PriorityTag({ priority }: { priority: Priority }) {
  return <Tag color={PRIORITY_COLOR[priority] ?? 'default'}>{priority.toUpperCase()}</Tag>;
}

export function RequestStatusTag({ status }: { status: RequestStatus }) {
  return <Tag color={REQUEST_COLOR[status] ?? 'default'}>{status.toUpperCase()}</Tag>;
}

export const PURPOSE_META: Record<AllocationPurpose, { label: string; color: string }> = {
  training: { label: 'Training', color: 'blue' },
  competition: { label: 'Competition', color: 'gold' },
  research: { label: 'R&D', color: 'purple' },
  borrowed: { label: 'Borrowed', color: 'orange' },
  other: { label: 'Other', color: 'default' },
};

const CONDITION_META: Record<Condition, { label: string; color: string }> = {
  new: { label: 'New', color: 'green' },
  good: { label: 'Good', color: 'cyan' },
  fair: { label: 'Fair', color: 'gold' },
  poor: { label: 'Poor', color: 'orange' },
  damaged: { label: 'Damaged', color: 'red' },
};

export function ConditionTag({ condition }: { condition: Condition }) {
  const meta = CONDITION_META[condition] ?? { label: condition, color: 'default' };
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

export function PurposeTag({ purpose }: { purpose: AllocationPurpose }) {
  const meta = PURPOSE_META[purpose] ?? { label: purpose, color: 'default' };
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

