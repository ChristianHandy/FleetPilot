# FleetPilot User Guide

**Version 1.7** · for administrators, operators and viewers

FleetPilot is one web interface for the servers, PCs, routers, disks, virtual machines, storage and backups in a home lab or small company. It reaches your machines over SSH and over the APIs of Proxmox, TrueNAS, Unraid and the backup systems. Nothing has to be installed on the managed machines.

Installing FleetPilot is covered in the **[installation guide](installation.md)**. *Deutsch: [de/benutzerhandbuch.md](de/benutzerhandbuch.md)*

**Contents**

- [1. Basics](#1-basics): signing in, the screen, roles, languages, accessibility
- [2. Home](#2-home)
- [3. Servers](#3-servers): [Manage Hosts](#manage-hosts) · [Network Scanner](#network-scanner) · [Routers](#routers) · [Update Dashboard](#update-dashboard) · [Server update](#server-update)
- [4. Hardware](#4-hardware): [Hardware overview](#hardware-overview) · [HW Monitor](#hw-monitor) · [SMART health](#smart-health) · [Storage & disks](#storage--disks) · [Fans & cooling](#fans--cooling)
- [5. Virtualisation and storage](#5-virtualisation-and-storage): [VM controllers](#vm-controllers) · [Storage controllers](#storage-controllers) · [Backup servers](#backup-servers)
- [6. Operations](#6-operations): [Scheduled shutdown](#scheduled-shutdown) · [CheckMK](#checkmk) · [System monitor](#system-monitor) · [FleetPilot update](#fleetpilot-update)
- [7. System](#7-system): [Update Settings](#update-settings) · [Email Config](#email-config) · [Proxy services](#proxy-services) · [Production status](#production-status) · [Security center](#security-center) · [Notifications](#notifications) · [Audit trail](#audit-trail) · [Backups](#backups) · [Plugins](#plugins)
- [8. Account](#8-account): [My Profile](#my-profile) · [Sign-in & security](#sign-in--security) · [Two-factor sign-in](#two-factor-sign-in) · [Accessibility](#accessibility) · [User Management](#user-management)
- [9. Integrations](#9-integrations): API tokens and REST API · Android app · Prometheus · Home Assistant · public status page
- [10. Security notes](#10-security-notes)
- [11. Frequently asked questions](#11-frequently-asked-questions)

---

## 1. Basics

### Signing in

Open FleetPilot in your browser (for example `https://192.168.1.62`) and sign in with your user name and password. If two-factor sign-in is on for your account, FleetPilot then asks for the code from your authenticator app, your security key or a backup code.

After signing in, a short message shows when and from where you last signed in and how many failed attempts happened since. If you do not recognise them, change your password and check **Account → Sign-in & security**.

Too many wrong passwords lock the account for a while (10 attempts and 10 minutes by default). Sessions end after 2 hours of inactivity or 12 hours in total; an administrator can change both in the Security center.

### The screen

- **Sidebar** (left): all areas, grouped into *Servers*, *Hardware*, *Virtualisation*, *Operations*, *System* and *Account*. Groups can be folded. On a phone the sidebar opens with the menu button.
- **Page header**: title, a one-line description and the main buttons of the page.
- **Top right**: language, light/dark theme, accessibility settings, your profile and *Logout*.

### Roles

Every user has one or more roles:

| Role | Can |
|---|---|
| **viewer** | See everything except security settings, users and secrets |
| **operator** | Also run actions: updates, SMART polls, backups, wake/shut down hosts, start/stop VMs, router backups |
| **admin** | Everything: add and remove systems, users, security settings, restore backups, update FleetPilot, restart routers |

Actions that change security-relevant data (users, tokens, security rules, backups) ask for your password again if you have not confirmed it in the last 10 minutes.

### Languages

English, Deutsch, Français, Español and Nederlands. Choose the language at the top right; the choice is saved in your profile.

### Accessibility

**Account → Accessibility** makes FleetPilot easier to read and use: larger text, high contrast, an easy-to-read font, wider spacing, underlined links, reduced motion, and *easy language* with simple menu names and a short plain explanation on every page (English and German *Leichte Sprache*). The settings follow your account to every device. FleetPilot works with the keyboard alone and with screen readers. Details: [accessibility.md](accessibility.md).

---

## 2. Home

The start page shows the state of everything at a glance: services and server map, VM and storage controllers, SMART disk health, environments, tags, recent updates and shortcuts.

- **Customize** lets you show, hide and reorder the cards (drag them, or use the keyboard). **Save Layout** keeps the order for your account; **Reset to Default** restores it.
- A banner appears when a new FleetPilot version is available (admins can install it from there).

---

## 3. Servers

### Manage Hosts

The list of all servers and PCs FleetPilot manages.

**Add a host** (operators and admins): fill in

| Field | Meaning |
|---|---|
| Name | A short unique name, for example `nas` or `web-01` |
| Address | IP address or hostname |
| User / Port | SSH user and port (22) |
| MAC address | Needed for Wake-on-LAN |
| Group, Location, Environment, Criticality, Tags | For sorting and filtering (for example *Production*, *Lab*, *High*) |
| OS profiles | What runs on the machine: Linux distribution, Windows, Proxmox, etc. A PC with dual boot can have several profiles |

Then click **Install key** on the host: FleetPilot asks once for that machine's password, installs its own SSH key there and does not store the password. From then on it signs in with the key.

**Per host** you can:

- see whether it is online (checked on the SSH port, without signing in),
- **Wake** it (Wake-on-LAN magic packet to the MAC address),
- **Shut down** it (Linux and Windows),
- run updates (see Update Dashboard),
- upload a picture for the card,
- edit or delete it.

Use the search box and the tag, group and environment filters for large lists. The two buttons at the top switch between cards and a compact table.

**Detect IP changes**: if machines get their address by DHCP, FleetPilot can compare the MAC addresses with the ARP table and update addresses that changed.

### Network Scanner

Finds devices in a network range (for example `192.168.1.0/24`). Enter the range and click **Start Scan**. FleetPilot pings each address and checks for an open SSH port, then lists the devices it found. **Add Host** turns a result into a managed host with the details filled in. Only scan networks you are responsible for.

### Routers

Routers, repeaters and access points: FRITZ!Box and FRITZ!Repeater, OpenWrt (also GL.iNet, Turris), OPNsense, pfSense, VyOS, DD-WRT/FreshTomato, MikroTik RouterOS, IPFire and other Linux routers, plus an availability check for any other repeater or access point.

- **Add device** (admins): choose the system and the role (router, repeater, access point), enter address and credentials. OPNsense uses an API key and secret; FRITZ! devices use a FRITZ! user with the *FRITZ!Box settings* right; the others use SSH.
- The detail page shows model, firmware, uptime, load, memory, interfaces, connected devices, Wi-Fi networks and (FRITZ!) the internet line and Mesh.
- **Check for updates** shows whether new firmware is available. FleetPilot never installs router firmware, because a failed upgrade can take the whole network down.
- **Configuration backups** (operators) are stored encrypted; admins can download them. The last 10 per router are kept.
- **Restart router** (admins) must be confirmed by typing the router's name.

Credentials are stored encrypted. More details and the required rights per system: [routers.md](routers.md).

### Update Dashboard

Updates for all managed hosts in one place: Debian/Ubuntu (`apt`), Fedora/RHEL (`dnf`/`yum`), Arch (`pacman`) and Windows (`winget`).

- Select one or more hosts and start the update. **Update Progress** shows the live output per host.
- **Update History** lists every run with its result and duration.
- **Automatic Updates** runs updates on a schedule (see [Update Settings](#update-settings)).

### Vulnerabilities

Known security vulnerabilities (CVEs) in the software on your machines, sorted by severity, with the version that fixes each one.

- **What is checked:**
  - **Linux servers:** FleetPilot reads the installed packages over SSH (`dpkg`, `apk` or `rpm`) and looks them up in the distribution's security data on [OSV.dev](https://osv.dev). This covers Debian, Ubuntu, Raspberry Pi OS, Proxmox VE and Backup Server, TrueNAS SCALE, Alpine, Rocky Linux and AlmaLinux.
  - **Docker containers** on those servers: FleetPilot scans their images with [Trivy](https://trivy.dev), if Trivy is installed on the server.
  - **pfSense and OPNsense:** their own `pkg audit`.
  - **FleetPilot itself:** its Python packages and the machine it runs on.
  - **Not covered:** Windows, FRITZ!OS and OpenWrt publish no package-level data. They are listed as "Not covered", with what to do instead.
- **Reading the results:**
  - **Scan now** (operators and admins) scans everything in the background; **Rescan** scans one target.
  - The list shows high and critical findings that have a fix by default. Change the filters to see everything, including vulnerabilities the distribution has not fixed yet.
  - Most findings go away after an update. Run it from Hosts or [Update Dashboard](#update-dashboard), then rescan.
- **Daily scans and alerts:** admins can turn on a daily scan. When a scan finds new high or critical vulnerabilities that have a fix, FleetPilot notifies every channel subscribed to "New vulnerabilities" ([Notifications](#notifications)). The first scan of a target is the baseline and sends no alert.
- **Privacy:** only package names and versions are sent to OSV.dev, never addresses, host names or other data. In offline mode (`FLEETPILOT_OFFLINE=true`) nothing is sent. `FLEETPILOT_OSV_URL` points FleetPilot at your own mirror of the OSV API instead.
- **Elsewhere:** results are also available as `GET /api/vulnerabilities` and as `fleetpilot_vulnerabilities*` metrics on `/metrics`, and the [Security center](#security-center) flags critical vulnerabilities that have a fix waiting.

### Server update

(Admins) Updates the operating system packages of the machine FleetPilot runs on. **Check for Updates Only** lists pending packages; **Start Update** installs them with live output; **Reboot Server** restarts the machine.

---

## 4. Hardware

### Hardware overview

Hardware details of every host: CPU, memory, mainboard, disks, network cards, GPU and sensors. **Collect hardware info** reads the data over SSH; **Refresh all** updates every host. Click a host for the full report.

### HW Monitor

Live view of temperatures, load, memory, network and disk I/O and fan speeds per server, with history charts.

- **Add server** with name, address and SSH user.
- **Setup** checks the tools each server needs (`lm-sensors`, `smartmontools`, `stress-ng`, `fio`) and installs missing ones.
- **Stress tests** (CPU, memory, disk) help to check cooling and stability of new hardware: **Start**, **Stop**, or **Start all tests**. Errors found during a test must be **acknowledged**.
- **Tasks** lists running and finished jobs with their logs.

The page refreshes faster while someone is viewing it and slows down otherwise.

### SMART health

Disk health for all disks FleetPilot knows: health status, temperature, power-on hours, reallocated and pending sectors.

- **Active Disk Alerts** lists disks that need attention. **Ack** acknowledges an alert so it stops being shown as new.
- **Poll Now** / **Poll Local Disks** read fresh SMART data; **Import Disks from Sources** collects disks from all SSH hosts, Proxmox nodes and NAS systems.
- **Polling Configuration** sets how often SMART data is read automatically.
- Click a disk for its history and attribute trends.

New problems can trigger an email and a push notification (see [Email Config](#email-config) and [Notifications](#notifications)).

### Storage & disks

The disk workspace: every disk with its SMART state, running storage jobs and remote systems.

- **Disk Overview** lists local disks and their partitions.
- **Validate** reads sampled blocks across the whole disk without writing anything and shows a map of the results, so you can spot a failing or fake-capacity disk quickly.
- **Format** (admins) erases a disk and creates an ext4, xfs or FAT32 file system. Choose *Quick wipe* (removes partitions and signatures) or *Full zero wipe* (overwrites every block, can take hours), then type `ERASE /dev/<disk>` to unlock the button. **This destroys all data on the disk.** System disks and disks with active mounts are blocked.
- **Remote Management** does the same for disks in other machines over SSH.
- **History** shows past operations and SMART imports; **SMART Import** accepts a `smartctl -a` report as a file.

Disk actions on the FleetPilot machine run through a small root helper that only accepts these specific actions.

### Fans & cooling

Controls fans on servers and PCs.

| Controller | Used for |
|---|---|
| lm-sensors (Linux PWM) | Mainboard fan headers |
| IPMI / ipmitool | Server BMCs (Supermicro, Dell iDRAC, HPE iLO, …) |
| nbfc-linux | Laptops |
| liquidctl | NZXT, Aquacomputer, Corsair and similar USB controllers |
| Arctic Fan Controller | Arctic USB fan hub |
| PWM sysfs | Direct kernel control |
| Raspberry Pi PWM fan | 3-wire fan on a GPIO pin |

**Add Fan Controller**: **Auto-Detect Controllers** looks for supported hardware on a host; **Use This** takes a result. On a device page you can set a **fixed speed**, use **auto mode**, or apply a **temperature profile** (fan speed by temperature). **Install Packages** installs the tools the controller needs.

**Commander Pro** (under Fans & cooling) controls a Corsair Commander Pro connected by USB to a remote PC, through SSH and liquidctl.

---

## 5. Virtualisation and storage

### VM controllers

Shows and controls the virtual machines and containers of **Proxmox VE** and the jobs of **Veeam Backup & Replication 12**.

- **Add endpoint** (admins): Proxmox on port 8006 with `root@pam` or an API user with the *PVEAdmin* role (Datacenter → Permissions → Users); Veeam on port 9419 with the REST API enabled.
- The detail page lists all VMs and containers with their state, CPU, memory and disk. Operators can **Start**, **Stop**, **Reboot**, **Suspend**, **Resume** and **Kill**.
- **Disks** shows the physical disks of each Proxmox node with their SMART state.
- For Veeam, the backup jobs and their last results are shown.

### Storage controllers

Shows pools, volumes, shares and disks of **TrueNAS SCALE/CORE** and **Unraid 6.12+**.

- **Add endpoint** with an API key: TrueNAS under *System → API Keys*, Unraid under *Settings → Management Access → API Keys*.
- The detail page shows disks, ZFS pools, SMB/NFS/Unraid shares and alerts. **Poll Disks** reads fresh disk data.

### Backup servers

Monitors backups on **Proxmox Backup Server**, **Duplicati**, **Restic REST server**, **BorgWarehouse**, **UrBackup**, **Bacula** (via `bconsole` over SSH) and any **generic SSH backup** (a command whose result FleetPilot reads).

- **Add Server** with type, address and credentials; **Test** checks the connection.
- The detail page shows datastores, jobs, snapshots and history. **Poll Now** refreshes; operators can trigger jobs where the system supports it.
- Failed or missing backups appear on the Home page and can be sent as notifications.

---

## 6. Operations

### Scheduled shutdown

Powers hosts down and up on a schedule, for example lab servers at night.

**Add Schedule**: choose a host, the action (*Shutdown*, *Reboot* or *Suspend*), the days and the time. **Now** runs a schedule immediately. **Recent Activity** shows what ran and whether it worked. To switch machines on again, use **Wake** on the host (Wake-on-LAN must be enabled in its BIOS/UEFI).

### CheckMK

Feeds FleetPilot's data into CheckMK (and other monitoring systems).

- **API Token**: the token monitoring systems use. **Regenerate** replaces it; old copies stop working.
- **Setup Instructions** offers four ways: a local check script, a piggyback script, a datasource program, or the REST API. Each comes with a ready-to-copy script.
- **Live Agent Output Preview** shows exactly what CheckMK will receive; **Failed / Critical Disks** and **Host Status Overview** show the current state.

The same token authenticates [Prometheus](#9-integrations).

### System monitor

(Admins) CPU, memory, disk, network and temperature of the FleetPilot machine itself, updated every 60 seconds, with history up to 24 hours.

### FleetPilot update

(Admins) **Check for Updates Only** shows whether a new FleetPilot version exists and what changes; **Pull & Update FleetPilot** installs it with live output and restarts FleetPilot. Your data and settings are kept. Download a backup first (see [Backups](#backups)).

---

## 7. System

### Update Settings

Rules for automatic host updates: on/off, how often (daily, weekly, monthly), and whether to send notifications and show update hints on the dashboard.

### Email Config

SMTP server, port, encryption, sender and recipients. **Send Test Email** checks the settings. **Report Configuration** chooses which reports are sent (update results, SMART alerts, daily summary). The SMTP password is stored encrypted.

### Proxy services

(Admins; Raspberry Pi with HAProxy) Publishes internal web services under one address, for example `/proxmox/` or `/unraid/`. Add a route in four steps: a unique public path, the internal destination, a health path, and FleetPilot applies it. Every change is validated before HAProxy reloads; invalid configurations are rolled back automatically. **Add Proxmox route(s)** creates the routes for Proxmox consoles in one step.

### Production status

A readiness view of the installation: runtime mode, session protection, reverse-proxy trust, CSRF protection, secret key, audit records and identity readiness. It is an operational checklist, not a certification.

### Security center

(Admins)

- **Checks**: HTTPS, admins without two-factor sign-in, a leftover first-run password file, secret-key permissions, CSRF, debug mode, failed sign-ins, backup age, never-expiring tokens and unused accounts. Each check says what to do.
- **Sign-in rules**: require 2FA for admins, idle timeout, absolute session lifetime, how long a password confirmation lasts, longest API-token lifetime, account lockout, audit retention, allowed networks (only these addresses may sign in), and a notice users must accept before signing in.
- **Active sessions** and **API tokens** of all users, each with *sign out* / *revoke*.
- **Recent failed sign-ins**.

### Notifications

Sends disk alerts, security events (lockouts, new administrators, changed settings, new write tokens), router and backup events to your phone or team chat: **ntfy**, **Gotify**, **Discord**, **Slack/Mattermost** and generic **JSON webhooks**.

**Add a channel**: type, URL (stored encrypted), which kinds of events it receives and the lowest level (info, warning, critical). **Test** sends a test message. Email is configured separately under *Email Config*.

### Audit trail

An append-only record of sign-ins and every change: who did what, when, from which address and with which result. Passwords, tokens, keys, request bodies and command output are never recorded.

Filter by event, user, outcome, period or text, and export as CSV. The records are chained with HMAC so that changed or deleted entries are detected; the Security center shows the result of the integrity check. Events are also written to the system log as JSON for forwarding to a SIEM.

### Backups

(Admins) Backups of FleetPilot's own data: users, hosts, controller settings, SMART history and the secret key.

- **Create backup now** makes one immediately; a daily backup runs automatically and the last 7 are kept.
- **Download** a backup to keep it elsewhere. It contains password hashes and encrypted credentials: store it safely.
- **Stage restore** uploads a backup. FleetPilot verifies its checksums and applies it at the next restart, keeping the previous files.

### Plugins

Extends FleetPilot. **Installed plugins** lists active plugins and the hook points they use; **Plugin Repository** lists available plugins; **Write Your Own Plugin** opens the developer documentation.

For security, the program folder is read-only for FleetPilot in a normal installation. To add a plugin, an administrator copies the plugin file into `/opt/fleetpilot/addons` on the server and restarts FleetPilot. Only install plugins you trust: a plugin runs with FleetPilot's rights.

---

## 8. Account

### My Profile

Your name, email address and password. A new password must have at least 12 characters.

### Sign-in & security

- **Active sessions**: every browser and device where you are signed in. **Sign out** ends one; **Sign out all other sessions** ends all but this one.
- **Recent sign-ins** with time, address and result.
- **API tokens** for scripts and integrations (see [Integrations](#9-integrations)).
- A link to set up two-factor sign-in if you have not yet.

### Two-factor sign-in

Protects your account even if your password is stolen. Choose one or more:

- **Authenticator app** (TOTP): scan the QR code with an app such as Aegis, Google Authenticator or 1Password, enter the code, **Verify & Enable**.
- **Security key or passkey** (WebAuthn): YubiKey, Windows Hello, Touch ID or a phone. **Register security key**, then touch the key.
- **Backup codes**: one-time codes for when you have no device. **Print** or save them somewhere safe; **Regenerate Codes** invalidates the old ones.

Administrators can require two-factor sign-in for all admins in the Security center.

### Accessibility

See [Accessibility](#accessibility) under Basics.

### User Management

(Admins) **Add User** with name, email, password and roles; edit a user to change roles or deactivate the account; **Delete** removes it. Give each person their own account: the audit trail then shows who did what. Keep at least two admin accounts, or know how to [reset a password](installation.md#4-first-sign-in) on the server.

---

## 9. Integrations

### API tokens and REST API

Create a token under **Account → Sign-in & security → API tokens**: give it a name, choose *read-only* or *read/write* and an expiry date. The token is shown once; FleetPilot stores only a hash. Use it as a bearer token:

```bash
curl -H "Authorization: Bearer fp_..." https://fleetpilot.example/api/me
```

Useful endpoints (all JSON): `/api/me`, `/api/hosts`, `/api/vms`, `/api/smart/summary`, `/api/smart/disks`, `/api/routers`, `/api/backup/servers`, `/api/hw/live`, `/api/fans/devices`, `/api/vulnerabilities`, `/api/monitor/latest`, `/api/registry/servers`. With a read/write token: `POST /api/hosts/<name>/wol` and `/shutdown` (operators), `/api/vms/<id>/action` (admins), `/api/fans/<id>/set_fan` (operators). Tokens only work for `/api/` addresses, never for the web pages; read-only tokens are refused for anything but reading.

### Android app (beta)

The FleetPilot app for Android 8.0 and newer shows the dashboard, servers, virtual machines, the HW monitor and fans, and can wake and shut down servers, start and stop VMs and set fan speeds. Download the APK from the [releases](https://github.com/ChristianHandy/FleetPilot/releases) (look for *Android app*) and install it; Android asks you to allow installing apps from your browser or file manager.

1. Create an API token as described above. A *read-only* token only shows; a *read/write* token also allows the actions your role permits (operators: wake, shut down, fans; admins: also VMs).
2. Open the app, enter your FleetPilot address (for example `https://192.168.1.62`) and the token.
3. FleetPilot uses its own certificate, which Android does not know. The app shows the certificate's SHA-256 fingerprint: compare it with the one your browser shows for FleetPilot, or with `sudo openssl x509 -in /etc/fleetpilot/tls/fullchain.pem -noout -fingerprint -sha256` on the server, then tap **Trust and sign in**. The app then accepts only this certificate.

The app needs FleetPilot 1.7.1 or newer. To sign out, tap the arrow at the top right; revoke the token in FleetPilot if the phone is lost.

### Prometheus

`/metrics` provides hosts, SMART health, temperatures and power-on hours, open alerts, disk tasks, router state and the FleetPilot machine's CPU and memory. Authenticate with the token from the CheckMK page:

```yaml
scrape_configs:
  - job_name: fleetpilot
    scheme: https
    authorization:
      credentials: "<token from the CheckMK page>"
    static_configs:
      - targets: ["fleetpilot.example"]
```

### Home Assistant

Read FleetPilot's data with Home Assistant's built-in RESTful sensor and a read-only API token:

```yaml
rest:
  - resource: https://fleetpilot.example/api/smart/summary
    headers:
      Authorization: !secret fleetpilot_token   # "Bearer fp_..."
    sensor:
      - name: FleetPilot open disk alerts
        value_template: "{{ value_json.active_alerts }}"
```

The repository also contains a separate custom integration, `integrations/home-assistant/custom_components/smart_monitor`, which reads SMART data from your machines directly over SSH.

### Public status page

`/status` shows published services and the managed hosts by name with their state, without signing in, for a wall display or for users. It shows no addresses or other details; if host names are confidential, do not expose this page.

---

## 10. Security notes

- Use HTTPS with a trusted certificate if FleetPilot is reachable by more people than you; see the [installation guide](installation.md#6-https-and-your-own-certificate).
- Turn on two-factor sign-in, at least for admins.
- Give people their own accounts with the smallest role they need.
- Do not expose FleetPilot directly to the internet. Use a VPN (WireGuard, Tailscale) or restrict *allowed networks* in the Security center.
- FleetPilot stores passwords for devices and APIs encrypted with the secret key in `.env`. Protect backups and the `.env` file like passwords.
- Regulated or air-gapped sites: see [High-security sites](installation.md#10-high-security-sites) and [SECURITY.md](../SECURITY.md).
- Report security problems privately as described in [SECURITY.md](../SECURITY.md).

---

## 11. Frequently asked questions

**Does FleetPilot need an agent on my servers?** No. It uses SSH and the systems' own APIs.

**Which user should FleetPilot use on my servers?** A dedicated user with your SSH key and sudo rights for the package manager and `smartctl` is the safest choice. `root` works too.

**A host shows offline but works.** FleetPilot checks the SSH port. Check the port in the host settings and any firewall between FleetPilot and the host.

**Can I manage Windows PCs?** Yes: enable the OpenSSH server on Windows, add the host with a Windows OS profile. Updates use `winget`; shutdown and Wake-on-LAN work.

**Can two FleetPilot instances back each other up?** Yes: data sync replicates all data from a primary to a secondary instance. Set the same `SYNC_TOKEN` on both.

**Where is my data?** In `/opt/fleetpilot/data` on the FleetPilot machine. Nothing is sent to anyone else; update checks contact GitHub, which `FLEETPILOT_OFFLINE=true` turns off.

**I forgot the admin password.** Run `sudo bash /opt/fleetpilot/reset-password.sh` on the FleetPilot machine.
