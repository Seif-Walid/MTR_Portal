import { BellOutlined } from '@ant-design/icons';
import { Badge, Button, List, Popover, Typography, theme } from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { AppNotification } from '../api/types';
import { clearAppBadge, onServiceWorkerMessage, pushState } from '../lib/push';
import EmptyState from './EmptyState';

dayjs.extend(relativeTime);

export default function NotificationsBell() {
  const [count, setCount] = useState(0);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { token } = theme.useToken();

  const refreshCount = useCallback(() => {
    api
      .get<{ count: number }>('/api/notifications/unread-count')
      .then((r) => setCount(r.count))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshCount();
    const timer = setInterval(refreshCount, 30_000);
    // a push arrived: update now instead of waiting for the next poll
    const off = onServiceWorkerMessage((m) => { if (m.type === 'notifications-changed') refreshCount(); });
    return () => { clearInterval(timer); off(); };
  }, [refreshCount]);

  // offer push notifications to people who haven't turned them on here
  const [pushOffer, setPushOffer] = useState(false);
  useEffect(() => {
    if (open) pushState().then((s) => setPushOffer(s === 'off' || s === 'ios-install')).catch(() => {});
  }, [open]);

  const onOpenChange = async (next: boolean) => {
    setOpen(next);
    if (next) {
      const list = await api.get<AppNotification[]>('/api/notifications');
      setItems(list);
    }
  };

  const markAllRead = async () => {
    await api.post('/api/notifications/mark-read', {});
    setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
    setCount(0);
    clearAppBadge();
  };

  const openTarget = (n: AppNotification) => {
    setOpen(false);
    if (n.task_id) navigate(`/tasks?task=${n.task_id}`);
    else if (n.request_id) navigate('/requests');
    else if (n.type === 'application_received') navigate('/applications');
  };

  const content = (
    <div style={{ width: 'min(360px, calc(100vw - 56px))', maxHeight: 'min(420px, calc(100vh - 120px))', overflow: 'auto' }}>
      {pushOffer && (
        <Button
          block
          size="small"
          type="dashed"
          style={{ marginBottom: 8 }}
          onClick={() => { setOpen(false); window.dispatchEvent(new Event('open-push-settings')); }}
        >
          Get these on your phone or computer
        </Button>
      )}
      {items.length === 0 ? (
        <EmptyState compact phrase="You're all caught up." />
      ) : (
        <>
          <div style={{ textAlign: 'right', marginBottom: 4 }}>
            <Button size="small" type="link" onClick={markAllRead} disabled={count === 0}>
              Mark all read
            </Button>
          </div>
          <List
            size="small"
            dataSource={items}
            renderItem={(n) => (
              <List.Item
                style={{ cursor: 'pointer', background: n.is_read ? undefined : token.colorFillTertiary }}
                onClick={() => openTarget(n)}
              >
                <List.Item.Meta
                  title={<Typography.Text style={{ fontSize: 13, overflowWrap: 'anywhere' }}>{n.message}</Typography.Text>}
                  description={dayjs(n.created_at).fromNow()}
                />
              </List.Item>
            )}
          />
        </>
      )}
    </div>
  );

  return (
    <Popover content={content} trigger="click" open={open} onOpenChange={onOpenChange} placement="bottomRight"
      // keep it on screen on narrow phones: slide sideways instead of hanging off the edge
      align={{ overflow: { adjustX: true, adjustY: true, shiftX: 16 } }}
    >
      <Badge count={count} size="small">
        <Button aria-label={count ? `Notifications, ${count} unread` : "Notifications"} aria-haspopup="dialog" aria-expanded={open} type="text" icon={<BellOutlined style={{ fontSize: 18 }} />} />
      </Badge>
    </Popover>
  );
}
