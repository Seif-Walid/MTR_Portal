import {
  Alert,
  Button,
  Divider,
  Form,
  Input,
  Modal,
  Result,
  Select,
  Space,
  Switch,
  Table,
  Typography,
  message,
} from 'antd';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { ImportPreview, ImportResult, UserBrief } from '../api/types';

// target item field -> friendly label; name is required
const FIELDS: { key: string; label: string; required?: boolean }[] = [
  { key: 'name', label: 'Name', required: true },
  { key: 'quantity', label: 'Total quantity' },
  { key: 'category', label: 'Category' },
  { key: 'unit', label: 'Unit' },
  { key: 'asset_tag', label: 'Asset tag' },
  { key: 'location', label: 'Location' },
  { key: 'condition', label: 'Condition' },
];

// guess a source column for a field by fuzzy header match
function guess(headers: string[], field: string): string | undefined {
  const aliases: Record<string, string[]> = {
    name: ['name', 'item', 'component', 'part'],
    quantity: ['qty', 'quantity', 'count', 'total', 'stock'],
    category: ['category', 'type', 'group'],
    unit: ['unit', 'uom'],
    asset_tag: ['asset', 'tag', 'sku', 'code'],
    location: ['location', 'where', 'shelf', 'bin'],
    condition: ['condition', 'state'],
  };
  const wants = aliases[field] ?? [field];
  return headers.find((h) => wants.some((w) => h.toLowerCase().includes(w)));
}

export default function ImportFromSheetModal({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const [source, setSource] = useState('');
  const [worksheet, setWorksheet] = useState('');
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | undefined>>({});
  const [teamLeadId, setTeamLeadId] = useState<number | undefined>();
  const [upsert, setUpsert] = useState(true);
  const [holders, setHolders] = useState<UserBrief[]>([]);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setSource('');
      setWorksheet('');
      setPreview(null);
      setMapping({});
      setResult(null);
      api.get<UserBrief[]>('/api/inventory/holders').then(setHolders).catch(() => {});
    }
  }, [open]);

  const runPreview = async () => {
    setBusy(true);
    try {
      const p = await api.post<ImportPreview>('/api/inventory/import/preview', {
        source,
        worksheet: worksheet || null,
      });
      setPreview(p);
      const seeded: Record<string, string | undefined> = {};
      FIELDS.forEach((f) => (seeded[f.key] = guess(p.headers, f.key)));
      setMapping(seeded);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not read the sheet');
    } finally {
      setBusy(false);
    }
  };

  const runImport = async () => {
    if (!preview) return;
    if (!mapping.name) {
      message.error('Map a column to the item name.');
      return;
    }
    setBusy(true);
    try {
      const cleaned = Object.fromEntries(
        Object.entries(mapping).filter(([, v]) => v),
      ) as Record<string, string>;
      const res = await api.post<ImportResult>('/api/inventory/import', {
        spreadsheet_id: preview.spreadsheet_id,
        worksheet: preview.worksheet,
        mapping: cleaned,
        team_lead_id: teamLeadId ?? null,
        upsert,
      });
      setResult(res);
      onImported();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Import failed');
    } finally {
      setBusy(false);
    }
  };

  const headerOptions = (preview?.headers ?? []).map((h) => ({ value: h, label: h }));

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="Import components from Google Sheet"
      width={720}
      footer={null}
      destroyOnHidden
    >
      {result ? (
        <Result
          status="success"
          title="Import complete"
          subTitle={`Created ${result.created} · Updated ${result.updated} · Skipped ${result.skipped}`}
          extra={<Button type="primary" onClick={onClose}>Done</Button>}
        />
      ) : (
        <>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Share the sheet with the service account"
            description="The Google Sheet must be shared (viewer is enough) with the portal's service-account email for the import to read it."
          />
          <Space.Compact style={{ width: '100%' }}>
            <Input
              placeholder="Paste the Google Sheet link or ID"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            />
            <Input
              placeholder="Worksheet (optional)"
              style={{ maxWidth: 200 }}
              value={worksheet}
              onChange={(e) => setWorksheet(e.target.value)}
            />
            <Button type="primary" loading={busy} disabled={!source} onClick={runPreview}>
              Preview
            </Button>
          </Space.Compact>

          {preview && (
            <>
              <Divider plain>{preview.total} rows found — map your columns</Divider>
              <Form layout="vertical">
                <Space wrap size={[16, 0]}>
                  {FIELDS.map((f) => (
                    <Form.Item
                      key={f.key}
                      label={f.required ? `${f.label} *` : f.label}
                      style={{ minWidth: 200 }}
                    >
                      <Select
                        allowClear={!f.required}
                        placeholder="— none —"
                        value={mapping[f.key]}
                        onChange={(v) => setMapping((m) => ({ ...m, [f.key]: v }))}
                        options={headerOptions}
                        status={f.required && !mapping[f.key] ? 'error' : undefined}
                      />
                    </Form.Item>
                  ))}
                </Space>
                <Form.Item label="Dedicate all imported items to a team (optional)">
                  <Select
                    allowClear
                    showSearch
                    optionFilterProp="label"
                    placeholder="General storage"
                    style={{ maxWidth: 360 }}
                    value={teamLeadId}
                    onChange={setTeamLeadId}
                    options={holders.map((u) => ({ value: u.id, label: `${u.full_name} (${u.email})` }))}
                  />
                </Form.Item>
                <Form.Item>
                  <Space>
                    <Switch checked={upsert} onChange={setUpsert} />
                    <Typography.Text>Update existing items (matched by asset tag or name)</Typography.Text>
                  </Space>
                </Form.Item>
              </Form>

              <Typography.Text type="secondary">Preview (first rows)</Typography.Text>
              <Table
                size="small"
                style={{ marginTop: 8 }}
                rowKey={(_, i) => String(i)}
                dataSource={preview.rows}
                pagination={false}
                scroll={{ x: 'max-content', y: 200 }}
                columns={preview.headers.map((h) => ({ title: h, dataIndex: h, ellipsis: true }))}
              />

              <Button
                type="primary"
                block
                style={{ marginTop: 16 }}
                loading={busy}
                disabled={!mapping.name}
                onClick={runImport}
              >
                Import {preview.total} rows
              </Button>
            </>
          )}
        </>
      )}
    </Modal>
  );
}
