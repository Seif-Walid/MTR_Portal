import { BellOutlined } from '@ant-design/icons';
import { Badge, Button, Empty, List, Popover, Typography, theme } from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import type { AppNotification } from '../api/types';

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
    return () => clearInterval(timer);
  }, [refreshCount]);

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
  };

  const openTarget = (n: AppNotification) => {
    setOpen(false);
    if (n.task_id) navigate(`/tasks?task=${n.task_id}`);
    else if (n.request_id) navigate('/requests');
  };

  const content = (
    <div style={{ width: 360, maxHeight: 420, overflow: 'auto' }}>
      {items.length === 0 ? (
        <Empty description="No notifications" image={Empty.PRESENTED_IMAGE_SIMPLE} />
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
                  title={<Typography.Text style={{ fontSize: 13 }}>{n.message}</Typography.Text>}
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
    <Popover content={content} trigger="click" open={open} onOpenChange={onOpenChange} placement="bottomRight">
      <Badge count={count} size="small">
        <Button type="text" icon={<BellOutlined style={{ fontSize: 18 }} />} />
      </Badge>
    </Popover>
  );
}
