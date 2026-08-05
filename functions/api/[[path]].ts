export async function onRequest(context) {
  try {
    const url = new URL(context.request.url);
    url.hostname = "mtr.tail4bd79c.ts.net";
    url.protocol = "https:";
    url.port = "443";

    const headers = new Headers(context.request.headers);
    headers.set("Host", "mtr.tail4bd79c.ts.net");

    const init = {
      method: context.request.method,
      headers: headers,
      redirect: "follow",
    };

    if (context.request.method !== "GET" && context.request.method !== "HEAD") {
      init.body = context.request.body;
    }

    const response = await fetch(url.toString(), init);
    return response;
  } catch (err) {
    return new Response(JSON.stringify({ error: "Proxy failed", details: err.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
}
