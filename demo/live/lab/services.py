"""Emulated appliances with HTTP APIs: Proxmox VE and Backup Server, TrueNAS, FRITZ!, OpenWrt, OPNsense."""
import json
import re
import secrets
import time
from xml.sax.saxutils import escape

from .machines import Device, Machine


def _ok(data, status=200):
    return status, "application/json", json.dumps({"data": data} if status < 400 else data)


def _raw(data, status=200):
    return status, "application/json", json.dumps(data)


# ── Proxmox VE ───────────────────────────────────────────────────────────────

class Guest:
    def __init__(self, vmid, name, kind, node, cpus=2, mem_gb=4, disk_gb=32, running=True, load=8.0, tags=""):
        self.vmid, self.name, self.kind, self.node = vmid, name, kind, node
        self.cpus, self.maxmem, self.maxdisk = cpus, mem_gb * 2**30, disk_gb * 2**30
        self.status, self.paused = ("running" if running else "stopped"), False
        self.started = time.time() - 86400 * (3 + vmid % 9)
        self.load, self.tags = load, tags
        self.snapshots = [{"name": "before-upgrade", "description": "Taken before the last OS upgrade",
                           "snaptime": int(time.time() - 86400 * 21)}]

    def as_dict(self, cluster=False):
        running = self.status == "running"
        cpu = (self.load / 100) * (1 + 0.3 * ((time.time() / 60 + self.vmid) % 1)) if running and not self.paused else 0
        d = {"vmid": self.vmid, "name": self.name, "status": self.status, "cpus": self.cpus, "maxcpu": self.cpus,
             "cpu": round(cpu, 4), "maxmem": self.maxmem, "mem": int(self.maxmem * 0.55) if running else 0,
             "maxdisk": self.maxdisk, "disk": int(self.maxdisk * 0.4),
             "uptime": int(time.time() - self.started) if running else 0,
             "netin": int((time.time() - self.started) * 9000) if running else 0,
             "netout": int((time.time() - self.started) * 4000) if running else 0, "tags": self.tags}
        if self.paused:
            d["qmpstatus"] = "paused"
        if cluster:
            d.update(id=f"{self.kind}/{self.vmid}", type=self.kind, node=self.node)
        return d


class ProxmoxCluster:
    def __init__(self, nodes, guests):
        self.nodes, self.guests = nodes, guests
        for node in nodes:
            node.cluster = self

    def guest(self, node, kind, vmid):
        return next((g for g in self.guests if g.node == node and g.kind == kind and g.vmid == int(vmid)), None)


