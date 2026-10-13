/* FleetPilot live demo: runs FleetPilot (Python) with Pyodide in this worker. */
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/';
importScripts(PYODIDE + 'pyodide.js');

let py = null;
let boot = null;
const progress = (step, text) => postMessage({ type: 'progress', step, text });

async function start({ origin, prefix, timezone }) {
  progress(1, 'Loading Python (WebAssembly)');
  py = await loadPyodide({ indexURL: PYODIDE });
  progress(2, 'Loading libraries');
  await py.loadPackage(['micropip', 'hashlib', 'sqlite3', 'ssl', 'cryptography', 'bcrypt', 'pynacl',
                        'markupsafe', 'tzdata'], { messageCallback: () => {} });
  const manifest = await (await fetch('lab/manifest.json', { cache: 'no-cache' })).json();
  const micropip = py.pyimport('micropip');
  await micropip.install.callKwargs(manifest.wheels.map((w) => new URL('lab/wheels/' + w, self.location.href).href),
                                    { deps: false });
  progress(3, 'Unpacking FleetPilot');
  const zip = await (await fetch('lab/' + manifest.app)).arrayBuffer();
  py.unpackArchive(zip, 'zip', { extractDir: '/fleetpilot' });
  progress(4, 'Switching on the virtual lab');
  py.globals.set('browser_tz', timezone || 'UTC');
  py.runPython("import os, sys; os.environ['FLEETPILOT_APP_DIR'] = '/fleetpilot'; os.environ['TZ'] = browser_tz; " +
               "sys.path.insert(0, '/fleetpilot/demo/live')");
  boot = py.pyimport('lab.boot');
  boot.start(origin, prefix, '/data');
  postMessage({ type: 'ready', state: JSON.parse(boot.state_json(0)) });
}

function handle(m) {
  const result = boot.handle_js(m.method, m.path, m.query, JSON.stringify(m.headers),
                                m.body ? new Uint8Array(m.body) : undefined);
  const [status, headers, body] = result.toJs();
  result.destroy();
  const buffer = body.buffer.slice(body.byteOffset, body.byteOffset + body.byteLength);
  postMessage({ type: 'response', id: m.id, status, headers: JSON.parse(headers), body: buffer }, [buffer]);
  setTimeout(() => {
    try { boot.after_request(); } catch (err) { console.error(err); }
  }, 0);
}

self.onmessage = async (event) => {
  const m = event.data;
  try {
    if (m.type === 'start') await start(m);
    else if (m.type === 'request') handle(m);
    else if (m.type === 'tick') postMessage({ type: 'state', state: JSON.parse(boot.tick_json(m.since || 0)) });
    else if (m.type === 'act') postMessage({ type: 'state', state: JSON.parse(boot.act_json(m.device, m.action, m.since || 0)) });
  } catch (err) {
    console.error(err);
    if (m.type === 'request') {
      const text = new TextEncoder().encode('The demo could not answer this request:\n' + err);
      postMessage({ type: 'response', id: m.id, status: 500, headers: [['Content-Type', 'text/plain']], body: text.buffer });
    } else {
      postMessage({ type: 'error', text: String(err && err.message || err) });
    }
  }
};
