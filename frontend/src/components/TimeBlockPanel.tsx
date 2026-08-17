import { CalendarOutlined, DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Checkbox, DatePicker, Form, Input, Modal, Popconfirm, Radio, Space, message } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client';
import type { TeamBlock, TimeBlock } from '../api/types';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const AMBER = '#ffb26b';

// bit i = Python weekday: Monday=0 .. Sunday=6
const WEEKDAYS = [
  { label: 'Mon', bit: 0 }, { label: 'Tue', bit: 1 }, { label: 'Wed', bit: 2 },
  { label: 'Thu', bit: 3 }, { label: 'Fri', bit: 4 }, { label: 'Sat', bit: 5 }, { label: 'Sun', bit: 6 },
];

function maskLabel(mask: number): string {
  if (mask === 0) return 'Every day';
  return WEEKDAYS.filter((w) => mask & (1 << w.bit)).map((w) => w.label).join(' · ');
}

// the query that identifies this team's blocks, or null if it can't be anchored
function anchorQuery(block: TeamBlock): string | null {
  if (block.kind === 'event' && block.team_id != null) return `team_type=event&event_team_id=${block.team_id}`;
  if (block.kind === 'org' && block.position_id != null) return `team_type=org&position_id=${block.position_id}`;
  return null;
}

export default function TimeBlockPanel({ block }: { block: TeamBlock }) {
  const [blocks, setBlocks] = useState<TimeBlock[]>([]);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const [mode, setMode] = useState<'span' | 'weekly'>('span');
  const [editing, setEditing] = useState<TimeBlock | null>(null);

  const query = anchorQuery(block);

  const load = useCallback(() => {
    if (!query) return;
    api.get<TimeBlock[]>(`/api/timeblocks?${query}`).then(setBlocks).catch(() => setBlocks([]));
  }, [query]);

  useEffect(load, [load]);

  if (!query) return null; // org unit with no schedulable anchor

  // event teams: can't schedule outside the event's own span; org units: no bound
  const disabledDate = (d: Dayjs): boolean => {
    if (block.kind !== 'event') return false;
    if (block.event_start && d.isBefore(dayjs(block.event_start), 'day')) return true;
    if (block.event_end && d.isAfter(dayjs(block.event_end), 'day')) return true;
    return false;
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setMode('span');
    setOpen(true);
  };

  const openEdit = (b: TimeBlock) => {
    setEditing(b);
    setMode(b.weekday_mask === 0 ? 'span' : 'weekly');
    form.setFieldsValue({
      title: b.title,
      range: [dayjs(b.start_date), dayjs(b.end_date)],
      weekdays: WEEKDAYS.filter((w) => b.weekday_mask & (1 << w.bit)).map((w) => w.bit),
    });
    setOpen(true);
  };

  const close = () => { setOpen(false); setEditing(null); form.resetFields(); setMode('span'); };

  const submit = async () => {
    const v = await form.validateFields();
    const [start, end] = v.range as [Dayjs, Dayjs];
    const mask = mode === 'weekly'
      ? (v.weekdays as number[] ?? []).reduce((m, bit) => m | (1 << bit), 0)
      : 0;
    if (mode === 'weekly' && mask === 0) { message.error('Pick at least one weekday'); return; }
    setSaving(true);
    try {
      if (editing) {
        await api.patch<TimeBlock>(`/api/timeblocks/${editing.id}`, {
          title: v.title?.trim() ?? '',
          start_date: start.format('YYYY-MM-DD'),
          end_date: end.format('YYYY-MM-DD'),
          weekday_mask: mask,
        });
        message.success('Time block updated');
      } else {
        await api.post<TimeBlock>('/api/timeblocks', {
          team_type: block.kind,
          event_team_id: block.kind === 'event' ? block.team_id : null,
          position_id: block.kind === 'org' ? block.position_id : null,
          title: v.title?.trim() ?? '',
          start_date: start.format('YYYY-MM-DD'),
          end_date: end.format('YYYY-MM-DD'),
          weekday_mask: mask,
        });
        message.success('Time block added');
      }
      close();
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : 'Failed');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: number) => {
    try { await api.delete(`/api/timeblocks/${id}`); load(); }
    catch (e) { message.error(e instanceof Error ? e.message : 'Failed'); }
  };

  return (
    <div style={{ marginTop: 4, marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: blocks.length ? 10 : 0 }}>
        <span style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.14em', textTransform: 'uppercase', color: 'rgba(224,236,252,.45)' }}>
          <CalendarOutlined style={{ marginRight: 6, color: AMBER }} />Calendar time
        </span>
        {block.can_schedule && (
          <Button size="small" icon={<PlusOutlined />} onClick={openCreate}>Schedule time</Button>
        )}
      </div>

      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        {blocks.map((b) => (
          <div key={b.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '7px 12px', borderRadius: 8, border: `1px solid rgba(255,178,107,.25)`, background: 'rgba(255,178,107,.06)' }}>
            <span style={{ color: '#eaf2ff', fontSize: 13 }}>{b.title || block.name}</span>
            <span style={{ fontFamily: MONO, fontSize: 11, color: 'rgba(224,236,252,.6)' }}>
              {b.start_date} → {b.end_date}
            </span>
            <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: '.06em', textTransform: 'uppercase', color: AMBER, border: `1px solid rgba(255,178,107,.3)`, padding: '1px 7px', borderRadius: 5 }}>
              {maskLabel(b.weekday_mask)}
            </span>
            <span style={{ flex: 1 }} />
            {block.can_schedule && (
              <>
                <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(b)} />
                <Popconfirm title="Remove this time block?" onConfirm={() => remove(b.id)} okText="Remove" okButtonProps={{ danger: true }}>
                  <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </>
            )}
          </div>
        ))}
      </Space>

      <Modal title={`${editing ? 'Edit time' : 'Schedule time'} — ${block.name}`} open={open} onOk={submit} confirmLoading={saving}
        okText={editing ? 'Save changes' : 'Add block'} onCancel={close} destroyOnClose>
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item name="title" label="Label (optional)">
            <Input placeholder={block.name} maxLength={255} />
          </Form.Item>
          <Form.Item name="range"
            label={block.kind === 'event' && (block.event_start || block.event_end)
              ? `Date range (event: ${block.event_start ?? '…'} → ${block.event_end ?? '…'})`
              : 'Date range'}
            rules={[{ required: true, message: 'Pick a start and end date' }]}>
            <DatePicker.RangePicker style={{ width: '100%' }} disabledDate={disabledDate} />
          </Form.Item>
          <Form.Item label="Occupies">
            <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)}>
              <Radio.Button value="span">Whole range</Radio.Button>
              <Radio.Button value="weekly">Certain weekdays</Radio.Button>
            </Radio.Group>
          </Form.Item>
          {mode === 'weekly' && (
            <Form.Item name="weekdays" label="Weekdays">
              <Checkbox.Group options={WEEKDAYS.map((w) => ({ label: w.label, value: w.bit }))} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