class ProxmoxNode(Machine):
    kind = "proxmox"
    icon = "boxes"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("ports", (22, 8006))
        kwargs.setdefault("pretty", "Debian GNU/Linux 13 (trixie) · Proxmox VE 9.0")
        kwargs.setdefault("kernel", "6.14.11-3-pve")
        super().__init__(*args, **kwargs)
        self.cluster = None

    def facts(self):
        mine = [g for g in self.cluster.guests if g.node == self.name]
        running = sum(g.status == "running" for g in mine)
        return super().facts() + [f"{running}/{len(mine)} guests running"]

    def power_off(self, why="shut down"):
        for g in self.cluster.guests:
            if g.node == self.name:
                g.status = "stopped"
        super().power_off(why)

    def http(self, method, port, path, query, headers, body):
        if port != 8006 or not path.startswith("/api2/json"):
            return None
        path = path[len("/api2/json"):]
        if path == "/access/ticket" and method == "POST":
            return _ok({"ticket": "PVE:root@pam:" + secrets.token_hex(8), "CSRFPreventionToken": secrets.token_hex(8),
                        "username": "root@pam"})
        if path == "/version":
            return _ok({"version": "9.0.10", "release": "9.0", "repoid": "deb1ca707ec72a89"})
        c = self.cluster
        live = [n for n in c.nodes if n.powered]
        if path == "/nodes":
            return _ok([{"node": n.name, "status": "online" if n.powered else "offline", "cpu": n.cpu_pct() / 100,
                         "maxcpu": n.cores, "mem": int(n.ram_mb * 2**20 * n.ram_pct() / 100),
                         "maxmem": n.ram_mb * 2**20, "uptime": int(n.uptime()) if n.powered else 0, "level": "",
                         "id": f"node/{n.name}", "type": "node"} for n in c.nodes])
        if path == "/cluster/resources":
            res = [{"id": f"node/{n.name}", "type": "node", "node": n.name, "status": "online",
                    "cpu": n.cpu_pct() / 100, "maxcpu": n.cores} for n in live]
            return _ok(res + [g.as_dict(cluster=True) for g in c.guests if self.cluster_node_up(g.node)])
        m = re.fullmatch(r"/nodes/([^/]+)/(qemu|lxc)", path)
        if m:
            if not self.cluster_node_up(m.group(1)):
                return _raw({"errors": "node offline"}, 595)
            return _ok([g.as_dict() for g in c.guests if g.node == m.group(1) and g.kind == m.group(2)])
        m = re.fullmatch(r"/nodes/([^/]+)/(qemu|lxc)/(\d+)/(status/current|status/(\w+)|snapshot)", path)
        if m:
            guest = c.guest(m.group(1), m.group(2), m.group(3))
            if not guest:
                return _raw({"errors": {"vmid": "does not exist"}}, 500)
            if m.group(4) == "status/current":
                return _ok(guest.as_dict())
            if m.group(4) == "snapshot":
                if method == "POST":
                    form = _form(body)
                    guest.snapshots.append({"name": form.get("snapname", "snap"),
                                            "description": form.get("description", ""), "snaptime": int(time.time())})
                    self._log("http", f"{guest.name}: snapshot {form.get('snapname')} created")
                    return _ok(f"UPID:{m.group(1)}:qmsnapshot:{guest.vmid}")
                return _ok(guest.snapshots + [{"name": "current", "description": "You are here!",
                                               "running": int(guest.status == "running")}])
            return self._power(guest, m.group(5), method)
        m = re.fullmatch(r"/nodes/([^/]+)/storage", path)
        if m:
            return _ok([{"storage": "local", "type": "dir", "content": "iso,vztmpl,backup", "active": 1, "enabled": 1,
                         "total": 100 * 2**30, "used": 38 * 2**30, "avail": 62 * 2**30, "shared": 0},
                        {"storage": "local-zfs", "type": "zfspool", "content": "images,rootdir", "active": 1,
                         "enabled": 1, "total": 1800 * 2**30, "used": 742 * 2**30, "avail": 1058 * 2**30, "shared": 0},
                        {"storage": "pbs-backup", "type": "pbs", "content": "backup", "active": 1, "enabled": 1,
                         "total": 7200 * 2**30, "used": 2900 * 2**30, "avail": 4300 * 2**30, "shared": 1}])
        m = re.fullmatch(r"/nodes/([^/]+)/disks/list", path)
        if m:
            node = next((n for n in c.nodes if n.name == m.group(1)), None)
            return _ok([{"devpath": f"/dev/{d.dev}", "model": d.model, "serial": d.serial, "size": d.bytes,
                         "health": "FAILED" if d.failed else "PASSED", "wearout": 100 - min(99, d.poh // 900),
                         "type": "nvme" if d.nvme else ("hdd" if d.rotational else "ssd"), "used": "ZFS",
                         "gpt": 1, "rpm": 7200 if d.rotational else 0} for d in (node.disks if node else [])])
        m = re.fullmatch(r"/nodes/([^/]+)/disks/smart", path)
        if m:
            node = next((n for n in c.nodes if n.name == m.group(1)), None)
            dev = query.get("disk", "").removeprefix("/dev/")
            disk = next((d for d in (node.disks if node else []) if d.dev == dev), None)
            if not disk:
                return _raw({"errors": {"disk": "invalid format - missing disk path"}}, 400)
            if disk.nvme:
                return _ok({"health": "PASSED", "type": "text", "text": disk.smartctl_a()})
            attrs = []
            for line in disk.smartctl_a().splitlines():
                p = line.split()
                if len(p) >= 10 and p[0].isdigit() and p[2].startswith("0x"):
                    attrs.append({"id": int(p[0]), "name": p[1], "flags": p[2], "value": int(p[3]),
                                  "worst": int(p[4]), "threshold": int(p[5]), "fail": "-", "raw": int(p[9])})
            return _ok({"health": "FAILED" if disk.failed else "PASSED", "type": "ata", "attributes": attrs})
        return None

    def cluster_node_up(self, name):
        node = next((n for n in self.cluster.nodes if n.name == name), None)
        return bool(node and node.powered)

    def _power(self, guest, action, method):
        if method != "POST":
            return None
        if action == "start" or action == "resume":
            if guest.status != "running":
                guest.started = time.time()
            guest.status, guest.paused = "running", False
        elif action in ("stop", "shutdown"):
            guest.status, guest.paused = "stopped", False
        elif action == "reboot" or action == "reset":
            guest.started = time.time()
        elif action == "suspend":
            guest.paused = True
        else:
            return _raw({"errors": {"action": "unknown"}}, 400)
        self._log("vm", f"{guest.kind} {guest.vmid} ({guest.name}): {action}")
        return _ok(f"UPID:{guest.node}:0000{guest.vmid}:q{action}:{guest.vmid}:root@pam:")


def _form(body):
    import urllib.parse
    text = (body or b"").decode(errors="replace")
    if text.startswith("{"):
        try:
            return json.loads(text)
        except ValueError:
            return {}
    return dict(urllib.parse.parse_qsl(text))


# ── Proxmox Backup Server ────────────────────────────────────────────────────

class BackupServer(Machine):
    kind = "pbs"
    icon = "archive"

    def __init__(self, *args, clients=(), **kwargs):
        kwargs.setdefault("ports", (22, 8007))
        kwargs.setdefault("pretty", "Debian GNU/Linux 13 (trixie) · Proxmox Backup Server 4.0")
        super().__init__(*args, **kwargs)
        now = int(time.time())
        self.clients = list(clients)
        self.fail_next = False
        self.tasks = []
        for day in range(6, -1, -1):
            for i, (kind, bid) in enumerate(self.clients):
                start = now - day * 86400 - 3 * 3600 + i * 420
                failed = day == 3 and bid == "105"
                self.tasks.append({"upid": f"UPID:{self.name}:{start:08X}:backup:{bid}", "type": "backup",
                                   "id": f"store1:{kind}/{bid}", "starttime": start, "endtime": start + 300 + i * 40,
                                   "duration": 300 + i * 40, "user": "root@pam",
                                   "status": "connection error: timed out" if failed else "OK"})

    def facts(self):
        return super().facts() + [f"{len(self.tasks)} backup tasks"]

    def actions(self):
        return super().actions() + ([{"id": "fail", "label": "Fail the next backup"}] if self._on else [])

    def act(self, action):
        if action == "fail":
            self.fail_next = True
            self._log("lab", f"{self.label}: the next backup will fail")
            return True
        return super().act(action)

    def run_backup(self, job):
        start = int(time.time())
        kind, bid = self.clients[self.rand.randrange(len(self.clients))]
        status = "error: datastore store1 is full" if self.fail_next else "OK"
        self.fail_next = False
        self.tasks.append({"upid": f"UPID:{self.name}:{start:08X}:backup:{bid}", "type": "backup",
                           "id": f"store1:{kind}/{bid}", "starttime": start, "endtime": start + 95,
                           "duration": 95, "user": "root@pam", "status": status})
        self._log("backup", f"{self.label}: backup job {job or 'manual'} for {kind}/{bid}: {status}")

    def http(self, method, port, path, query, headers, body):
        if port != 8007 or not path.startswith("/api2/json"):
            return None
        path = path[len("/api2/json"):]
        if path == "/access/ticket":
            return _ok({"ticket": "PBS:root@pam:" + secrets.token_hex(8), "CSRFPreventionToken": secrets.token_hex(8)})
        if path == "/version":
            return _ok({"version": "4.0.14", "release": "4.0", "repoid": "8b7ff5c2"})
        if path == "/nodes/localhost/storage":
            return _ok([{"storage": "store1", "total": 8 * 10**12, "used": 3_100_000_000_000,
                         "avail": 4_900_000_000_000}])
        if path == "/nodes/localhost/tasks":
            return _ok(sorted(self.tasks, key=lambda t: -t["starttime"])[: int(query.get("limit", 50))])
        if path == "/config/sync":
            return _ok([{"id": "offsite", "store": "store1", "remote": "offsite-pbs", "schedule": "daily"}])
        if path == "/config/backup":
            return _ok([{"id": "nightly", "schedule": "03:00", "store": "store1"}])
        if path == "/nodes/localhost/storage/store1/snapshots":
            now = int(time.time())
            return _ok([{"backup-type": kind, "backup-id": bid, "backup-time": now - day * 86400 - 3 * 3600,
                         "size": (12 + int(bid) % 7 * 9) * 2**30, "comment": name}
                        for day in range(3) for (kind, bid), name in zip(self.clients, self._names())])
        if path == "/nodes/localhost/backup" and method == "POST":
            self.run_backup(_form(body).get("job-id", ""))
            return _ok("UPID:started")
        return None

    def _names(self):
        return [f"{k}-{b}" for k, b in self.clients]


# ── TrueNAS SCALE ────────────────────────────────────────────────────────────

class TrueNas(Machine):
    kind = "truenas"
    icon = "device-hdd"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("ports", (22, 80, 443))
        kwargs.setdefault("pretty", "TrueNAS SCALE 25.04.2.4")
        super().__init__(*args, **kwargs)

    def http(self, method, port, path, query, headers, body):
        if port != 443 or not path.startswith("/api/v2.0"):
            return None
        path = path[len("/api/v2.0"):]
        data_disks = [d for d in self.disks if not d.nvme]
        if path == "/system/info":
            return _raw({"version": "TrueNAS-SCALE-25.04.2.4", "hostname": self.name, "physmem": self.ram_mb * 2**20,
                         "model": self.cpu, "cores": self.cores, "uptime_seconds": int(self.uptime()),
                         "system_product": "TrueNAS Mini X+"})
        if path == "/disk":
            return _raw([{"name": d.dev, "identifier": d.serial, "serial": d.serial, "model": d.model,
                          "size": d.bytes, "type": "HDD" if d.rotational else "SSD", "togglesmart": True,
                          "hddstandby": "ALWAYS ON", "pool": "tank" if d in data_disks else "boot-pool"}
                         for d in self.disks])
        if path == "/disk/temperatures":
            return _raw({d.dev: d.temp for d in self.disks})
        if path == "/pool":
            degraded = any(d.realloc or d.failed for d in data_disks)
            return _raw([{"id": 1, "name": "tank", "status": "DEGRADED" if degraded else "ONLINE",
                          "healthy": not degraded, "size": 32 * 10**12, "allocated": 13 * 10**12,
                          "free": 19 * 10**12, "path": "/mnt/tank", "scan": {"state": "FINISHED", "errors": 0}},
                         {"id": 2, "name": "fast", "status": "ONLINE", "healthy": True, "size": 2 * 10**12,
                          "allocated": 6 * 10**11, "free": 14 * 10**11, "path": "/mnt/fast"}])
        if path == "/pool/dataset":
            return _raw([{"id": f"tank/{n}", "name": f"tank/{n}", "pool": "tank", "type": "FILESYSTEM",
                          "used": {"parsed": u * 10**9}, "available": {"parsed": 19 * 10**12}}
                         for n, u in (("media", 8200), ("backups", 3100), ("documents", 140), ("photos", 1600))])
        if path == "/sharing/smb":
            return _raw([{"id": i, "name": n, "path": f"/mnt/tank/{n}", "enabled": True, "comment": ""}
                         for i, n in enumerate(("media", "documents", "photos"), 1)])
        if path == "/sharing/nfs":
            return _raw([{"id": 1, "path": "/mnt/tank/backups", "paths": ["/mnt/tank/backups"], "enabled": True,
                          "hosts": ["192.0.2.10", "192.0.2.11"], "networks": []}])
        if path == "/alert/list":
            alerts = [{"level": "WARNING", "formatted": f"Device /dev/{d.dev} has {d.realloc} reallocated sectors.",
                       "dismissed": False} for d in data_disks if d.realloc]
            return _raw(alerts)
        if path == "/zfs/snapshot":
            return _raw([{"name": f"tank/documents@auto-2026-10-{day:02d}_00-00"} for day in range(1, 13)])
        m = re.fullmatch(r"/smart/test/results/(\w+)", path)
        if m:
            return _raw([{"disk": m.group(1), "tests": [{"num": 1, "description": "Short offline",
                                                         "status": "SUCCESS", "lifetime": 21000}]}])
        if path == "/smart/test" and method == "POST":
            return _raw([1])
        return None


# ── AVM FRITZ! (TR-064) ──────────────────────────────────────────────────────

class Fritz(Device):
    kind = "fritz"
    icon = "router"

    def __init__(self, name, ip, mac, model, version="8.20", repeater=False, clients=(), mesh=(), wan=True, **kw):
        super().__init__(name, ip, mac, ports=(80, 443, 49000, 49443), **kw)
        self.model, self.version, self.repeater = model, version, repeater
        self.clients, self.mesh, self.wan = list(clients), list(mesh), wan
        self.serial = "".join(self.rand.choice("0123456789ABCDEF") for _ in range(12))
        self.update_available = None

    def facts(self):
        f = [f"{self.model}", f"FRITZ!OS {self.version}", f"{len(self.clients)} devices"]
        return f + ([f"FRITZ!OS {self.update_available} available"] if self.update_available else [])

    def actions(self):
        acts = super().actions()
        if self._on and not self.update_available:
            acts.append({"id": "fw", "label": "Publish FRITZ!OS update"})
        if self._on:
            acts.append({"id": "client", "label": "A new device joins"})
        return acts

    def act(self, action):
        if action == "fw":
            major, minor = self.version.split(".")
            self.update_available = f"{major}.{int(minor) + 1:02d}"
            self._log("lab", f"{self.label}: FRITZ!OS {self.update_available} published")
        elif action == "client":
            n = len(self.clients) + 120
            self.clients.append({"ip": f"192.0.2.{n}", "mac": f"aa:bb:cc:00:01:{n:02x}",
                                 "hostname": self.rand.choice(["guest-phone", "smart-plug", "new-laptop", "e-reader"]),
                                 "connection": "Wi-Fi"})
            self._log("lab", f"{self.label}: {self.clients[-1]['hostname']} joined the network")
        else:
            return super().act(action)
        return True

    def http(self, method, port, path, query, headers, body):
        if port not in (49000, 49443):
            return None
        if path == "/hostlist.lua":
            items = "".join(
                f"<Item><Index>{i}</Index><IPAddress>{c['ip']}</IPAddress><MACAddress>{c['mac'].upper()}</MACAddress>"
                f"<Active>1</Active><HostName>{escape(c['hostname'])}</HostName>"
                f"<InterfaceType>{'802.11' if c.get('connection') == 'Wi-Fi' else 'Ethernet'}</InterfaceType></Item>"
                for i, c in enumerate(self.clients))
            return 200, "text/xml", f'<?xml version="1.0"?><List>{items}</List>'
        if path == "/meshlist.lua":
            nodes = [{"device_name": self.name, "device_model": self.model, "is_meshed": True,
                      "mesh_role": "slave" if self.repeater else "master",
                      "device_firmware_version": self.version, "node_interfaces": []}]
            for other in self.mesh:
                nodes.append({"device_name": other.name, "device_model": other.model, "is_meshed": other.powered,
                              "mesh_role": "slave", "device_firmware_version": other.version,
                              "node_interfaces": [{"type": "WLAN", "node_links": [{"state": "CONNECTED"}]}]})
            return 200, "application/json", json.dumps({"nodes": nodes})
        if path == "/config.export":
            return 200, "application/octet-stream", (
                f"**** FRITZ!Box configuration export\nProduct={self.model}\nFirmware={self.version}\n"
                "**** CFGFILE:ar7.cfg (encrypted)\n" + secrets.token_hex(400) + "\n**** END OF EXPORT\n")
        m = re.search(r'#(\S+)"', headers.get("Soapaction", headers.get("SOAPAction", "")))
        action = m.group(1) if m else ""
        out = self._soap(path, action, body.decode(errors="replace"))
        if out is None:
            return 500, "text/xml", self._envelope("Fault", {"faultstring": "UPnPError", "errorCode": "401"})
        return 200, "text/xml", self._envelope(action + "Response", out)

    def _tr064_version(self, version):
        major, minor = version.split(".")
        return f"{'191' if self.repeater else '164'}.{int(major):02d}.{minor}"

    @staticmethod
    def _envelope(name, values):
        inner = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in values.items())
        return ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:{name} '
                f'xmlns:u="urn:dslforum-org:service">{inner}</u:{name}></s:Body></s:Envelope>')

    def _soap(self, path, action, body):
        svc = path.rsplit("/", 1)[-1]
        if svc == "deviceinfo" and action == "GetInfo":
            return {"NewModelName": self.model, "NewDescription": f"{self.model} {self.version}",
                    "NewSoftwareVersion": self._tr064_version(self.version),
                    "NewUpTime": int(self.uptime()), "NewSerialNumber": self.serial}
        if svc == "userif" and action == "GetInfo":
            return {"NewUpgradeAvailable": "1" if self.update_available else "0",
                    "NewX_AVM-DE_Version": self._tr064_version(self.update_available) if self.update_available else ""}
        if svc == "deviceconfig" and action == "Reboot":
            self.reboot(60)
            return {}
        if svc == "deviceconfig" and action == "X_AVM-DE_GetConfigFile":
            return {"NewX_AVM-DE_ConfigFileUrl": f"https://{self.ip}:49443/config.export"}
        if svc == "hosts" and action == "X_AVM-DE_GetHostListPath":
            return {"NewX_AVM-DE_HostListPath": "/hostlist.lua"}
        if svc == "hosts" and action == "X_AVM-DE_GetMeshListPath":
            return {"NewX_AVM-DE_MeshListPath": "/meshlist.lua"}
        if svc.startswith("wan") and not self.wan:
            return None
        if svc == "wancommonifconfig1" and action == "GetCommonLinkProperties":
            return {"NewWANAccessType": "DSL", "NewPhysicalLinkStatus": "Up",
                    "NewLayer1DownstreamMaxBitRate": "250000000", "NewLayer1UpstreamMaxBitRate": "40000000"}
        if svc == "wanpppconn1" and action == "GetInfo":
            return {"NewConnectionStatus": "Connected", "NewUptime": int(min(self.uptime(), 86400 * 2.5))}
        if svc == "wanpppconn1" and action == "GetExternalIPAddress":
            return {"NewExternalIPAddress": "203.0.113.47"}
        m = re.fullmatch(r"wlanconfig(\d)", svc)
        if m:
            n = int(m.group(1))
            if n > (2 if self.repeater else 3):
                return None
            ssid = {1: "Lab-WLAN", 2: "Lab-WLAN", 3: "Lab-Guest"}[n]
            if action == "GetTotalAssociations":
                wifi = [c for c in self.clients if c.get("connection") == "Wi-Fi"]
                return {"NewTotalAssociations": len(wifi[n - 1::2]) if n < 3 else 0}
            return {"NewSSID": ssid, "NewEnable": "1", "NewStatus": "Up", "NewChannel": {1: 6, 2: 36, 3: 6}[n],
                    "NewBSSID": self.mac[:-2] + f"{n:02x}"}
        return None


