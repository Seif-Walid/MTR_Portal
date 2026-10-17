import { ArrowLeftOutlined, EditOutlined, PlusOutlined, SearchOutlined, TableOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { AutoComplete, Breadcrumb, Button, Descriptions, Empty, Grid, Input, Segmented, Select, Skeleton, Space, Table, Tabs, Tag, Typography, theme } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import { Panel } from '../components/charts';
import DataGrid from '../components/DataGrid';
import RecordEditor from '../components/grid/RecordEditor';
import RecordGraph from '../components/explorer/RecordGraph';
import SchemaMap from '../components/explorer/SchemaMap';
import type {
  AddableGroup,
  ExploreRecord,
  ExploreRow,
  ExploreSchema,
  RecordRef,
  RelatedGroup,
  SearchGroup,
} from '../components/explorer/types';
import { formatCell } from '../components/explorer/types';
import InsightsPage from './InsightsPage';

const PAGE = 50;

/** The dashboard: every record the viewer may see, how the kinds of record
 *  relate, and any single record with everything connected to it — click
 *  through from one to the next. */
export default function ExplorerPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const [, , tableParam, idParam] = location.pathname.split('/');
  const table = tableParam || null;
  const recordId = idParam ? Number(idParam) : null;

  const [schema, setSchema] = useState<ExploreSchema | null>(null);
  const [trail, setTrail] = useState<{ table: string; id: number; title: string }[]>([]);

  useEffect(() => {
    api.get<ExploreSchema>('/api/explore/schema').then(setSchema).catch(() => {});
  }, []);

  // opening another record or list starts at the top, not wherever the last one was scrolled to
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  const entity = schema?.entities.find((e) => e.table === table);
  const go = useCallback((t: string | null, id?: number) => {
    navigate(t ? (id != null ? `/explore/${t}/${id}` : `/explore/${t}`) : '/explore');
  }, [navigate]);

  const onRecordLoaded = useCallback((r: ExploreRecord) => {
    setTrail((tr) => [...tr.filter((x) => !(x.table === r.table && x.id === r.id)), { table: r.table, id: r.id, title: r.title }].slice(-6));
  }, []);

  const sidebar = schema && (
    screens.md ? (
      <nav style={{ position: 'sticky', top: 76, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <SideItem active={!table} onClick={() => go(null)} label="How it all connects" />
        {schema.groups.map((g) => (
          <div key={g} style={{ marginTop: 10 }}>
            <div className="u-label" style={{ padding: '4px 10px', color: token.colorTextQuaternary }}>{g}</div>
            {schema.entities.filter((e) => e.group === g).map((e) => (
              <SideItem key={e.table} active={table === e.table} onClick={() => go(e.table)} label={e.label} count={e.count} />
            ))}
          </div>
        ))}
      </nav>
    ) : (
      <Select
        value={table ?? '__map'}
        onChange={(v) => go(v === '__map' ? null : v)}
        style={{ width: '100%' }}
        options={[
          { value: '__map', label: 'How it all connects' },
          ...schema.groups.map((g) => ({
            label: g,
            options: schema.entities.filter((e) => e.group === g).map((e) => ({ value: e.table, label: `${e.label} (${e.count})` })),
          })),
        ]}
      />
    )
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <GlobalSearch onPick={(t, id) => go(t, id)} />
      <div style={{ display: 'grid', gridTemplateColumns: screens.md ? '220px minmax(0, 1fr)' : '1fr', gap: 18, alignItems: 'start' }}>
        <div>{sidebar ?? <Skeleton active />}</div>
        <div style={{ minWidth: 0 }}>
          {!table && schema && (
            <Tabs
              items={[
                {
                  key: 'map',
                  label: 'How it all connects',
                  children: (
                    <Panel title="Every kind of record, and how they point at each other"
                      extra="Hover a box to light up its links · click to browse it">
                      <SchemaMap schema={schema} onOpen={(t) => go(t)} />
                    </Panel>
                  ),
                },
                { key: 'charts', label: 'Charts', children: <InsightsPage /> },
              ]}
            />
          )}
          {table && recordId == null && entity && <EntityList key={table} table={table} label={entity.label} edit={entity.edit} onOpen={(id) => go(table, id)} />}
          {table && recordId != null && (
            <RecordView
              key={`${table}-${recordId}`}
              table={table}
              id={recordId}
              trail={trail}
              onGo={go}
              onLoaded={onRecordLoaded}
            />
          )}
          {table && schema && !entity && <Empty description="Nothing to show here" />}
        </div>
      </div>
    </div>
  );
}

function SideItem({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count?: number }) {
  const { token } = theme.useToken();
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        all: 'unset',
        boxSizing: 'border-box',
        width: '100%',
        display: 'flex',
        justifyContent: 'space-between',
        gap: 8,
        padding: '5px 10px',
        borderRadius: 6,
        cursor: 'pointer',
        fontSize: 13,
        color: active ? token.colorText : token.colorTextSecondary,
        fontWeight: active ? 600 : 400,
        background: active ? 'rgba(92,198,255,0.12)' : undefined,
      }}
    >
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
      {count != null && <span className="u-mono" style={{ fontSize: 11, color: token.colorTextTertiary }}>{count}</span>}
    </button>
  );
}

