import {
  ArrowLeftOutlined,
  CheckOutlined,
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
  FileOutlined,
  LeftOutlined,
  LinkOutlined,
  LockOutlined,
  PlusOutlined,
  RightOutlined,
  SearchOutlined,
  SettingOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  Button,
  ColorPicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Spin,
  Switch,
  Tag,
  Upload,
  message,
} from 'antd';
import type { UploadFile } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { api, ApiError } from '../api/client';
import type { Course, CourseDetail, CourseMaterial, MaterialKind } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import { C, hexA } from '../theme/circuitTokens';

type Kind = { key: MaterialKind; label: string };

const fail = (e: unknown) => message.error(e instanceof ApiError ? e.message : 'Failed');

function useKinds(): Kind[] {
  const [kinds, setKinds] = useState<Kind[]>([]);
  useEffect(() => {
    api.get<Kind[]>('/api/courses/kinds').then(setKinds).catch(() => {});
  }, []);
  return kinds;
}

// --- cover -------------------------------------------------------------------

/** An uploaded image when the course has one, otherwise a lit gradient in the
 * course's accent with its cover label set large across it. */
function CourseCover({ course, height = 190 }: { course: Course; height?: number | string }) {
  const a = course.accent || C.accent;
  if (course.cover_url) {
    return (
      <div style={{ height, background: `center/cover no-repeat url("${course.cover_url}"), ${C.bgInset}` }} />
    );
  }
  const label = course.cover_label
    || course.title.split(/\s+/).map((w) => w.match(/[\p{L}\p{N}]/u)?.[0] ?? '').join('').slice(0, 3).toUpperCase();
  return (
    <div
      style={{
        height,
        position: 'relative',
        overflow: 'hidden',
        background: `radial-gradient(120% 90% at 85% 10%, ${hexA(a, 0.55)}, transparent 55%),
          radial-gradient(90% 80% at 0% 100%, ${hexA(a, 0.3)}, transparent 60%),
          linear-gradient(160deg, #0d1420, #070a10)`,
        display: 'grid',
        placeItems: 'center',
      }}
    >
      <div
        style={{
          position: 'absolute', inset: 0,
          backgroundImage: `linear-gradient(${hexA(a, 0.09)} 1px, transparent 1px), linear-gradient(90deg, ${hexA(a, 0.09)} 1px, transparent 1px)`,
          backgroundSize: '22px 22px',
          maskImage: 'radial-gradient(circle at 50% 50%, #000 30%, transparent 75%)',
        }}
      />
      <div
        style={{
          position: 'relative', fontFamily: C.display, fontWeight: 700, letterSpacing: '-.02em',
          fontSize: Math.min(typeof height === 'number' ? height * 0.42 : 88, 340 / Math.max(label.length, 2)), lineHeight: 1,
          color: '#f4f9ff', textShadow: `0 0 28px ${hexA(a, 0.75)}, 0 0 2px ${hexA(a, 0.9)}`,
          padding: '0 18px', textAlign: 'center',
        }}
      >
        {label}
      </div>
    </div>
  );
}

function Progress({ percent, accent }: { percent: number; accent: string }) {
  return (
    <div style={{ height: 6, borderRadius: 6, background: 'rgba(120,170,230,.12)', overflow: 'hidden' }}>
      <div style={{ width: `${percent}%`, height: '100%', borderRadius: 6, background: accent, transition: 'width .3s' }} />
    </div>
  );
}

function PercentLabel({ percent, accent }: { percent: number; accent: string }) {
  return (
    <div style={{ textAlign: 'right' }}>
      <div style={{ fontFamily: C.display, fontWeight: 600, fontSize: 18, color: accent, lineHeight: 1 }}>{percent}%</div>
      <div style={{ fontFamily: C.mono, fontSize: 9.5, letterSpacing: '.12em', color: accent, marginTop: 3 }}>COMPLETE</div>
    </div>
  );
}

// --- catalogue ---------------------------------------------------------------

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'progress', label: 'In progress' },
  { value: 'new', label: 'Not started' },
  { value: 'done', label: 'Completed' },
];

