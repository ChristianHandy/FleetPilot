"""
router_manager.py — routers and open-source router operating systems.

Supported platforms
  openwrt   OpenWrt and derivatives (GL.iNet, Turris OS)        SSH, ubus
  opnsense  OPNsense                                            REST API (key + secret)
  pfsense   pfSense CE / Plus                                   SSH
  vyos      VyOS                                                SSH
  ddwrt     DD-WRT, FreshTomato                                 SSH (BusyBox, nvram)
  routeros  MikroTik RouterOS                                   SSH (RouterOS CLI)
  linux     IPFire and other Linux-based routers                SSH

What FleetPilot reads: model, firmware, uptime, load, memory, interfaces and
DHCP clients. Operators can check for updates, take configuration backups and
(admins) reboot. Updates are only checked, never installed: a failed router
upgrade can take the whole network down, so it stays a deliberate manual step.

Security
  * Every command sent to a router is a constant in this file; nothing from a
    request or from the router's database row is put into a command line.
  * SSH goes through ssh_helper (host keys verified, strict mode supported).
  * Passwords, API secrets and configuration backups (which contain Wi-Fi keys,
    PPPoE passwords and VPN keys) are encrypted with SecretBox.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import safe_errors
import secret_box

logger = logging.getLogger(__name__)
_box = secret_box.SecretBox("sha256")

PLATFORMS: Dict[str, Dict[str, Any]] = {
    "openwrt":  {"label": "OpenWrt", "transport": "ssh", "port": 22, "user": "root",
                 "backup_ext": "tar.gz", "updates": True},
    "opnsense": {"label": "OPNsense", "transport": "api", "port": 443, "user": "",
                 "backup_ext": "xml", "updates": True},
    "pfsense":  {"label": "pfSense", "transport": "ssh", "port": 22, "user": "admin",
                 "backup_ext": "xml", "updates": True},
    "vyos":     {"label": "VyOS", "transport": "ssh", "port": 22, "user": "vyos",
                 "backup_ext": "boot", "updates": False},
    "ddwrt":    {"label": "DD-WRT / FreshTomato", "transport": "ssh", "port": 22, "user": "root",
                 "backup_ext": "nvram.txt", "updates": False},
    "routeros": {"label": "MikroTik RouterOS", "transport": "ssh", "port": 22, "user": "admin",
                 "backup_ext": "rsc", "updates": True},
    "linux":    {"label": "IPFire / Linux router", "transport": "ssh", "port": 22, "user": "root",
                 "backup_ext": "", "updates": False},
}

MAX_TEXT = 2 * 1024 * 1024        # largest command output read from a router
MAX_BACKUP = 20 * 1024 * 1024     # largest backup accepted
KEEP_BACKUPS = 10                 # per router
_HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_BACKUP_RE = re.compile(r"^r(\d+)-(\d{8}-\d{6})\.([a-z0-9.]+)\.enc$")

_DATA_DIR: Optional[str] = None
_lock = threading.Lock()


# ── Storage ──────────────────────────────────────────────────────────────────

def _data_dir() -> str:
    return _DATA_DIR or os.environ.get("FLEETPILOT_DATA_DIR",
                                       os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(os.path.join(_data_dir(), "router_manager.db"), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _backup_dir() -> str:
    path = os.path.join(_data_dir(), "router_backups")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def init_db(data_dir: Optional[str] = None) -> None:
    global _DATA_DIR
    if data_dir:
        _DATA_DIR = str(data_dir)
    with _db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS routers (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL UNIQUE,
            platform     TEXT NOT NULL,
            host         TEXT NOT NULL,
            port         INTEGER NOT NULL,
            username     TEXT NOT NULL DEFAULT '',
            password     TEXT NOT NULL DEFAULT '',
            api_key      TEXT NOT NULL DEFAULT '',
            api_secret   TEXT NOT NULL DEFAULT '',
            verify_tls   INTEGER NOT NULL DEFAULT 1,
            notes        TEXT NOT NULL DEFAULT '',
            status_json  TEXT NOT NULL DEFAULT '{}',
            online       INTEGER,
            last_poll    REAL,
            created_at   REAL NOT NULL
        );
        """)


def validate(fields: Dict[str, Any], existing: Optional[Dict] = None) -> Dict[str, Any]:
    """Clean and check user input for a router. Raises ValueError with a readable message."""
    platform = str(fields.get("platform") or (existing or {}).get("platform") or "")
    if platform not in PLATFORMS:
        raise ValueError("Choose a router platform.")
    spec = PLATFORMS[platform]
    name = str(fields.get("name", "")).strip()
    if not name or len(name) > 64:
        raise ValueError("The name must be 1 to 64 characters.")
    host = str(fields.get("host", "")).strip()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not _HOST_RE.match(host):
            raise ValueError("Enter an IP address or host name for the router.") from None
    try:
        port = int(fields.get("port") or spec["port"])
    except (TypeError, ValueError):
        raise ValueError("The port must be a number.") from None
    if not 1 <= port <= 65535:
        raise ValueError("The port must be between 1 and 65535.")
    username = str(fields.get("username") or spec["user"]).strip()
    if spec["transport"] == "ssh" and not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", username):
        raise ValueError("The SSH user name may only contain letters, digits, dot, dash and underscore.")
    clean = {"name": name, "platform": platform, "host": host, "port": port, "username": username,
             "verify_tls": 1 if fields.get("verify_tls") in (True, 1, "1", "on", "true") else 0,
             "notes": str(fields.get("notes", "")).strip()[:500]}
    if spec["transport"] == "api":
        key = str(fields.get("api_key", "")).strip()
        secret = str(fields.get("api_secret", "")).strip()
        if not existing and not (key and secret):
            raise ValueError("OPNsense needs an API key and secret (System → Access → Users → API keys).")
        if key:
            clean["api_key"] = key[:200]
        if secret:
            clean["api_secret"] = secret[:200]
    password = str(fields.get("password", ""))
    if password:
        clean["password"] = password[:200]
    return clean


