import { Button, Checkbox, DatePicker, Form, Input, Modal, Segmented, Select, message } from 'antd';
import type { Dayjs } from 'dayjs';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Task, TeamBlock, TeamOption, UserBrief } from '../api/types';
import { useAuth } from '../auth/AuthContext';

interface FormValues {
  assignee_ids?: number[];
  event_team_id?: number;
  people_team_id?: number;
  team_visible?: boolean;
  title: string;
  description?: string;
  due_date?: Dayjs;
  priority: string;
  category?: string;
}

type Target = 'people' | 'team';

export default function NewTaskModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { me } = useAuth();
  const [form] = Form.useForm<FormValues>();
  const [assignable, setAssignable] = useState<UserBrief[]>([]);
  const [teams, setTeams] = useState<TeamBlock[]>([]);
  const [target, setTarget] = useState<Target>('people');
  const [teamOptions, setTeamOptions] = useState<TeamOption[]>([]);
  const [busy, setBusy] = useState(false);
  const picked = Form.useWatch('assignee_ids', form);
  const peopleTeamId = Form.useWatch('people_team_id', form);

  useEffect(() => {
    if (open) {
      setTarget('people');
      setTeamOptions([]);
      api.get<UserBrief[]>('/api/users/assignable').then(setAssignable).catch(() => {});
      api
        .get<TeamBlock[]>('/api/team/mine')
        .then((blocks) => setTeams(blocks.filter((b) => b.kind === 'event')))
        .catch(() => {});
    }
  }, [open]);

  // Which team the task belongs to: the teams every selected assignee is on.
  // One candidate is picked automatically ("we're on the same team, obviously
  // that one"); several means the assigner says which, since the same person
  // can sit on Sumo 1 and Sumo 2 at once.
  useEffect(() => {
    const ids = picked ?? [];
    if (target !== 'people' || ids.length === 0) {
      setTeamOptions([]);
      form.setFieldValue('people_team_id', undefined);
      return;
    }
    let stale = false;
    api
      .get<TeamOption[]>(`/api/tasks/team-options?assignee_ids=${ids.join(',')}`)
      .then((options) => {
        if (stale) return;
        setTeamOptions(options);
        const current = form.getFieldValue('people_team_id') as number | undefined;
        if (options.length === 1) form.setFieldValue('people_team_id', options[0].team_id);
        else if (!options.some((o) => o.team_id === current))
          form.setFieldValue('people_team_id', undefined);
      })
      .catch(() => {});
    return () => {
      stale = true;
    };
  }, [picked, target, form]);

  const submit = async (values: FormValues) => {
    setBusy(true);
    try {
      const body =
        target === 'team'
          ? {
              title: values.title,
              description: values.description,
              event_team_id: values.event_team_id,
              team_visible: values.team_visible ?? false,
              due_date: values.due_date?.format('YYYY-MM-DD') ?? null,
              priority: values.priority,
              category: values.category,
            }
          : {
              title: values.title,
              description: values.description,
              assignee_ids: values.assignee_ids,
              event_team_id: values.people_team_id ?? null,
              team_visible: values.people_team_id ? (values.team_visible ?? false) : false,
              due_date: values.due_date?.format('YYYY-MM-DD') ?? null,
              priority: values.priority,
              category: values.category,
            };
      const created = await api.post<Task[]>('/api/tasks', body);
      message.success(
        created.length > 1 ? `Task assigned to ${created.length} people` : 'Task assigned',
      );
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
        <Form.Item label="Assign to">
          <Segmented
            block
            value={target}
            onChange={(v) => setTarget(v as Target)}
            options={[
              { label: 'People', value: 'people' },
              { label: 'A whole team', value: 'team' },
            ]}
          />
        </Form.Item>

        {target === 'people' ? (
          <>
            <Form.Item
              name="assignee_ids"
              label="Yourself or people connected below you — your reports, seats under yours, or a team you lead. Pick one or more to assign the same task"
              rules={[{ required: true, message: 'Pick at least one assignee' }]}
            >
              <Select
                mode="multiple"
                showSearch
                optionFilterProp="label"
                placeholder={assignable.length ? 'Select one or more people' : 'No one to assign to'}
                options={assignable.map((u) => ({
                  value: u.id,
                  label: `${u.full_name}${u.id === me?.id ? ' (you)' : ''} (${u.email})`,
                }))}
              />
            </Form.Item>
            {teamOptions.length > 0 && (
              <Form.Item
                name="people_team_id"
                label={
                  teamOptions.length === 1
                    ? "Team — the only one they're all on, selected for you"
                    : 'Which team is this task for? They are on more than one'
                }
                rules={[
                  {
                    required: teamOptions.length > 1,
                    message: 'Pick which team this task belongs to',
                  },
                ]}
              >
                <Select
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  placeholder="No team — a personal task"
                  options={teamOptions.map((t) => ({
                    value: t.team_id,
                    label: `${t.name} · ${t.category_name} · ${t.event_name}${
                      t.shared_with_me ? '' : ' (you are not on it)'
                    }`,
                  }))}
                />
              </Form.Item>
            )}
            {peopleTeamId !== undefined && peopleTeamId !== null && (
              <Form.Item name="team_visible" valuePropName="checked">
                <Checkbox>
                  Visible to the whole team (a shared board, not just each assignee)
                </Checkbox>
              </Form.Item>
            )}
          </>
        ) : (
          <>
            <Form.Item
              name="event_team_id"
              label="Team — the task fans out to every member you can task"
              rules={[{ required: true, message: 'Pick a team' }]}
            >
              <Select
                showSearch
                optionFilterProp="label"
                placeholder={teams.length ? 'Select a team' : "You're not on any event team"}
                options={teams.map((t) => ({
                  value: t.team_id as number,
                  label: `${t.name} · ${t.event_name}`,
                }))}
              />
            </Form.Item>
            <Form.Item name="team_visible" valuePropName="checked">
              <Checkbox>Visible to the whole team (a shared board, not just each assignee)</Checkbox>
            </Form.Item>
          </>
        )}

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
