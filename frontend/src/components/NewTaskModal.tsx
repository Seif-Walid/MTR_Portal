import { Button, DatePicker, Form, Input, Modal, Select, message } from 'antd';
import type { Dayjs } from 'dayjs';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Task, UserBrief } from '../api/types';

interface FormValues {
  assignee_id: number;
  title: string;
  description?: string;
  due_date?: Dayjs;
  priority: string;
  category?: string;
}

export default function NewTaskModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form] = Form.useForm<FormValues>();
  const [assignable, setAssignable] = useState<UserBrief[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      api.get<UserBrief[]>('/api/users/assignable').then(setAssignable).catch(() => {});
    }
  }, [open]);

  const submit = async (values: FormValues) => {
    setBusy(true);
    try {
      await api.post<Task>('/api/tasks', {
        ...values,
        due_date: values.due_date?.format('YYYY-MM-DD') ?? null,
      });
      message.success('Task assigned');
      form.resetFields();
      onCreated();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to create task');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title="Assign a task" footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={submit} initialValues={{ priority: 'medium' }}>
        <Form.Item
          name="assignee_id"
          label="Assign to (people below you in the hierarchy)"
          rules={[{ required: true, message: 'Pick an assignee' }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            placeholder={assignable.length ? 'Select a person' : 'No one reports to you'}
            options={assignable.map((u) => ({
              value: u.id,
              label: `${u.full_name} (${u.email})`,
            }))}
          />
        </Form.Item>
        <Form.Item name="title" label="Title" rules={[{ required: true, max: 255 }]}>
          <Input placeholder="What needs to be done?" />
        </Form.Item>
        <Form.Item name="description" label="Description">
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item name="due_date" label="Due date">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="priority" label="Priority">
          <Select
            options={['low', 'medium', 'high', 'urgent'].map((p) => ({
              value: p,
              label: p.toUpperCase(),
            }))}
          />
        </Form.Item>
        <Form.Item name="category" label="Category">
          <Input placeholder="e.g. design, bug, research" />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={busy} block>
          Assign task
        </Button>
      </Form>
    </Modal>
  );
}
