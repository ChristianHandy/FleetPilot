# Routers

**Servers → Routers** shows the routers in your network: whether they are online,
model and firmware, uptime, load, memory, interfaces and the devices that got an
address from them (DHCP). Operators can check for updates and take configuration
backups. Administrators add routers, download backups and restart routers.

| System | Connection | Status | Devices | Update check | Backup | Restart |
|---|---|---|---|---|---|---|
| OpenWrt (also GL.iNet, Turris OS) | SSH | ✓ | ✓ | ✓ (opkg / apk) | ✓ sysupgrade archive | ✓ |
| OPNsense | REST API | ✓ | ✓ | ✓ | ✓ config.xml | ✓ |
| pfSense CE / Plus | SSH | ✓ | ✓ | ✓ | ✓ config.xml | ✓ |
| VyOS | SSH | ✓ | ✓ | – | ✓ config.boot | ✓ |
| DD-WRT, FreshTomato | SSH | ✓ | ✓ | – | ✓ nvram | ✓ |
| MikroTik RouterOS | SSH | ✓ | ✓ | ✓ | ✓ /export | ✓ |
| IPFire, other Linux routers | SSH | ✓ | ✓ | – | – | ✓ |

FleetPilot **only checks** for router updates and never installs them. A router
upgrade that fails can take the whole network down, so it stays a step you do in
the router's own interface, where you can watch it.

## Security

- Every command FleetPilot sends to a router is fixed in `router_manager.py`.
  Nothing typed into FleetPilot ends up in a command line on the router.
- SSH connections check the router's host key (trust on first use, or strict
  mode with `FLEETPILOT_SSH_STRICT_HOST_KEYS=true`).
- Passwords, API secrets and **backups are stored encrypted**. Backups contain
  Wi-Fi keys, PPPoE and VPN credentials: downloading one needs the admin role and
  a recent password confirmation, and every download is in the audit trail.
- The newest 10 backups per router are kept.

## Setting up each system

Use an SSH key instead of a password where you can: leave the password empty and
FleetPilot signs in with its own key, the same one *Manage Hosts → Install key* uses (`~/.ssh/id_rsa.pub` of the `fleetpilot` user).

### OpenWrt
1. *System → Administration → SSH-Keys*: paste FleetPilot's public key.
2. Add the router with user `root`, port 22.
FleetPilot uses `ubus` for status, `/tmp/dhcp.leases` for devices, `opkg` or
`apk` (OpenWrt 25+) for the update check, and `sysupgrade -b` for backups.
Restore a backup under *System → Backup / Flash Firmware*.

### OPNsense
1. *System → Access → Users*: create a user `fleetpilot` with the privileges
   *Diagnostics: System Activity / Interface*, *Status: DHCP leases*,
   *System: Firmware*, *Diagnostics: Configuration History* (backups) and, if you
   want restarts from FleetPilot, *Diagnostics: Halt/Reboot*.
2. Create an API key for that user and enter key and secret in FleetPilot.
3. Keep "Check the router's HTTPS certificate" on and give OPNsense a certificate
   from your CA. Turn it off only for the self-signed first-boot certificate.

### pfSense
1. *System → Advanced → Admin Access*: enable Secure Shell, key-only login.
2. *System → User Manager*: add FleetPilot's key to the `admin` user.
Status comes from `sysctl`/`ifconfig`, devices from the ISC or Kea lease file,
the update check from `pfSense-upgrade -c`, backups from `/cf/conf/config.xml`.

### VyOS
`set system login user vyos authentication public-keys fleetpilot key '<key>'`
and `type ssh-ed25519`, then `commit; save`. Restarts need `sudo` (the default
`vyos` user has it).

### DD-WRT / FreshTomato
*Services → Secure Shell*: enable SSHd and paste the key into *Authorized Keys*.
The backup is the text output of `nvram show`, useful for comparing settings;
restore it by re-entering settings, not by loading it as a binary.

### MikroTik RouterOS
Create a group with `ssh,read,test` (add `reboot` and `write` only if you want
restarts and update checks), a user `fleetpilot` in that group, and import the
key with `/user ssh-keys import`. RouterOS 7 leaves passwords out of `/export`.

### IPFire and other Linux routers
Add FleetPilot's key to `/root/.ssh/authorized_keys`. Status uses `/proc`,
`ip -j addr` and the usual dnsmasq, ISC or Kea lease files.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `FLEETPILOT_ROUTER_POLL_MINUTES` | `5` | How often all routers are checked in the background; `0` turns it off |

Routers that go offline or come back, and newly found updates, are sent to
notification channels that subscribe to *Routers* (System → Notifications).
Prometheus gets `fleetpilot_router_up`, `fleetpilot_router_uptime_seconds`,
`fleetpilot_router_dhcp_clients` and `fleetpilot_router_updates_available`.
`GET /api/routers` returns the inventory (works with read-only API tokens).
