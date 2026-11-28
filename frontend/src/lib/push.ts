import { api } from '../api/client';

/* Push notifications on this device (Web Push through the service worker in
   public/push-sw.js). The server side is backend/app/domains/notifications/push.py. */

export type PushState =
  | 'unsupported' // browser has no Web Push
  | 'ios-install' // iPhone/iPad Safari: only works from the Home Screen app
  | 'denied' // the person blocked notifications for the site
  | 'off'
  | 'on';

export interface PushDevice {
  id: number;
  device: string;
  created_at: string;
  last_used_at: string | null;
}

const isIos = () =>
  /iphone|ipad|ipod/i.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

const isStandalone = () =>
  window.matchMedia('(display-mode: standalone)').matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true;

const supported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null;
  // ready never settles when no worker is registered (e.g. the dev server)
  const reg = await navigator.serviceWorker.getRegistration();
  return reg ? navigator.serviceWorker.ready : null;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await registration();
  return reg ? reg.pushManager.getSubscription() : null;
}

export async function pushState(): Promise<PushState> {
  if (!supported()) return isIos() && !isStandalone() ? 'ios-install' : 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  if (!(await registration())) return 'unsupported';
  const sub = await currentSubscription();
  return sub && Notification.permission === 'granted' ? 'on' : 'off';
}

function urlBase64ToUint8Array(b64: string): Uint8Array {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Must run from a click/tap (iOS refuses the permission prompt otherwise). */
export async function enablePush(): Promise<PushState> {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return permission === 'denied' ? 'denied' : 'off';
  const reg = await registration();
  if (!reg) return 'unsupported';
  const { public_key } = await api.get<{ public_key: string }>('/api/notifications/push/key');
  let sub = await reg.pushManager.getSubscription();
  // a subscription made with another server key can't be reused
  const key = sub?.options.applicationServerKey;
  if (sub && key && btoa(String.fromCharCode(...new Uint8Array(key))) !== btoa(String.fromCharCode(...urlBase64ToUint8Array(public_key)))) {
    await sub.unsubscribe();
    sub = null;
  }
  sub ??= await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(public_key) as BufferSource,
  });
  await api.post('/api/notifications/push/subscribe', sub.toJSON());
  return 'on';
}

export async function disablePush(): Promise<PushState> {
  const sub = await currentSubscription();
  if (sub) {
    await api.post('/api/notifications/push/unsubscribe', { endpoint: sub.endpoint }).catch(() => {});
    await sub.unsubscribe();
  }
  return 'off';
}

/** Re-send this device's subscription after sign-in, so a shared computer's
 *  notifications follow whoever is signed in now. */
export async function resyncPush(): Promise<void> {
  try {
    if (!supported() || Notification.permission !== 'granted') return;
    const sub = await currentSubscription();
    if (sub) await api.post('/api/notifications/push/subscribe', sub.toJSON());
  } catch {
    /* best effort */
  }
}

export const listDevices = () => api.get<PushDevice[]>('/api/notifications/push/devices');
export const removeDevice = (id: number) => api.delete(`/api/notifications/push/devices/${id}`);
export const sendTestPush = () => api.post<{ sent: number }>('/api/notifications/push/test');

export function clearAppBadge() {
  const n = navigator as Navigator & { clearAppBadge?: () => Promise<void> };
  n.clearAppBadge?.().catch(() => {});
}

/** Messages the service worker posts to open windows. */
export function onServiceWorkerMessage(handler: (msg: { type: string; url?: string }) => void) {
  if (!('serviceWorker' in navigator)) return () => {};
  const fn = (e: MessageEvent) => {
    if (e.data && typeof e.data.type === 'string') handler(e.data);
  };
  navigator.serviceWorker.addEventListener('message', fn);
  return () => navigator.serviceWorker.removeEventListener('message', fn);
}

/** On sign-out: stop sending this person's notifications to this device
 *  (the next person to sign in here gets it via resyncPush). */
export async function forgetDeviceOnServer(): Promise<void> {
  try {
    const sub = await currentSubscription();
    if (sub) await api.post('/api/notifications/push/unsubscribe', { endpoint: sub.endpoint });
  } catch {
    /* best effort */
  }
}
