import { PaperClipOutlined, StopOutlined, UploadOutlined } from '@ant-design/icons';
import {
  Alert,
  Avatar,
  Button,
  Descriptions,
  Divider,
  Drawer,
  Input,
  List,
  Space,
  Typography,
  Upload,
  message,
} from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Task, TaskHistoryEntry, TaskStatus } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { PriorityTag, STATUS_META, StatusTag } from './tags';

type ActivityItem =
  | { kind: 'comment'; at: string; author: string; body: string }
  | { kind: 'history'; at: string; actor: string; action: string; detail: string };

function historyLine(actor: string, action: string, detail: string): string {
  let d: Record<string, unknown> = {};
  try {
    d = JSON.parse(detail);
  } catch {
    /* ignore */
  }
  switch (action) {
    case 'created':
      return `${actor} created this task, assigned to ${d.assignee ?? '—'}`;
    case 'status_changed': {
      const from = STATUS_META[d.from as TaskStatus]?.label ?? String(d.from);
      const to = STATUS_META[d.to as TaskStatus]?.label ?? String(d.to);
      return `${actor} moved this from "${from}" to "${to}"`;
    }
    case 'edited': {
      const fields = Array.isArray(d.changed_fields) ? d.changed_fields.join(', ') : '';
      return `${actor} edited ${fields || 'this task'}`;
    }
    case 'blocked':
      return `${actor} marked this blocked${d.reason ? `: ${d.reason}` : ''}`;
    case 'unblocked':
      return `${actor} unblocked this task`;
    default:
      return `${actor} ${action}`;
  }
}

interface WorkflowAction {
  to: TaskStatus;
  label: string;
  danger?: boolean;
}

// which transitions each party may trigger from a given status
const ASSIGNEE_ACTIONS: Partial<Record<TaskStatus, WorkflowAction[]>> = {
  todo: [{ to: 'in_progress', label: 'Start Working' }],
  in_progress: [
    { to: 'submitted', label: 'Submit for Review' },
    { to: 'todo', label: 'Move back to To Do' },
  ],
  revision_requested: [{ to: 'in_progress', label: 'Resume Work' }],
};

const REVIEWER_ACTIONS: Partial<Record<TaskStatus, WorkflowAction[]>> = {
  submitted: [
    { to: 'approved', label: 'Approve' },
    { to: 'revision_requested', label: 'Request Revision', danger: true },
  ],
};

