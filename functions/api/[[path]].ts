export async function onRequest(context) {
  const url = new URL(context.request.url);
  url.hostname = "mtr.tail4bd79c.ts.net";
  url.protocol = "https:";
  url.port = "443";

  // Natively clones and forwards the method, headers, and body without throwing exceptions
  return fetch(new Request(url.toString(), context.request));
}
