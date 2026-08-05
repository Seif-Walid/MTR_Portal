export const onRequest: PagesFunction = async (context) => {
  const url = new URL(context.request.url);
  const target = `https://mtr.tail4bd79c.ts.net${url.pathname}${url.search}`;

  // Build upstream request, forwarding method, headers, and body.
  const headers = new Headers(context.request.headers);
  headers.set("Host", "mtr.tail4bd79c.ts.net");

  const init: RequestInit = {
    method: context.request.method,
    headers,
    redirect: "manual", // pass redirects through untouched
  };

  // Only attach body for methods that support it.
  if (!["GET", "HEAD"].includes(context.request.method)) {
    init.body = context.request.body;
    // @ts-ignore – Cloudflare Workers support duplex streaming
    init.duplex = "half";
  }

  const upstream = await fetch(target, init);

  // Reconstruct the response so Set-Cookie headers survive intact.
  const responseHeaders = new Headers(upstream.headers);
  // Remove any domain attribute from Set-Cookie so the browser scopes
  // the cookie to the Pages origin (mtr-portal.pages.dev).
  const cookies = upstream.headers.getAll?.("Set-Cookie")
    ?? [upstream.headers.get("Set-Cookie")].filter(Boolean);

  if (cookies.length) {
    responseHeaders.delete("Set-Cookie");
    for (const cookie of cookies) {
      // Strip Domain=...; from the cookie string if present
      const cleaned = (cookie as string).replace(/;\s*Domain=[^;]*/gi, "");
      responseHeaders.append("Set-Cookie", cleaned);
    }
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
};
