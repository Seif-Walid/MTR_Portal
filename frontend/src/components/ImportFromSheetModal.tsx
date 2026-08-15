import { InboxOutlined } from '@ant-design/icons';
import {
  Button,
  Divider,
  Form,
  Modal,
  Result,
  Select,
  Space,
  Switch,
  Table,
  Typography,
  Upload,
  message,
} from 'antd';
import type { UploadFile } from 'antd/es/upload/interface';
import { useEffect, useState } from 'react';

import { api, ApiError } from '../api/client';
import type { FileImportPreview, ImportResult, UserBrief } from '../api/types';

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
  // Local file only (Google Sheet import was removed)
  const [file, setFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<FileImportPreview | null>(null);

  const [mapping, setMapping] = useState<Record<string, string | undefined>>({});
  const [teamLeadId, setTeamLeadId] = useState<number | undefined>();
  const [upsert, setUpsert] = useState(true);
  const [holders, setHolders] = useState<UserBrief[]>([]);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setFile(null);
      setFilePreview(null);
      setMapping({});
      setResult(null);
      api.get<UserBrief[]>('/api/inventory/holders').then(setHolders).catch(() => {});
    }
  }, [open]);

  const seedMapping = (headers: string[]) => {
    const seeded: Record<string, string | undefined> = {};
    FIELDS.forEach((f) => (seeded[f.key] = guess(headers, f.key)));
    setMapping(seeded);
  };

  const runFilePreview = async (f: File, sheet?: string) => {
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', f);
      if (sheet) form.append('sheet', sheet);
      const p = await api.upload<FileImportPreview>('/api/inventory/import/file/preview', form);
      setFilePreview(p);
      seedMapping(p.headers);
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not read the file');
      setFilePreview(null);
    } finally {
      setBusy(false);
    }
  };

  const runImport = async () => {
    if (!mapping.name) {
      message.error('Map a column to the item name.');
      return;
    }
    if (!file || !filePreview) return;
    setBusy(true);
    try {
      const cleaned = Object.fromEntries(
        Object.entries(mapping).filter(([, v]) => v),
      ) as Record<string, string>;
      const form = new FormData();
      form.append('file', file);
      if (filePreview.sheet) form.append('sheet', filePreview.sheet);
      form.append('mapping', JSON.stringify(cleaned));
      if (teamLeadId) form.append('team_lead_id', String(teamLeadId));
      form.append('upsert', String(upsert));
      const res = await api.upload<ImportResult>('/api/inventory/import/file', form);
      setResult(res);
      onImported();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Import failed');
    } finally {
      setBusy(false);
    }
  };

  const active = filePreview;
  const headerOptions = (active?.headers ?? []).map((h) => ({ value: h, label: h }));

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="Import components"
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
          <Upload.Dragger
            accept=".xlsx,.xlsm,.csv"
            showUploadList={false}
            maxCount={1}
            customRequest={() => {}}
            beforeUpload={(f: UploadFile | File) => {
              const realFile = f as File;
              setFile(realFile);
              setFilePreview(null);
              runFilePreview(realFile);
              return false;
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">
              {file ? file.name : 'Click or drag a .xlsx or .csv file here'}
            </p>
            <p className="ant-upload-hint">Import components from a spreadsheet — the file is read once and discarded.</p>
          </Upload.Dragger>

          {filePreview?.sheets && filePreview.sheets.length > 1 && (
            <Form.Item label="Tab" style={{ marginTop: 12, marginBottom: 0 }}>
              <Select
                value={filePreview.sheet ?? undefined}
                style={{ maxWidth: 360 }}
                options={filePreview.sheets.map((s) => ({ value: s, label: s }))}
                onChange={(s) => file && runFilePreview(file, s)}
              />
            </Form.Item>
          )}

          {active && (
            <>
              <Divider plain>{active.total} rows found — map your columns</Divider>
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
              <Table className="circuit-table"
                size="small"
                style={{ marginTop: 8 }}
                rowKey={(_, i) => String(i)}
                dataSource={active.rows}
                pagination={false}
                scroll={{ x: 'max-content', y: 200 }}
                columns={active.headers.map((h) => ({ title: h, dataIndex: h, ellipsis: true }))}
              />

              <Button
                type="primary"
                block
                style={{ marginTop: 16 }}
                loading={busy}
                disabled={!mapping.name}
                onClick={runImport}
              >
                Import {active.total} rows
              </Button>
            </>
          )}
        </>
      )}
    </Modal>
  );
}