# ── OpenWrt (SSH) ────────────────────────────────────────────────────────────

class OpenWrt(Device):
    kind = "openwrt"
    icon = "router"

    def __init__(self, name, ip, mac, model, version="24.10.2", clients=(), **kw):
        super().__init__(name, ip, mac, ports=(22, 80, 443), **kw)
        self.model, self.version, self.clients = model, version, list(clients)
        self.upgradable = [("luci-app-adblock", "4.2.2-r4", "4.3.1-r1"), ("curl", "8.12.1-r1", "8.12.1-r2"),
                           ("dnsmasq-full", "2.90-r4", "2.91-r1")]

    def facts(self):
        return [self.model, f"OpenWrt {self.version}", f"{len(self.upgradable)} package updates"]

    def shell(self, command, stdin="", user="root"):
        self._log("ssh", f"$ {command.split(';')[0][:120]}")
        if "@@fp:board" in command:
            up = int(self.uptime())
            board = {"kernel": "6.6.93", "hostname": self.name, "system": "ARMv8 Processor rev 4",
                     "model": self.model, "board_name": "glinet,gl-mt6000",
                     "release": {"distribution": "OpenWrt", "version": self.version, "revision": "r28739-d9340319c6"}}
            info = {"uptime": up, "load": [8448, 5632, 2304],
                    "memory": {"total": 1_048_576_000, "free": 612_000_000, "available": 702_000_000,
                               "buffered": 22_000_000}}
            ifaces = {"interface": [{"interface": "lan", "up": True, "l3_device": "br-lan", "proto": "static",
                                     "ipv4-address": [{"address": self.ip, "mask": 24}]},
                                    {"interface": "wan", "up": True, "l3_device": "eth1", "proto": "dhcp",
                                     "ipv4-address": [{"address": "198.51.100.23", "mask": 24}]}]}
            leases = "".join(f"{int(time.time()) + 3600} {c['mac']} {c['ip']} {c['hostname']} *\n" for c in self.clients)
            out = (f"@@fp:board\n{json.dumps(board)}\n@@fp:info\n{json.dumps(info)}\n@@fp:ifaces\n"
                   f"{json.dumps(ifaces)}\n@@fp:leases\n{leases}@@fp:load\n0.08 0.05 0.01 1/97 2711\n")
            return 0, out, ""
        if "opkg list-upgradable" in command or "apk list --upgradable" in command:
            return 0, "".join(f"{p} - {o} - {n}\n" for p, o, n in self.upgradable), ""
        if "sysupgrade -b" in command:
            return 0, "backup-" + self.name + "\x1f\x8b" + secrets.token_hex(300), ""
        if command.strip() == "reboot":
            self.reboot(45)
            return 0, "", ""
        return 127, "", f"ash: {command.split()[0]}: not found\n"