function GlobalSearch({ onPick }: { onPick: (table: string, id: number) => void }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<SearchGroup[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    clearTimeout(timer.current);
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    timer.current = setTimeout(() => {
      api.get<SearchGroup[]>(`/api/explore/search?q=${encodeURIComponent(q.trim())}`).then(setResults).catch(() => {});
    }, 250);
  }, [q]);

  return (
    <AutoComplete
      value={q}
      onChange={setQ}
      style={{ width: '100%', maxWidth: 560 }}
      options={results.map((g) => ({
        label: `${g.label}`,
        options: g.rows.map((r) => ({ value: `${g.table}:${r.id}`, label: r.title })),
      }))}
      onSelect={(v: string) => {
        const [t, id] = v.split(':');
        setQ('');
        onPick(t, Number(id));
      }}
      notFoundContent={q.trim().length >= 2 ? 'No matches' : null}
    >
      <Input size="large" allowClear prefix={<SearchOutlined style={{ opacity: 0.5 }} />}
        placeholder="Find anything — a member, an event, a budget item, a team, a season…" />
    </AutoComplete>
  );
}

const MODE_KEY = 'explore-list-mode';

function EntityList({ table, label, edit, onOpen }: { table: string; label: string; edit?: string | null; onOpen: (id: number) => void }) {
  const [mode, setMode] = useState<'browse' | 'sheet'>(() => {
    try {
      return localStorage.getItem(MODE_KEY) === 'sheet' ? 'sheet' : 'browse';
    } catch {
      return 'browse';
    }
  });
  const pickMode = (m: 'browse' | 'sheet') => {
    setMode(m);
    try {
      localStorage.setItem(MODE_KEY, m);
    } catch {
      /* storage unavailable */
    }
  };
  const toggle = edit ? (
    <Segmented
      size="small"
      value={mode}
      onChange={(v) => pickMode(v as 'browse' | 'sheet')}
      options={[
        { value: 'browse', label: 'Browse', icon: <UnorderedListOutlined /> },
        { value: 'sheet', label: 'Edit as sheet', icon: <TableOutlined /> },
      ]}
    />
  ) : null;

  if (edit && mode === 'sheet') {
    return (
      <Panel title={label} extra={toggle}>
        <DataGrid table={edit} allowUpload onOpenRow={onOpen} showDescription height="68vh" />
      </Panel>
    );
  }
  return <EntityBrowse table={table} label={label} toggle={toggle} onOpen={onOpen} />;
}

function EntityBrowse({ table, label, toggle, onOpen }: { table: string; label: string; toggle: React.ReactNode; onOpen: (id: number) => void }) {
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; columns: { name: string; label: string }[]; rows: ExploreRow[] } | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      api
        .get<{ total: number; columns: { name: string; label: string }[]; rows: ExploreRow[] }>(
          `/api/explore/${table}?q=${encodeURIComponent(q.trim())}&offset=${(page - 1) * PAGE}&limit=${PAGE}`,
        )
        .then(setData)
        .catch(() => setData({ total: 0, columns: [], rows: [] }));
    }, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [table, q, page]);

  const cols = data?.columns ?? [];

  return (
    <Panel
      title={label}
      extra={
        <Space size={12}>
          {data && <span>{`${data.total.toLocaleString('en-US')} record${data.total === 1 ? '' : 's'}`}</span>}
          {toggle}
        </Space>
      }
    >
      <Input
        allowClear
        prefix={<SearchOutlined style={{ opacity: 0.5 }} />}
        placeholder={`Search ${label.toLowerCase()}`}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setPage(1);
        }}
        style={{ maxWidth: 320, marginBottom: 12 }}
      />
      <Table<ExploreRow>
        size="small"
        rowKey="id"
        className="circuit-table"
        loading={data === null}
        dataSource={data?.rows ?? []}
        onRow={(r) => ({ onClick: () => onOpen(r.id) })}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: page,
          pageSize: PAGE,
          total: data?.total ?? 0,
          onChange: setPage,
          showSizeChanger: false,
          size: 'small',
          hideOnSinglePage: true,
        }}
        columns={[
          { title: 'Name', dataIndex: 'title', render: (v: string) => <span style={{ fontWeight: 500 }}>{v}</span> },
          ...cols.map((c) => ({
            title: c.label,
            key: c.name,
            render: (_: unknown, r: ExploreRow) => formatCell(r.fields[c.name], c.name),
          })),
        ]}
      />
    </Panel>
  );
}

