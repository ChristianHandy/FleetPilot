# Installing FleetPilot

This guide covers every way to install FleetPilot, what the installer sets up, the first sign-in, HTTPS, updates, backups, removal and troubleshooting.

*Deutsch: [de/installation.md](de/installation.md)*

**Contents**

1. [Choose a way to install](#1-choose-a-way-to-install)
2. [Proxmox VE: one command (recommended)](#2-proxmox-ve-one-command-recommended)
3. [Debian, Ubuntu or Raspberry Pi OS](#3-debian-ubuntu-or-raspberry-pi-os)
4. [First sign-in](#4-first-sign-in)
5. [Give FleetPilot access to your servers](#5-give-fleetpilot-access-to-your-servers)
6. [HTTPS and your own certificate](#6-https-and-your-own-certificate)
7. [Updating](#7-updating)
8. [Backup and restore](#8-backup-and-restore)
9. [Settings reference (`.env`)](#9-settings-reference-env)
10. [High-security sites](#10-high-security-sites)
11. [Uninstalling](#11-uninstalling)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Choose a way to install

| You have | Use | Time |
|---|---|---|
| A Proxmox VE server | The [Proxmox helper script](#2-proxmox-ve-one-command-recommended): it creates a container and installs FleetPilot in it | about 4 minutes |
| A Debian/Ubuntu server, VM or container | [`install.sh`](#3-debian-ubuntu-or-raspberry-pi-os) | about 3 minutes |
| A Raspberry Pi (3, 4 or 5) | [`install.sh`](#3-debian-ubuntu-or-raspberry-pi-os); it also installs the fan and USB tools | about 5 minutes |

**Requirements**

- Debian 12 or 13, Ubuntu 22.04 or 24.04, or Raspberry Pi OS (Bookworm or Trixie), 64-bit recommended.
- 1 CPU core, 1 GB RAM and 4 GB disk at minimum; 2 cores, 2 GB RAM and 8 GB disk are recommended (the Proxmox script uses these).
- Internet access during installation (GitHub and the Python package index).
- Root access.

FleetPilot manages other machines over SSH, so it does not need to run on the machines it manages.

---

## 2. Proxmox VE: one command (recommended)

Open the **Shell** of your Proxmox node (web UI → node → *Shell*) and run:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)"
```

The script asks one question:

- **Default settings**: next free container ID, 2 cores, 2 GB RAM, 8 GB disk, DHCP on `vmbr0`, HTTPS on. The storage is picked automatically.
- **Advanced**: choose the container ID, hostname, cores, RAM, disk, storage, bridge, VLAN, a static IP with gateway, an SSH key for the container's root user, and HTTPS or plain HTTP.

It then:

1. Downloads the newest Debian 13 container template (Debian 12 if 13 is not available).
2. Creates an **unprivileged** container with nesting enabled, starting at boot, tagged `fleetpilot`.
3. Installs FleetPilot inside it with `install.sh` (see the next section for what that does).
4. Writes the address and where to find the credentials into the container's **Notes** in the Proxmox UI, and prints a summary:

```text
 ✔ FleetPilot is ready in container 114.
  Open:       https://192.168.1.62
  User:       admin
  Password:   (shown once; also in /root/fleetpilot-credentials.txt inside the container)
```

The password is generated on first install. It is shown once and saved in `/root/fleetpilot-credentials.txt` inside the container (readable by root only). To read it later:

```bash
pct exec 114 -- cat /root/fleetpilot-credentials.txt
```

### Unattended install

All questions can be answered in advance with environment variables, for example:

```bash
CT_ID=150 CT_HOSTNAME=fleetpilot CT_RAM=4096 CT_IP=192.168.1.50/24 CT_GW=192.168.1.1 FP_DEFAULTS=1 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)"
```

| Variable | Default | Meaning |
|---|---|---|
| `CT_ID` | next free ID | Container ID |
| `CT_HOSTNAME` | `fleetpilot` | Hostname |
| `CT_CORES` / `CT_RAM` / `CT_DISK` | `2` / `2048` (MB) / `8` (GB) | Resources |
| `CT_STORAGE` | first storage for containers | Storage for the root disk, e.g. `local-lvm` |
| `CT_TEMPLATE_STORAGE` | first storage for templates | Where the Debian template is stored, e.g. `local` |
| `CT_BRIDGE` / `CT_VLAN` | `vmbr0` / none | Network bridge and optional VLAN tag |
| `CT_IP` / `CT_GW` | `dhcp` / none | `dhcp`, or an address like `192.168.1.50/24` with a gateway |
| `CT_SSH_KEY` | none | Public key file for the container's root user |
| `FP_HTTPS` | `yes` | `no` serves plain HTTP on port 5000 |
| `FP_BRANCH` | `main` | Git branch or tag to install |
| `FP_DEFAULTS` | unset | `1` skips all questions |

### Managing the Proxmox host itself

A container cannot see the host's disks. To get SMART data, updates and hardware information for the Proxmox node, add the node under **Manage Hosts** like any other server. The script prints FleetPilot's public SSH key and the exact command to authorise it on the host.

To show the node's virtual machines and containers, add it under **VM controllers** with an API token (see the [user guide](user-guide.md#vm-controllers)).

### Updating the container

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)" -- update 114
```

Replace `114` with your container ID. Data and settings are kept.

---

## 3. Debian, Ubuntu or Raspberry Pi OS

As root on the machine that will run FleetPilot:

```bash
curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/install.sh | bash
```

Or from a copy of the repository:

```bash
git clone https://github.com/ChristianHandy/FleetPilot.git
```

```bash
sudo bash FleetPilot/install.sh
```

The older `install-debian.sh` and `install_raspberry_pi.sh` still work; they run `install.sh`.

### What the installer does

| Step | Details |
|---|---|
| Packages | Python 3, venv, git, OpenSSH client, `smartmontools`, `sudo`; nginx and OpenSSL for HTTPS. On a Raspberry Pi also `lm-sensors`, `ipmitool` and the USB HID libraries |
| Service user | A system user `fleetpilot` with no password and no login shell |
| Code | `/opt/fleetpilot`, owned by root and **read-only for the service** |
| Data | `/opt/fleetpilot/data` (databases, settings, backups) and `/opt/fleetpilot/logs`, owned by `fleetpilot`, mode 0700/0750 |
| SSH key | A new Ed25519 key in `/opt/fleetpilot/.ssh/id_ed25519` that FleetPilot uses to reach your servers |
| Root helpers | Three small root-owned helpers in `/usr/local/lib/fleetpilot` (disk actions, FleetPilot update, proxy apply). One sudo rule allows exactly these with fixed arguments; nothing else |
| Settings | `/opt/fleetpilot/.env` (root:fleetpilot, 0640) with a random `SECRET_KEY`. Existing values are never overwritten |
| Service | `fleetpilot.service` (gunicorn), started at boot, with a systemd sandbox |
| HTTPS | nginx on port 443 with a self-signed certificate in `/etc/fleetpilot/tls`; FleetPilot itself listens on `127.0.0.1:5000` only |
| Check | Waits until `/healthz` answers, then prints the address and credentials and saves them to `/root/fleetpilot-credentials.txt` |

Running the installer again **updates** the installation and keeps your data and settings.

### Options

| Variable | Default | Meaning |
|---|---|---|
| `FP_NONINTERACTIVE` | `0` | `1` never asks questions |
| `FP_HTTPS` | `yes` | `no` serves `http://<ip>:5000` directly without nginx (only for trusted networks) |
| `FP_ADMIN_PASSWORD` | generated | Password of the first admin account (at least 12 characters) |
| `FP_EXTRAS` | `yes` on a Pi, `no` elsewhere | Fan, IPMI and USB-HID tools |
| `FP_BRANCH` | `main` | Branch or tag to install |
| `FP_REPO` | GitHub URL | Repository to install from (for forks or mirrors) |

Example:

```bash
curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/install.sh | FP_NONINTERACTIVE=1 FP_EXTRAS=yes bash
```

### Raspberry Pi extras

On a Raspberry Pi the installer can also set the Pi up as a **Proxmox QDevice** (a tie-breaker vote for a two-node cluster). Answer *yes* when asked, then run `pvecm qdevice setup <pi-ip>` on one Proxmox node.

### Ports

| Port | Listens on | Purpose |
|---|---|---|
| 443 | all addresses | FleetPilot over HTTPS (nginx) |
| 5000 | 127.0.0.1 | FleetPilot itself (gunicorn); not reachable from the network with HTTPS on |
| 8080 | 127.0.0.1 | Plain HTTP for a local HAProxy (Proxy services); not reachable from the network |

Port 80 stays free so the optional HAProxy ingress can use it. Open `https://<ip>` directly.

---

## 4. First sign-in

1. Open the address shown by the installer, for example `https://192.168.1.62`.
2. The browser warns about the self-signed certificate once. Accept it, or [install your own certificate](#6-https-and-your-own-certificate).
3. Sign in as `admin` with the generated password.
4. Recommended right away:
   - **Account → My Profile**: change the password.
   - **Account → Sign-in & security**: follow the link to set up two-factor sign-in with an authenticator app or a security key (YubiKey, passkey). Admins can be required to use 2FA under **System → Security center**.
   - **System → Security center**: read the checks; all should be green on a fresh install except the ones that depend on your choices (for example a trusted certificate).
   - **Account → Users**: create personal accounts for other people instead of sharing `admin`. Roles: *admin* (everything), *operator* (run actions), *viewer* (read only).

Lost the admin password? On the FleetPilot server or container:

```bash
sudo bash /opt/fleetpilot/reset-password.sh
```

Use `--generate` to create and print a random password, `--list` to list users, or pass another user name. Open sessions of that user are signed out.

---

## 5. Give FleetPilot access to your servers

FleetPilot reaches your servers over SSH with its own key. Show the public key with:

```bash
cat /opt/fleetpilot/.ssh/id_ed25519.pub
```

Then, for each server, either:

- **In the web UI**: *Manage Hosts → Add Host*, then *Install key* on the host (asks once for that server's password and stores nothing), or
- **By hand**: append the key to `~/.ssh/authorized_keys` of the user FleetPilot should use on that server.

For updates, disk tools and SMART, that user needs root rights or a sudo rule for the package manager and `smartctl`. Windows hosts need the OpenSSH server feature.

On first contact FleetPilot stores the server's host key (*trust on first use*) and refuses to connect if it changes later. Sites that must not trust on first use can enable [strict host keys](#10-high-security-sites).

---

## 6. HTTPS and your own certificate

The installer creates a self-signed certificate (ECDSA P-256, valid for 825 days) for the machine's hostname and IP address. HSTS stays off, because browsers cannot trust a self-signed certificate.

To use a certificate from your own CA or Let's Encrypt, replace the two files (certificate chain and private key, PEM format) and reload nginx:

```bash
sudo cp fullchain.pem /etc/fleetpilot/tls/fullchain.pem
```

```bash
sudo install -m 0600 privkey.pem /etc/fleetpilot/tls/privkey.pem
```

```bash
sudo nginx -t
```

```bash
sudo systemctl reload nginx
```

With a trusted certificate you can turn on HSTS: set `FLEETPILOT_HSTS=true` in `/opt/fleetpilot/.env` and restart FleetPilot (`sudo systemctl restart fleetpilot`). The complete hardened TLS configuration is in `deploy/nginx-fleetpilot-tls.conf`.

Behind your own reverse proxy (Traefik, Caddy, nginx Proxy Manager), keep `GUNICORN_BIND=127.0.0.1:5000` if the proxy runs on the same machine, set `FLEETPILOT_TRUST_PROXY=true`, and make sure the proxy sets `X-Forwarded-For` and `X-Forwarded-Proto`. Only enable `FLEETPILOT_TRUST_PROXY` when a proxy is really in front; otherwise clients could fake their address.

---

## 7. Updating

Any of these works; data and settings are always kept:

- **Web UI**: *System → FleetPilot update* (admins) checks for and applies new versions.
- **Installer**: run the same `install.sh` command again.
- **Proxmox**: run the helper script with `-- update <container ID>`.

Download a backup under *System → Backups* before a major update. After an update, reload the browser page once.

---

## 8. Backup and restore

*System → Backups* creates a consistent backup of users, hosts, controller settings, SMART history and the secret key. Automatic daily backups run at 03:00 and the last 7 are kept (`FLEETPILOT_AUTO_BACKUP`, `FLEETPILOT_BACKUP_HOUR`, `FLEETPILOT_BACKUP_KEEP`). Backups are stored in `/opt/fleetpilot/data/backups`.

- **Download** a backup to keep a copy elsewhere. It contains password hashes and encrypted credentials; store it safely.
- **Restore**: upload a backup and choose *Stage restore*. FleetPilot checks it and applies it at the next restart, keeping the previous files.

For a full-machine backup, back up `/opt/fleetpilot/data` and `/opt/fleetpilot/.env`, or the whole container with Proxmox Backup Server.

---

## 9. Settings reference (`.env`)

Settings live in `/opt/fleetpilot/.env`. Restart after a change: `sudo systemctl restart fleetpilot`.

| Setting | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | generated | Signs sessions and encrypts stored credentials. Never change it on a running installation: stored passwords could no longer be decrypted |
| `DASHBOARD_USERNAME` | `admin` | Name of the first admin account |
| `DASHBOARD_PASSWORD` | generated | First admin password; only read on first start and removed by the installer afterwards |
| `FLEETPILOT_DATA_DIR` | `/opt/fleetpilot/data` | Where all data is stored |
| `GUNICORN_BIND` | `127.0.0.1:5000` | Address and port of the app server |
| `GUNICORN_THREADS` | `4` | Request threads |
| `FLEETPILOT_PRODUCTION` | `true` with HTTPS | Production defaults (secure cookies, strict checks) |
| `FLEETPILOT_COOKIE_SECURE` | `true` with HTTPS | Send cookies over HTTPS only |
| `FLEETPILOT_TRUST_PROXY` | `true` with HTTPS | Trust `X-Forwarded-*` headers from the local proxy |
| `FLEETPILOT_HSTS` | `false` | Send HSTS; only with a trusted certificate |
| `FLEETPILOT_SESSION_MINUTES` | `480` | Session lifetime (15–1440) |
| `FLEETPILOT_AUTO_BACKUP` / `_BACKUP_HOUR` / `_BACKUP_KEEP` | `true` / `3` / `7` | Daily data backups |
| `FLEETPILOT_ROUTER_POLL_MINUTES` | `5` | How often routers are checked; `0` turns it off |
| `FLEETPILOT_VERIFY_SSL` | `false` | Verify TLS certificates of VM, storage and backup APIs. Turn on when they have trusted certificates |
| `FLEETPILOT_WEBAUTHN_RP_ID` / `_ORIGIN` | from the address | Domain and origin for security keys when FleetPilot runs behind another name |
| `FLEETPILOT_FIPS` | off | See [High-security sites](#10-high-security-sites) |
| `FLEETPILOT_SSH_STRICT_HOST_KEYS` | off | See [High-security sites](#10-high-security-sites) |
| `FLEETPILOT_OFFLINE` | off | See [High-security sites](#10-high-security-sites) |
| `SYNC_TOKEN` | none | Shared secret when two FleetPilot instances replicate data |
| `YUBICO_CLIENT_ID` / `YUBICO_SECRET_KEY` | none | Only for legacy YubiKey OTP |

---

## 10. High-security sites

For regulated or air-gapped environments, add to `.env`:

```ini
FLEETPILOT_FIPS=true
FLEETPILOT_SSH_STRICT_HOST_KEYS=true
FLEETPILOT_OFFLINE=true
```

- **FIPS**: passwords are stored with PBKDF2-HMAC-SHA256 only; existing hashes are upgraded at the next sign-in.
- **Strict host keys**: FleetPilot connects only to servers whose host key is already in `/opt/fleetpilot/data/known_hosts`.
- **Offline**: no update checks and no online plugin catalogue.

For an even tighter systemd sandbox, install the strict profile:

```bash
sudo install -D -m 0644 /opt/fleetpilot/deploy/fleetpilot-strict.conf /etc/systemd/system/fleetpilot.service.d/strict.conf
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl restart fleetpilot
```

The strict profile blocks local disk tools and fan control on the FleetPilot machine itself; managing other machines over SSH is unaffected. Details are in [SECURITY.md](../SECURITY.md) and [production_profile.md](production_profile.md).

---

## 11. Uninstalling

**Proxmox container**: stop and remove the container in the Proxmox UI, or:

```bash
pct stop 114
```

```bash
pct destroy 114
```

**Debian/Ubuntu/Raspberry Pi**: make a backup first if you want to keep your data, then:

```bash
sudo systemctl disable --now fleetpilot
```

```bash
sudo rm -rf /opt/fleetpilot /etc/fleetpilot /usr/local/lib/fleetpilot /etc/sudoers.d/fleetpilot /etc/systemd/system/fleetpilot.service /etc/systemd/system/fleetpilot.service.d /etc/nginx/sites-enabled/fleetpilot* /etc/nginx/sites-available/fleetpilot* /root/fleetpilot-credentials.txt
```

```bash
sudo userdel fleetpilot
```

```bash
sudo systemctl reload nginx
```

Remove FleetPilot's public key from the `authorized_keys` files of your servers.

---

## 12. Troubleshooting

| Problem | What to do |
|---|---|
| The page does not load | `systemctl status fleetpilot nginx`, then `journalctl -u fleetpilot -n 50` |
| `http://<ip>` does not answer | Use `https://<ip>`. Port 80 is left free for HAProxy |
| "Security token expired or missing" | The page was open too long, or cookies are blocked. Reload the page and try again. Behind your own proxy, check that it passes `X-Forwarded-Proto: https` |
| Locked out after failed sign-ins | Wait for the lockout to end (10 minutes by default, set in *Security center → Sign-in rules*) or reset the password with `reset-password.sh` |
| A server shows offline | FleetPilot checks the SSH port. Check the address, port and firewall; test with `sudo -u fleetpilot ssh -i /opt/fleetpilot/.ssh/id_ed25519 user@server` |
| "Host key changed" | The server was reinstalled or its address now belongs to another machine. If expected, remove its line from `/opt/fleetpilot/data/known_hosts` |
| Installer stops in a Proxmox container | Run the Proxmox update command again; the installer resumes. The full log is in the container: `journalctl -u fleetpilot` |
| Service does not start inside an older LXC | The installer adds a compatible sandbox drop-in automatically (`/etc/systemd/system/fleetpilot.service.d/lxc.conf`) |
| Plugin install says the folder is read-only | That is intended. Copy the plugin file into `/opt/fleetpilot/addons` as root and restart FleetPilot |

Still stuck? Open an issue with the output of `journalctl -u fleetpilot -n 100` (remove addresses and names you consider private): <https://github.com/ChristianHandy/FleetPilot/issues>