function Catalogue() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('all');
  const [creating, setCreating] = useState(false);
  const manage = can(me, 'courses.manage');

  const load = useCallback(() => {
    api.get<Course[]>('/api/courses').then(setCourses).catch(fail);
  }, []);
  useEffect(load, [load]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (courses ?? []).filter((c) => {
      if (needle && !`${c.title} ${c.description ?? ''}`.toLowerCase().includes(needle)) return false;
      if (filter === 'progress') return c.percent > 0 && c.percent < 100;
      if (filter === 'new') return c.completed === 0;
      if (filter === 'done') return c.total > 0 && c.percent === 100;
      return true;
    });
  }, [courses, q, filter]);

  return (
    <div style={{ maxWidth: 1180, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 26 }}>
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 4, padding: '2px 4px 2px 14px',
            background: C.bgPanel, border: `1px solid ${C.hairline}`, borderRadius: 10,
          }}
        >
          <span style={{ color: C.textMuted, fontSize: 14 }}>Show:</span>
          <Select variant="borderless" value={filter} onChange={setFilter} options={FILTERS} popupMatchSelectWidth={false}
            style={{ minWidth: 120, color: C.accent }} />
        </div>
        <div style={{ flex: 1 }} />
        <Input
          allowClear
          placeholder="Find a course"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          suffix={<SearchOutlined style={{ color: C.textMuted }} />}
          style={{ width: 300, maxWidth: '100%' }}
        />
        {manage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>New course</Button>
        )}
      </div>

      {courses === null ? (
        <div style={{ display: 'grid', placeItems: 'center', padding: 80 }}><Spin /></div>
      ) : shown.length === 0 ? (
        <Empty description={courses.length ? 'No course matches' : 'No courses yet'} style={{ padding: 60 }} />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 28 }}>
          {shown.map((c) => (
            <button
              key={c.id}
              type="button"
              className="mtr-course-card"
              onClick={() => navigate(`/courses/${c.id}`)}
              style={{
                all: 'unset', cursor: 'pointer', display: 'flex', flexDirection: 'column',
                background: C.bgPanel, border: `1px solid ${C.hairline}`, borderRadius: 14, overflow: 'hidden',
              }}
            >
              <CourseCover course={c} />
              <div style={{ padding: '16px 18px 18px', display: 'flex', flexDirection: 'column', gap: 14, flex: 1 }}>
                <div style={{ fontFamily: C.display, fontWeight: 600, fontSize: 17, color: C.text, lineHeight: 1.3 }}>
                  {c.title}
                  {!c.is_published && <Tag style={{ marginLeft: 8, verticalAlign: 2 }}>Draft</Tag>}
                </div>
                <Progress percent={c.percent} accent={c.accent} />
                <div style={{ flex: 1 }} />
                <PercentLabel percent={c.percent} accent={c.accent} />
              </div>
            </button>
          ))}
        </div>
      )}

      {creating && (
        <CourseFormModal
          onClose={() => setCreating(false)}
          onSaved={(id) => { setCreating(false); navigate(`/courses/${id}`); }}
        />
      )}
    </div>
  );
}

// --- course page -------------------------------------------------------------

