import { Tag } from 'antd';

import type { Priority, RequestStatus, TaskStatus } from '../api/types';

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

export function RoleTags({ roles }: { roles: { slug: string; name: string }[] }) {
  return (
    <>
      {roles.map((r) => (
        <Tag key={r.slug} color="geekblue">
          {r.name}
        </Tag>
      ))}
    </>
  );
}
