export async function onRequest(context) {
  const url = new URL(context.request.url);
  
  // Forward the request to your Tailscale HTTPS backend
  url.hostname = "mtr.tail4bd79c.ts.net";
  url.protocol = "https:";
  url.port = "443";
  
  const request = new Request(url.toString(), context.request);
  return fetch(request);
}