function CoursePage({ courseId }: { courseId: number }) {
  const navigate = useNavigate();
  const kinds = useKinds();
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [tab, setTab] = useState<MaterialKind | null>(null);
  const [editing, setEditing] = useState<CourseMaterial | null>(null);
  const [settings, setSettings] = useState(false);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    api.get<CourseDetail>(`/api/courses/${courseId}`).then(setCourse).catch((e) => {
      fail(e);
      navigate('/courses');
    });
  }, [courseId, navigate]);
  useEffect(load, [load]);

  const active = tab ?? kinds.find((k) => course?.counts[k.key])?.key ?? kinds[0]?.key ?? null;
  if (!course || !active) return <div style={{ display: 'grid', placeItems: 'center', padding: 80 }}><Spin /></div>;

  const items = course.materials.filter((m) => m.kind === active);
  const toggleDone = async (m: CourseMaterial) => {
    const url = `/api/courses/${course.id}/materials/${m.id}/progress`;
    try {
      await (m.completed ? api.delete(url) : api.put(url, {}));
      load();
    } catch (e) {
      fail(e);
    }
  };

  return (
    <div style={{ maxWidth: 1180, margin: '0 auto' }}>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/courses')} style={{ marginBottom: 14, color: C.textMuted }}>
        All courses
      </Button>

      <div
        style={{
          display: 'grid', gridTemplateColumns: 'minmax(0, 340px) 1fr', gap: 28, alignItems: 'stretch',
          background: C.bgPanel, border: `1px solid ${C.hairline}`, borderRadius: 16, overflow: 'hidden', marginBottom: 26,
        }}
        className="mtr-course-hero"
      >
        <div style={{ minHeight: 210 }}><CourseCover course={course} height="100%" /></div>
        <div style={{ padding: '24px 26px 24px 0', alignSelf: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
            <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600, color: C.text, lineHeight: 1.15, flex: 1 }}>
              {course.title}
              {!course.is_published && <Tag style={{ marginLeft: 10, verticalAlign: 5 }}>Draft</Tag>}
            </h1>
            {course.can_manage && (
              <Button icon={<SettingOutlined />} onClick={() => setSettings(true)}>Course settings</Button>
            )}
          </div>
          {course.description && (
            <p style={{ color: C.textBody, margin: '10px 0 0', maxWidth: '68ch', lineHeight: 1.55 }}>{course.description}</p>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 18, marginTop: 20 }}>
            <div style={{ flex: 1, maxWidth: 420 }}><Progress percent={course.percent} accent={course.accent} /></div>
            <PercentLabel percent={course.percent} accent={course.accent} />
            <div style={{ fontFamily: C.mono, fontSize: 11, color: C.textFaint }}>{course.completed}/{course.total} done</div>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', borderBottom: `1px solid ${C.hairline}`, marginBottom: 22 }}>
        {kinds.map((k) => {
          const on = k.key === active;
          return (
            <button
              key={k.key}
              type="button"
              onClick={() => setTab(k.key)}
              style={{
                all: 'unset', cursor: 'pointer', padding: '10px 14px', marginBottom: -1,
                borderBottom: `2px solid ${on ? course.accent : 'transparent'}`,
                color: on ? C.text : C.textMuted, fontWeight: on ? 600 : 400, fontSize: 14,
              }}
            >
              {k.label}
              <span style={{ fontFamily: C.mono, fontSize: 11, marginLeft: 7, color: on ? course.accent : C.textFaint }}>
                {course.counts[k.key] ?? 0}
              </span>
            </button>
          );
        })}
      </div>

      {course.can_manage && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 14 }}>
          <Button icon={<PlusOutlined />} onClick={() => setAdding(true)}>
            Add to {kinds.find((k) => k.key === active)?.label ?? active}
          </Button>
        </div>
      )}
      {items.length === 0 ? (
        <Empty description="Nothing on this shelf yet" style={{ padding: 50 }} />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
          {items.map((m) => (
            <MaterialCard
              key={m.id}
              m={m}
              accent={course.accent}
              manage={course.can_manage}
              onOpen={() => navigate(`/courses/${course.id}/${m.id}`)}
              onToggle={() => toggleDone(m)}
              onEdit={() => setEditing(m)}
            />
          ))}
        </div>
      )}

      {editing && (
        <MaterialEditModal
          courseId={course.id}
          material={editing}
          kinds={kinds}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
      {adding && (
        <AddMaterialsModal
          courseId={course.id}
          kind={kinds.find((k) => k.key === active)!}
          onClose={() => setAdding(false)}
          onSaved={() => { setAdding(false); load(); }}
        />
      )}
      {settings && (
        <CourseFormModal
          course={course}
          onClose={() => setSettings(false)}
          onSaved={() => { setSettings(false); load(); }}
          onDeleted={() => navigate('/courses')}
        />
      )}
    </div>
  );
}

