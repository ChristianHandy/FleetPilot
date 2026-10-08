# Changelog

Alle bemerkenswerten Änderungen an FleetPilot werden in diesem Dokument festgehalten. Die Versionsnummern folgen dem Prinzip der semantischen Versionierung.

## [Unreleased]

### Added

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

### Security

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
