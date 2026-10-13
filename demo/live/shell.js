/* FleetPilot live demo: starts FleetPilot in a worker and shows it in the frame.
 *
 * sw.js sends every request for app/<lab>/... here; this page passes it to worker.js,
 * where FleetPilot answers it, and hands the answer back. The lab panel shows the
 * emulated devices and lets the visitor switch them off, break a disk, and so on.
 */
(function () {
  'use strict';
  const LAB = Math.random().toString(36).slice(2, 8);
  const BASE = new URL('./', location.href);
  const PREFIX = new URL('app/' + LAB, BASE).pathname;
  const $ = (id) => document.getElementById(id);
  const frame = $('app');
  const pending = new Map();
  const staticCache = new Map();
  let worker = null;
  let nextId = 1;
  let lastEvent = 0;
  let outboxSeen = 0;
  let state = { devices: [], events: [], outbox: [] };
  const events = [];

  function fail(text) {
    $('loader-error').textContent = text;
    $('loader-error').hidden = false;
    $('loader-note').hidden = true;
    document.querySelectorAll('.steps li.active').forEach((li) => li.classList.remove('active'));
  }

  function step(n) {
    document.querySelectorAll('#steps li').forEach((li) => {
      const s = Number(li.dataset.step);
      li.classList.toggle('done', s < n);
      li.classList.toggle('active', s === n);
    });
    $('bar').style.width = Math.min(100, n * 24) + '%';
  }

  // ── Requests from the service worker ──
  function onServiceWorkerMessage(event) {
    if (event.origin && event.origin !== location.origin) return;
    const m = event.data || {};
    const port = event.ports[0];
    if (m.type !== 'fp-request' || !port) return;
    if (m.lab !== LAB || !worker) { port.postMessage({ mine: false }); return; }
    const cacheable = m.method === 'GET' && m.path.includes('/static/');
    if (cacheable && staticCache.has(m.path)) {
      const hit = staticCache.get(m.path);
      port.postMessage({ mine: true, status: hit.status, headers: hit.headers, body: hit.body.slice(0) });
      return;
    }
    const id = nextId++;
    pending.set(id, (res) => {
      if (cacheable && res.status === 200) staticCache.set(m.path, { status: 200, headers: res.headers, body: res.body.slice(0) });
      port.postMessage({ mine: true, status: res.status, headers: res.headers, body: res.body }, [res.body]);
    });
    worker.postMessage({ type: 'request', id, method: m.method, path: m.path, query: m.query, headers: m.headers, body: m.body },
                       m.body ? [m.body] : []);
  }

  function onWorkerMessage(event) {
    const m = event.data;
    if (m.type === 'progress') step(m.step);
    else if (m.type === 'response') {
      const done = pending.get(m.id);
      pending.delete(m.id);
      if (done) done(m);
    } else if (m.type === 'ready') {
      step(5);
      render(m.state);
      openApp();
      setInterval(() => worker.postMessage({ type: 'tick', since: lastEvent }), 4000);
    } else if (m.type === 'state') render(m.state);
    else if (m.type === 'error') {
      if (!frame.hidden) console.error(m.text);
      else fail('The demo could not start: ' + m.text);
    }
  }

  function openApp() {
    const wanted = new URLSearchParams(location.search).get('page') || '/index';
    frame.src = PREFIX + (wanted.startsWith('/') ? wanted : '/index');
    frame.hidden = false;
    frame.addEventListener('load', () => {
      $('loader').hidden = true;
      try { document.title = frame.contentDocument.title.replace(/^FleetPilot\s*[-–·|]?\s*/, '') + ' · FleetPilot Live Demo'; } catch (e) { /* ignore */ }
    });
    $('lab-toggle').disabled = false;
    if (window.matchMedia('(min-width: 1200px)').matches) toggleLab(true);
  }

  // ── Lab panel ──
  function toggleLab(open) {
    const lab = $('lab');
    const show = open === undefined ? lab.hidden : open;
    lab.hidden = !show;
    $('lab-toggle').setAttribute('aria-expanded', String(show));
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'text') node.textContent = v;
      else if (k === 'class') node.className = v;
      else node.setAttribute(k, v);
    });
    (children || []).forEach((c) => node.appendChild(c));
    return node;
  }

  function render(next) {
    state = next;
    (next.events || []).forEach((e) => { if (e.id > lastEvent) { events.unshift(e); lastEvent = e.id; } });
    events.splice(400);
    if (next.credentials) {
      $('creds').textContent = `Logged in as ${next.credentials.username}. After logging out, sign in again with `
        + `${next.credentials.username} / ${next.credentials.password}.`;
    }
    const list = $('devices');
    list.replaceChildren(...next.devices.map((d) => {
      const facts = el('div', { class: 'facts' });
      d.facts.forEach((f, i) => {
        if (i) facts.appendChild(document.createTextNode(' · '));
        facts.appendChild(el('span', { class: /fail|pending|available|load/.test(f) ? 'warn' : '', text: f }));
      });
      const actions = el('div', { class: 'dev-actions' }, d.actions.map((a) => {
        const b = el('button', { type: 'button', text: a.label });
        b.addEventListener('click', () => worker.postMessage({ type: 'act', device: d.name, action: a.id, since: lastEvent }));
        return b;
      }));
      return el('li', { class: 'device' }, [
        el('div', { class: 'device-top' }, [
          el('span', { class: 'dot ' + d.state, title: d.state }),
          el('i', { class: 'bi bi-' + d.icon, 'aria-hidden': 'true' }),
          el('span', { class: 'device-name', text: d.label }),
          el('span', { class: 'device-ip', text: d.ip }),
        ]),
        facts, actions,
      ]);
    }));
    const log = $('log');
    const shown = $('show-bg').checked ? events : events.filter((e) => !e.bg);
    log.replaceChildren(...(shown.length ? shown.slice(0, 120).map((e) => el('li', { class: 'k-' + e.kind }, [
      el('span', { class: 'who', text: new Date(e.t * 1000).toLocaleTimeString() + ' ' + e.device + ' ' }),
      document.createTextNode(e.text),
    ])) : [el('li', { class: 'empty', text: 'Nothing yet. Click something in FleetPilot.' })]));
    const outbox = $('outbox');
    const mails = (next.outbox || []).slice().reverse();
    outbox.replaceChildren(...(mails.length ? mails.map((m) => el('li', {}, [
      el('div', { class: 'subject', text: m.subject }),
      el('div', { class: 'meta', text: `${m.channel} → ${m.to} · ${new Date(m.t * 1000).toLocaleTimeString()}` }),
      el('pre', { text: m.body }),
    ])) : [el('li', { class: 'empty', text: 'No alerts sent yet.' })]));
    const unseen = mails.filter((m) => m.id > outboxSeen).length;
    $('outbox-count').hidden = !unseen;
    $('outbox-count').textContent = unseen;
    $('lab-count').hidden = !unseen;
    $('lab-count').textContent = unseen;
  }

  document.querySelectorAll('.tabs button').forEach((tab) => tab.addEventListener('click', () => {
    document.querySelectorAll('.tabs button').forEach((t) => t.setAttribute('aria-selected', String(t === tab)));
    document.querySelectorAll('.panel').forEach((p) => { p.hidden = p.dataset.panel !== tab.dataset.tab; });
    if (tab.dataset.tab === 'outbox') {
      outboxSeen = Math.max(0, ...(state.outbox || []).map((m) => m.id));
      render(Object.assign({}, state, { events: [] }));
    }
  }));
  $('show-bg').addEventListener('change', () => render(Object.assign({}, state, { events: [] })));
  $('lab-toggle').addEventListener('click', () => toggleLab());
  $('lab-close').addEventListener('click', () => toggleLab(false));
  $('restart').addEventListener('click', () => { location.href = BASE.pathname; });

  // ── Start ──
  async function main() {
    if (!('serviceWorker' in navigator) || typeof WebAssembly !== 'object') {
      fail('This browser cannot run the live demo (it needs service workers and WebAssembly; private windows in some browsers turn them off).');
      return;
    }
    if (new URLSearchParams(location.search).has('restart')) history.replaceState(null, '', BASE.pathname);
    navigator.serviceWorker.onmessage = onServiceWorkerMessage;
    try {
      await navigator.serviceWorker.register('sw.js', { scope: './' });
      await navigator.serviceWorker.ready;
    } catch (err) {
      fail('The browser refused the demo\'s service worker: ' + err.message);
      return;
    }
    step(1);
    worker = new Worker('worker.js');
    worker.onmessage = onWorkerMessage;
    worker.onerror = (e) => fail('The demo could not start: ' + (e.message || 'worker error'));
    worker.postMessage({ type: 'start', origin: location.origin, prefix: PREFIX,
                         timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
  }
  main();
})();