function MaterialCard({
  m, accent, manage, onOpen, onToggle, onEdit,
}: {
  m: CourseMaterial; accent: string; manage: boolean;
  onOpen: () => void; onToggle: () => void; onEdit: () => void;
}) {
  const locked = m.url === null;
  return (
    <div
      className={locked ? undefined : 'mtr-course-card'}
      onClick={locked ? undefined : onOpen}
      style={{
        cursor: locked ? 'not-allowed' : 'pointer', position: 'relative',
        background: C.bgPanel, borderRadius: 12, padding: '14px 16px',
        border: `1px ${locked ? 'dashed' : 'solid'} ${m.completed ? hexA(accent, 0.45) : C.hairline}`,
        opacity: locked ? 0.55 : 1, display: 'flex', alignItems: 'flex-start', gap: 12,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        {m.unit_label && (
          <div style={{ fontFamily: C.mono, fontSize: 10, letterSpacing: '.16em', textTransform: 'uppercase', color: accent, marginBottom: 5 }}>
            {m.unit_label}
          </div>
        )}
        <div style={{ fontWeight: 600, color: C.text, fontSize: 14.5, lineHeight: 1.35 }}>{m.title}</div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
          {locked && <span style={{ fontSize: 12, color: C.amber }}><LockOutlined /> Not released yet</span>}
          {manage && !m.is_released && <Tag color="warning" style={{ margin: 0 }}>Held back</Tag>}
          {m.is_link && <Tag icon={<LinkOutlined />} style={{ margin: 0 }}>Link</Tag>}
          {manage && (m.is_link ? m.url : m.path) && (
            <span style={{ fontFamily: C.mono, fontSize: 10.5, color: C.textFaint, overflowWrap: 'anywhere' }}>
              {m.is_link ? m.url : m.path}
            </span>
          )}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
        {manage && <Button size="small" type="text" icon={<EditOutlined />} onClick={onEdit} aria-label="Edit" />}
        {!locked && (
          <Button
            size="small"
            shape="circle"
            onClick={onToggle}
            aria-label={m.completed ? 'Mark not done' : 'Mark done'}
            title={m.completed ? 'Done — click to undo' : 'Mark done'}
            icon={<CheckOutlined />}
            style={m.completed ? { background: accent, borderColor: accent, color: '#06080c' } : { color: C.textFaint }}
          />
        )}
      </div>
    </div>
  );
}

// --- viewer ------------------------------------------------------------------

/** What the browser can show in a frame; anything else is offered as a download. */
const inline = (media: string | null) =>
  !!media && (/^(text|image|video|audio)\//.test(media) || media === 'application/pdf');

function MaterialViewer({ courseId, materialId }: { courseId: number; materialId: number }) {
  const navigate = useNavigate();
  const kinds = useKinds();
  const [course, setCourse] = useState<CourseDetail | null>(null);

  const load = useCallback(() => {
    api.get<CourseDetail>(`/api/courses/${courseId}`).then(setCourse).catch((e) => {
      fail(e);
      navigate('/courses');
    });
  }, [courseId, navigate]);
  useEffect(load, [load]);

  const m = course?.materials.find((x) => x.id === materialId);
  if (!course) return <div style={{ display: 'grid', placeItems: 'center', padding: 80 }}><Spin /></div>;
  if (!m || !m.url) {
    return <Empty description="This material isn't available" style={{ padding: 60 }} />;
  }
  const shelf = course.materials.filter((x) => x.kind === m.kind && x.url);
  const i = shelf.findIndex((x) => x.id === m.id);
  const prev = shelf[i - 1];
  const next = shelf[i + 1];
  const go = (x?: CourseMaterial) => x && navigate(`/courses/${course.id}/${x.id}`);
  const toggle = async () => {
    const url = `/api/courses/${course.id}/materials/${m.id}/progress`;
    try {
      await (m.completed ? api.delete(url) : api.put(url, {}));
      load();
    } catch (e) {
      fail(e);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: 'calc(100vh - 170px)', minHeight: 520 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(`/courses/${course.id}`)} style={{ color: C.textMuted }}>
          {course.title}
        </Button>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontFamily: C.mono, fontSize: 10, letterSpacing: '.16em', textTransform: 'uppercase', color: course.accent }}>
            {kinds.find((k) => k.key === m.kind)?.label ?? m.kind}{m.unit_label ? ` · ${m.unit_label}` : ''}
          </div>
          <div style={{ fontFamily: C.display, fontWeight: 600, fontSize: 17, color: C.text }}>{m.title}</div>
        </div>
        <Button icon={<LeftOutlined />} disabled={!prev} onClick={() => go(prev)} aria-label="Previous" />
        <Button icon={<RightOutlined />} disabled={!next} onClick={() => go(next)} aria-label="Next" />
        <Button icon={<ExportOutlined />} href={m.url} target="_blank" rel="noopener">Open in new tab</Button>
        <Button
          type={m.completed ? 'default' : 'primary'}
          icon={<CheckOutlined />}
          onClick={toggle}
          style={m.completed ? { borderColor: course.accent, color: course.accent } : undefined}
        >
          {m.completed ? 'Done' : 'Mark done'}
        </Button>
      </div>
      {m.is_link || !inline(m.media_type) ? (
        <div
          style={{
            flex: 1, display: 'grid', placeItems: 'center', textAlign: 'center',
            border: `1px solid ${C.hairline}`, borderRadius: 12, background: C.bgPanel, padding: 24,
          }}
        >
          <div>
            <div style={{ color: C.textBody, marginBottom: 16, maxWidth: '52ch' }}>
              {m.is_link
                ? 'This one lives on another site.'
                : "This file type can't be shown in the browser — download it to open it."}
            </div>
            <Button type="primary" size="large" icon={<ExportOutlined />} href={m.url} target="_blank" rel="noopener"
              download={m.is_link ? undefined : true}>
              {m.is_link ? 'Open link' : 'Download'}
            </Button>
          </div>
        </div>
      ) : (
      <iframe
        key={m.id}
        src={m.url}
        title={m.title}
        allow="fullscreen; clipboard-write"
        allowFullScreen
        style={{ flex: 1, width: '100%', border: `1px solid ${C.hairline}`, borderRadius: 12, background: '#fff' }}
      />
      )}
    </div>
  );
}

// --- editing -----------------------------------------------------------------

/** An item queued for a shelf before it's sent: a file or a link, with an
 * optional title and group (blank = worked out from the file). */
type Staged = { uid: string; kind: MaterialKind; file?: File; url?: string; title: string; unit_label: string };

let stagedSeq = 0;
const stagedUid = () => `s${++stagedSeq}`;

function ShelfStager({
  kind, items, onChange,
}: {
  kind: Kind; items: Staged[]; onChange: (items: Staged[]) => void;
}) {
  const mine = items.filter((it) => it.kind === kind.key);
  const patch = (uid: string, p: Partial<Staged>) => onChange(items.map((it) => (it.uid === uid ? { ...it, ...p } : it)));
  return (
    <div>
      {mine.map((it) => (
        <div key={it.uid} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
          <div style={{ width: 22, color: C.textMuted, textAlign: 'center' }}>
            {it.file ? <FileOutlined /> : <LinkOutlined />}
          </div>
          {it.file ? (
            <div style={{ flex: '1 1 160px', minWidth: 0, fontFamily: C.mono, fontSize: 12, color: C.textBody, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={it.file.name}>
              {it.file.name}
            </div>
          ) : (
            <Input
              style={{ flex: '1 1 160px' }}
              placeholder="https://…"
              value={it.url}
              onChange={(e) => patch(it.uid, { url: e.target.value })}
            />
          )}
          <Input
            style={{ flex: '1 1 150px' }}
            placeholder={it.file ? 'Title (from the file)' : 'Title'}
            value={it.title}
            onChange={(e) => patch(it.uid, { title: e.target.value })}
          />
          <Input
            style={{ width: 100 }}
            placeholder="Week 1"
            value={it.unit_label}
            onChange={(e) => patch(it.uid, { unit_label: e.target.value })}
          />
          <Button type="text" icon={<DeleteOutlined />} aria-label="Remove" onClick={() => onChange(items.filter((x) => x.uid !== it.uid))} />
        </div>
      ))}
      <div style={{ display: 'flex', gap: 8 }}>
        <Upload
          multiple
          showUploadList={false}
          beforeUpload={(f, batch) => {
            // antd calls this once per file; the whole selection arrives as
            // `batch`, so queue it all on the first call and skip the rest —
            // adding one at a time would read a stale `items` each round.
            if (f !== batch[0]) return false;
            onChange([
              ...items,
              ...batch.map((b) => ({
                uid: stagedUid(), kind: kind.key, file: b as File, title: '', unit_label: '',
              })),
            ]);
            return false;
          }}
        >
          <Button size="small" icon={<UploadOutlined />}>Add files</Button>
        </Upload>
        <Button
          size="small"
          icon={<LinkOutlined />}
          onClick={() => onChange([...items, { uid: stagedUid(), kind: kind.key, url: '', title: '', unit_label: '' }])}
        >
          Add link
        </Button>
      </div>
    </div>
  );
}

/** Sends queued items one by one; returns how many failed. */
async function sendStaged(courseId: number, items: Staged[]): Promise<number> {
  let failed = 0;
  for (const it of items) {
    if (!it.file && !it.url?.trim()) continue;
    const fd = new FormData();
    fd.append('kind', it.kind);
    if (it.title.trim()) fd.append('title', it.title.trim());
    if (it.unit_label.trim()) fd.append('unit_label', it.unit_label.trim());
    if (it.file) fd.append('file', it.file);
    else fd.append('url', it.url!.trim());
    try {
      await api.upload(`/api/courses/${courseId}/materials`, fd);
    } catch (e) {
      failed += 1;
      message.error(`${it.file?.name ?? it.url}: ${e instanceof ApiError ? e.message : 'failed'}`);
    }
  }
  return failed;
}

function AddMaterialsModal({
  courseId, kind, onClose, onSaved,
}: {
  courseId: number; kind: Kind; onClose: () => void; onSaved: () => void;
}) {
  const [items, setItems] = useState<Staged[]>([]);
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    if (!items.length) { onClose(); return; }
    setSaving(true);
    const failed = await sendStaged(courseId, items);
    setSaving(false);
    if (failed < items.length) message.success(`Added ${items.length - failed} to ${kind.label}`);
    onSaved();
  };
  return (
    <Modal open width={720} title={`Add to ${kind.label}`} onCancel={onClose} onOk={submit} okText="Add" confirmLoading={saving} destroyOnHidden>
      <p style={{ color: C.textMuted, marginTop: 0 }}>
        Add as many files or links as you like. Leave the title blank to use the file's own title.
      </p>
      <ShelfStager kind={kind} items={items} onChange={setItems} />
    </Modal>
  );
}

function zipField(files: UploadFile[], set: (f: UploadFile[]) => void, label: string) {
  return (
    <Upload
      accept=".zip"
      maxCount={1}
      fileList={files}
      beforeUpload={(f) => { set([f as unknown as UploadFile]); return false; }}
      onRemove={() => set([])}
    >
      <Button icon={<UploadOutlined />}>{label}</Button>
    </Upload>
  );
}

const ZIP_HELP =
  'A .zip of the course folder. HTML/PDF pages in slides/, book/, tasks/ and solutions/ go on those shelves; any other page becomes a tool. Answers start held back.';

function CourseFormModal({
  course, onClose, onSaved, onDeleted,
}: {
  course?: CourseDetail; onClose: () => void; onSaved: (id: number) => void; onDeleted?: () => void;
}) {
  const [form] = Form.useForm();
  const kinds = useKinds();
  const [mode, setMode] = useState<'shelves' | 'zip'>('shelves');
  const [staged, setStaged] = useState<Staged[]>([]);
  const [bundle, setBundle] = useState<UploadFile[]>([]);
  const [cover, setCover] = useState<UploadFile[]>([]);
  const [saving, setSaving] = useState(false);
  const editing = !!course;

  const submit = async () => {
    const v = await form.validateFields();
    const accent = typeof v.accent === 'string' ? v.accent : v.accent?.toHexString?.() ?? '#5cc6ff';
    setSaving(true);
    try {
      let id = course?.id;
      if (!editing) {
        if (mode === 'zip' && !bundle.length) { message.error('Choose the course bundle (.zip)'); return; }
        const fd = new FormData();
        fd.append('title', v.title);
        if (v.description) fd.append('description', v.description);
        if (v.cover_label) fd.append('cover_label', v.cover_label);
        fd.append('accent', accent);
        if (mode === 'zip') fd.append('bundle', bundle[0] as unknown as Blob);
        const r = await api.upload<{ id: number; files: number; materials_added: number }>('/api/courses', fd);
        id = r.id;
        if (mode === 'zip') {
          message.success(`Course created — ${r.files} files, ${r.materials_added} materials shelved`);
        } else {
          const failed = await sendStaged(id, staged);
          message.success(`Course created${staged.length ? ` with ${staged.length - failed} items` : ''}`);
        }
      } else {
        await api.patch(`/api/courses/${id}`, {
          title: v.title, description: v.description ?? '', cover_label: v.cover_label ?? '', accent,
          is_published: v.is_published, sort_order: v.sort_order, ...(v.clear_cover ? { cover_path: '' } : {}),
        });
        if (bundle.length) {
          const fd = new FormData();
          fd.append('bundle', bundle[0] as unknown as Blob);
          const r = await fetch(`/api/courses/${id}/bundle`, { method: 'PUT', body: fd, credentials: 'include' });
          if (!r.ok) throw new ApiError(r.status, (await r.json().catch(() => ({}))).detail ?? 'Upload failed');
          const s = await r.json();
          message.success(`Bundle imported — ${s.materials_added} added, ${s.materials_removed} removed`);
        }
        if (cover.length) {
          const fd = new FormData();
          fd.append('image', cover[0] as unknown as Blob);
          await api.upload(`/api/courses/${id}/cover`, fd);
        }
        message.success('Saved');
      }
      onSaved(id!);
    } catch (e) {
      fail(e);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    try {
      await api.delete(`/api/courses/${course!.id}`);
      message.success('Course deleted');
      onDeleted?.();
    } catch (e) {
      fail(e);
    }
  };

  return (
    <Modal
      open
      width={editing ? 560 : 820}
      title={editing ? 'Course settings' : 'New course'}
      onCancel={onClose}
      onOk={submit}
      okText={editing ? 'Save' : 'Create'}
      confirmLoading={saving}
      destroyOnHidden
      footer={(_, { OkBtn, CancelBtn }) => (
        <div style={{ display: 'flex', gap: 8 }}>
          {editing && (
            <Popconfirm title="Delete this course?" description="Its files and everyone's progress go with it." onConfirm={remove} okButtonProps={{ danger: true }}>
              <Button danger>Delete</Button>
            </Popconfirm>
          )}
          <div style={{ flex: 1 }} />
          <CancelBtn />
          <OkBtn />
        </div>
      )}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          title: course?.title, description: course?.description, cover_label: course?.cover_label,
          accent: course?.accent ?? '#5cc6ff', is_published: course?.is_published ?? true, sort_order: course?.sort_order ?? 0,
        }}
      >
        <Form.Item name="title" label="Title" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="description" label="Description">
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item name="cover_label" label="Cover text" tooltip="Set large on the cover when there's no cover image" style={{ flex: 1 }}>
            <Input maxLength={40} placeholder="e.g. PY" />
          </Form.Item>
          <Form.Item name="accent" label="Accent">
            <ColorPicker disabledAlpha />
          </Form.Item>
          {editing && (
            <Form.Item name="sort_order" label="Order">
              <InputNumber style={{ width: 80 }} />
            </Form.Item>
          )}
        </div>

        {!editing && (
          <>
            <Form.Item label="Content">
              <Segmented
                value={mode}
                onChange={(v) => setMode(v as 'shelves' | 'zip')}
                options={[
                  { value: 'shelves', label: 'Build shelf by shelf' },
                  { value: 'zip', label: 'Import a .zip' },
                ]}
              />
            </Form.Item>
            {mode === 'zip' ? (
              <Form.Item label="Course bundle" required extra={ZIP_HELP}>
                {zipField(bundle, setBundle, 'Choose .zip')}
              </Form.Item>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 8 }}>
                {kinds.map((k) => (
                  <div key={k.key} style={{ border: `1px solid ${C.hairline}`, borderRadius: 10, padding: '12px 14px', background: C.bgInset }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
                      <span style={{ fontWeight: 600, color: C.text }}>{k.label}</span>
                      <span style={{ fontFamily: C.mono, fontSize: 11, color: C.textFaint }}>
                        {staged.filter((s) => s.kind === k.key).length}
                      </span>
                      {k.key === 'answers' && <span style={{ fontSize: 12, color: C.amber }}>held back until you release them</span>}
                    </div>
                    <ShelfStager kind={k} items={staged} onChange={setStaged} />
                  </div>
                ))}
                <div style={{ fontSize: 12, color: C.textFaint }}>
                  Every shelf can be changed later from the course page — add, replace, rename or remove anything.
                </div>
              </div>
            )}
          </>
        )}

        {editing && (
          <>
            <Form.Item label="Import from .zip" extra={`${ZIP_HELP} Re-importing keeps items you added shelf by shelf.`}>
              {zipField(bundle, setBundle, 'Choose .zip')}
            </Form.Item>
            <Form.Item label="Cover image" extra={course?.cover_path ? `Current: ${course.cover_path}` : undefined}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <Upload
                  accept="image/*"
                  maxCount={1}
                  fileList={cover}
                  beforeUpload={(f) => { setCover([f as unknown as UploadFile]); return false; }}
                  onRemove={() => setCover([])}
                >
                  <Button icon={<UploadOutlined />}>Choose image</Button>
                </Upload>
                {course?.cover_path && (
                  <Form.Item name="clear_cover" valuePropName="checked" noStyle>
                    <Switch checkedChildren="Remove" unCheckedChildren="Keep" />
                  </Form.Item>
                )}
              </div>
            </Form.Item>
            <Form.Item name="is_published" label="Published" valuePropName="checked" extra="Drafts are only visible to course managers.">
              <Switch />
            </Form.Item>
          </>
        )}
      </Form>
    </Modal>
  );
}