def add_router(fields: Dict[str, Any]) -> int:
    clean = validate(fields)
    for secret in ("password", "api_key", "api_secret"):
        if secret in clean:
            clean[secret] = _box.encrypt(clean[secret])
    clean["created_at"] = time.time()
    cols = ", ".join(clean)
    with _db() as db:
        try:
            cur = db.execute(f"INSERT INTO routers ({cols}) VALUES ({', '.join('?' for _ in clean)})",  # nosec B608 - column names come from validate()
                             list(clean.values()))
        except sqlite3.IntegrityError:
            raise ValueError("A router with this name already exists.") from None
        return cur.lastrowid


def update_router(router_id: int, fields: Dict[str, Any]) -> None:
    existing = get_router(router_id, secrets=False)
    if not existing:
        raise ValueError("Router not found.")
    clean = validate(dict(fields, platform=existing["platform"]), existing)
    for secret in ("password", "api_key", "api_secret"):
        if secret in clean:
            clean[secret] = _box.encrypt(clean[secret])
    # Column names come from validate() only.
    sets = ", ".join(f"{k} = ?" for k in clean)
    with _db() as db:
        try:
            db.execute(f"UPDATE routers SET {sets} WHERE id = ?", list(clean.values()) + [router_id])  # nosec B608 - column names come from validate()
        except sqlite3.IntegrityError:
            raise ValueError("A router with this name already exists.") from None


def delete_router(router_id: int) -> None:
    with _db() as db:
        db.execute("DELETE FROM routers WHERE id = ?", (router_id,))
    for item in list_backups(router_id):
        try:
            os.remove(item["path"])
        except OSError:
            pass


def _row(row: sqlite3.Row, secrets: bool) -> Dict[str, Any]:
    data = dict(row)
    try:
        data["status"] = json.loads(data.pop("status_json") or "{}")
    except ValueError:
        data["status"] = {}
    data["platform_label"] = PLATFORMS.get(data["platform"], {}).get("label", data["platform"])
    data["has_password"] = bool(data["password"])
    data["has_api_key"] = bool(data["api_key"])
    for secret in ("password", "api_key", "api_secret"):
        data[secret] = _box.decrypt(data[secret]) if (secrets and data[secret]) else ""
    return data


def get_router(router_id: int, secrets: bool = False) -> Optional[Dict[str, Any]]:
    with _db() as db:
        row = db.execute("SELECT * FROM routers WHERE id = ?", (router_id,)).fetchone()
    return _row(row, secrets) if row else None


def list_routers() -> List[Dict[str, Any]]:
    with _db() as db:
        return [_row(r, False) for r in db.execute("SELECT * FROM routers ORDER BY name COLLATE NOCASE")]


def _save_status(router_id: int, status: Dict[str, Any]) -> None:
    with _db() as db:
        db.execute("UPDATE routers SET status_json = ?, online = ?, last_poll = ? WHERE id = ?",
                   (json.dumps(status), 1 if status.get("online") else 0, time.time(), router_id))


# ── Parsers (pure functions, unit-tested with sample output) ─────────────────

def split_sections(text: str) -> Dict[str, str]:
    """Split output that marks parts with lines like '@@fp:name'."""
    sections: Dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("@@fp:"):
            current = line[5:].strip()
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"
    return sections


def _json(text: str) -> Any:
    try:
        return json.loads(text) if text and text.strip() else None
    except ValueError:
        return None


def parse_meminfo(text: str) -> Dict[str, int]:
    values = {}
    for line in text.splitlines():
        m = re.match(r"(\w+):\s+(\d+)\s*kB", line)
        if m:
            values[m.group(1)] = int(m.group(2)) * 1024
    total = values.get("MemTotal")
    available = values.get("MemAvailable", values.get("MemFree", 0) + values.get("Cached", 0) + values.get("Buffers", 0))
    return {"mem_total": total, "mem_used": total - available} if total else {}


def parse_uptime(text: str) -> Optional[int]:
    m = re.match(r"\s*(\d+)", text or "")
    return int(m.group(1)) if m else None


def parse_loadavg(text: str) -> List[float]:
    try:
        return [float(x) for x in (text or "").split()[:3]]
    except ValueError:
        return []


