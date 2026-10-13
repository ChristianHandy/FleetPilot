/* FleetPilot live demo: service worker.
 *
 * Requests below <scope>/app/<lab-id>/ are FleetPilot pages. They are not sent to any
 * server: the worker hands them to the demo page (index.html) that started lab <lab-id>,
 * where FleetPilot runs in Pyodide, and returns its answer to the browser.
 */
const SCOPE = new URL(self.registration.scope).pathname;
const APP = SCOPE + 'app/';
const NO_BODY = new Set([101, 204, 205, 304]);

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith(APP)) return;
  event.respondWith(forward(event.request, url));
});

async function forward(request, url) {
  const lab = url.pathname.slice(APP.length).split('/')[0];
  const headers = {};
  request.headers.forEach((value, key) => { headers[key] = value; });
  if (request.referrer && request.referrer.startsWith(self.location.origin)) headers.referer = request.referrer;
  const body = ['GET', 'HEAD'].includes(request.method) ? null : await request.arrayBuffer();
  const message = { type: 'fp-request', lab, method: request.method, path: url.pathname,
                    query: url.search.slice(1), headers, body };

  const shells = (await self.clients.matchAll({ type: 'window', includeUncontrolled: true }))
    .filter((c) => { const p = new URL(c.url).pathname; return p === SCOPE || p === SCOPE + 'index.html'; });
  const answer = await firstAnswer(shells.map((client) => ask(client, message)));

  if (!answer) {
    if (request.mode === 'navigate') return Response.redirect(SCOPE + '?restart=1', 302);
    return new Response('The demo lab of this page is no longer running. Reload the demo.', { status: 503 });
  }
  return new Response(NO_BODY.has(answer.status) ? null : answer.body,
                      { status: answer.status, headers: answer.headers });
}

function ask(client, message) {
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => resolve(null), 60000);
    channel.port1.onmessage = (event) => { clearTimeout(timer); resolve(event.data && event.data.mine ? event.data : null); };
    client.postMessage(message, [channel.port2]);
  });
}

function firstAnswer(promises) {
  return new Promise((resolve) => {
    let open = promises.length;
    if (!open) resolve(null);
    promises.forEach((p) => p.then((value) => {
      if (value) resolve(value);
      else if (--open === 0) resolve(null);
    }));
  });
}
