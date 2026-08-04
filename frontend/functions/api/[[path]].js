// Cloudflare Pages Function — reverse-proxies every /api/* request to the
// FastAPI backend, so the browser only ever talks to the Pages origin. That
// keeps the session cookie first-party (same trick as the Vite dev proxy),
// with no CORS and no SameSite=None needed.
//
// Set BACKEND_URL in the Pages project (Settings → Environment variables) to
// the backend's public base URL, e.g. https://mtr-portal-api.onrender.com
export async function onRequest({ request, env }) {
  const backend = env.BACKEND_URL;
  if (!backend) {
    return new Response('BACKEND_URL is not configured on this Pages project.', { status: 500 });
  }

  const url = new URL(request.url);
  const target = backend.replace(/\/$/, '') + url.pathname + url.search;

  // Forward the request as-is, but drop Host so fetch sets the backend's own
  // Host (some hosts route by Host header).
  const headers = new Headers(request.headers);
  headers.delete('host');

  const init = {
    method: request.method,
    headers,
    redirect: 'manual', // pass 3xx (e.g. Google OAuth) back to the browser untouched
  };
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = request.body;
    init.duplex = 'half';
  }

  const resp = await fetch(target, init);
  // Return the backend's response verbatim, including Set-Cookie.
  return new Response(resp.body, {
    status: resp.status,
    statusText: resp.statusText,
    headers: resp.headers,
  });
}