def parse_dnsmasq_leases(text: str) -> List[Dict[str, Any]]:
    """dnsmasq: '<expiry> <mac> <ip> <hostname> <client-id>' (OpenWrt, DD-WRT, many Linux routers)."""
    clients = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and re.fullmatch(r"[0-9a-fA-F:]{11,17}", parts[1]):
            clients.append({"mac": parts[1].lower(), "ip": parts[2],
                            "hostname": "" if parts[3] == "*" else parts[3],
                            "expires": int(parts[0]) if parts[0].isdigit() and parts[0] != "0" else None})
    return clients


def parse_isc_leases(text: str) -> List[Dict[str, Any]]:
    """ISC dhcpd.leases (pfSense, IPFire, older VyOS); the newest entry per IP wins."""
    clients: Dict[str, Dict[str, Any]] = {}
    for m in re.finditer(r"lease\s+([\d.]+)\s*\{(.*?)\}", text or "", re.S):
        body = m.group(2)
        state = re.search(r"binding state (\w+);", body)
        if state and state.group(1) != "active":
            clients.pop(m.group(1), None)
            continue
        mac = re.search(r"hardware ethernet ([0-9a-fA-F:]+);", body)
        host = re.search(r'client-hostname "([^"]*)";', body)
        ends = re.search(r"ends \d (\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2});", body)
        clients[m.group(1)] = {"ip": m.group(1), "mac": mac.group(1).lower() if mac else "",
                               "hostname": host.group(1) if host else "",
                               "expires": int(datetime.strptime(ends.group(1), "%Y/%m/%d %H:%M:%S").timestamp())
                               if ends else None}
    return list(clients.values())


