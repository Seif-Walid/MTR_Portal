import { DeleteOutlined } from '@ant-design/icons';
import { Alert, App as AntApp, Button, List, Modal, Space, Switch, Typography } from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useCallback, useEffect, useState } from 'react';

import {
  disablePush,
  enablePush,
  listDevices,
  pushState,
  removeDevice,
  sendTestPush,
  type PushDevice,
  type PushState,
} from '../lib/push';

dayjs.extend(relativeTime);

/** "Notifications on this device" — turn push on/off here, send a test, and
 *  see / remove the other devices that get your notifications. */
export default function PushSettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = AntApp.useApp();
  const [state, setState] = useState<PushState | null>(null);
  const [devices, setDevices] = useState<PushDevice[]>([]);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setState(await pushState());
    setDevices(await listDevices().catch(() => []));
  }, []);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  const toggle = async (on: boolean) => {
    setBusy(true);
    try {
      const next = on ? await enablePush() : await disablePush();
      setState(next);
      if (on && next === 'on') message.success('Notifications turned on for this device');
      if (on && next === 'denied') message.error('Notifications are blocked for this site in your browser settings');
      setDevices(await listDevices().catch(() => []));
    } catch (e) {
      message.error(e instanceof Error ? e.message : 'Could not change notifications');
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    try {
      const { sent } = await sendTestPush();
      if (sent) message.success(`Test sent to ${sent} device${sent === 1 ? '' : 's'}`);
      else message.warning('No device accepted the test. Turn notifications on first.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    await removeDevice(id);
    await refresh();
  };

  return (
    <Modal open={open} onCancel={onClose} footer={null} title="Notifications" destroyOnClose>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          Get task assignments, comments, requests and applications as phone or computer notifications,
          even when the portal is closed.
        </Typography.Paragraph>

        {state === 'ios-install' && (
          <Alert
            type="info"
            showIcon
            message="Install the app first"
            description='On iPhone and iPad, notifications only work from the installed app: tap Share, then "Add to Home Screen", open the portal from there and come back here.'
          />
        )}
        {state === 'unsupported' && (
          <Alert type="warning" showIcon message="This browser can't receive push notifications." />
        )}
        {state === 'denied' && (
          <Alert
            type="warning"
            showIcon
            message="Notifications are blocked"
            description="Allow notifications for this site in your browser or phone settings, then come back here."
          />
        )}

        {(state === 'on' || state === 'off') && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <Typography.Text strong>On this device</Typography.Text>
            <Space>
              {state === 'on' && (
                <Button size="small" onClick={test} loading={busy}>
                  Send test
                </Button>
              )}
              <Switch checked={state === 'on'} loading={busy} onChange={toggle} aria-label="Notifications on this device" />
            </Space>
          </div>
        )}

        {devices.length > 0 && (
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Devices getting your notifications
            </Typography.Text>
            <List
              size="small"
              dataSource={devices}
              renderItem={(d) => (
                <List.Item
                  actions={[
                    <Button
                      key="rm"
                      size="small"
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      aria-label={`Stop notifications on ${d.device}`}
                      onClick={() => remove(d.id)}
                    />,
                  ]}
                >
                  <List.Item.Meta
                    title={d.device}
                    description={
                      d.last_used_at ? `Last notified ${dayjs(d.last_used_at).fromNow()}` : `Added ${dayjs(d.created_at).fromNow()}`
                    }
                  />
                </List.Item>
              )}
            />
          </div>
        )}
      </Space>
    </Modal>
  );
}
