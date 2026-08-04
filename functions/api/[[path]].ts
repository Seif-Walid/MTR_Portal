export async function onRequest(requestContext) {
  const originalRequest = requestContext.request;
  const targetUrl = new URL(originalRequest.url);
  
  targetUrl.hostname = "mtr.tail4bd79c.ts.net";
  targetUrl.protocol = "https:";
  targetUrl.port = "443";
  
  const modifiedHeaders = new Headers(originalRequest.headers);
  modifiedHeaders.set("Host", targetUrl.hostname);
  
  const fetchConfiguration = {
    method: originalRequest.method,
    headers: modifiedHeaders,
  };
  
  if (originalRequest.method !== "GET" && originalRequest.method !== "HEAD") {
    fetchConfiguration.body = originalRequest.body;
  }
  
  return fetch(targetUrl.toString(), fetchConfiguration);
}