def parse_kea_csv(text: str) -> List[Dict[str, Any]]:
    """Kea memfile leases (pfSense with Kea, VyOS 1.4+, OPNsense)."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    if not lines or not lines[0].startswith("address,"):
        return []
    header = lines[0].split(",")
    clients: Dict[str, Dict[str, Any]] = {}
    for line in lines[1:]:
        row = dict(zip(header, line.split(",")))
        if row.get("state", "0") != "0":
            continue
        expire = row.get("expire", "")
        clients[row.get("address", "")] = {"ip": row.get("address", ""), "mac": row.get("hwaddr", "").lower(),
                                           "hostname": row.get("hostname", "").rstrip("."),
                                           "expires": int(expire) if expire.isdigit() else None}
    return [c for c in clients.values() if c["ip"]]


def parse_ip_json(text: str) -> List[Dict[str, Any]]:
    """`ip -j addr` (iproute2)."""
    data = _json(text) or []
    out = []
    for link in data if isinstance(data, list) else []:
        name = link.get("ifname", "")
        if not name or name == "lo":
            continue
        out.append({"name": name, "up": "UP" in (link.get("flags") or []) and link.get("operstate") != "DOWN",
                    "mac": link.get("address", ""),
                    "ipv4": [f'{a["local"]}/{a.get("prefixlen", "")}' for a in link.get("addr_info", [])
                             if a.get("family") == "inet"]})
    return out


def parse_linux_ifconfig(text: str) -> List[Dict[str, Any]]:
    """BusyBox / net-tools ifconfig (DD-WRT, FreshTomato)."""
    out = []
    for block in re.split(r"\n(?=\S)", text or ""):
        m = re.match(r"(\S+)\s", block)
        if not m or m.group(1) == "lo":
            continue
        mac = re.search(r"HWaddr ([0-9A-Fa-f:]{17})", block)
        ip = re.search(r"inet addr:([\d.]+).*?Mask:([\d.]+)", block, re.S)
        ipv4 = []
        if ip:
            prefix = ipaddress.IPv4Network(f"0.0.0.0/{ip.group(2)}").prefixlen
            ipv4.append(f"{ip.group(1)}/{prefix}")
        out.append({"name": m.group(1), "up": bool(re.search(r"\bUP\b", block)),
                    "mac": mac.group(1).lower() if mac else "", "ipv4": ipv4})
    return out


def parse_bsd_ifconfig(text: str) -> List[Dict[str, Any]]:
    """FreeBSD ifconfig (pfSense)."""
    out = []
    for block in re.split(r"\n(?=\S)", text or ""):
        m = re.match(r"([A-Za-z0-9_.]+): flags=\w+<([^>]*)>", block)
        if not m or m.group(1).startswith(("lo", "pflog", "pfsync", "enc", "gif", "gre")):
            continue
        ipv4 = []
        for ip in re.finditer(r"inet ([\d.]+) netmask 0x([0-9a-f]{8})", block):
            ipv4.append(f"{ip.group(1)}/{bin(int(ip.group(2), 16)).count('1')}")
        mac = re.search(r"ether ([0-9a-f:]{17})", block)
        status = re.search(r"status: (\w+)", block)
        out.append({"name": m.group(1), "mac": mac.group(1) if mac else "", "ipv4": ipv4,
                    "up": "UP" in m.group(2).split(",") and (not status or status.group(1) == "active")})
    return out


def parse_openwrt_interfaces(text: str) -> List[Dict[str, Any]]:
    data = _json(text) or {}
    out = []
    for iface in data.get("interface", []) if isinstance(data, dict) else []:
        if iface.get("interface") == "loopback":
            continue
        out.append({"name": iface.get("interface", ""), "device": iface.get("l3_device") or iface.get("device", ""),
                    "up": bool(iface.get("up")), "proto": iface.get("proto", ""), "mac": "",
                    "ipv4": [f'{a.get("address")}/{a.get("mask")}' for a in iface.get("ipv4-address", [])]})
    return out


def parse_opkg_upgradable(text: str) -> List[str]:
    """opkg: 'name - old - new'; apk: 'name-new arch {origin} (lic) [upgradable from: name-old]'."""
    items = []
    for line in (text or "").splitlines():
        line = line.strip()
        if re.match(r"^\S+ - \S+ - \S+$", line):
            name, old, new = line.split(" - ")
            items.append(f"{name}: {old} → {new}")
        else:
            m = re.match(r"^(\S+)\s.*\[upgradable from: (\S+)\]", line)
            if m:
                items.append(f"{m.group(2)} → {m.group(1)}")
    return items


def parse_routeros_kv(text: str) -> Dict[str, str]:
    """RouterOS 'print' output: lines of 'key: value'."""
    values = {}
    for line in (text or "").replace("\r", "").splitlines():
        m = re.match(r"\s*([a-z0-9-]+):\s(.*)$", line)
        if m:
            values[m.group(1)] = m.group(2).strip()
    return values


def parse_routeros_terse(text: str) -> List[Dict[str, str]]:
    """RouterOS 'print terse': ' 0 R name=ether1 type=ether ...' per line."""
    rows = []
    for line in (text or "").replace("\r", "").splitlines():
        m = re.match(r"\s*\d+\s+([A-Z ]*?)\s*((?:[a-z0-9.-]+=\S*\s*)+)$", line)
        if m:
            row = dict(re.findall(r"([a-z0-9.-]+)=(\S*)", m.group(2)))
            row["_flags"] = m.group(1).strip()
            rows.append(row)
    return rows


def parse_routeros_uptime(text: str) -> Optional[int]:
    """RouterOS durations such as '2w3d04:05:06' or '3d2h1m5s'."""
    if not text:
        return None
    total = 0
    for value, unit in re.findall(r"(\d+)([wdhms])", text):
        total += int(value) * {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    clock = re.search(r"(\d+):(\d+):(\d+)$", text)
    if clock:
        total += int(clock.group(1)) * 3600 + int(clock.group(2)) * 60 + int(clock.group(3))
    return total or None


def parse_routeros_size(text: str) -> Optional[int]:
    m = re.match(r"([\d.]+)\s*(KiB|MiB|GiB|B)?", text or "")
    if not m:
        return None
    return int(float(m.group(1)) * {"KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}.get(m.group(2) or "B", 1))


# ── Drivers ──────────────────────────────────────────────────────────────────

class _SshDriver:
    def __init__(self, router: Dict[str, Any]):
        self.router = router
        self.client = None

    def __enter__(self):
        import ssh_helper
        r = self.router
        self.client = ssh_helper.create_client(
            r["host"], port=int(r["port"]), username=r["username"],
            password=r.get("password") or None,
            look_for_keys=not r.get("password"), timeout=10)
        return self

    def __exit__(self, *exc):
        try:
            self.client.close()
        except Exception:
            pass

    def run(self, command: str, timeout: int = 30, stdin: Optional[bytes] = None) -> bytes:
        chan_in, out, _err = self.client.exec_command(command, timeout=timeout)
        if stdin:
            chan_in.write(stdin)
            chan_in.channel.shutdown_write()
        data = out.read(MAX_BACKUP + 1)
        return data[:MAX_BACKUP + 1]

    def text(self, command: str, timeout: int = 30) -> str:
        return self.run(command, timeout).decode("utf-8", errors="replace")[:MAX_TEXT]


# Shell scripts are constants. Section markers let one SSH call collect everything.
_OPENWRT_STATUS = (
    "echo @@fp:board; ubus call system board 2>/dev/null; "
    "echo @@fp:info; ubus call system info 2>/dev/null; "
    "echo @@fp:ifaces; ubus call network.interface dump 2>/dev/null; "
    "echo @@fp:leases; cat /tmp/dhcp.leases 2>/dev/null; "
    "echo @@fp:load; cat /proc/loadavg"
)
_OPENWRT_UPDATES = (
    "if command -v apk >/dev/null 2>&1; then apk update >/dev/null 2>&1; apk list --upgradable 2>/dev/null; "
    "else opkg update >/dev/null 2>&1; opkg list-upgradable 2>/dev/null; fi"
)
_OPENWRT_BACKUP = 'f=$(mktemp) && sysupgrade -b "$f" >/dev/null 2>&1 && cat "$f"; rm -f "$f"'

_LINUX_STATUS = (
    "echo @@fp:os; cat /etc/os-release 2>/dev/null; cat /etc/system-release 2>/dev/null; "
    "echo @@fp:vyos; cat /usr/share/vyos/version.json 2>/dev/null; "
    "echo @@fp:hostname; hostname; "
    "echo @@fp:uptime; cat /proc/uptime; "
    "echo @@fp:load; cat /proc/loadavg; "
    "echo @@fp:mem; cat /proc/meminfo; "
    "echo @@fp:ip; ip -j addr 2>/dev/null; "
    "echo @@fp:dnsmasq; cat /var/lib/misc/dnsmasq.leases /tmp/dhcp.leases 2>/dev/null; "
    "echo @@fp:isc; cat /var/state/dhcp/dhcpd.leases /config/dhcpd.leases /var/lib/dhcp/dhcpd.leases 2>/dev/null; "
    "echo @@fp:kea; cat /config/dhcp/dhcp4-leases.csv /var/lib/kea/kea-leases4.csv 2>/dev/null"
)
_DDWRT_STATUS = (
    "echo @@fp:model; nvram get DD_BOARD 2>/dev/null || nvram get t_model_name 2>/dev/null; "
    "echo @@fp:firmware; nvram get os_version 2>/dev/null; "
    "echo @@fp:hostname; nvram get router_name 2>/dev/null || hostname; "
    "echo @@fp:uptime; cat /proc/uptime; "
    "echo @@fp:load; cat /proc/loadavg; "
    "echo @@fp:mem; cat /proc/meminfo; "
    "echo @@fp:ifconfig; ifconfig 2>/dev/null; "
    "echo @@fp:leases; cat /tmp/dnsmasq.leases /tmp/var/lib/misc/dnsmasq.leases 2>/dev/null"
)
_PFSENSE_STATUS = (
    "echo @@fp:version; cat /etc/version 2>/dev/null; "
    "echo @@fp:uname; uname -mrs; "
    "echo @@fp:hostname; hostname; "
    "echo @@fp:boottime; sysctl -n kern.boottime; "
    "echo @@fp:now; date +%s; "
    "echo @@fp:load; sysctl -n vm.loadavg; "
    "echo @@fp:physmem; sysctl -n hw.physmem; "
    "echo @@fp:freemem; sysctl -n vm.stats.vm.v_free_count vm.stats.vm.v_inactive_count hw.pagesize; "
    "echo @@fp:model; sysctl -n hw.model; "
    "echo @@fp:ifconfig; ifconfig -a; "
    "echo @@fp:isc; cat /var/dhcpd/var/db/dhcpd.leases 2>/dev/null; "
    "echo @@fp:kea; cat /var/lib/kea/dhcp4.leases 2>/dev/null"
)


class OpenWrtDriver(_SshDriver):
    def status(self) -> Dict[str, Any]:
        s = split_sections(self.text(_OPENWRT_STATUS))
        board = _json(s.get("board", "")) or {}
        info = _json(s.get("info", "")) or {}
        release = board.get("release", {})
        mem = info.get("memory", {})
        total = mem.get("total")
        used = total - mem.get("available", mem.get("free", 0) + mem.get("buffered", 0)) if total else None
        return {"model": board.get("model", ""), "hostname": board.get("hostname", ""),
                "firmware": " ".join(x for x in (release.get("distribution"), release.get("version"),
                                                 release.get("revision")) if x),
                "uptime": info.get("uptime"), "load": parse_loadavg(s.get("load", "")),
                "mem_total": total, "mem_used": used,
                "interfaces": parse_openwrt_interfaces(s.get("ifaces", "")),
                "clients": parse_dnsmasq_leases(s.get("leases", ""))}

    def updates(self) -> Dict[str, Any]:
        items = parse_opkg_upgradable(self.text(_OPENWRT_UPDATES, timeout=120))
        return {"count": len(items), "items": items,
                "note": "Install updates with the OpenWrt firmware selector or attended sysupgrade; "
                        "upgrading single packages is not recommended on OpenWrt."}

    def backup(self) -> bytes:
        return self.run(_OPENWRT_BACKUP, timeout=120)

    def reboot(self) -> None:
        self.run("reboot", timeout=10)


class LinuxDriver(_SshDriver):
    def status(self) -> Dict[str, Any]:
        s = split_sections(self.text(_LINUX_STATUS))
        os_release = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', s.get("os", ""), re.M))
        vyos = _json(s.get("vyos", "")) or {}
        os_lines = [l for l in s.get("os", "").splitlines() if l.strip() and "=" not in l]
        if vyos.get("version"):
            firmware = f'VyOS {vyos["version"]}'
        else:  # /etc/system-release (IPFire: "IPFire 2.29 (x86_64) - core188") beats os-release
            firmware = (os_lines[-1].strip() if os_lines else "") or os_release.get("PRETTY_NAME", "")
        clients = (parse_kea_csv(s.get("kea", "")) or parse_isc_leases(s.get("isc", "")) or
                   parse_dnsmasq_leases(s.get("dnsmasq", "")))
        return dict({"model": vyos.get("hardware_model", ""), "hostname": s.get("hostname", "").strip(),
                     "firmware": firmware, "uptime": parse_uptime(s.get("uptime", "")),
                     "load": parse_loadavg(s.get("load", "")), "interfaces": parse_ip_json(s.get("ip", "")),
                     "clients": clients}, **parse_meminfo(s.get("mem", "")))

    def reboot(self) -> None:
        self.run("sudo -n /sbin/reboot 2>/dev/null || /sbin/reboot", timeout=10)


class VyosDriver(LinuxDriver):
    def backup(self) -> bytes:
        return self.run("cat /config/config.boot", timeout=60)


class DdwrtDriver(_SshDriver):
    def status(self) -> Dict[str, Any]:
        s = split_sections(self.text(_DDWRT_STATUS))
        return dict({"model": s.get("model", "").strip(), "firmware": s.get("firmware", "").strip(),
                     "hostname": s.get("hostname", "").strip(), "uptime": parse_uptime(s.get("uptime", "")),
                     "load": parse_loadavg(s.get("load", "")),
                     "interfaces": parse_linux_ifconfig(s.get("ifconfig", "")),
                     "clients": parse_dnsmasq_leases(s.get("leases", ""))}, **parse_meminfo(s.get("mem", "")))

    def backup(self) -> bytes:
        return self.run("nvram show 2>/dev/null", timeout=60)

    def reboot(self) -> None:
        self.run("reboot", timeout=10)


class PfsenseDriver(_SshDriver):
    def status(self) -> Dict[str, Any]:
        s = split_sections(self.text(_PFSENSE_STATUS))
        boot = re.search(r"sec = (\d+)", s.get("boottime", ""))
        now = parse_uptime(s.get("now", ""))
        free = [int(x) for x in s.get("freemem", "").split() if x.isdigit()]
        total = parse_uptime(s.get("physmem", ""))
        used = total - (free[0] + free[1]) * free[2] if total and len(free) == 3 else None
        version = s.get("version", "").strip()
        return {"model": s.get("model", "").strip(), "hostname": s.get("hostname", "").strip(),
                "firmware": f"pfSense {version}" if version else s.get("uname", "").strip(),
                "uptime": now - int(boot.group(1)) if boot and now else None,
                "load": parse_loadavg(s.get("load", "").strip("{} \n")),
                "mem_total": total, "mem_used": used,
                "interfaces": parse_bsd_ifconfig(s.get("ifconfig", "")),
                "clients": parse_kea_csv(s.get("kea", "")) or parse_isc_leases(s.get("isc", ""))}

    def updates(self) -> Dict[str, Any]:
        out = self.text("pfSense-upgrade -c 2>&1", timeout=180)
        # pfSense prints e.g. "2.8.0 version of pfSense is available".
        m = re.search(r"(\d+\.\d+(?:\.\d+)?(?:[_-][\w.]+)?)\s+(?:version of pfSense\s+)?is available", out)
        if "up to date" in out.lower() or not m:
            return {"count": 0, "items": [], "note": "pfSense reports that the system is up to date."
                    if "up to date" in out.lower() else out.strip()[-300:]}
        return {"count": 1, "items": [f"pfSense {m.group(1)}"],
                "note": "Install it from System → Update in the pfSense web interface."}

    def backup(self) -> bytes:
        return self.run("cat /cf/conf/config.xml", timeout=60)

    def reboot(self) -> None:
        self.run("/sbin/shutdown -r now", timeout=10)


class RouterOsDriver(_SshDriver):
    def status(self) -> Dict[str, Any]:
        res = parse_routeros_kv(self.text("/system resource print"))
        ident = parse_routeros_kv(self.text("/system identity print"))
        board = parse_routeros_kv(self.text("/system routerboard print"))
        addresses: Dict[str, List[str]] = {}
        for row in parse_routeros_terse(self.text("/ip address print terse")):
            addresses.setdefault(row.get("interface", ""), []).append(row.get("address", ""))
        interfaces = [{"name": row.get("name", ""), "mac": row.get("mac-address", "").lower(),
                       "up": "R" in row["_flags"] and "X" not in row["_flags"],
                       "ipv4": addresses.get(row.get("name", ""), [])}
                      for row in parse_routeros_terse(self.text("/interface print terse"))]
        clients = [{"ip": row.get("address", ""), "mac": row.get("mac-address", "").lower(),
                    "hostname": row.get("host-name", ""), "expires": None}
                   for row in parse_routeros_terse(self.text("/ip dhcp-server lease print terse"))
                   if row.get("status") in ("bound", None)]
        total = parse_routeros_size(res.get("total-memory", ""))
        free = parse_routeros_size(res.get("free-memory", ""))
        return {"model": board.get("model") or res.get("board-name", ""), "hostname": ident.get("name", ""),
                "firmware": f'RouterOS {res.get("version", "")}'.strip(),
                "uptime": parse_routeros_uptime(res.get("uptime", "")),
                "load": [float(res["cpu-load"].rstrip("%")) / 100] if res.get("cpu-load", "").rstrip("%").isdigit() else [],
                "mem_total": total, "mem_used": total - free if total and free is not None else None,
                "interfaces": interfaces, "clients": clients}

    def updates(self) -> Dict[str, Any]:
        info = parse_routeros_kv(self.text("/system package update check-for-updates once", timeout=60))
        installed, latest = info.get("installed-version", ""), info.get("latest-version", "")
        if latest and installed and latest != installed:
            return {"count": 1, "items": [f"RouterOS {installed} → {latest}"],
                    "note": "Install with System → Packages → Check For Updates in WinBox or WebFig."}
        return {"count": 0, "items": [], "note": info.get("status", "RouterOS is up to date.")}

    def backup(self) -> bytes:
        # RouterOS 7 hides passwords and keys in exports by default.
        return self.run("/export terse", timeout=60)

    def reboot(self) -> None:
        self.run("/system reboot", timeout=10, stdin=b"y\n")


class OpnsenseDriver:
    """OPNsense REST API with an API key + secret (HTTP basic authentication)."""

    def __init__(self, router: Dict[str, Any]):
        self.router = router
        self.base = f'https://{router["host"]}:{int(router["port"])}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _call(self, method: str, path: str, **kw):
        import requests
        resp = requests.request(method, self.base + path, auth=(self.router["api_key"], self.router["api_secret"]),
                                verify=bool(self.router.get("verify_tls")), timeout=kw.pop("timeout", 15),
                                allow_redirects=False, **kw)
        if resp.status_code in (401, 403):
            raise PermissionError("The OPNsense API rejected the key or it lacks the required privileges.")
        resp.raise_for_status()
        return resp

    def _get(self, path: str) -> Any:
        try:
            return self._call("GET", path).json()
        except PermissionError:
            raise
        except Exception:
            return None  # endpoint missing on this OPNsense version

    def status(self) -> Dict[str, Any]:
        info = self._get("/api/diagnostics/system/system_information")
        if info is None:
            # Raise a real error if the API is unreachable at all.
            self._call("GET", "/api/core/firmware/status")
            info = {}
        times = self._get("/api/diagnostics/system/system_time") or {}
        resources = self._get("/api/diagnostics/system/system_resources") or {}
        ifaces = self._get("/api/interfaces/overview/interfaces_info") or {}
        leases = (self._get("/api/dhcpv4/leases/search_lease") or {}).get("rows") or \
                 (self._get("/api/kea/leases4/search") or {}).get("rows") or []
        mem = resources.get("memory", {})
        boot = times.get("boottime") or ""
        uptime = None
        try:
            uptime = int(time.time() - datetime.strptime(boot, "%a %b %d %H:%M:%S %Z %Y").timestamp()) if boot else None
        except ValueError:
            uptime = None
        return {"model": "", "hostname": info.get("name", ""),
                "firmware": (info.get("versions") or [""])[0],
                "uptime": uptime, "load": parse_loadavg((times.get("loadavg") or "").replace(",", " ")),
                "mem_total": int(mem["total"]) if str(mem.get("total", "")).isdigit() else None,
                "mem_used": int(mem["used"]) if str(mem.get("used", "")).isdigit() else None,
                "interfaces": [{"name": r.get("description") or r.get("identifier", ""), "device": r.get("device", ""),
                                "up": r.get("status") == "up", "mac": r.get("macaddr", ""),
                                "ipv4": [a for a in [r.get("addr4", "")] if a]}
                               for r in ifaces.get("rows", [])],
                "clients": [{"ip": r.get("address", ""), "mac": (r.get("mac") or r.get("hwaddr") or "").lower(),
                             "hostname": r.get("hostname", ""), "expires": None} for r in leases]}

    def updates(self) -> Dict[str, Any]:
        self._call("POST", "/api/core/firmware/check")
        status: Dict[str, Any] = {}
        for _ in range(30):            # the check runs in the background on the firewall
            time.sleep(2)
            status = self._get("/api/core/firmware/status") or {}
            if status.get("status") not in (None, "running"):
                break
        items = [f'{p.get("name")}: {p.get("current_version")} → {p.get("new_version")}'
                 for p in (status.get("upgrade_packages") or [])]
        if status.get("status") == "upgrade" and status.get("upgrade_major_version"):
            items.insert(0, f'OPNsense {status["upgrade_major_version"]} (major upgrade)')
        return {"count": len(items), "items": items[:200],
                "note": status.get("status_msg") or "Install updates under System → Firmware in OPNsense."}

    def backup(self) -> bytes:
        return self._call("GET", "/api/core/backup/download/this", timeout=60).content[:MAX_BACKUP + 1]

    def reboot(self) -> None:
        self._call("POST", "/api/core/system/reboot")


_DRIVERS = {"openwrt": OpenWrtDriver, "opnsense": OpnsenseDriver, "pfsense": PfsenseDriver, "vyos": VyosDriver,
            "ddwrt": DdwrtDriver, "routeros": RouterOsDriver, "linux": LinuxDriver}


def _driver(router: Dict[str, Any]):
    return _DRIVERS[router["platform"]](router)


# ── Operations ───────────────────────────────────────────────────────────────

def poll(router_id: int) -> Dict[str, Any]:
    """Read the router's current state and store it. Returns the new status."""
    router = get_router(router_id, secrets=True)
    if not router:
        raise ValueError("Router not found.")
    previous = router["status"]
    status: Dict[str, Any] = {"checked_at": time.time()}
    try:
        with _driver(router) as drv:
            status.update(drv.status())
        status["online"] = True
    except Exception as exc:
        status.update(online=False, error=safe_errors.public_error(exc, f'Contacting {router["name"]}'))
    if previous.get("updates"):
        status["updates"] = previous["updates"]
    _save_status(router_id, status)
    _report_change(router, previous, status)
    return status


