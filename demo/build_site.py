"""Render the static, clickable FleetPilot demo for GitHub Pages.

    python demo/build_site.py [OUT]      # writes OUT (default demo/site/tour/)

Pages are rendered by the real app in demo mode (see seed.py); links between them are
rewritten to the static files, the few API reads are answered from captured data, and
every change shows a "demo" note instead of being sent anywhere.
"""
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seed import fp, REPO  # noqa: E402  (seeds the example data)
import account_security  # noqa: E402
import user_management  # noqa: E402

SITE = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "tour"))
shutil.rmtree(SITE, ignore_errors=True)
os.makedirs(SITE)

PAGES = ["/index", "/hosts", "/scanner", "/routers", "/routers/1", "/routers/2", "/routers/3", "/routers/4",
         "/dashboard", "/hw_overview", "/hw", "/smart", "/storage/workspace", "/fans", "/vm", "/storage",
         "/backup", "/shutdown_schedule", "/checkmk", "/monitor", "/update_settings", "/email_settings",
         "/system/proxy", "/system/production", "/system/security", "/system/notifications", "/system/audit",
         "/system/backups", "/plugins", "/users/profile", "/users/security", "/users/accessibility", "/users",
         "/fleetpilot_update", "/server_update", "/status"]
API_GETS = ["/api/dashboard/layout", "/api/update_notification", "/api/hw/servers", "/api/hw/live", "/api/hosts"]


def page_file(path):
    return "index.html" if path in ("/", "/index") else path.strip("/").replace("/", "-") + ".html"


fp.app.config.update(TESTING=True)
client = fp.app.test_client()
user = user_management.get_user("admin")
with client.session_transaction("/", base_url="https://fleetpilot.home") as s:
    s.update(user_id=user["id"], username="admin", pw_tag=fp._password_tag(user_management.get_user_by_id(user["id"])),
             sid=account_security.create_session(user["id"]), auth_time=time.time())

rendered, api = {}, {}
for path in PAGES:
    r = client.get(path, base_url="https://fleetpilot.home")
    if r.status_code == 200 and r.mimetype == "text/html":
        rendered[path] = r.get_data(as_text=True)
    else:
        print("skipped", path, r.status_code)
for path in API_GETS:
    r = client.get(path, base_url="https://fleetpilot.home")
    if r.status_code == 200 and r.is_json:
        api[path] = r.get_json()

LINK = re.compile(r'''(\b(?:href|src|action)=)(["'])(/[^"'#?]*)([^"']*)\2''')


def rewrite(html):
    def repl(m):
        attr, q, path, rest = m.groups()
        if path.startswith("/static/"):
            return f"{attr}{q}{path[1:]}{rest}{q}"
        if path in rendered or (path == "/" and "/index" in rendered):
            return f"{attr}{q}{page_file(path)}{q}"
        return f"{attr}{q}#demo-unavailable{q}"
    html = LINK.sub(repl, html)
    html = html.replace("url(/static/", "url(static/").replace("url('/static/", "url('static/")
    inject = ('<script>window.FP_DEMO_API = ' + json.dumps(api) + ';</script>'
              '<script src="demo.js"></script><link rel="stylesheet" href="demo.css">')
    return html.replace("</head>", inject + "</head>", 1)


for path, html in rendered.items():
    with open(os.path.join(SITE, page_file(path)), "w", encoding="utf-8") as fh:
        fh.write(rewrite(html))

shutil.copytree(os.path.join(REPO, "static"), os.path.join(SITE, "static"),
                ignore=shutil.ignore_patterns("host_images"))
for root, _, files in os.walk(os.path.join(SITE, "static")):
    for name in files:
        if name.endswith(".css"):
            p = os.path.join(root, name)
            rel = os.path.relpath(os.path.join(SITE, "static"), root).replace(os.sep, "/")
            css = open(p, encoding="utf-8", errors="replace").read()
            css = re.sub(r"""url\((['"]?)/static/""", lambda m: f"url({m.group(1)}{rel}/", css)
            open(p, "w", encoding="utf-8").write(css)

with open(os.path.join(SITE, "demo.js"), "w") as fh:
    fh.write(r"""// Static demo: answers the few API reads from captured data and turns every change into a note.
(function () {
  function note(text) {
    var n = document.getElementById('fp-demo-note');
    if (!n) { n = document.createElement('div'); n.id = 'fp-demo-note'; n.setAttribute('role', 'status'); document.body.appendChild(n); }
    n.textContent = text; n.className = 'show'; clearTimeout(n._t); n._t = setTimeout(function () { n.className = ''; }, 3500);
  }
  var realFetch = window.fetch;
  window.fetch = function (url, opts) {
    var method = ((opts && opts.method) || 'GET').toUpperCase();
    var path = String(url).split('?')[0];
    if (method !== 'GET') { note('The static tour cannot do this. The live demo can: open it from the bar above.'); }
    var data = (window.FP_DEMO_API || {})[path];
    return Promise.resolve(new Response(JSON.stringify(data || {ok: true}), {status: 200, headers: {'Content-Type': 'application/json'}}));
  };
  document.addEventListener('submit', function (e) { e.preventDefault(); note('The static tour cannot do this. The live demo can: open it from the bar above.'); }, true);
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href="#demo-unavailable"]');
    if (a) { e.preventDefault(); note('This page is not part of the static demo.'); }
  }, true);
  document.addEventListener('DOMContentLoaded', function () {
    var bar = document.createElement('div');
    bar.id = 'fp-demo-bar';
    bar.innerHTML = 'Static tour with example data: buttons do nothing here. ' +
      '<a href="../demo/">Try the live demo</a>, where they work · ' +
      '<a href="https://github.com/ChristianHandy/FleetPilot#quick-start">Install FleetPilot</a>';
    document.body.insertBefore(bar, document.body.firstChild);
  });
})();
""")
with open(os.path.join(SITE, "demo.css"), "w") as fh:
    fh.write("""#fp-demo-bar{position:sticky;top:0;z-index:2000;background:#12355b;color:#fff;font:600 13px/1.4 system-ui,sans-serif;
padding:8px 16px;text-align:center}#fp-demo-bar a{color:#9fd0ff;text-decoration:underline}
#fp-demo-note{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#12355b;color:#fff;padding:10px 16px;
border-radius:8px;font:14px system-ui,sans-serif;opacity:0;transition:opacity .2s;z-index:2001;pointer-events:none}
#fp-demo-note.show{opacity:1}
""")
open(os.path.join(SITE, ".nojekyll"), "w").close()
print("pages:", len(rendered), "api:", sorted(api))
