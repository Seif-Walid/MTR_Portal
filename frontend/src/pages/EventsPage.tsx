import { DeleteOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons';
import {
  Button, DatePicker, Empty, Form, Input, List, Modal, Popconfirm, Space, Tag, Typography, message,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { Event, EventKind, RoleRoot } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import EventDetailPanel from '../components/EventDetailPanel';
import PositionPicker from '../components/PositionPicker';

const MONO = "'Geist Mono Variable', 'Geist Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk Variable', 'Space Grotesk', sans-serif";

interface FormValues {
  name: string;
  description?: string;
  dates?: [Dayjs, Dayjs];
  role_root_position_id?: number;
}

/* ---- EventModal — unchanged auth/data flow -------------------------------- */
function EventModal({ kind, event, open, onClose, onSaved }: {
  kind: EventKind;
  event: Event | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form] = Form.useForm<FormValues>();
  const [busy, setBusy] = useState(false);
  const [needsRoot, setNeedsRoot] = useState(false);
  const label = kind.event_label;

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (event) {
      form.setFieldsValue({
        name: event.name,
        description: event.description,
        dates: event.start_date && event.end_date
          ? [dayjs(event.start_date), dayjs(event.end_date)] : undefined,
      });
    } else {
      api.get<RoleRoot>('/api/org/roles/root')
        .then((r) => setNeedsRoot(r.has_templates && r.root_position_id === null))
        .catch(() => setNeedsRoot(false));
    }
  }, [open, event, form]);

  const submit = async (values: FormValues) => {
    setBusy(true);
    const body = {
      name: values.name,
      description: values.description ?? '',
      start_date: values.dates?.[0]?.format('YYYY-MM-DD') ?? null,
      end_date: values.dates?.[1]?.format('YYYY-MM-DD') ?? null,
      ...(event ? {} : { kind_id: kind.id, role_root_position_id: values.role_root_position_id ?? null }),
    };
    try {
      if (event) await api.patch(`/api/events/${event.id}`, body);
      else await api.post('/api/events', body);
      message.success('Saved');
      onSaved();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title={event ? `Edit ${event.name}` : `Add ${label}`} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item name="name" label="Name" rules={[{ required: true, max: 255 }]}>
          <Input placeholder={`e.g. ${kind.slug === 'training' ? 'Summer Bootcamp' : kind.slug === 'rnd' ? 'Line-follower R&D' : 'RoboCup 2026'}`} />
        </Form.Item>
        <Form.Item name="dates" label="Dates">
          <DatePicker.RangePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="description" label="Description">
          <Input.TextArea rows={2} />
        </Form.Item>
        {!event && needsRoot && (
          <Form.Item
            name="role_root_position_id"
            label="Where does the first automatic role go in the org chart?"
            rules={[{ required: true, message: 'Pick a position — this is only asked once' }]}
            extra="Asked once, ever — every later automatic role reuses this or chains under an earlier one."
          >
            <PositionPicker />
          </Form.Item>
        )}
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Add {kind.category_label.toLowerCase()}, {kind.team_label.toLowerCase()}s, and members after creating — open the event.
        </Typography.Paragraph>
        <Button type="primary" htmlType="submit" block loading={busy}>
          {event ? 'Save changes' : `Add ${label.toLowerCase()}`}
        </Button>
      </Form>
    </Modal>
  );
}

/* ---- EventsList — prototype card grid ------------------------------------- */
function EventCard({ kind, c, onEdit, onStatus, onRemove, expanded, onToggle, onChanged }: {
  kind: EventKind;
  c: Event;
  onEdit: () => void;
  onStatus: (status: 'active' | 'archived') => void;
  onRemove: () => void;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const active = c.status === 'active';
  const dates = c.start_date && c.end_date
    ? `${dayjs(c.start_date).format('DD MMM')}–${dayjs(c.end_date).format('DD MMM YY')}`.toUpperCase()
    : '—';
  const lead = c.roles.flatMap((r) => r.occupants.map((u) => u.full_name)).join(', ') || 'Unassigned';
  const trace = active ? '#5cc6ff' : 'rgba(120,170,230,.4)';
  const stat = (value: number, label: string, accent?: boolean) => (
    <div style={{ flex: 1, background: '#0f141d', padding: '10px 12px' }}>
      <div style={{ fontFamily: MONO, fontWeight: 600, fontSize: 18, color: accent ? '#5cc6ff' : '#eaf2ff' }}>{value || '—'}</div>
      <div style={{ fontFamily: MONO, fontSize: 8.5, letterSpacing: '.14em', textTransform: 'uppercase', color: 'rgba(224,236,252,.4)', marginTop: 3 }}>{label}</div>
    </div>
  );
  return (
    <div
      style={{
        position: 'relative',
        border: `1px solid ${active ? 'rgba(92,198,255,.22)' : 'rgba(120,170,230,.1)'}`,
        borderRadius: 14,
        overflow: 'hidden',
        background: 'rgba(15,20,29,.6)',
        padding: 20,
        boxShadow: active ? '0 20px 50px -30px rgba(92,198,255,.4)' : 'none',
        gridColumn: expanded ? '1 / -1' : 'auto',
      }}
    >
      <svg viewBox="0 0 300 90" style={{ position: 'absolute', top: 0, right: 0, width: '60%', opacity: 0.25, pointerEvents: 'none' }}>
        <g fill="none" stroke={trace} strokeWidth="1"><path d="M300 20 H200 L170 50 H90" /><path d="M300 60 H240 L215 30 H150" /></g>
        <circle cx="170" cy="50" r="2.5" fill={trace} />
      </svg>
      <div style={{ position: 'relative' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
          <span style={{ fontFamily: MONO, fontSize: 9, letterSpacing: '.14em', textTransform: 'uppercase', color: active ? '#5cc6ff' : 'rgba(224,236,252,.45)', border: `1px solid ${active ? 'rgba(92,198,255,.35)' : 'rgba(120,170,230,.18)'}`, background: active ? 'rgba(92,198,255,.08)' : 'transparent', padding: '3px 8px', borderRadius: 5 }}>{c.status.toUpperCase()}</span>
          <span style={{ fontFamily: MONO, fontSize: 11, color: 'rgba(224,236,252,.45)' }}>{dates}</span>
        </div>
        <div
          role="button"
          tabIndex={0}
          onClick={onToggle}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); } }}
          style={{ cursor: 'pointer', outline: 'none' }}
        >
          <div style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 18, color: '#eaf2ff', marginTop: 14 }}>{c.name}</div>
          <div style={{ fontSize: 12, color: 'rgba(224,236,252,.5)', marginTop: 4 }}>Lead: {lead}</div>
        </div>
        <div style={{ display: 'flex', gap: 1, marginTop: 18, background: 'rgba(120,170,230,.1)', borderRadius: 9, overflow: 'hidden', border: '1px solid rgba(120,170,230,.1)' }}>
          {stat(c.category_count, kind.category_label, true)}
          {stat(c.team_count, `${kind.team_label}s`)}
          {stat(c.member_count, kind.member_label ? `${kind.member_label}s` : 'Members')}
        </div>
        {c.can_manage && (
          <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
            <Button size="small" onClick={onEdit}>Edit</Button>
            <Button size="small" onClick={() => onStatus('archived')}>Archive</Button>
            <Popconfirm
              title={c.allocation_count ? 'In use — archive it instead.' : 'Delete this?'}
              onConfirm={onRemove} disabled={!!c.allocation_count}>
              <Button size="small" danger disabled={!!c.allocation_count}>Delete</Button>
            </Popconfirm>
            <span style={{ flex: 1 }} />
            <Button size="small" type="text" onClick={onToggle} style={{ color: '#5cc6ff' }}>{expanded ? 'Close' : 'Open'}</Button>
          </div>
        )}
        {expanded && (
          <div style={{ marginTop: 18, borderTop: '1px solid rgba(120,170,230,.12)', paddingTop: 16 }}>
            <EventDetailPanel eventId={c.id} onChanged={onChanged} />
          </div>
        )}
      </div>
    </div>
  );
}

