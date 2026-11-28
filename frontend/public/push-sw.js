/* Push notifications, loaded into the service worker (see vite.config.ts).
   The server sends { id, kind, title, body, url, tag, unread } — see
   backend/app/domains/notifications/push.py. */

const ICON = '/icons/icon-192.png?v=2';
const BADGE = '/icons/badge-96.png?v=1'; // white line-art, tinted by Android's status bar

async function tellWindows(msg) {
  const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  wins.forEach((c) => c.postMessage(msg));
}

async function setBadge(n) {
  if (typeof n !== 'number' || !self.navigator.setAppBadge) return;
  try { n > 0 ? await self.navigator.setAppBadge(n) : await self.navigator.clearAppBadge(); } catch {}
}

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data && event.data.text() }; }
  const title = data.title || 'MindTech Portal';
  const isTask = typeof data.url === 'string' && data.url.startsWith('/tasks');

  event.waitUntil((async () => {
    await self.registration.showNotification(title, {
      body: data.body || '',
      icon: ICON,
      badge: BADGE,
      dir: 'auto', // Arabic names and titles read right-to-left
      tag: data.tag || undefined,
      renotify: Boolean(data.tag),
      timestamp: Date.now(),
      vibrate: [60, 40, 60],
      data: { url: data.url || '/home', id: data.id },
      actions: [
        { action: 'open', title: isTask ? 'Open task' : 'Open' },
        ...(data.id ? [{ action: 'read', title: 'Mark as read' }] : []),
      ],
    });
    await setBadge(data.unread);
    await tellWindows({ type: 'notifications-changed' }); // open windows refresh their bell now
  })());
});

self.addEventListener('notificationclick', (event) => {
  const { url = '/home', id } = event.notification.data || {};
  event.notification.close();

  if (event.action === 'read') {
    event.waitUntil((async () => {
      try {
        await fetch('/api/notifications/mark-read', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: [id] }),
        });
        const r = await fetch('/api/notifications/unread-count', { credentials: 'include' });
        if (r.ok) await setBadge((await r.json()).count);
      } catch {}
      await tellWindows({ type: 'notifications-changed' });
    })());
    return;
  }

  const target = new URL(url, self.location.origin).href;
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const win = wins.find((c) => new URL(c.url).origin === self.location.origin);
    if (win) {
      await win.focus();
      // let the app route in place (keeps state)
      win.postMessage({ type: 'open-url', url: target });
      return;
    }
    await self.clients.openWindow(target);
  })());
});
