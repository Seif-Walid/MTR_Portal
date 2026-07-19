import { PlusOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useState } from 'react';
import { Button, Drawer, Input, Modal, Segmented, Select, Space, Table, Tag, Typography, message } from 'antd';
import dayjs from 'dayjs';

import { api, ApiError } from '../api/client';
import type { InventoryRequest, InventoryRequestStatus, Location, Whereabouts } from '../api/types';
import { can, useAuth } from '../auth/AuthContext';
import RequestUnitsModal from './RequestUnitsModal';

const STATUS_META: Record<InventoryRequestStatus, { label: string; color: string }> = {
  submitted: { label: 'Submitted', color: 'processing' },
  approved: { label: 'Approved', color: 'blue' },
  rejected: { label: 'Rejected', color: 'error' },
  issued: { label: 'Issued', color: 'gold' },
  returned: { label: 'Returned', color: 'success' },
};

function IssueModal({ req, open, onClose, onDone }: {
  req: InventoryRequest | null;
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [options, setOptions] = useState<{ value: number; label: string }[]>([]);
  const [locationId, setLocationId] = useState<number>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && req) {
      setLocationId(undefined);
      api.get<Whereabouts>(`/api/inventory/${req.item.id}/whereabouts`).then((w) => {
        setOptions(
          w.by_location
            .filter((p) => p.quantity >= req.quantity)
            .map((p) => ({ value: p.location!.id, label: `${p.location!.name} (${p.quantity} on hand)` })),
        );
      });
    }
  }, [open, req]);

  const issue = async () => {
    if (!req || !locationId) return;
    setBusy(true);
    try {
      await api.post(`/api/inventory/requests/${req.id}/issue`, { from_location_id: locationId });
      message.success('Issued');
      onDone();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to issue');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title={`Issue ${req?.quantity} ${req?.item.unit}(s) of ${req?.item.name}`} onOk={issue} okButtonProps={{ disabled: !locationId, loading: busy }}>
      <Select
        style={{ width: '100%' }}
        placeholder={options.length ? 'Issue from…' : 'No location has enough on hand'}
        options={options}
        value={locationId}
        onChange={setLocationId}
      />
    </Modal>
  );
}

function ReturnModal({ req, open, onClose, onDone }: {
  req: InventoryRequest | null;
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [locations, setLocations] = useState<Location[]>([]);
  const [locationId, setLocationId] = useState<number>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setLocationId(undefined);
      api.get<Location[]>('/api/inventory/locations').then(setLocations);
    }
  }, [open]);

  const doReturn = async () => {
    if (!req || !locationId) return;
    setBusy(true);
    try {
      await api.post(`/api/inventory/requests/${req.id}/return`, { to_location_id: locationId });
      message.success('Returned');
      onDone();
      onClose();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed to return');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} title={`Return ${req?.quantity} ${req?.item.unit}(s) of ${req?.item.name}`} onOk={doReturn} okButtonProps={{ disabled: !locationId, loading: busy }}>
      <Select
        style={{ width: '100%' }}
        placeholder="Return to…"
        options={locations.map((l) => ({ value: l.id, label: l.name }))}
        value={locationId}
        onChange={setLocationId}
      />
    </Modal>
  );
}

export default function InventoryRequestsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { me } = useAuth();
  const canManage = can(me, 'inventory.approve');
  const [view, setView] = useState<'mine' | 'to_review'>('mine');
  const [requests, setRequests] = useState<InventoryRequest[]>([]);
  const [loading, setLoading] = useState(false);
  const [issuing, setIssuing] = useState<InventoryRequest | null>(null);
  const [returning, setReturning] = useState<InventoryRequest | null>(null);
  const [rejecting, setRejecting] = useState<InventoryRequest | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.get<InventoryRequest[]>(`/api/inventory/requests?view=${view}`)
      .then(setRequests)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false));
  }, [view]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const approve = async (req: InventoryRequest) => {
    try {
      await api.post(`/api/inventory/requests/${req.id}/approve`);
      message.success('Approved');
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };

  const reject = async () => {
    if (!rejecting) return;
    try {
      await api.post(`/api/inventory/requests/${rejecting.id}/reject`, { reason: rejectReason });
      message.success('Rejected');
      setRejecting(null);
      setRejectReason('');
      load();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Failed');
    }
  };

  const columns = [
    { title: 'Item', render: (_: unknown, r: InventoryRequest) => r.item.name },
    { title: 'Qty', dataIndex: 'quantity', width: 70 },
    { title: 'Requester', render: (_: unknown, r: InventoryRequest) => r.requester.full_name },
    {
      title: 'Status', width: 140,
      render: (_: unknown, r: InventoryRequest) => (
        <Space size={4}>
          <Tag color={STATUS_META[r.status].color}>{STATUS_META[r.status].label}</Tag>
          {r.is_overdue && <Tag color="red">OVERDUE</Tag>}
        </Space>
      ),
    },
    {
      title: 'Needed / Return by', width: 180,
      render: (_: unknown, r: InventoryRequest) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {r.needed_by ? `need ${dayjs(r.needed_by).format('DD MMM')}` : ''}
          {r.needed_by && r.return_by ? ' · ' : ''}
          {r.return_by ? `return ${dayjs(r.return_by).format('DD MMM')}` : ''}
          {!r.needed_by && !r.return_by ? '—' : ''}
        </Typography.Text>
      ),
    },
    {
      title: '', width: 220,
      render: (_: unknown, r: InventoryRequest) => (
        <Space wrap>
          {r.status === 'submitted' && canManage && (
            <>
              <Button size="small" type="primary" onClick={() => approve(r)}>Approve</Button>
              <Button size="small" danger onClick={() => setRejecting(r)}>Reject</Button>
            </>
          )}
          {r.status === 'approved' && canManage && (
            <Button size="small" type="primary" onClick={() => setIssuing(r)}>Issue</Button>
          )}
          {r.status === 'issued' && (canManage || r.requester.id === me?.id) && (
            <Button size="small" onClick={() => setReturning(r)}>Return</Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <Drawer open={open} onClose={onClose} width={760} title="Inventory requests">
        <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'space-between' }}>
          <Segmented
            value={view}
            onChange={(v) => setView(v as 'mine' | 'to_review')}
            options={[
              { label: 'My requests', value: 'mine' },
              ...(canManage ? [{ label: 'To review', value: 'to_review' }] : []),
            ]}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            New request
          </Button>
        </Space>
        <Table rowKey="id" loading={loading} dataSource={requests} columns={columns} pagination={{ pageSize: 10, hideOnSinglePage: true }} />
      </Drawer>

      <IssueModal req={issuing} open={!!issuing} onClose={() => setIssuing(null)} onDone={load} />
      <ReturnModal req={returning} open={!!returning} onClose={() => setReturning(null)} onDone={load} />
      <Modal
        open={!!rejecting}
        onCancel={() => setRejecting(null)}
        title={`Reject request for ${rejecting?.item.name}`}
        onOk={reject}
      >
        <Input.TextArea rows={2} placeholder="Reason (optional)" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} />
      </Modal>
      <RequestUnitsModal open={creating} onClose={() => setCreating(false)} onRequested={load} />
    </>
  );
}