def check_updates(router_id: int) -> Dict[str, Any]:
    router = get_router(router_id, secrets=True)
    if not router:
        raise ValueError("Router not found.")
    if not PLATFORMS[router["platform"]]["updates"]:
        raise ValueError(f'Update checks are not available for {router["platform_label"]}.')
    with _driver(router) as drv:
        result = drv.updates()
    result["checked_at"] = time.time()
    status = dict(router["status"], updates=result)
    _save_status(router_id, status)
    if result["count"] and not router["status"].get("updates", {}).get("count"):
        _notify(f'FleetPilot: updates for {router["name"]}',
                f'{result["count"]} update(s) available for {router["name"]} ({router["platform_label"]}).', "info")
    return result


def backup(router_id: int) -> str:
    """Download the configuration, store it encrypted and return the backup file name."""
    router = get_router(router_id, secrets=True)
    if not router:
        raise ValueError("Router not found.")
    ext = PLATFORMS[router["platform"]]["backup_ext"]
    if not ext:
        raise ValueError(f'Configuration backups are not available for {router["platform_label"]}.')
    with _driver(router) as drv:
        data = drv.backup()
    if not data or len(data) < 16:
        raise RuntimeError("The router returned an empty backup.")
    if len(data) > MAX_BACKUP:
        raise RuntimeError("The backup is larger than FleetPilot accepts.")
    name = f'r{router_id}-{datetime.now().strftime("%Y%m%d-%H%M%S")}.{ext}.enc'
    path = os.path.join(_backup_dir(), name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(_box.encrypt(base64.b64encode(data).decode()))
    for old in list_backups(router_id)[KEEP_BACKUPS:]:
        os.remove(old["path"])
    return name


def list_backups(router_id: int) -> List[Dict[str, Any]]:
    items = []
    folder = _backup_dir()
    for entry in sorted(os.listdir(folder), reverse=True):
        m = _BACKUP_RE.match(entry)
        if m and int(m.group(1)) == router_id:
            path = os.path.join(folder, entry)
            items.append({"name": entry, "path": path, "size": os.path.getsize(path),
                          "created": datetime.strptime(m.group(2), "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
                          "download_name": entry[:-4]})
    return items


def read_backup(router_id: int, name: str):
    """Return (download name, decrypted bytes) of a stored backup, or None."""
    for item in list_backups(router_id):
        if item["name"] == name:
            with open(item["path"]) as fh:
                return item["download_name"], base64.b64decode(_box.decrypt(fh.read()))
    return None


def reboot(router_id: int) -> None:
    router = get_router(router_id, secrets=True)
    if not router:
        raise ValueError("Router not found.")
    try:
        with _driver(router) as drv:
            drv.reboot()
    except (EOFError, ConnectionResetError):
        pass  # the router closed the connection while going down


def summary() -> Dict[str, int]:
    routers = list_routers()
    return {"total": len(routers),
            "online": sum(1 for r in routers if r["online"]),
            "offline": sum(1 for r in routers if r["online"] == 0),
            "updates": sum(1 for r in routers if r["status"].get("updates", {}).get("count")),
            "clients": sum(len(r["status"].get("clients") or []) for r in routers)}


# ── Notifications and background polling ────────────────────────────────────

def _notify(title: str, message: str, level: str) -> None:
    try:
        import notify
        notify.send("router", title, message, level)
    except Exception as exc:
        logger.warning("[routers] notification failed: %s", exc)


def _report_change(router: Dict, previous: Dict, status: Dict) -> None:
    if "online" not in previous or previous.get("online") == status.get("online"):
        return
    if status.get("online"):
        _notify(f'FleetPilot: {router["name"]} is back online', f'{router["name"]} ({router["host"]}) answers again.', "info")
    else:
        _notify(f'FleetPilot: {router["name"]} is offline',
                f'{router["name"]} ({router["host"]}) did not answer: {status.get("error", "")}', "critical")


_poller: Optional[threading.Thread] = None


def start_poller(interval_minutes: Optional[int] = None) -> None:
    """Poll all routers in the background (FLEETPILOT_ROUTER_POLL_MINUTES, 0 = off)."""
    global _poller
    minutes = interval_minutes if interval_minutes is not None else \
        int(os.environ.get("FLEETPILOT_ROUTER_POLL_MINUTES", "5") or 0)
    if minutes <= 0 or (_poller and _poller.is_alive()):
        return

    def loop():
        time.sleep(60)
        while True:
            for router in list_routers():
                try:
                    poll(router["id"])
                except Exception as exc:
                    logger.warning("[routers] poll of %s failed: %s", router["name"], exc)
            time.sleep(minutes * 60)

    _poller = threading.Thread(target=loop, name="router-poller", daemon=True)
    _poller.start()