# ── OPNsense (REST) ──────────────────────────────────────────────────────────

class OpnSense(Device):
    kind = "opnsense"
    icon = "shield-lock"

    def __init__(self, name, ip, mac, version="26.1.4", clients=(), **kw):
        super().__init__(name, ip, mac, ports=(22, 443), **kw)
        self.version, self.clients = version, list(clients)
        self.pending = []

    def facts(self):
        return [f"OPNsense {self.version}", f"{len(self.clients)} DHCP leases"] + \
            ([f"{len(self.pending)} updates"] if self.pending else [])

    def actions(self):
        acts = super().actions()
        if self._on and not self.pending:
            acts.append({"id": "fw", "label": "Publish OPNsense update"})
        return acts

    def act(self, action):
        if action == "fw":
            self.pending = [("opnsense", self.version, self.version[:-1] + str(int(self.version[-1]) + 1)),
                            ("openssl", "3.0.17", "3.0.18")]
            self._log("lab", f"{self.label}: OPNsense update published")
            return True
        return super().act(action)

    def http(self, method, port, path, query, headers, body):
        if port != 443 or not path.startswith("/api/"):
            return None
        if path == "/api/diagnostics/system/system_information":
            return _raw({"name": f"{self.name}.lab.example", "versions": [f"OPNsense {self.version}-amd64",
                                                                        "FreeBSD 14.3-RELEASE-p2", "OpenSSL 3.0.17"]})
        if path == "/api/diagnostics/system/system_time":
            boot = time.strftime("%a %b %d %H:%M:%S UTC %Y", time.gmtime(self.booted_at))
            return _raw({"boottime": boot, "loadavg": "0.21, 0.18, 0.15", "datetime": time.ctime()})
        if path == "/api/diagnostics/system/system_resources":
            return _raw({"memory": {"total": str(8 * 2**30), "used": str(int(2.3 * 2**30))}})
        if path == "/api/interfaces/overview/interfaces_info":
            return _raw({"rows": [{"description": "WAN", "identifier": "wan", "device": "igc0", "status": "up",
                                   "macaddr": self.mac, "addr4": "198.51.100.2/24"},
                                  {"description": "LAN", "identifier": "lan", "device": "igc1", "status": "up",
                                   "macaddr": self.mac[:-1] + "1", "addr4": f"{self.ip}/24"}]})
        if path == "/api/dhcpv4/leases/search_lease":
            return _raw({"rows": [{"address": c["ip"], "mac": c["mac"], "hostname": c["hostname"]}
                                  for c in self.clients]})
        if path == "/api/core/firmware/check":
            return _raw({"status": "ok"})
        if path == "/api/core/firmware/status":
            if self.pending:
                return _raw({"status": "update", "status_msg": f"There are {len(self.pending)} updates available.",
                             "upgrade_packages": [{"name": n, "current_version": o, "new_version": v}
                                                  for n, o, v in self.pending]})
            return _raw({"status": "none", "status_msg": "There are no updates available on the selected mirror."})
        if path == "/api/core/firmware/audit" and method == "POST":
            return _raw({"status": "ok", "msg_uuid": secrets.token_hex(8)})
        if path == "/api/core/firmware/upgradestatus":
            return _raw({"status": "done", "log": "***GOT REQUEST TO AUDIT SECURITY***\n"
                                                  "Currently running OPNsense " + self.version + "\n"
                                                  "vulnxml file up-to-date\n"
                                                  "0 problem(s) in 0 installed package(s) found.\n"
                                                  "***DONE***\n"})
        if path == "/api/core/backup/download/this":
            return 200, "application/xml", (f'<?xml version="1.0"?>\n<opnsense><version>{self.version}</version>'
                                            f"<system><hostname>{self.name}</hostname></system></opnsense>\n")
        if path == "/api/core/system/reboot" and method == "POST":
            self.reboot(90)
            return _raw({"status": "ok"})
        return None