export default function TaskDrawer({
  taskId,
  onClose,
  onChanged,
}: {
  taskId: number | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { me } = useAuth();
  const [task, setTask] = useState<Task | null>(null);
  const [history, setHistory] = useState<TaskHistoryEntry[]>([]);
  const [batch, setBatch] = useState<Task[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [blocking, setBlocking] = useState(false);
  const [blockReason, setBlockReason] = useState('');
  const [commentBody, setCommentBody] = useState('');
  const [commenting, setCommenting] = useState(false);

  const load = (id: number) =>
    api
      .get<Task>(`/api/tasks/${id}`)
      .then(setTask)
      .catch((e) => message.error(e.message));

  useEffect(() => {
    setTask(null);
    setHistory([]);
    setBatch(null);
    setBlocking(false);
    setBlockReason('');
    if (taskId !== null) {
      void load(taskId);
      api.get<TaskHistoryEntry[]>(`/api/tasks/${taskId}/history`).then(setHistory).catch(() => {});
    }
  }, [taskId]);

  useEffect(() => {
    if (task?.batch_id && me && (task.assigner.id === me.id || me.level?.rank === 1)) {
      api.get<Task[]>(`/api/tasks/batch/${task.batch_id}`).then(setBatch).catch(() => setBatch(null));
    } else {
      setBatch(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.batch_id]);

  if (!me) return null;

  const refreshHistory = (id: number) =>
    api.get<TaskHistoryEntry[]>(`/api/tasks/${id}/history`).then(setHistory).catch(() => {});

  const setStatus = async (to: TaskStatus) => {
    if (!task) return;
    setBusy(true);
    try {
      setTask(await api.patch<Task>(`/api/tasks/${task.id}/status`, { status: to }));
      await refreshHistory(task.id);
      onChanged();
      message.success('Status updated');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to update');
    } finally {
      setBusy(false);
    }
  };

  const isAssignee = task?.assignee.id === me.id;
  const isAssigner = task?.assigner.id === me.id;
  const canToggleBlocked = isAssignee || isAssigner || me.level?.rank === 1;
  const actions = task
    ? [
        ...(isAssignee || me.level?.rank === 1 ? ASSIGNEE_ACTIONS[task.status] ?? [] : []),
        // the API decides who may review; we optimistically show the buttons
        // to anyone who is not the assignee and let 403s surface otherwise
        ...(!isAssignee || me.level?.rank === 1 ? REVIEWER_ACTIONS[task.status] ?? [] : []),
      ]
    : [];

  const upload = async (file: File) => {
    if (!task) return false;
    const form = new FormData();
    form.append('file', file);
    try {
      await api.upload(`/api/tasks/${task.id}/attachments`, form);
      await load(task.id);
      message.success('Attachment uploaded');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Upload failed');
    }
    return false; // prevent antd's own upload
  };

  const submitBlock = async (isBlocked: boolean) => {
    if (!task) return;
    setBusy(true);
    try {
      setTask(await api.patch<Task>(`/api/tasks/${task.id}/blocked`, { is_blocked: isBlocked, reason: blockReason }));
      await refreshHistory(task.id);
      setBlocking(false);
      setBlockReason('');
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to update');
    } finally {
      setBusy(false);
    }
  };

  const submitComment = async () => {
    if (!task || !commentBody.trim()) return;
    setCommenting(true);
    try {
      setTask(await api.post<Task>(`/api/tasks/${task.id}/comments`, { body: commentBody.trim() }));
      setCommentBody('');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to comment');
    } finally {
      setCommenting(false);
    }
  };

  const activity: ActivityItem[] = task
    ? [
        ...task.comments.map(
          (c): ActivityItem => ({ kind: 'comment', at: c.created_at, author: c.author.full_name, body: c.body }),
        ),
        ...history.map(
          (h): ActivityItem => ({ kind: 'history', at: h.created_at, actor: h.actor, action: h.action, detail: h.detail }),
        ),
      ].sort((a, b) => a.at.localeCompare(b.at))
    : [];

  return (
    <Drawer open={taskId !== null} onClose={onClose} width={560} title={task?.title ?? 'Task'}>
      {task && (
        <>
          <Space wrap>
            <StatusTag status={task.status} />
            <PriorityTag priority={task.priority} />
            {task.category && <Typography.Text type="secondary">#{task.category}</Typography.Text>}
          </Space>

          {task.is_blocked && (
            <Alert
              type="error"
              showIcon
              icon={<StopOutlined />}
              style={{ marginTop: 12 }}
              message="Blocked"
              description={task.blocked_reason || 'No reason given'}
              action={
                canToggleBlocked && (
                  <Button size="small" danger loading={busy} onClick={() => submitBlock(false)}>
                    Unblock
                  </Button>
                )
              }
            />
          )}

          {batch && batch.length > 1 && (
            <Alert
              type="info"
              style={{ marginTop: 12 }}
              message={`Part of a team assignment — ${batch.length} people`}
              description={
                <Space direction="vertical" size={2}>
                  {batch.map((t) => (
                    <Space key={t.id} size={6}>
                      <Typography.Text>{t.assignee.full_name}</Typography.Text>
                      <StatusTag status={t.status} />
                      {t.is_blocked && <Typography.Text type="danger">blocked</Typography.Text>}
                    </Space>
                  ))}
                </Space>
              }
            />
          )}

          <Descriptions column={1} size="small" style={{ marginTop: 16 }}>
            <Descriptions.Item label="Assigned by">{task.assigner.full_name}</Descriptions.Item>
            <Descriptions.Item label="Assigned to">{task.assignee.full_name}</Descriptions.Item>
            <Descriptions.Item label="Due date">
              {task.due_date ? dayjs(task.due_date).format('DD MMM YYYY') : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="Created">
              {dayjs(task.created_at).format('DD MMM YYYY HH:mm')}
            </Descriptions.Item>
            {task.origin_request_id && (
              <Descriptions.Item label="Origin">
                Spawned from request #{task.origin_request_id}
              </Descriptions.Item>
            )}
          </Descriptions>
          {task.description && (
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginTop: 8 }}>
              {task.description}
            </Typography.Paragraph>
          )}

          {canToggleBlocked && !task.is_blocked && (
            <div style={{ marginTop: 8 }}>
              {blocking ? (
                <Space.Compact style={{ width: '100%' }}>
                  <Input
                    placeholder="Why is this blocked?"
                    value={blockReason}
                    onChange={(e) => setBlockReason(e.target.value)}
                    onPressEnter={() => submitBlock(true)}
                  />
                  <Button danger loading={busy} onClick={() => submitBlock(true)}>
                    Mark blocked
                  </Button>
                  <Button onClick={() => setBlocking(false)}>Cancel</Button>
                </Space.Compact>
              ) : (
                <Button size="small" icon={<StopOutlined />} onClick={() => setBlocking(true)}>
                  Mark as blocked
                </Button>
              )}
            </div>
          )}

          {actions.length > 0 && (
            <>
              <Divider plain>Workflow</Divider>
              <Space wrap>
                {actions.map((a) => (
                  <Button
                    key={a.to}
                    danger={a.danger}
                    type={a.to === 'approved' ? 'primary' : 'default'}
                    loading={busy}
                    onClick={() => setStatus(a.to)}
                  >
                    {a.label}
                  </Button>
                ))}
              </Space>
            </>
          )}

          <Divider plain>Attachments</Divider>
          <List
            size="small"
            locale={{ emptyText: 'No attachments' }}
            dataSource={task.attachments}
            renderItem={(a) => (
              <List.Item>
                <a href={`/api/tasks/attachments/${a.id}`} target="_blank" rel="noreferrer">
                  <PaperClipOutlined /> {a.filename}
                </a>
                <Typography.Text type="secondary">{(a.size / 1024).toFixed(1)} KB</Typography.Text>
              </List.Item>
            )}
          />
          {(isAssignee || task.assigner.id === me.id || me.level?.rank === 1) && (
            <Upload beforeUpload={upload} showUploadList={false}>
              <Button icon={<UploadOutlined />} style={{ marginTop: 8 }}>
                Add attachment
              </Button>
            </Upload>
          )}

          <Divider plain>Activity</Divider>
          <List
            size="small"
            locale={{ emptyText: 'No activity yet' }}
            dataSource={activity}
            renderItem={(item) =>
              item.kind === 'comment' ? (
                <List.Item>
                  <Space align="start">
                    <Avatar size="small">{item.author.charAt(0)}</Avatar>
                    <div>
                      <div>
                        <Typography.Text strong>{item.author}</Typography.Text>{' '}
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {dayjs(item.at).format('DD MMM HH:mm')}
                        </Typography.Text>
                      </div>
                      <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>{item.body}</Typography.Text>
                    </div>
                  </Space>
                </List.Item>
              ) : (
                <List.Item>
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    {historyLine(item.actor, item.action, item.detail)} ·{' '}
                    {dayjs(item.at).format('DD MMM HH:mm')}
                  </Typography.Text>
                </List.Item>
              )
            }
          />
          <Space.Compact style={{ width: '100%', marginTop: 8 }}>
            <Input
              placeholder="Add a comment…"
              value={commentBody}
              onChange={(e) => setCommentBody(e.target.value)}
              onPressEnter={submitComment}
            />
            <Button loading={commenting} disabled={!commentBody.trim()} onClick={submitComment}>
              Comment
            </Button>
          </Space.Compact>
        </>
      )}
    </Drawer>
  );
}
