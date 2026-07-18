import { CloudSyncOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Input,
  List,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { RebuildBatch, RebuildReport, SheetExportStatus } from '../api/types';

const TAB_LABELS: Record<string, string> = {
  people: 'People',
  positions: 'Positions',
  competitions: 'Competitions',
  competition_categories: 'Competition categories',
  competition_teams: 'Competition teams',
  competition_pms: 'Competition PMs',
  competition_team_members: 'Team members',
  inventory_locations: 'Inventory locations',
  inventory_items: 'Inventory items',
  inventory_movements: 'Inventory movements',
};

function RebuildModal({
  open,
  spreadsheetId,
  orgName,
  report,
  onClose,
  onCommit,
  busy,
}: {
  open: boolean;
  spreadsheetId: string;
  orgName: string;
  report: RebuildReport | null;
  onClose: () => void;
  onCommit: (phrase: string) => void;
  busy: boolean;
}) {
  const [phrase, setPhrase] = useState('');

  useEffect(() => {
    if (open) setPhrase('');
  }, [open]);

  if (!report) return null;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={
        <Space>
          <WarningOutlined style={{ color: '#cf1322' }} />
          <span>Rebuild from Sheets — destructive</span>
        </Space>
      }
      footer={null}
      width={640}
      destroyOnHidden
    >
      <Alert
        type="error"
        showIcon
        message="This replaces the entire database with what's in the sheet."
        description="Anything created in the portal since the last export and not present in the sheet will be destroyed — people, positions, competitions, and inventory. This is a restore from spreadsheet, not a sync. Everyone will need to sign in again afterward. A full snapshot is taken automatically before anything is touched."
        style={{ marginBottom: 16 }}
      />

      <Typography.Text strong>Rows that would be imported:</Typography.Text>
      <List
        size="small"
        dataSource={Object.entries(report.tab_counts)}
        renderItem={([tab, count]) => (
          <List.Item>
            <span>{TAB_LABELS[tab] ?? tab}</span>
            <Typography.Text strong>{count}</Typography.Text>
          </List.Item>
        )}
        style={{ marginBottom: 16 }}
      />

      {report.errors.length > 0 && (
        <Alert
          type="error"
          showIcon
          message={`${report.errors.length} validation error(s) — nothing can be committed until these are fixed in the sheet`}
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {report.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {report.errors.length === 0 && (
        <>
          <Typography.Paragraph>
            Type <Typography.Text code>{orgName}</Typography.Text> to confirm you understand this
            destroys and rebuilds the database from <Typography.Text code>{spreadsheetId}</Typography.Text>.
          </Typography.Paragraph>
          <Input
            placeholder={orgName}
            value={phrase}
            onChange={(e) => setPhrase(e.target.value)}
            style={{ marginBottom: 12 }}
          />
          <Button
            danger
            type="primary"
            block
            disabled={!orgName || phrase !== orgName}
            loading={busy}
            onClick={() => onCommit(phrase)}
          >
            I understand — rebuild the database now
          </Button>
        </>
      )}
    </Modal>
  );
}

export default function SheetsSyncPage() {
  const [spreadsheetId, setSpreadsheetId] = useState('');
  const [orgName, setOrgName] = useState('');
  const [exports, setExports] = useState<SheetExportStatus[]>([]);
  const [history, setHistory] = useState<RebuildBatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [dryRunning, setDryRunning] = useState(false);
  const [report, setReport] = useState<RebuildReport | null>(null);
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [committing, setCommitting] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get<SheetExportStatus[]>('/api/sync/exports'),
      api.get<RebuildBatch[]>('/api/sync/rebuild/history'),
    ])
      .then(([e, h]) => {
        setExports(e);
        setHistory(h);
      })
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    api
      .get<{ credentials: boolean; org_name: string }>('/api/sync/status')
      .then((s) => setOrgName(s.org_name))
      .catch(() => {});
  }, []);

  const syncAll = async () => {
    if (!spreadsheetId.trim()) {
      message.warning('Enter a spreadsheet link or ID first');
      return;
    }
    setSyncing(true);
    try {
      const counts = await api.post<Record<string, number>>('/api/sync/export', {
        spreadsheet_id: spreadsheetId.trim(),
      });
      const total = Object.values(counts).reduce((a, b) => a + b, 0);
      message.success(`Synced ${total} rows across ${Object.keys(counts).length} tabs`);
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Export failed');
    } finally {
      setSyncing(false);
    }
  };

  const runDryRun = async () => {
    if (!spreadsheetId.trim()) {
      message.warning('Enter a spreadsheet link or ID first');
      return;
    }
    setDryRunning(true);
    try {
      const r = await api.post<RebuildReport>('/api/sync/rebuild/dry-run', {
        spreadsheet_id: spreadsheetId.trim(),
      });
      setReport(r);
      setRebuildOpen(true);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Dry-run failed');
    } finally {
      setDryRunning(false);
    }
  };

  const commit = async (phrase: string) => {
    setCommitting(true);
    try {
      const r = await api.post<RebuildReport>('/api/sync/rebuild/commit', {
        spreadsheet_id: spreadsheetId.trim(),
        confirm_phrase: phrase,
      });
      if (r.committed) {
        message.success('Rebuild complete — the database now matches the sheet.');
        setRebuildOpen(false);
      } else {
        message.error('Rebuild did not commit — see the report.');
        setReport(r);
      }
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Rebuild failed');
    } finally {
      setCommitting(false);
    }
  };

  return (
    <>
      <Typography.Title level={4} style={{ margin: 0 }}>
        Data Sync
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        The portal is the source of truth; Sheets is a mirror. Export pushes the current
        database out, one tab per entity. Rebuild is the opposite, destructive direction —
        it replaces the database with what's in the sheet.
      </Typography.Paragraph>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="Google Sheet link or ID"
            value={spreadsheetId}
            onChange={(e) => setSpreadsheetId(e.target.value)}
          />
          <Button icon={<CloudSyncOutlined />} loading={syncing} onClick={syncAll}>
            Sync all tabs
          </Button>
          <Button danger icon={<WarningOutlined />} loading={dryRunning} onClick={runDryRun}>
            Rebuild from Sheets…
          </Button>
        </Space.Compact>
      </Card>

      <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={5} style={{ margin: 0 }}>
          Export status
        </Typography.Title>
        <Button size="small" icon={<ReloadOutlined />} onClick={load} />
      </Space>
      <Table
        size="small"
        rowKey="tab"
        loading={loading}
        dataSource={exports}
        pagination={false}
        style={{ marginBottom: 24 }}
        columns={[
          { title: 'Tab', dataIndex: 'tab', render: (t: string) => TAB_LABELS[t] ?? t },
          { title: 'Rows', dataIndex: 'row_count', width: 80 },
          {
            title: 'Status',
            width: 120,
            render: (_, r) =>
              r.last_error ? (
                <Tag color="red">Error</Tag>
              ) : r.is_dirty ? (
                <Tag color="gold">Stale</Tag>
              ) : (
                <Tag color="green">Synced</Tag>
              ),
          },
          {
            title: 'Last synced',
            dataIndex: 'last_synced_at',
            width: 160,
            render: (d: string | null) => (d ? dayjs(d).format('DD MMM HH:mm') : 'never'),
          },
          {
            title: 'Error',
            dataIndex: 'last_error',
            render: (e: string) => e || '—',
          },
        ]}
      />

      <Typography.Title level={5} style={{ margin: '0 0 8px' }}>
        Rebuild history
      </Typography.Title>
      <Table
        size="small"
        rowKey="id"
        dataSource={history}
        pagination={{ pageSize: 10, hideOnSinglePage: true }}
        columns={[
          {
            title: 'Status',
            dataIndex: 'status',
            width: 110,
            render: (s: string) => (
              <Tag color={s === 'succeeded' ? 'green' : s === 'failed' ? 'red' : 'default'}>
                {s.toUpperCase()}
              </Tag>
            ),
          },
          {
            title: 'When',
            dataIndex: 'started_at',
            width: 160,
            render: (d: string) => dayjs(d).format('DD MMM HH:mm'),
          },
          {
            title: 'Rows',
            render: (_, r) => {
              try {
                const counts = JSON.parse(r.tab_counts) as Record<string, number>;
                return Object.values(counts).reduce((a, b) => a + b, 0);
              } catch {
                return '—';
              }
            },
            width: 80,
          },
          { title: 'Snapshot', dataIndex: 'snapshot_path', ellipsis: true, render: (p: string) => p || '—' },
        ]}
      />

      <RebuildModal
        open={rebuildOpen}
        spreadsheetId={spreadsheetId}
        orgName={orgName}
        report={report}
        onClose={() => setRebuildOpen(false)}
        onCommit={commit}
        busy={committing}
      />
    </>
  );
}