function RecordView({
  table,
  id,
  trail,
  onGo,
  onLoaded,
}: {
  table: string;
  id: number;
  trail: { table: string; id: number; title: string }[];
  onGo: (table: string | null, id?: number) => void;
  onLoaded: (r: ExploreRecord) => void;
}) {
  const { token } = theme.useToken();
  const [rec, setRec] = useState<ExploreRecord | null>(null);
  const [missing, setMissing] = useState(false);
  const [showEmpty, setShowEmpty] = useState(false);
  const [editFields, setEditFields] = useState(false);
  const [sheets, setSheets] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState<AddableGroup[]>([]); // related lists opened from "add", kept in place
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const toggleSheet = (key: string) =>
    setSheets((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  useEffect(() => {
    api
      .get<ExploreRecord>(`/api/explore/${table}/${id}`)
      .then((r) => {
        setRec(r);
        onLoaded(r);
      })
      .catch(() => setMissing(true));
  }, [table, id, onLoaded, tick]);

  if (missing) return <Empty description="This record doesn't exist or isn't visible to you" />;
  if (!rec) return <Skeleton active paragraph={{ rows: 10 }} />;

  const openRef = (r: RecordRef) => onGo(r.table, r.id);
  const openGroup = (g: RelatedGroup) =>
    sectionRefs.current[g.key]?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const allFields = rec.fields.filter((f) => f.name !== 'id');
  const isEmpty = (f: (typeof allFields)[number]) => !f.link && (f.value === null || f.value === '');
  const emptyCount = allFields.filter(isEmpty).length;
  const fields = showEmpty ? allFields : allFields.filter((f) => !isEmpty(f));
  const past = trail.filter((t) => !(t.table === rec.table && t.id === rec.id));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <a onClick={() => onGo(rec.table)} style={{ fontSize: 13 }}>
          <ArrowLeftOutlined /> Back to the list
        </a>
        {past.length > 0 && (
          <Breadcrumb
            items={[
              { title: <span style={{ color: token.colorTextQuaternary }}>Recently</span> },
              ...past.map((t) => ({ title: <a onClick={() => onGo(t.table, t.id)}>{t.title}</a> })),
            ]}
          />
        )}
      </div>

      <div>
        <Tag color="processing">{rec.entity}</Tag>
        <Typography.Title level={3} style={{ margin: '6px 0 0' }}>{rec.title}</Typography.Title>
        <Typography.Text type="secondary">
          {rec.outgoing.length} link{rec.outgoing.length === 1 ? '' : 's'} out ·{' '}
          {rec.incoming.reduce((n, g) => n + g.total, 0).toLocaleString('en-US')} record
          {rec.incoming.reduce((n, g) => n + g.total, 0) === 1 ? '' : 's'} linked to it
        </Typography.Text>
      </div>

      {(rec.outgoing.length > 0 || rec.incoming.length > 0) && (
        <Panel title="Connections" extra="Left: what it points to · right: what points to it">
          <RecordGraph record={rec} onOpenRecord={openRef} onOpenGroup={openGroup} />
        </Panel>
      )}

      <Panel
        title="Details"
        extra={
          <Space size={12}>
            {!editFields && emptyCount > 0 && (
              <a onClick={() => setShowEmpty((v) => !v)}>
                {showEmpty ? 'Hide empty fields' : `Show ${emptyCount} empty field${emptyCount === 1 ? '' : 's'}`}
              </a>
            )}
            {rec.edit && (
              <Button size="small" type={editFields ? 'primary' : 'default'} icon={<EditOutlined />} onClick={() => setEditFields((v) => !v)}>
                {editFields ? 'Done' : 'Edit'}
              </Button>
            )}
          </Space>
        }
      >
        {editFields && rec.edit ? (
          <RecordEditor table={rec.edit} id={rec.id} onSaved={reload} />
        ) : (
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }} bordered>
          {fields.map((f) => (
            <Descriptions.Item key={f.name} label={f.computed ? <span>{f.label} <span style={{ opacity: 0.6 }}>(computed)</span></span> : f.label}>
              {f.link ? (
                <a onClick={() => openRef(f.link!)}>{f.link.title}</a>
              ) : (
                <span style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{formatCell(f.value, f.name)}</span>
              )}
            </Descriptions.Item>
          ))}
        </Descriptions>
        )}
        {rec.outgoing.some((o) => o.via) && (
          <div style={{ marginTop: 10, fontSize: 13, color: token.colorTextSecondary }}>
            Also, through the {rec.outgoing.find((o) => o.via)!.via!.toLowerCase()}:{' '}
            {rec.outgoing.filter((o) => o.via).map((o, i) => (
              <span key={`${o.table}-${o.id}`}>
                {i > 0 && ' · '}
                {o.relation}: <a onClick={() => openRef(o)}>{o.title}</a>
              </span>
            ))}
          </div>
        )}
      </Panel>

      {rec.incoming.filter((g) => !adding.some((a) => a.key === g.key)).map((g) => (
        <div key={g.key} ref={(el) => (sectionRefs.current[g.key] = el)} style={{ scrollMarginTop: 80 }}>
          <Panel
            title={g.label}
            extra={
              <Space size={12}>
                <span>{`${g.total.toLocaleString('en-US')}${g.total > g.rows.length && !sheets.has(g.key) ? ` · showing ${g.rows.length}` : ''}${g.via ? ` · via ${g.via.toLowerCase()}` : ` · as ${g.relation.toLowerCase()}`}`}</span>
                {g.edit && (
                  <Button size="small" type={sheets.has(g.key) ? 'primary' : 'default'} icon={<TableOutlined />} onClick={() => toggleSheet(g.key)}>
                    {sheets.has(g.key) ? 'Done' : 'Edit'}
                  </Button>
                )}
              </Space>
            }
          >
            {g.edit && g.fk && sheets.has(g.key) ? (
              <DataGrid
                table={g.edit}
                fixed={{ [g.fk]: String(rec.id) }}
                compact
                showDescription={false}
                height="48vh"
                onChanged={reload}
                onOpenRow={(rid) => onGo(g.table, rid)}
              />
            ) : (
            <Table<ExploreRow>
              size="small"
              rowKey={(r) => `${r.id}`}
              className="circuit-table"
              dataSource={g.rows}
              onRow={(r) => ({ onClick: () => onGo(g.table, r.id) })}
              pagination={{ pageSize: 10, size: 'small', hideOnSinglePage: true }}
              scroll={{ x: 'max-content' }}
              columns={[
                { title: 'Name', dataIndex: 'title', render: (v: string) => <span style={{ fontWeight: 500 }}>{v}</span> },
                ...g.columns.map((c) => ({
                  title: c.label,
                  key: c.name,
                  render: (_: unknown, r: ExploreRow) => formatCell(r.fields[c.name], c.name),
                })),
              ]}
            />
            )}
          </Panel>
        </div>
      ))}

      {adding.map((a) => (
        <Panel
          key={a.key}
          title={a.label}
          extra={
            <Button size="small" type="primary" icon={<TableOutlined />} onClick={() => setAdding((xs) => xs.filter((x) => x.key !== a.key))}>
              Done
            </Button>
          }
        >
          <DataGrid
            table={a.edit}
            fixed={{ [a.fk]: String(rec.id) }}
            compact
            showDescription={false}
            height="48vh"
            onChanged={reload}
            onOpenRow={(rid) => onGo(a.table, rid)}
          />
        </Panel>
      ))}

      {!!rec.addable?.some((a) => !adding.some((x) => x.key === a.key)) && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>Add linked records:</Typography.Text>
          {rec.addable.filter((a) => !adding.some((x) => x.key === a.key)).map((a) => (
            <Button key={a.key} size="small" icon={<PlusOutlined />} onClick={() => setAdding((xs) => [...xs, a])}>
              {a.label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
