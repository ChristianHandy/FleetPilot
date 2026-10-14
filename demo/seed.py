# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo mode: a FleetPilot with example data (RFC 5737 addresses, made-up devices).

Importing this module seeds a fresh data folder (demo/.data) and returns the app as `fp`.
It never contacts the example machines: online checks and discovery are answered locally.
Used by demo/build_site.py (GitHub Pages demo) and demo/screenshots.py (README pictures).
"""
import json
import os
import secrets
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, ".data")
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA)
PASSWORD = secrets.token_urlsafe(16)          # local demo account only
os.environ.update(FLEETPILOT_DATA_DIR=DATA, DASHBOARD_USERNAME="admin", DASHBOARD_PASSWORD=PASSWORD,
                  FLEETPILOT_OFFLINE="true", FLEETPILOT_ROUTER_POLL_MINUTES="0", FLEETPILOT_AUTO_BACKUP="false")


def host(addr, desc, group, env, crit, tags, location, user="root"):
    return {"host": addr, "user": user, "mac": "", "description": desc, "notes": "", "group": group,
            "location": location, "environment": env, "criticality": crit, "tags": tags, "port": 22,
            "ssh_key": "", "os_profiles": [], "last_update": None, "last_seen": None}


HOSTS = {
    "pve-01": host("192.0.2.10", "Proxmox VE 9 node", "Virtualisation", "Production", "High", ["proxmox", "server"], "Rack"),
    "pve-02": host("192.0.2.11", "Proxmox VE 9 node", "Virtualisation", "Production", "High", ["proxmox", "server"], "Rack"),
    "nas": host("192.0.2.20", "TrueNAS SCALE storage", "Storage", "Production", "High", ["nas", "zfs"], "Rack"),
    "docker-01": host("192.0.2.30", "Debian 13 · Docker host", "Services", "Production", "Medium", ["docker", "debian"], "Rack"),
    "web-01": host("192.0.2.31", "Ubuntu 24.04 · nginx", "Services", "Production", "Medium", ["web", "ubuntu"], "Cloud", "admin"),
    "pihole": host("192.0.2.53", "Raspberry Pi 5 · DNS", "Network", "Production", "Medium", ["dns", "raspberry-pi"], "Office", "pi"),
    "backup": host("192.0.2.40", "Proxmox Backup Server", "Storage", "Production", "High", ["backup"], "Basement"),
    "lab-01": host("192.0.2.60", "Fedora 42 · test box", "Lab", "Testing", "Low", ["lab"], "Office"),
    "win-desk": host("192.0.2.70", "Windows 11 workstation", "Clients", "Production", "Low", ["windows"], "Office", "admin"),
}
OFFLINE = {"lab-01"}
for _name, _h in HOSTS.items():
    _h["management"] = {"state": "unreachable" if _name in OFFLINE else "manageable"}
with open(os.path.join(DATA, "hosts.json"), "w") as fh:
    json.dump(HOSTS, fh, indent=2)

sys.path.insert(0, REPO)
os.chdir(REPO)
import smart_manager as _sm  # noqa: E402
_sm.collect_all_local_disks = lambda: []     # keep this PC's own disks out of the demo
_sm.collect_all_ssh_hosts = lambda: []
import app as fp  # noqa: E402
import router_manager as rm  # noqa: E402
import smart_manager as sm  # noqa: E402

# Demo: machines answer as online without any network traffic.
fp.hosts_online = lambda hosts: {name: name not in OFFLINE for name in hosts}
fp.is_online = lambda h, user=None, port=22: True
fp._discover_host_and_store = lambda name: None

for dev, serial, model, size, temp, poh, realloc, health in [
    ("/dev/sda", "S6PNNM0T1001", "Samsung SSD 870 EVO 1TB", 1000, 34, 8120, 0, "GOOD"),
    ("/dev/sdb", "WD-WX12A3456", "WDC WD40EFZX Red Plus 4TB", 4000, 37, 21544, 0, "GOOD"),
    ("/dev/sdc", "WD-WX12A3457", "WDC WD40EFZX Red Plus 4TB", 4000, 38, 21540, 0, "GOOD"),
    ("/dev/sdd", "ZL2ABC12", "Seagate IronWolf 8TB", 8000, 41, 30211, 24, "WARNING"),
    ("/dev/nvme0n1", "S5GXNF0R2002", "Samsung 980 PRO 2TB", 2000, 46, 4410, 0, "GOOD"),
    ("/dev/sde", "Z1F0ABCD", "Toshiba MG08 16TB", 16000, 35, 1290, 0, "GOOD"),
]:
    disk_id = sm.register_disk("local", dev, serial, model, size)
    sm._save_snapshot(disk_id, {"overall_status": "PASSED", "temp": temp, "poh": poh, "reallocated": realloc,
                                "pending": 0, "uncorrectable": 0, "attributes": []}, health)
    if health == "WARNING":
        with sm.get_db() as db:
            db.execute("INSERT INTO disk_alerts(disk_id,level,message) VALUES (?,?,?)",
                       (disk_id, "WARNING", f"{dev}: 24 reallocated sectors (was 0)"))

clients = [{"ip": f"192.0.2.{n}", "mac": f"aa:bb:cc:00:00:{n:02x}", "hostname": h, "expires": None, "connection": c}
           for n, h, c in [(101, "phone-anna", "Wi-Fi"), (102, "laptop", "Wi-Fi"), (103, "tv", "LAN"),
                           (104, "printer", "Wi-Fi"), (105, "nas", "LAN"), (106, "tablet", "Wi-Fi")]]
for fields, status in [
    ({"name": "FRITZ!Box", "platform": "fritzbox", "host": "192.0.2.1", "username": "fleetpilot", "password": "demo-password"},
     {"online": True, "model": "FRITZ!Box 7590 AX", "firmware": "FRITZ!OS 8.20", "uptime": 1_814_400, "latency_ms": 2,
      "clients": clients, "updates": {"count": 0, "items": []}}),
    ({"name": "Repeater upstairs", "platform": "fritzrepeater", "host": "192.0.2.2", "username": "fleetpilot",
      "password": "demo-password", "role": "repeater"},
     {"online": True, "model": "FRITZ!Repeater 3000 AX", "firmware": "FRITZ!OS 8.20", "uptime": 950_000, "latency_ms": 4,
      "clients": clients[:2]}),
    ({"name": "GL.iNet travel router", "platform": "openwrt", "host": "192.0.2.3", "username": "root", "password": "demo-password"},
     {"online": True, "model": "GL.iNet GL-MT6000", "firmware": "OpenWrt 24.10.2", "uptime": 432_000, "latency_ms": 3,
      "load": [0.08, 0.05, 0.01], "mem_total": 1_048_576_000, "mem_used": 312_000_000, "clients": clients[2:5],
      "updates": {"count": 3, "items": ["luci-app-adblock", "curl", "dnsmasq-full"]}}),
    ({"name": "OPNsense", "platform": "opnsense", "host": "192.0.2.254", "api_key": "demo-key", "api_secret": "demo-secret"},
     {"online": True, "model": "OPNsense", "firmware": "OPNsense 26.1.4", "uptime": 2_592_000, "latency_ms": 1,
      "clients": clients, "updates": {"count": 0, "items": []}}),
]:
    rid = rm.add_router(fields)
    rm._save_status(rid, status)

