/* Push notifications, loaded into the service worker (see vite.config.ts).
   The server sends { title, body, url, tag, unread } — see
   backend/app/domains/notifications/push.py. */

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data && event.data.text() }; }
  const title = data.title || 'MindTech Portal';
  const url = data.url || '/home';

  event.waitUntil((async () => {
    await self.registration.showNotification(title, {
      body: data.body || '',
      icon: '/icons/icon-192.png?v=2',
      tag: data.tag || undefined,
      renotify: Boolean(data.tag),
      data: { url },
    });
    // app-icon badge (installed app, where supported)
    if (typeof data.unread === 'number' && self.navigator.setAppBadge) {
      try { data.unread > 0 ? await self.navigator.setAppBadge(data.unread) : await self.navigator.clearAppBadge(); } catch {}
    }
    // open windows refresh their bell straight away
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    wins.forEach((c) => c.postMessage({ type: 'notifications-changed' }));
  })());
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || '/home', self.location.origin).href;
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const win = wins.find((c) => new URL(c.url).origin === self.location.origin);
    if (win) {
      await win.focus();
      // let the app route in place (keeps state) — falls back to a full load
      win.postMessage({ type: 'open-url', url: target });
      return;
    }
    await self.clients.openWindow(target);
  })());
});
