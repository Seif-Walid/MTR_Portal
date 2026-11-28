import { Button, Checkbox, DatePicker, Form, Input, Modal, Segmented, Select, message } from 'antd';
import type { Dayjs } from 'dayjs';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { Task, TaskScope, TeamBlock, TeamOption, UserBrief } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { personLabel } from '../lib/people';

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
  scope,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  /** Opened from inside an event's tab (and maybe one team's chip): people
   * and teams are picked from that event/team instead of the whole roster. */
  scope?: { event: TaskScope; teamId: number | null } | null;
}) {
  const { me } = useAuth();
  const [form] = Form.useForm<FormValues>();
  const [assignable, setAssignable] = useState<UserBrief[]>([]);
  const [teams, setTeams] = useState<{ team_id: number; label: string }[]>([]);
  const [narrow, setNarrow] = useState(true);
  const [target, setTarget] = useState<Target>('people');
  const [teamOptions, setTeamOptions] = useState<TeamOption[]>([]);
  const [busy, setBusy] = useState(false);
  const picked = Form.useWatch('assignee_ids', form);
  const peopleTeamId = Form.useWatch('people_team_id', form);

  const scopeTeamId = scope?.teamId ?? null;
  const scopeTeam = scope?.event.teams.find((t) => t.team_id === scopeTeamId) ?? null;
  const narrowed = !!scope && narrow;
  const scopeEventId = scope?.event.event_id ?? null;

  useEffect(() => {
    if (open) {
      setNarrow(true);
      setTarget('people');
      setTeamOptions([]);
      if (scope) {
        setTeams(scope.event.teams.map((t) => ({ team_id: t.team_id, label: `${t.path_name} · ${t.category_name}` })));
        if (scopeTeamId != null) form.setFieldValue('event_team_id', scopeTeamId);
      } else {
        api
          .get<TeamBlock[]>('/api/team/mine')
          .then((blocks) => setTeams(blocks
            .filter((b) => b.kind === 'event' && b.team_id != null)
            .map((b) => ({ team_id: b.team_id as number, label: `${b.name} · ${b.event_name}` }))))
          .catch(() => {});
      }
    }
  }, [open, scopeEventId, scopeTeamId, form]); // eslint-disable-line react-hooks/exhaustive-deps

  // who can be picked: the open team's / event's people, or everyone you may task
  useEffect(() => {
    if (!open) return;
    const qs = narrowed
      ? scopeTeamId != null ? `?team_id=${scopeTeamId}` : `?event_id=${scopeEventId}`
      : '';
    api.get<UserBrief[]>(`/api/users/assignable${qs}`).then(setAssignable).catch(() => {});
  }, [open, narrowed, scopeTeamId, scopeEventId]);

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
    if (narrowed && scopeTeam) {
      setTeamOptions([{ team_id: scopeTeam.team_id, name: scopeTeam.path_name, event_name: scope!.event.name,
        category_name: scopeTeam.category_name, shared_with_me: true }]);
      form.setFieldValue('people_team_id', scopeTeam.team_id);
      return;
    }
    let stale = false;
    api
      .get<TeamOption[]>(`/api/tasks/team-options?assignee_ids=${ids.join(',')}`)
      .then((all) => {
        if (stale) return;
        const inEvent = new Set(scope?.event.teams.map((t) => t.team_id) ?? []);
        const options = narrowed ? all.filter((o) => inEvent.has(o.team_id)) : all;
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
  }, [picked, target, form, narrowed, scopeTeam?.team_id, scopeEventId]); // eslint-disable-line react-hooks/exhaustive-deps

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
              label={narrowed
                ? `People on ${scopeTeam ? scopeTeam.path_name : scope!.event.name} — pick one or more to assign the same task`
                : 'Yourself or people connected below you — your reports, seats under yours, or a team you lead. Pick one or more to assign the same task'}
              extra={scope && (
                <Button type="link" size="small" style={{ padding: 0 }}
                  onClick={() => { setNarrow(!narrow); form.setFieldValue('assignee_ids', []); }}>
                  {narrow ? 'Pick from everyone instead' : `Only people on ${scopeTeam ? scopeTeam.path_name : scope.event.name}`}
                </Button>
              )}
              rules={[{ required: true, message: 'Pick at least one assignee' }]}
            >
              <Select
                mode="multiple"
                showSearch
                optionFilterProp="label"
                placeholder={assignable.length ? 'Select one or more people' : narrowed ? 'No one on this team you can task yet' : 'No one to assign to'}
                options={assignable.map((u) => ({
                  value: u.id,
                  label: u.id === me?.id ? `${personLabel(u)} · you` : personLabel(u),
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
                placeholder={teams.length ? 'Select a team' : scope ? 'This event has no teams yet' : "You're not on any event team"}
                options={teams.map((t) => ({ value: t.team_id, label: t.label }))}
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