function MaterialEditModal({
  courseId, material, kinds, onClose, onSaved,
}: {
  courseId: number; material: CourseMaterial; kinds: Kind[]; onClose: () => void; onSaved: () => void;
}) {
  const [form] = Form.useForm();
  const [file, setFile] = useState<UploadFile[]>([]);
  const [saving, setSaving] = useState(false);
  const base = `/api/courses/${courseId}/materials/${material.id}`;
  const submit = async () => {
    const v = await form.validateFields();
    setSaving(true);
    try {
      await api.patch(base, { ...v, unit_label: v.unit_label ?? '', unit: v.unit ?? null });
      if (file.length) {
        const fd = new FormData();
        fd.append('file', file[0] as unknown as Blob);
        const r = await fetch(`${base}/file`, { method: 'PUT', body: fd, credentials: 'include' });
        if (!r.ok) throw new ApiError(r.status, (await r.json().catch(() => ({}))).detail ?? 'Upload failed');
      }
      onSaved();
    } catch (e) {
      fail(e);
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    try {
      await api.delete(base);
      message.success('Removed');
      onSaved();
    } catch (e) {
      fail(e);
    }
  };
  return (
    <Modal
      open
      title="Edit material"
      onCancel={onClose}
      onOk={submit}
      okText="Save"
      confirmLoading={saving}
      destroyOnHidden
      footer={(_, { OkBtn, CancelBtn }) => (
        <div style={{ display: 'flex', gap: 8 }}>
          <Popconfirm title="Remove this from the course?" description="Learners' ticks on it go too." onConfirm={remove} okButtonProps={{ danger: true }}>
            <Button danger icon={<DeleteOutlined />}>Remove</Button>
          </Popconfirm>
          <div style={{ flex: 1 }} />
          <CancelBtn />
          <OkBtn />
        </div>
      )}
    >
      {material.path && <div style={{ fontFamily: C.mono, fontSize: 11, color: C.textFaint, marginBottom: 14 }}>{material.path}</div>}
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          title: material.title, kind: material.kind, unit: material.unit, unit_label: material.unit_label,
          sort_order: material.sort_order, is_released: material.is_released,
          ...(material.is_link ? { external_url: material.url } : {}),
        }}
      >
        <Form.Item name="title" label="Title" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={300} />
        </Form.Item>
        {material.is_link && (
          <Form.Item name="external_url" label="Link" rules={[{ required: true, type: 'url' }]}>
            <Input />
          </Form.Item>
        )}
        <Form.Item
          label={material.is_link ? 'Replace with a file' : 'Replace file'}
          extra={material.is_link ? 'Uploading a file turns this link into that file.' : undefined}
        >
          <Upload
            maxCount={1}
            fileList={file}
            beforeUpload={(f) => { setFile([f as unknown as UploadFile]); return false; }}
            onRemove={() => setFile([])}
          >
            <Button icon={<UploadOutlined />}>Choose file</Button>
          </Upload>
        </Form.Item>
        <Form.Item name="kind" label="Shelf">
          <Select options={kinds.map((k) => ({ value: k.key, label: k.label }))} />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item name="unit_label" label="Group" tooltip="Shown above the title, e.g. the week" style={{ flex: 1 }}>
            <Input maxLength={100} placeholder="e.g. Week 3" />
          </Form.Item>
          <Form.Item name="unit" label="Unit #">
            <InputNumber style={{ width: 90 }} />
          </Form.Item>
          <Form.Item name="sort_order" label="Order">
            <InputNumber style={{ width: 90 }} />
          </Form.Item>
        </div>
        <Form.Item name="is_released" label="Released to learners" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// --- route -------------------------------------------------------------------

export default function CoursesPage() {
  const { courseId, materialId } = useParams();
  if (courseId && materialId) return <MaterialViewer courseId={Number(courseId)} materialId={Number(materialId)} />;
  if (courseId) return <CoursePage courseId={Number(courseId)} />;
  return <Catalogue />;
}