function EventsList({ kind, canCreate }: { kind: EventKind; canCreate: boolean }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Event | null>(null);
  const [open, setOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api.get<Event[]>(`/api/events?kind_id=${kind.id}`)
      .then(setEvents)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, [kind.id]);

  useEffect(load, [load]);

  const setStatus = async (c: Event, status: 'active' | 'archived') => {
    try { await api.patch(`/api/events/${c.id}`, { status }); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Failed'); }
  };
  const remove = async (c: Event) => {
    try { await api.delete(`/api/events/${c.id}`); message.success('Deleted'); load(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Delete failed'); }
  };

  return (
    <>
      {canCreate && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setOpen(true); }}>
            Add {kind.event_label.toLowerCase()}
          </Button>
        </div>
      )}
      {loading && !events.length ? (
        <div style={{ fontFamily: MONO, fontSize: 12, color: 'rgba(224,236,252,.4)', padding: 24 }}>LOADING…</div>
      ) : events.length === 0 ? (
        <Empty description={`No ${kind.event_label.toLowerCase()}s yet.`} />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', gap: 16 }}>
          {events.map((c) => (
            <EventCard
              key={c.id}
              kind={kind}
              c={c}
              expanded={expandedId === c.id}
              onToggle={() => setExpandedId((id) => (id === c.id ? null : c.id))}
              onEdit={() => { setEditing(c); setOpen(true); }}
              onStatus={(s) => setStatus(c, s)}
              onRemove={() => remove(c)}
              onChanged={load}
            />
          ))}
        </div>
      )}
      <EventModal kind={kind} event={editing} open={open} onClose={() => setOpen(false)} onSaved={load} />
    </>
  );
}

