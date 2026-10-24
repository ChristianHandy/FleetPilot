# Changelog

All notable changes to FleetPilot are recorded here. Version numbers follow [semantic versioning](https://semver.org).

## [Unreleased]

### Security

- **certifi updated to 2026.10.19** (PYSEC-2026-4320 in 2026.7.22, found by `pip-audit`), in `requirements-lock.txt` and `requirements-dev-lock.txt`.
- **brotli updated to 1.2.1** (PYSEC-2026-4322 in 1.2.0, found by `pip-audit`), in `requirements-lock.txt`.

### Added

- **Release workflow for every kind of release:** Actions → *Prepare release* prepares a beta, a main release, a patch (subrelease such as 1.8.1), a hotfix from a `release/X.Y` branch, or a major release: it sets the version in the app and the Android app, closes the changelog section and opens the way to the release pull request (`prepare-release.yml`, `scripts/release.py`). Hotfix releases are named "FleetPilot vX.Y.Z (hotfix)", and a hotfix of an older line no longer becomes the "Latest" release.
- **Pull request summary comment:** one comment per pull request, updated whenever a check finishes, says whether it is ready to merge (required checks, merge conflicts, draft), lists the changed files by area and gives a fix hint for each failed check (`pr-summary.yml`, `scripts/pr_summary.py`). Copilot code review is also requested automatically on pull requests to `main`.

- **Maintainer override for the AI assistance check:** the check stays required, but the repository owner, a member or a collaborator can allow one pull request by commenting `/allow-ai <head commit> <reason>`. Members and collaborators cannot allow their own pull requests; the owner can, since nobody else could approve them. The approval counts only for that commit, and the reason is shown in the check summary. The comment re-runs the check (`ai-override.yml`, `scripts/ai_override.py`).

- **More pull request checks:** at least 70 % of the changed Python lines must be run by the tests (part of the pytest check; the summary lists the untested lines), and the new *Change checks* job, part of *Safe to merge*, runs ShellCheck on the install, update and root helper scripts, requires a `CHANGELOG.md` entry for changes users notice (label `no changelog` to skip), fails when a change adds interface text without a German translation, and warns above 800 changed lines (`scripts/pr_checks.py`).

- **AI share of the current code:** a README badge, rebuilt daily by the Pages workflow, shows how many of today's code lines come from AI-assisted commits (`git blame`, `scripts/ai_share.py --codebase-json/--badge`; per-area numbers in `ai-codebase.json`). At the start: 79.6 % of 68,983 lines.
- **AI artifacts fail the pull request check:** leftovers that give AI-generated code away (chat text such as "Here's the updated code", elided-code placeholders, pasted Markdown code fences, placeholder secrets, "in a real implementation" stubs, model tokens and tool signatures) and AI tool files (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `copilot-instructions.md`, ...). The daily repository scan checks all files for them (`scripts/ai_detect.py --all`).

- **Pull requests must be free of AI-written code** (required check "AI assistance" in `pr-check.yml`, `scripts/ai_detect.py`): it fails when a commit declares AI help (same rules as the AI-share chart) or the pull request's "AI assistance" section does, or when style signals in the added code (section dividers, check-mark emoji, em dashes, stock phrases, boilerplate docstrings) reach 50 of 100. The score is an estimate; the job summary shows what it found. The detector runs from the base branch.

### Changed

- Tests moved from the repository root into tests/ (#171).
- `hw_monitor.py` and `fan_controller.py` route warnings and errors through `logging.getLogger(__name__)` instead of `print()` or `warnings.warn()` ([#160](https://github.com/ChristianHandy/FleetPilot/issues/160)).

### Fixed

- **Example dashboard widget and `dashboard_widget` hook receive host reachability counts** ([#144](https://github.com/ChristianHandy/FleetPilot/issues/144)). `templates/index.html` passed raw host dicts without a `status` key and `stats={}`, so `addons/example_dashboard_widget.py` always reported 0% Fleet Health with every host offline. Each host passed to `dashboard_widget` now includes `name` and `status` (`"online"`, `"offline"` or `"unknown"`) from the last capability check, `stats` provides `{"total", "online", "offline", "unknown"}`, and unchecked hosts are shown as unknown rather than offline.
- **Backup servers:** the "Verify SSL certificate" setting (and optional `FLEETPILOT_BACKUP_CA` custom CA bundle path) is now respected across all HTTP backup backends (Proxmox Backup Server, Duplicati, Restic REST-Server, BorgWarehouse, and UrBackup) including connection tests, and defaults to enabled for newly added backup servers with a clear error message when certificate verification fails ([#147](https://github.com/ChristianHandy/FleetPilot/issues/147)).

## [1.8.0] — 2026-10-18

**Stable release with two security fixes. Please update.** It contains everything from 1.8.0-beta.2 (below: Windows support for every supported release, the Android app, the live demo, stricter checks and much more) plus the changes here. After updating, change the SSH passwords that were stored for scheduled shutdowns or in the server registry.


### Security

- **Scheduled shutdown exposed SSH passwords to every signed-in user** (all versions up to 1.8.0-beta.2). The schedules page and `GET /api/shutdown_schedule` returned each schedule's SSH password in plain text, readable by viewers and read-only API tokens, and the passwords were stored unencrypted. Passwords are now encrypted like all other device credentials (existing ones on the first start), never sent to the browser or the API, and kept when a schedule is edited without a new one. **If you use scheduled shutdown with passwords, change those passwords** (or switch to SSH keys). Schedules are also validated now (host, time, days, port, action); an unknown action no longer falls back to a shutdown, and a host that cannot be reached is logged instead of failing silently.
- **Server registry exposed SSH passwords to every signed-in user** (all versions up to 1.8.0-beta.2; [GHSA-7h7w-wfff-7p6w](https://github.com/ChristianHandy/FleetPilot/security/advisories/GHSA-7h7w-wfff-7p6w)). `GET /api/registry/servers` and `/api/registry/servers/<id>` returned each server's stored SSH password in plain text and its SSH key, readable by viewers and read-only API tokens, and the Fan controller's add page put known servers' passwords into its JavaScript. Registry passwords are now encrypted at rest (existing ones on the first start), the API returns `has_password`/`has_ssh_key` instead, and only the code that opens the SSH connection reads the password. **Change the SSH passwords of servers that had a password in the registry.**

### Added

- **"Safe to merge" check on pull requests:** one required verdict that passes only when the functional check passes (`install.sh` installs the code on a fresh Ubuntu machine over HTTP and HTTPS, an admin signs in and every page the app links to opens, an installation of the latest release updates to the new code, and the Android app builds) and ClamAV plus `scripts/pr_threat_scan.py` find no virus or backdoor pattern in the change. The scanner runs from the base branch, so a pull request cannot switch it off.
- **Daily repository scan** (and on every push to main): the functional check, ClamAV over every tracked file and the backdoor scan of the whole repository.

### Fixed

- **Plugin hooks `update_pre`, `update_post` and `notification` are fired now** ([#145](https://github.com/ChristianHandy/FleetPilot/issues/145)). They were registered by the add-on loader and documented on the plugin docs page, but nothing ever called `AddonManager.fire_hooks()`, so the bundled Slack example never sent a message and any third-party plugin built on these hooks silently did nothing:
  - `update_pre` and `update_post` run around every host update (`updater.run_update`, which is also what the scheduler and the update routes call). `update_post` receives a result with `success`, `packages_updated`, `name`, `host` and `error`.
  - `notification` fires with the event `new_version_available` (`data={"type", "version", "description", "url"}`) when a newer release or commit appears — once per version, not on every 24-hour check — and also fires for email update reports (`event="update_report"`, `data={"hosts_status", "history"}`), host update error notifications (`event="update_error"`, `data={"host", "error"}`), and `notify.send()` messages (`event` set to the notification category such as `smart`, `security`, `backup`, `router` or `vulnerability`, `data={"title", "message", "level"}`).
  - A hook runs after the update result is stored, and an exception inside a hook is logged instead of propagated, so a notification can never break or delay the update it reports on.
- The two-factor page's "Back" button pointed to `/settings`, which doesn't exist; it goes back to My Profile now ([#194](https://github.com/ChristianHandy/FleetPilot/issues/194)).
- The SMART button on the Storage workspace pointed to `/disks/smart/<disk>`, which doesn't exist; it opens the disk's SMART report now ([#195](https://github.com/ChristianHandy/FleetPilot/issues/195)).
- The network scanner page left a socket open when it could not find the local subnet.

## [1.8.0-beta.2] — 2026-10-18

**Pre-release for testers.** Everything below is new since 1.7.0. Please try it on your own hardware and [report what breaks](https://github.com/ChristianHandy/FleetPilot/issues/new?template=bug_report.yml).

### Security

- Fan, disk and CheckMK pages put names and the monitoring token into inline JavaScript as JSON now (`|tojson`); a test checks every template for unencoded values in scripts.
- A new test sends a request without signing in to every route, add-on routes included, and fails if anything but the short list of public pages answers.
- Fixes for CodeQL's security-extended findings:
  - **Proxmox, Veeam and Duplicati:** API paths now only use names the device itself reported (node, guest type, power action, job, disk). A request can no longer put arbitrary text into the URL; before, the node and guest type from the form went into the Proxmox API path unchecked.
  - **Logs:** host, device and path names have their line breaks escaped, so they cannot forge log entries.
  - **File permissions:** the generated public SSH key, the proxy routes and the HAProxy candidate configuration are readable by their owner only.
  - **Data sync:** the optional sync checks the peer's certificate by default (`FLEETPILOT_SYNC_CA` for a self-signed peer).
- VM power actions answered a rejected node, guest type or action with the exception's text; they now return only fixed messages (CodeQL `py/stack-trace-exposure`).
- `/vm/<id>/disks` stored disks without their node, so the disks of a cluster's nodes overwrote each other there too.

### Added

- **Translation report:** `python scripts/missing_translations.py` lists untranslated literal template strings and per-language totals without starting the application; `--lang` checks one language.
- **Windows PCs and servers, every release Microsoft still supports**, all over OpenSSH (see [WINDOWS_SUPPORT.md](WINDOWS_SUPPORT.md)):
  - covers Windows 11 up to 26H2, Windows 10/11 LTSC 2019/2021/2024 (including IoT and evaluation editions) and Windows Server 2016, 2019, 2022 and 2025 (Desktop or Core), in any display language
  - **Detect OS** names the exact release and edition and shows Microsoft's support end date; the host list warns about ended support
  - updates use the built-in Windows Update Agent, run once as SYSTEM through a scheduled task (Windows does not let an SSH session install updates), never restart the machine, and work with WSUS, LTSC and Server Core; a full update also runs `winget upgrade` where winget exists
  - an installation is never cut off: after two hours FleetPilot stops waiting while Windows carries on, and the next update run (or one after a lost connection) follows the running installation to its result
  - hardware overview and SMART (with smartmontools for Windows) for Windows hosts; **Install SSH key** puts the key where Windows OpenSSH reads it for administrators
  - all commands are encoded PowerShell, so they work with cmd.exe or PowerShell as the SSH shell
- **Android app (beta)**, now working with FleetPilot itself:
  - signs in with a personal API token
  - trusts FleetPilot's self-signed certificate after you confirm its fingerprint, and then only that certificate
  - shows the dashboard, servers, VMs, HW monitor and fans
  - wakes and shuts down servers, runs VM power actions and sets fan speeds, within the token's scope and your role
  - the API gains `GET /api/vms`, `POST /api/vms/<id>/action` and `POST /api/fans/<id>/set_fan`, and `/api/hosts` now reports each host's state
- **Enforced coding standard and strict warnings:** ruff (PEP 8, rules in `ruff.toml`) fails CI on any finding, the test suite treats every warning as an error, and CI measures statement and branch coverage with a floor that only goes up.
- **License headers:** every source file states `SPDX-License-Identifier: GPL-3.0-or-later` and its copyright holder; a test keeps it that way.
- Project documents for the OpenSSF silver level: a [code of conduct](CODE_OF_CONDUCT.md) (Contributor Covenant 2.1), a [roadmap](ROADMAP.md), code review standards in CONTRIBUTING.md, continuity rules in GOVERNANCE.md, and a [security assurance case](docs/security/assurance-case.md).
- Pull requests are fuzzed with ClusterFuzzLite (`.clusterfuzzlite/`, Atheris), focused on the changed code.
- **Signed releases with build provenance**: each release now carries the source archive, the SBOM, `SHA256SUMS` and Sigstore-signed SLSA provenance (`gh attestation verify`). It is assembled as a draft and published in one step.
- **Hardened CI**:
  - Least-privilege permissions per job and no stored checkout credentials.
  - Concurrency limits for every workflow.
  - CodeQL with the security-extended queries, now also for the workflows themselves.
  - A zizmor audit of all workflows.
  - Dependabot groups, a 7-day cooldown, and updates for the fuzzing image.
  - CODEOWNERS.
  - The unused "Notify New Version Available" workflow is removed.

- **Vulnerability scan** (Servers → Vulnerabilities): known CVEs in the installed packages of every Linux server (Debian, Ubuntu, Raspberry Pi OS, Proxmox VE/Backup Server, TrueNAS SCALE, Alpine, Rocky Linux, AlmaLinux) from OSV.dev, Docker container images through Trivy when it is installed, pfSense/OPNsense `pkg audit`, and FleetPilot's own Python packages and server. Shows severity (CVSS), the fixing version and where each vulnerability is; filters; scan one target or all; optional daily scan with notifications about new high/critical findings that have a fix; `GET /api/vulnerabilities`, Prometheus metrics and a Security center check. Only package names and versions are sent to OSV.dev; nothing in offline mode; `FLEETPILOT_OSV_URL` for a mirror.

- **Live demo you can try before installing** (https://christianhandy.github.io/FleetPilot/): the real FleetPilot runs in the browser with Pyodide against an emulated homelab of Proxmox nodes, TrueNAS, Proxmox Backup Server, Linux and Windows machines, FRITZ!Box/Repeater, OpenWrt and OPNsense. Updates, Wake-on-LAN, VM power, fan control, SMART alerts and router checks all work; a "Virtual lab" panel switches devices off, fails disks or publishes updates. The previous static demo is now the lighter tour at `/tour/`. See `demo/README.md`.

- **Releases:** pre-release tags (`v1.8.0-beta.2`) are published by the release workflow too, as pre-releases. Files attached to a draft release before the tag is pushed, such as the Android APK, get checksums and signed provenance like the source archive.
- **Android app in every release:** the release workflow builds the APK from the tag, signs it with the release key, checks the signing certificate and attaches it to beta and stable releases, covered by `SHA256SUMS` and the signed provenance.

### Fixed

- **SSH connections leaked** when a command or read timed out: the HW monitor's polling, the hardware overview, the live host stats, shutdown and the remote-disk plugin closed the connection only on success, and a failed connect left its socket open. On a slow Windows host FleetPilot held 193 connections until Windows' sshd refused every new one ("Exceeded MaxStartups"). Every path now closes the connection.
- An SSH server that closes the connection before greeting is reported as overloaded, out of memory or with too many logins waiting, not as paramiko's "Error reading SSH protocol banner". [WINDOWS_SUPPORT.md](WINDOWS_SUPPORT.md) explains how to recognise and clear an sshd that has too many connections waiting. A Windows Update that Windows ends by restarting (task result 0x41306) now says so.
- Windows Update no longer stops with "The process cannot access the file … update.log" when the log is being written while FleetPilot reads it (seen after an hour of installing on Server 2025).
- SSH connections send keepalives every 30 seconds, so a long Windows Update whose host stops answering (a firewall that starts dropping packets) ends with an error instead of waiting forever.
- Windows hosts were detected as Linux, could not be shut down (FleetPilot sent the Linux `shutdown -h now`), and updates failed when the SSH shell was PowerShell or the PowerShell Gallery was unreachable.
- Editing a host dropped every field the form does not show (custom image, reachability state, detected OS) and, when it was renamed, its last-update and last-seen times.
- **HW Monitor never collected live metrics:** the collector script sent to each host had broken indentation since an earlier clean-up, so it failed on every host and every server showed as unreachable. A test now runs the script.
- The hardware stress test kept going after the GPU dropped off the bus: the GPU and combined phases set a local `running` flag instead of the global one.
- SQLite connections opened with `with get_db() as conn:` were committed but never closed, leaking file handles until garbage collection; they are now closed at the end of the block.
- A test of the network allowlist's lockout guard never checked its result; it does now.
- SMART data from Proxmox nodes was never read: FleetPilot asked the API for an empty disk name instead of the `devpath` Proxmox reports.
- In a Proxmox cluster, disks with the same name on different nodes (every node's `sda`) overwrote each other in the SMART registry; they are now stored as `node:sda`.
- Fan controllers (lm-sensors) showed the sensor limits (`temp1_max`, `temp1_crit`) as extra temperature readings; only measured values are shown now.
- HW Monitor showed German labels ("Netz", "CPU Last") in the English interface.
- **Ping button (example plugin):** the round-trip time started before the port 80 attempt, so a host without a web server was charged that attempt's full timeout even when SSH answered in a millisecond; every attempt is timed on its own and the time of the one that answered is reported. A refused connection also counts as an answer (the host is up, only the port is closed), so a host with neither port 80 nor port 22 open is no longer shown as "Timeout". The button shows `3 ms (22)` or the reason a host did not answer (`timeout`, `dns`, `unreachable`) instead of always "Timeout".

## [1.7.0] — 2026-10-09

### Added

- **One-command install on Proxmox VE**: `proxmox/fleetpilot-lxc.sh` creates an unprivileged Debian 13 container (default or advanced settings, static IP, VLAN, SSH key) and installs FleetPilot with HTTPS; `-- update <ID>` updates it. Tested on Proxmox VE 9.2. Files for submission to community-scripts.org are in `proxmox/community-scripts/`.
- **Unified installer** `install.sh` for Debian 12/13, Ubuntu 22.04/24.04 and Raspberry Pi OS: read-only code directory, `fleetpilot` service user, its own Ed25519 SSH key, root helpers behind one narrow sudo rule, nginx with a self-signed certificate on 443, unattended options, safe re-runs as updates. `install-debian.sh` and `install_raspberry_pi.sh` now call it.
- **New documentation**: installation guide and a user guide covering every feature, in English and German, with PDFs (`docs/installation.md`, `docs/user-guide.md`, `docs/de/`).
- `reset-password.sh` rewritten: finds the user database in the data directory, `--generate`, `--list`, signs out open sessions, never puts the password on a command line.
- HW Monitor is now in the menu (Hardware → HW Monitor); the German menu is fully translated.

- **AVM FRITZ!Box and FRITZ!Repeater** via TR-064: model, FRITZ!OS version, uptime, internet line (status, external IP, line speed), Wi-Fi networks with client counts, all devices, the Mesh overview, FRITZ!OS update check, encrypted FRITZ! export backup and restart. **Repeaters and access points** of any brand can be added for an availability check; every device has a role (router, repeater, access point).
- Tables that scroll sideways on small screens can be reached and scrolled with the keyboard on every page.
- **Routers** (Servers → Routers): OpenWrt, OPNsense (REST API), pfSense, VyOS, DD-WRT/FreshTomato, MikroTik RouterOS and IPFire/Linux routers. Shows status, firmware, uptime, memory, interfaces and DHCP clients; update checks (OpenWrt opkg/apk, OPNsense, pfSense, RouterOS), encrypted configuration backups, restart with name confirmation, offline/online and update notifications, Prometheus metrics and `GET /api/routers`. See `docs/routers.md`.
- **Security center** (System → Security center): checks for HTTPS, admins without 2FA, the first-run password file, secret-key permissions, CSRF, debug mode, failed sign-ins, backup age, never-expiring tokens and unused accounts; sign-in rules (require 2FA for admins, idle timeout, password-confirmation window, longest token life, audit retention, allowed networks); every active session and API token with sign-out/revoke.
- **Sign-in & security** (Account): your active sessions by device with "sign out" and "sign out all other sessions", recent sign-ins and failures, and personal **API tokens** (read-only or read/write, expiring, shown once, stored hashed) for scripts and Home Assistant. `GET /api/me` shows who a token belongs to.
- After signing in, FleetPilot shows when and from where you last signed in and how many failed attempts happened since.
- **Notifications** (System → Notifications): ntfy, Gotify, Discord, Slack/Mattermost and generic JSON webhooks for disk alerts, security events (lockouts, new administrators, settings changes, write tokens) and backup downloads/restores, with a minimum level per channel and a test button. Webhook URLs are stored encrypted.
- **Audit trail** filters (event, user, outcome, period, search), CSV export and a retention period.
- **Accessibility** (Account → Accessibility): text size, high contrast, easy-to-read font, wider spacing, underlined links, reduced motion, and easy language with simple menu names and a plain explanation on each page (English and German Leichte Sprache). Skip link, landmarks, one heading per page, labelled fields and icon buttons, announced status messages, keyboard reordering on the Home page. See `docs/accessibility.md`.
- Every page uses the same page header (title, description, actions), card, stat-tile and button styles as the Home page; the HW Monitor pages are now in English.

- **Backups** (System → Backups): one-click and daily automatic backups of FleetPilot's data with consistent SQLite snapshots and checksums; restores are verified and applied at the next start, keeping the previous files.
- **Prometheus metrics** at `/metrics` (token-authenticated): hosts, SMART health/temperatures/power-on hours, open alerts, Disk Tools tasks, server CPU/memory.
- **SMART alert emails** when a disk is newly flagged; repeat polls of the same problem no longer create duplicate alerts.
- Styled error pages; production checklist in `docs/production_profile.md`.

- **High-security deployment** (see SECURITY.md): FIPS mode (`FLEETPILOT_FIPS`, PBKDF2-HMAC-SHA256 with automatic re-hashing at sign-in), strict SSH host keys (`FLEETPILOT_SSH_STRICT_HOST_KEYS`), offline mode for air-gapped networks (`FLEETPILOT_OFFLINE`), a strict systemd profile (`deploy/fleetpilot-strict.conf`, exposure 1.2) and a TLS reference configuration (`deploy/nginx-fleetpilot-tls.conf`).
- Security center: notice that must be accepted before sign-in, absolute session lifetime (default 12 hours), configurable account lockout, audit-trail integrity check.
- The audit trail is HMAC-chained so changed or deleted events are detected, and every event is also logged as JSON for forwarding to a SIEM.

### Performance

- Update dashboard: hosts are checked in parallel with a TCP connection to the SSH port (cached 30 s) instead of a full SSH login one after another. With 10 switched-off hosts a page view went from 30 s to 1.6 s (then instant); monitored hosts no longer log failed SSH logins from FleetPilot.
- HW Monitor polls every 8 s only while someone views it, otherwise every 30 s (history resolution unchanged): about 70 % fewer SSH logins to monitored servers.
- Role checks are read once per request; user list and security center use one query for all users' roles; the audit-chain check is reused for 5 minutes.
- Server-registry imports at startup and host saves use one database transaction instead of one commit per server; the timing-equaliser password hash is created on first use instead of at startup.
- The online plugin catalogue is cached for 10 minutes (also when GitHub is unreachable) instead of being downloaded on every page view.

### Fixed

- Found by the first real Proxmox install: FleetPilot no longer writes into its program directory (SMART CSV exports, host pictures, version check, gunicorn control socket); SMART collection read demo hosts from the program directory instead of the configured hosts; the repository no longer ships demo `hosts.json`/`history.json`; installer re-runs no longer stop at "Writing settings".
- Security (CodeQL): RouterOS and SMART parsers no longer use regular expressions that could backtrack on crafted input; router backup file names are checked to stay inside the backup folder; SSH and smartctl errors no longer return raw exception text.
- Uploaded host pictures are served from the data directory with a sandboxing Content-Security-Policy, so an uploaded SVG cannot run script.
- HW Monitor never imported servers from hosts.json (it expected a list); it now does, and stores SSH passwords encrypted like every other module (existing plain-text passwords are encrypted at start).

### Security

- All fonts, icons, Bootstrap and Chart.js are served by FleetPilot; pages no longer contact Google Fonts or CDNs (GDPR, air-gapped networks) and the Content-Security-Policy only allows FleetPilot itself.
- Turning off or changing two-factor sign-in asks for the password again.
- Passwords that are repetitive, sequential, or contain the user name or product name are rejected (NIST SP 800-63B).
- Session cookies are signed with HMAC-SHA256; `/healthz` no longer reveals the version; host shutdown now verifies the SSH host key.
- Fixed the CodeQL findings: uploaded SMART reports were saved under the browser-supplied filename (a name like `../app.py` could overwrite files); redirects that followed the `Referer` header could leave the site; exception text with paths, hosts or credential-bearing URLs was returned to the browser; the CheckMK host lookup echoed the host name into an HTML page.
- Disk commands only run for devices that exist on the server; plugin, add-on template and backup files are looked up safely; fan-controller SSH keys must be in the data folder or `~/.ssh`.
- GitHub workflows: fixed a script injection in `notify-version.yml`, pinned every action to a commit SHA, read-only token permissions by default; added CI tests (Python 3.11–3.13, pip-audit, Bandit, crash lint), OpenSSF Scorecard and Dependabot.
- Fixed "Update this server" failing with `UnboundLocalError` before it started.
- Removed local databases, build output and old duplicate folders from the repository and ignore them from now on.

- Every request now validates the session centrally. Routes using `user_management.login_required` (audit trail, production status, Storage workspace, plugin manager) accepted sessions of deactivated users and sessions that had ended through a password change.
- Sessions are recorded on the server: logout really ends a session (a copied cookie no longer works), sessions end after inactivity (default 120 minutes), and resetting a user's password or disabling the account signs out all their devices.
- Signing in with a security key (WebAuthn) created a session without the password fingerprint, so the next page signed the user out again.
- Sensitive actions (user management, backups, API tokens, security settings) ask for the password again after 10 minutes.
- The last active administrator can no longer be deleted, disabled or demoted.
- Login lockouts are written to the audit trail; deleting a user also removes their roles, preferences, sessions and tokens.
- Content-Security-Policy no longer allows `eval` and adds `object-src 'none'`, `base-uri 'self'`, `form-action 'self'` and `frame-ancestors 'none'`; added `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy`.
- Removed `/api/sync/manifest` and `/api/sync/pull/<file>`, which served every file in the data directory (including `users.db`, 2FA secrets and the CheckMK token) without login.
- `data_sync.py` no longer has a built-in token; it needs `SYNC_TOKEN` (32+ characters), compares it in constant time and only transfers allow-listed files.
- Viewer accounts can no longer shut down or wake hosts, control fans, install packages, trigger backups, run shutdown schedules or change the HW monitor and server registry.
- Sessions of deleted or deactivated users are rejected.
- CSRF protection is on by default and checked per request; state-changing links (system updates, SMART tests, auto mode, history and remote deletion) are now POST forms.
- Fixed command injection through fan channels, backup job IDs and device settings passed to `liquidctl`, `ipmitool` and `bconsole`.
- Escaped data from remote hosts, network scans and the plugin repository before it is inserted into pages (stored XSS).
- Remote helper scripts run from stdin instead of fixed `/tmp` paths on the target host.
- No default admin passwords in the app, the Raspberry Pi installer or the C# port; a random first-run password is generated instead.
- `SECRET_KEY` is loaded before modules derive encryption keys; placeholder values are rejected. All stored controller credentials use one encryption helper with no plain-text fallback; older values still decrypt.
- Raised dependency minimums past known CVEs (Flask, Werkzeug, Jinja2, requests, urllib3, gunicorn, python-dotenv, paramiko, cryptography; SSH.NET for the C# port) and pinned CDN assets with Subresource Integrity hashes.
- SSH host keys are verified on first use in the Home Assistant integration and the C# port.
- Removed the standalone `hw_monitor/app.py`, which had no login.
- Login throttling per address and per account; 2FA codes limited to 5 tries; failed logins are audited.
- Passwords need 12+ characters; changing your password requires the current one and ends your other sessions.
- Email settings live in the data folder with the SMTP password encrypted and never sent back to the browser.
- Plugin manager and plugin source view are admin-only.
- HW monitor fan control validated and quoted the PWM path (command injection).
- Data folder `0700`/files `0600`, SQLite WAL with 15 s lock timeout, gunicorn binds to loopback by default, one worker without recycling, request limits, more systemd sandboxing.

### Fixed

- Disk Tools auto mode crashed on its first new disk and never started under gunicorn. It now runs in the background service and only processes disks attached after it is switched on.
- Remote plugin installation failed (missing `requests` import); live host metrics always failed (undefined SSH client).
- The hosts page crashed for hosts without tags.
- Disk validation showed an error page when the disk helper was missing; it now explains what to install.
- Saving one form on the email settings page wiped the other form's settings; "Send test email" ignored what was typed.
- Signing in always went to Home instead of the page you were trying to open.
- Duplicate names returned server errors instead of a message; HW monitor fan control crashed without a PWM path.
- The Debian installer ran two gunicorn workers (duplicate pollers and SQLite writers).
- The server registry never imported servers from HW Monitor, fan controllers or backups (wrong table names, rows read with `.get()`); it no longer copies encrypted module passwords.
- Several pages showed flash messages twice; the 2FA step showed the full menu before sign-in was complete; its "Use a backup code" link pointed to a page that does not exist.
- Bootstrap badge colors overrode the theme (low contrast); chart colors ignored the theme.
- Translated strings showed literal HTML entities (`&rarr;`, `&amp;`, `&nbsp;`).

## [1.6.0] — 2026-08-14

### Added

- Dedicated **Unraid TLS passthrough** route for the centrally registered Unraid server at `https://192.168.1.100:8200/`.
- Administrator-only Unraid route installation with fixed destination port `443`, fixed public port `8200`, HAProxy validation, and automatic registry rollback if configuration activation fails.
- Unraid console labeling in both the authenticated service map and the read-only public status overview.

## [1.5.3] — 2026-08-14

### Fixed

- Proxmox TLS passthrough backends now use reliable TCP-connect health checks. The prior SSL hello probe was rejected by the Proxmox proxy and incorrectly marked healthy HTTPS backends unavailable.

## [1.5.2] — 2026-08-14

### Fixed

- Replaced the unsupported HAProxy `no option httplog` directive with a compatible frontend-level `option tcplog` setting for Proxmox TLS listeners. The active configuration remains protected from failed candidate replacements.

## [1.5.1] — 2026-08-14

### Fixed

- Dedicated Proxmox TLS passthrough listeners now explicitly use TCP logging instead of inheriting the HTTP logging option, eliminating non-functional HAProxy configuration warnings while preserving console traffic handling.

## [1.5.0] — 2026-08-14

### Added

- A read-only, unauthenticated **Service Status** page at `/status` that lists published services and registered host health without exposing internal addresses, credentials, logs, inventory, or management actions.
- A visible status-page entry point from the sign-in screen.
- Dedicated **Proxmox TLS passthrough routes** for named `pveNN` hosts. Each route receives a deterministic high port (`8101` for `pve01`, `8102` for `pve02`, and so on) while preserving Proxmox WebSocket consoles and Proxmox-native login.
- Administrator-only Proxmox route installation with validation, HAProxy syntax checking, atomic configuration replacement, and automatic route-registry rollback on failure.

### Changed

- The proxy route registry now distinguishes conventional HTTP path routes from constrained Proxmox TLS passthrough routes. The public status view never exposes the private backend addresses associated with either route type.

## [1.4.0] — 2026-08-14

### Added

- A visible, POST-only **Log out** control in the Account navigation; it clears the complete FleetPilot browser session.
- Browser-native **WebAuthn/FIDO2 security-key** enrolment and second-factor verification for YubiKey and compatible security keys.
- Persistent public-key credential records, replay-resistant server challenges, per-credential signature counters, security-key removal, and security-key audit events.
- Explicit separation between browser-native WebAuthn security keys and the existing legacy YubiKey OTP option.

### Security

- WebAuthn enrolment and authentication are deliberately available only through a trusted HTTPS origin with a relying-party ID that matches the current host.
- Existing TOTP, legacy YubiKey OTP, password login, and one-time backup-code recovery remain available as independent break-glass paths.

## [1.3.2] — 2026-08-14

### Geändert

- Die zentrale Übersicht zeigt jetzt als Hauptinhalt eine **Services & Server Map** statt einer allgemeinen Liste von FleetPilot-Seiten.
- Jede Proxy-Route wird mit öffentlichem Pfad, registriertem Zielserver, Backend-Adresse, aktivem Zustand und einem zwischengespeicherten direkten Health-Check dargestellt.
- Alle registrierten Infrastrukturhosts zeigen explizit, welche veröffentlichten Proxy-Routen sie bereitstellen. Hosts ohne zugeordnete Route sind ebenfalls sichtbar.
- Konfigurierte Routen, die auf einen nicht registrierten Server zeigen, werden deutlich als **Unregistered** markiert.

## [1.3.1] — 2026-08-14

### Behoben

- Bereits angemeldete Nutzer werden beim Aufruf der zentralen Adresse <code>http://192.168.1.100/</code> nun automatisch zur **FleetPilot Service Hub**-Übersicht unter <code>/index</code> weitergeleitet, statt erneut die Anmeldeseite zu sehen.

## [1.3.0] — 2026-08-14

Dieses Funktionsrelease macht den zentralen FleetPilot-Einstieg verständlicher und erkennt verwaltbare Fähigkeiten neuer Hosts automatisch, ohne Zugangsdaten oder Änderungen auf dem Zielgerät vorzunehmen.

### Hinzugefügt

- Einen **FleetPilot Service Hub** auf der Hauptseite mit allen für den aktuellen Benutzer erreichbaren Bereichen, gruppiert nach Funktion und Rolle.
- Einen zentralen Überblick über die Raspberry-Pi-Ingress-Adresse, veröffentlichte Proxy-Pfade und den aktuellen Status verwaltbarer Hosts.
- Eine klare vierstufige Erklärung des Proxy-Workflows direkt auf der Startseite und auf der Seite **System → Proxy Services**, einschließlich eines vollständigen Praxisbeispiels.
- Passive Management-Erkennung für neue Hosts: FleetPilot prüft nur die explizit konfigurierte Adresse auf SSH, Proxmox API sowie HTTP/HTTPS und schlägt passende Module vor.
- Einen sicheren Einzel- und Sammel-Refresh der Fähigkeitserkennung für bereits konfigurierte Hosts.

### Sicherheit

- Die automatische Erkennung authentifiziert sich nicht, probiert keine Zugangsdaten, führt keine Remote-Befehle aus und scannt keine Netzwerkbereiche. Sie untersucht ausschließlich die Adresse eines bereits konfigurierten Hosts.

## [1.1.2] — 2026-08-14

### Behoben

- Die FleetPilot-Service-Sandbox lässt dem streng begrenzten root-eigenen Proxy-Helper nun ausschließlich Schreibzugriff auf `/etc/haproxy` zu. Dadurch funktionieren Route-Änderungen aus der Weboberfläche, ohne den restlichen Hostschutz aufzuweichen.
- Fehler des Proxy-Helpers werden als sichere Kurzmeldung statt als internem Python-Traceback zurückgegeben.

## [1.1.1] — 2026-08-14

### Behoben

- Der root-eigene Proxy-Apply-Helper verwendet beim ersten Einsatz `systemctl reload-or-restart`, sodass HAProxy nach der Migration auch dann zuverlässig startet, wenn zuvor noch kein Dienst aktiv war.

## [1.1.0] — 2026-08-14

Dieses Feature-Release verlagert den zentralen HTTP-Ingress auf den Raspberry Pi und ergänzt eine kontrollierte Verwaltung interner Dienste und Pfadrouten direkt in FleetPilot.

### Hinzugefügt

- Eine admin-geschützte Seite **Proxy Services** zum Hinzufügen, Testen und Entfernen interner HTTP-Dienstrouten.
- Eine persistent gespeicherte, validierte Routenregistrierung für Dienstname, öffentlichem Pfad, Backend-Ziel, Port und Health-Check.
- Einen root-eigenen HAProxy-Renderer, der die Registry erneut prüft, eine feste Konfiguration erzeugt, diese validiert und nur dann atomar neu lädt.
- Automatisches Rollback der FleetPilot-Routenregistrierung, wenn ein HAProxy-Reload nicht erfolgreich ist.
- Eine private Nginx-Upstream-Konfiguration auf `127.0.0.1:8080`; HAProxy besitzt den LAN-Ingress auf Port 80.

### Sicherheit

- Die Proxy-Kette entfernt klientengelieferte Weiterleitungsheader und setzt vertrauenswürdige Header neu, bevor die Anfrage an FleetPilot weitergegeben wird.
- Der FleetPilot-Webdienst erhält nur die eng begrenzten Sudo-Rechte `proxy-apply apply` und `proxy-apply status`; er kann keine beliebigen HAProxy-Befehle, Pfade oder Backends als Root ausführen.

## [1.0.1] — 2026-08-14

Dieses Patch-Release behebt die fehlgeschlagene Aktualisierung aus der FleetPilot-Weboberfläche, ohne dem Webdienst Schreibzugriff auf den Anwendungscode zu geben.

### Behoben

- Der Selbstupdate-Workflow verwendet nun einen root-eigenen, auf das freigegebene GitHub-Repository und den Branch `main` beschränkten Helper. Dadurch kann der eingeschränkte `fleetpilot`-Dienst keine `.git`-Dateien mehr direkt verändern müssen.
- Die Update-Prüfung ist schreibgeschützt. Eine tatsächliche Aktualisierung führt ausschließlich einen kontrollierten Fast-Forward-Updatepfad aus und installiert Anforderungen nur aus dem geprüften Repository.
- Der Dienstneustart wird als separater systemd-Auftrag geplant, damit Browserantwort und Update-Status vor dem Neustart zuverlässig verarbeitet werden.
- Der Raspberry-Pi-Installer installiert den Helper und eine Sudo-Regel, die nur die Aktionen `check`, `apply` und `restart` erlaubt.

## [1.0.0] — 2026-08-14

Dies ist das erste formale, produktionsorientierte FleetPilot-Release für kleine interne IT-Umgebungen.

### Hinzugefügt

- Eine einheitliche **Storage & Disks**-Arbeitsfläche für Datenträgerinventar, SMART-Zustand, dauerhafte Aufgaben und verwaltete Speichersysteme.
- Ein append-only **Audit Trail** für zustandsändernde Anfragen, ohne Passwörter, Tokens, SSH-Schlüssel, Request-Bodies oder Kommandoausgaben zu speichern.
- Eine administrative **Production Status**-Ansicht mit Laufzeit-, Cookie-, Proxy-, CSRF-, Secret- und Audit-Status.
- Ein `/healthz`-Endpunkt mit maschinenlesbaren Release-Metadaten.
- Eine gehärtete Gunicorn-/systemd-Laufzeit für den Raspberry-Pi-Betrieb hinter Nginx.
- Zentrale Versionsmetadaten in `fleetpilot_version.py`, die Weboberfläche, Health-Endpunkt, Selbstupdate-Ansicht und künftige Clients verwenden können.

### Verbessert

- Die zentrale Navigation enthält die administrative Production-Status-Seite.
- Der Versions-Toast verwendet den korrekten Selbstupdate-Endpunkt.
- Android-Client und C#-Backend tragen ebenfalls die Release-Version `1.0.0`.

### Sicherheits- und Betriebsstatus

- Der Live-Service läuft als dedizierter `fleetpilot`-Benutzer über Gunicorn hinter Nginx.
- Das Umgebungsdatei-Recht auf dem Raspberry Pi ist auf `root:fleetpilot` mit Modus `0640` eingeschränkt.
- HTTPS, sichere Cookies und die globale CSRF-Erzwingung bleiben bewusst als nächste, separat testbare Produktionsschritte ausstehend.

[1.6.0]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.6.0
[1.5.3]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.5.3
[1.5.2]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.5.2
[1.5.1]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.5.1
[1.5.0]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.5.0
[1.4.0]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.4.0
[1.3.2]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.3.2
[1.3.1]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.3.1
[1.3.0]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.3.0
[1.1.2]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.1.2
[1.1.1]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.1.1
[1.1.0]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.1.0
[1.0.1]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.0.1
[1.0.0]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.0.0
