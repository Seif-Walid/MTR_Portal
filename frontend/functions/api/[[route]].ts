export const onRequest: PagesFunction = async (context) => {
  const url = new URL(context.request.url);
  // The route matches /api/...
  // We want to proxy to https://mtr.tail4bd79c.ts.net/api/...
  const targetUrl = new URL(`https://mtr.tail4bd79c.ts.net${url.pathname}${url.search}`);
  const req = new Request(targetUrl.toString(), context.request);
  req.headers.set("Host", "mtr.tail4bd79c.ts.net");
  return fetch(req);
};