/* ---- KindsManagerModal — unchanged --------------------------------------- */
function KindsManagerModal({ kinds, open, onClose, onChanged }: {
  kinds: EventKind[];
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [form] = Form.useForm();

  const add = async (v: { name: string; event_label: string; category_label?: string; team_label?: string; member_label?: string }) => {
    try {
      await api.post('/api/events/kinds', {
        name: v.name,
        event_label: v.event_label,
        category_label: v.category_label || 'Category',
        team_label: v.team_label || 'Team',
        member_label: v.member_label || 'Member',
      });
      form.resetFields();
      onChanged();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };
  const patch = async (k: EventKind, field: keyof EventKind, value: string) => {
    if (!value || value === k[field]) return;
    try { await api.patch(`/api/events/kinds/${k.id}`, { [field]: value }); onChanged(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Failed'); }
  };
  const remove = async (k: EventKind) => {
    try { await api.delete(`/api/events/kinds/${k.id}`); message.success('Removed'); onChanged(); }
    catch (e) { message.error(e instanceof ApiError ? e.message : 'Delete failed'); }
  };

  return (
    <Modal open={open} onCancel={onClose} title="Event types" footer={null} destroyOnHidden width={620}>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Each type is a tab. It reuses the same structure — only the labels for its top level, {' '}
        divisions, teams and members differ. Automatic roles can target one type or all.
      </Typography.Paragraph>
      <List
        size="small"
        dataSource={kinds}
        renderItem={(k) => (
          <List.Item
            actions={[
              <Popconfirm key="d" title={`Delete "${k.name}"?`} description="Only if it has no events or roles." onConfirm={() => remove(k)}>
                <Button type="text" size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>,
            ]}
          >
            <Space wrap size={6}>
              <Typography.Text editable={{ onChange: (v) => patch(k, 'name', v) }} strong>{k.name}</Typography.Text>
              <Tag>one is a <Typography.Text editable={{ onChange: (v) => patch(k, 'event_label', v) }}>{k.event_label}</Typography.Text></Tag>
              <Tag>team = <Typography.Text editable={{ onChange: (v) => patch(k, 'team_label', v) }}>{k.team_label}</Typography.Text></Tag>
              <Tag>division = <Typography.Text editable={{ onChange: (v) => patch(k, 'category_label', v) }}>{k.category_label}</Typography.Text></Tag>
            </Space>
          </List.Item>
        )}
      />
      <Form form={form} layout="vertical" onFinish={add} style={{ marginTop: 12 }}>
        <Space align="end" wrap>
          <Form.Item name="name" label="New type" rules={[{ required: true }]} style={{ marginBottom: 8 }}>
            <Input placeholder="e.g. Workshop" />
          </Form.Item>
          <Form.Item name="event_label" label="One is called" rules={[{ required: true }]} style={{ marginBottom: 8 }}>
            <Input placeholder="e.g. Session" />
          </Form.Item>
          <Form.Item name="team_label" label="Team label" style={{ marginBottom: 8 }}>
            <Input placeholder="Team" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" icon={<PlusOutlined />}>Add type</Button>
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}

/* ---- Page ----------------------------------------------------------------- */
export default function EventsPage() {
  const { me } = useAuth();
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const [kinds, setKinds] = useState<EventKind[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [managing, setManaging] = useState(false);
  const canCreate = can(me, 'events.create');
  const canManageKinds = can(me, 'org.edit');

  const loadKinds = useCallback(() => {
    api.get<EventKind[]>('/api/events/kinds')
      .then(setKinds)
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);
  useEffect(loadKinds, [loadKinds]);

  if (loaded && !slug && kinds.length) return <Navigate to={`/events/${kinds[0].slug}`} replace />;

  const kind = kinds.find((k) => k.slug === slug);

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 18 }}>
        <h2 style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 22, margin: 0, color: '#eaf2ff' }}>{kind ? kind.name : 'Events'}</h2>
        {canManageKinds && (
          <Button icon={<SettingOutlined />} onClick={() => setManaging(true)}>Event types</Button>
        )}
      </div>

      {/* segmented kind switch (mirrors the nav sub-items) */}
      {kinds.length > 1 && (
        <div style={{ display: 'inline-flex', gap: 4, background: 'rgba(8,11,17,.6)', border: '1px solid rgba(120,170,230,.12)', borderRadius: 10, padding: 4, marginBottom: 20 }}>
          {kinds.map((k) => {
            const on = k.slug === slug;
            return (
              <div
                key={k.id}
                onClick={() => navigate(`/events/${k.slug}`)}
                style={{
                  padding: '7px 16px', borderRadius: 7, fontSize: 13, cursor: 'pointer',
                  color: on ? '#eaf2ff' : 'rgba(224,236,252,.5)',
                  background: on ? 'linear-gradient(90deg,rgba(92,198,255,.2),rgba(92,198,255,.05))' : 'transparent',
                  border: `1px solid ${on ? 'rgba(92,198,255,.3)' : 'transparent'}`,
                }}
              >
                {k.name}
              </div>
            );
          })}
        </div>
      )}

      {kind ? (
        <EventsList key={kind.id} kind={kind} canCreate={canCreate} />
      ) : loaded && kinds.length === 0 ? (
        <Empty
          description={
            canManageKinds
              ? 'No event types yet. Use "Event types" to add one (e.g. Event, Training, R&D).'
              : 'No event types have been set up yet.'
          }
        />
      ) : loaded ? (
        <Empty description="No such event type" />
      ) : null}
      <KindsManagerModal kinds={kinds} open={managing} onClose={() => setManaging(false)} onChanged={loadKinds} />
    </>
  );
}
