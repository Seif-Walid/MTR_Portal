import { PaperClipOutlined, UploadOutlined } from '@ant-design/icons';
import {
  Button,
  Descriptions,
  Divider,
  Drawer,
  List,
  Space,
  Typography,
  Upload,
  message,
} from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Task, TaskStatus } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { PriorityTag, StatusTag } from './tags';

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
  const [busy, setBusy] = useState(false);

  const load = (id: number) =>
    api
      .get<Task>(`/api/tasks/${id}`)
      .then(setTask)
      .catch((e) => message.error(e.message));

  useEffect(() => {
    setTask(null);
    if (taskId !== null) void load(taskId);
  }, [taskId]);

  if (!me) return null;

  const setStatus = async (to: TaskStatus) => {
    if (!task) return;
    setBusy(true);
    try {
      setTask(await api.patch<Task>(`/api/tasks/${task.id}/status`, { status: to }));
      onChanged();
      message.success('Status updated');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to update');
    } finally {
      setBusy(false);
    }
  };

  const isAssignee = task?.assignee.id === me.id;
  const actions = task
    ? [
        ...(isAssignee || me.is_admin ? ASSIGNEE_ACTIONS[task.status] ?? [] : []),
        // the API decides who may review; we optimistically show the buttons
        // to anyone who is not the assignee and let 403s surface otherwise
        ...(!isAssignee || me.is_admin ? REVIEWER_ACTIONS[task.status] ?? [] : []),
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

  return (
    <Drawer open={taskId !== null} onClose={onClose} width={560} title={task?.title ?? 'Task'}>
      {task && (
        <>
          <Space wrap>
            <StatusTag status={task.status} />
            <PriorityTag priority={task.priority} />
            {task.category && <Typography.Text type="secondary">#{task.category}</Typography.Text>}
          </Space>
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
          {(isAssignee || task.assigner.id === me.id || me.is_admin) && (
            <Upload beforeUpload={upload} showUploadList={false}>
              <Button icon={<UploadOutlined />} style={{ marginTop: 8 }}>
                Add attachment
              </Button>
            </Upload>
          )}
        </>
      )}
    </Drawer>
  );
}
