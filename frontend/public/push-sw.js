/* Push notifications, loaded into the service worker (see vite.config.ts).
   The server sends { id, kind, title, body, url, tag, unread, attachment? } — see
   backend/app/domains/notifications/push.py.
   Header: the installed app's own icon (Android puts it there for the app).
   Side: the task's attached photo / a PDF, link or file icon / the logo. */

// the picture at the side: the logo, unless the task has something attached
const LOGO = '/icons/notify-logo.png?v=1';
const ATTACHMENT_ICONS = {
  pdf: '/icons/att-pdf.png?v=1',
  link: '/icons/att-link.png?v=1',
  file: '/icons/att-file.png?v=1',
};
const BADGE = '/icons/monochrome-96.png'; // white line-art, tinted by Android's status bar

async function tellWindows(msg) {
  const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  wins.forEach((c) => c.postMessage(msg));
}

/** An attached photo, fetched signed-in and shrunk to a data: URL (the
 *  notification itself can't send the session cookie). */
async function imagePreview(src) {
  try {
    const r = await fetch(src, { credentials: 'include' });
    if (!r.ok) return null;
    const bmp = await createImageBitmap(await r.blob());
    const scale = Math.min(1, 720 / Math.max(bmp.width, bmp.height));
    const canvas = new OffscreenCanvas(Math.round(bmp.width * scale), Math.round(bmp.height * scale));
    canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
    const blob = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.82 });
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return `data:image/jpeg;base64,${btoa(bin)}`;
  } catch {
    return null;
  }
}

async function sidePicture(att) {
  if (!att) return { icon: LOGO };
  if (att.kind === 'image' && att.src) {
    const preview = await imagePreview(att.src);
    if (preview) return { icon: preview, image: preview }; // thumbnail + big picture when expanded
  }
  return { icon: ATTACHMENT_ICONS[att.kind] || LOGO };
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
    const picture = await sidePicture(data.attachment);
    await self.registration.showNotification(title, {
      body: data.body || '',
      ...picture,
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
