# Full code audit — findings and fixes

Methodology: syntax-checked all 46 Python files, ran `pyflakes` across the
whole codebase and triaged every finding, searched systematically for SQL
injection, command injection, and XSS patterns, then cross-checked every
internal link/fetch URL in every template against actually-registered
routes. This is not a claim of 100% line-by-line coverage of a codebase
this size — see "Not covered" at the bottom for what's genuinely left.

## Fixed

### XSS — Network Scanner (`templates/scanner.html`) — CRITICAL
Scan results rendered `r.hostname` (resolved via DNS/mDNS/NetBIOS from
devices on the network) directly into `innerHTML`, unescaped. **Any
device on the network — zero prior access needed — could set its
hostname to a script payload** and have it execute in the admin's
browser the next time someone ran a scan. The "Add Host" button's
`onclick="openModal('${r.ip}','${r.mac}',...)"` had the same problem one
layer deeper, inside a JS string within the attribute.

Fix: added `escapeHtml()`, applied to `ip`/`mac`/`hostname`; replaced the
string-built `onclick` with a real `addEventListener` carrying the actual
values — sidesteps the escaping question for that control entirely.

### XSS — Hardware Overview (`hw_overview/index.html`, `detail.html`) — HIGH
Same bug class, lower bar to trigger (requires SSH access to one of your
own hosts, e.g. if it's compromised): CPU/GPU/disk/NIC model names,
drivers, BIOS strings, and `lspci`/log output collected from remote hosts
were interpolated into `innerHTML` unescaped in both files' full-card
detail rendering — `index.html`'s `renderCard()` and `detail.html`'s
`row()` / Network / Storage / PCIe sections (the latter three build HTML
entirely outside the `row()` helper, so it needed separate treatment).

Also hardened `fmtBytes()` / `fmtMB()` / `tempBadge()` in `detail.html`:
each had a `if (isNaN(v)) return kb` fallback that returned the *raw*
value verbatim when it wasn't a valid number — a compromised host
returning a non-numeric string for e.g. `total_kb` would have bypassed
escaping entirely through that path.

Fix: added `escapeHtml()` + a `trusted()` marker so the render/`row()`
loops escape every value by default, with markup-producing helpers
(`bar()`, `tempBadge()`) explicitly opted in. Verified against a real
payload (`<script>alert(1)</script>` inserted as a simulated malicious
GPU vendor string) that it's actually neutralized, not just eyeballed.

### XSS + broken-on-quotes bug — Hardware Monitor (`hw_monitor.py`, `hw_monitor/index.html`) — MEDIUM
Same unescaped-remote-data pattern in `renderCard()`, with *partial*
existing protection (`.replace(/</g,'&lt;')` on log/error text — handles
`<` but not `>`, `&`, or quotes). Separately, both the "quick-select known
server" button and the error-acknowledge button built `onclick="fn('${s.name}',...)"` 
strings from admin-set server names — this isn't just a security
edge case, it **breaks on any server name containing a quote** (e.g.
"Bob's NAS"), no malicious intent required.

Fix: added `escapeHtml()`, applied throughout `renderCard()`; replaced
both `onclick`-string patterns with `addEventListener`/`data-*`-attribute
+ delegated-listener approaches, matching the scanner.html fix shape.

### Command injection (latent, not currently reachable) — `hw_monitor.py`
`stress_script`/`stress_log` database fields were f-string-interpolated
unescaped into a command sent over SSH (`exec_command`, which the remote
shell interprets). No UI form currently sets these fields — they're
always the hardcoded default — so this isn't exploitable *today*, but the
pattern was live and would silently reopen the moment anyone adds a
"customize the stress test path" field. Fixed with `shlex.quote()`.
(Confirmed the identical pattern in `hw_monitor/app.py` is a completely
separate, never-imported standalone script — not reachable through the
running app at all — so left alone.)

### Broken links / missing endpoint
- `base.html`: the update-available toast's "Update Now" button linked to
  `/dashboard_update`, which has never existed — real route is
  `/dashboard_version/update`. Every admin who saw that toast and clicked
  it got a 404.
- `2fa_setup.html`: "← Back to Settings" linked to `/settings`, which
  doesn't exist anywhere in the app. Pointed at `/users/profile` instead.
- `hw_monitor/index.html` called `fetch('/api/known_servers')` for its
  "quick-fill from a server you already configured" convenience feature —
  no such route existed (`_get_known_servers_for_module()` was only ever
  used as server-side template context elsewhere, never exposed over
  the API this page needed). Added `@app.route('/api/known_servers')`
  in `app.py`, deliberately not including stored passwords in the
  response.

These three came from a script that cross-referenced every `href`/`action`/
`fetch()` URL in every template against every registered `@app.route` —
2 other flags it raised (`/2fa/backup`, `/api/fans/`) were false positives
from dynamic URL concatenation the script couldn't parse; verified both
resolve correctly before ruling them out.

## Found, documented, not fixed (flagging for you to prioritize)

- **`backup_controller.py`**: fetches backup-schedule config and sync-job
  config from two separate API calls, then discards both results
  entirely — never stored, never displayed. Whatever UI is supposed to
  show configured backup schedules is working with incomplete data. Not
  a quick fix (needs a new storage/display path, not just a missing
  escape or a typo'd URL), so flagging rather than attempting it here.
- **`smart_manager.py`'s `classify_health()`** (found in an earlier
  session): defaults to `"GOOD"` when it can't get real SMART data,
  rather than `"UNKNOWN"`.
- **~18 remaining `innerHTML`-using templates** not yet individually
  triaged: `smart/dashboard.html`, `checkmk/index.html`, `vm/detail.html`,
  `backup/detail.html`, `fans/*.html`, `plugin_manager.html`,
  `plugin_source.html`, `server_update.html`, `hosts.html`, and others.
  A quick sample of a few (`fans/*`, `backup/detail.html`) showed mostly
  button-state changes (spinners, icons) rather than raw remote-data
  interpolation, which is lower risk than what's been fixed — but that
  was a sample, not a full pass.
- Path traversal review and a CSRF-coverage audit were planned but not
  reached.

## Testing

Fresh-install server start, full login flow, and a page crawl across
every touched page (`/index`, `/hw_overview`, `/hw_overview/<name>`,
`/scanner`, `/2fa`, `/users/profile`, `/hw`, `/api/known_servers`) — all
200, no server errors. Confirmed `/api/known_servers` returns real merged
data from both the registry and `hosts.json`. Confirmed both broken-link
fixes render the corrected URLs. The scanner and hw_overview escaping
fixes were verified against an actual XSS payload (not just read through),
inserted directly into the cache DB to simulate a compromised/malicious
remote source, and confirmed neutralized end-to-end.
