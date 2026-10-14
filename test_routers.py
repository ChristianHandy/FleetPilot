# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Router support: parsers, drivers (with simulated devices), storage, permissions."""
import io
import json
import os
import sqlite3
import time

import pytest

import account_security
import app as fp
import notify
import router_manager as rm
import user_management

# ── Sample output captured from each router system ───────────────────────────

OPENWRT = {
    "board": json.dumps({"hostname": "gw", "model": "GL.iNet GL-MT6000",
                         "release": {"distribution": "OpenWrt", "version": "24.10.0", "revision": "r28427"}}),
    "info": json.dumps({"uptime": 93784, "load": [6144, 4096, 2048],
                        "memory": {"total": 1048576000, "free": 600000000, "available": 700000000, "buffered": 1000}}),
    "ifaces": json.dumps({"interface": [
        {"interface": "lan", "up": True, "proto": "static", "l3_device": "br-lan",
         "ipv4-address": [{"address": "192.168.1.1", "mask": 24}]},
        {"interface": "wan", "up": True, "proto": "dhcp", "l3_device": "eth1",
         "ipv4-address": [{"address": "203.0.113.7", "mask": 24}]},
        {"interface": "loopback", "up": True}]}),
    "leases": "1767225600 aa:bb:cc:dd:ee:01 192.168.1.20 laptop 01:aa:bb:cc:dd:ee:01\n"
              "0 aa:bb:cc:dd:ee:02 192.168.1.21 * *\n",
    "load": "0.09 0.06 0.03 1/120 4242\n",
}
OPKG = "luci-base - 24.1.1-r1 - 24.2.0-r1\nopenssl-util - 3.0.15-1 - 3.0.16-1\n"
APK = "dnsmasq-2.91-r1 aarch64_cortex-a53 {dnsmasq} (GPL-2.0) [upgradable from: dnsmasq-2.90-r4]\n"
ISC = """lease 192.168.10.50 {
  starts 4 2026/10/08 10:00:00;
  ends 4 2026/10/08 22:00:00;
  binding state active;
  hardware ethernet 00:11:22:33:44:55;
  client-hostname "printer";
}
lease 192.168.10.51 {
  binding state free;
  hardware ethernet 00:11:22:33:44:66;
}
"""
KEA = ("address,hwaddr,client_id,valid_lifetime,expire,subnet_id,fqdn_fwd,fqdn_rev,hostname,state,user_context\n"
       "10.0.0.20,00:aa:bb:cc:dd:01,,3600,1767225600,1,0,0,nas.,0,\n"
       "10.0.0.21,00:aa:bb:cc:dd:02,,3600,1767225600,1,0,0,old.,2,\n")
BSD_IFCONFIG = """igb0: flags=1008843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST,LOWER_UP> metric 0 mtu 1500
\tether 00:0d:b9:aa:bb:cc
\tinet 203.0.113.2 netmask 0xffffff00 broadcast 203.0.113.255
\tstatus: active
igb1: flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> metric 0 mtu 1500
\tether 00:0d:b9:aa:bb:cd
\tinet 192.168.10.1 netmask 0xffffff00 broadcast 192.168.10.255
\tstatus: no carrier
lo0: flags=1008049<UP,LOOPBACK,RUNNING,MULTICAST,LOWER_UP> metric 0 mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
"""
BUSYBOX_IFCONFIG = """br0       Link encap:Ethernet  HWaddr 14:DD:A9:11:22:33
          inet addr:192.168.1.1  Bcast:192.168.1.255  Mask:255.255.255.0
          UP BROADCAST RUNNING MULTICAST  MTU:1500  Metric:1

lo        Link encap:Local Loopback
          inet addr:127.0.0.1  Mask:255.0.0.0
          UP LOOPBACK RUNNING  MTU:65536  Metric:1
"""
IP_JSON = json.dumps([
    {"ifname": "lo", "flags": ["LOOPBACK", "UP"], "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
    {"ifname": "eth0", "flags": ["BROADCAST", "UP", "LOWER_UP"], "operstate": "UP", "address": "52:54:00:12:34:56",
     "addr_info": [{"family": "inet", "local": "10.0.0.1", "prefixlen": 24}]},
    {"ifname": "eth1", "flags": ["BROADCAST"], "operstate": "DOWN", "address": "52:54:00:12:34:57", "addr_info": []}])
MEMINFO = "MemTotal:        2048000 kB\nMemFree:          512000 kB\nMemAvailable:    1024000 kB\n"
ROS_RESOURCE = ("                   uptime: 2w3d04:05:06\r\n                  version: 7.16.1 (stable)\r\n"
                "              free-memory: 800.5MiB\r\n             total-memory: 1024.0MiB\r\n"
                "                 cpu-load: 3%\r\n               board-name: RB5009UG+S+\r\n")
ROS_IFACES = (" 0  R  name=ether1 default-name=ether1 type=ether mtu=1500 mac-address=48:A9:8A:00:00:01\r\n"
              " 1  X  name=ether2 default-name=ether2 type=ether mtu=1500 mac-address=48:A9:8A:00:00:02\r\n")
ROS_ADDR = " 0   address=192.168.88.1/24 network=192.168.88.0 interface=ether1 actual-interface=ether1\r\n"
ROS_LEASES = " 0 D address=192.168.88.10 mac-address=AA:00:00:00:00:10 host-name=phone status=bound\r\n"


class FakeChannel:
    def shutdown_write(self):
        pass


class FakeStdin:
    def __init__(self, sent):
        self.sent = sent
        self.channel = FakeChannel()

    def write(self, data):
        self.sent.append(data)


class FakeSSH:
    """Answers exec_command from a {command-substring: output} table and records every command."""

    def __init__(self, answers):
        self.answers = answers
        self.commands = []
        self.stdin = []

    def exec_command(self, command, timeout=None):
        self.commands.append(command)
        out = b""
        for key, value in self.answers.items():
            if key in command:
                out = value if isinstance(value, bytes) else value.encode()
                break
        return FakeStdin(self.stdin), io.BytesIO(out), io.BytesIO(b"")

    def close(self):
        pass


def _sections(parts):
    return "".join(f"@@fp:{k}\n{v}\n" for k, v in parts.items())


@pytest.fixture
def fake_ssh(monkeypatch):
    holder = {}

    def enter(self):
        self.client = holder["client"]
        return self
    monkeypatch.setattr(rm._SshDriver, "__enter__", enter)

    def use(answers):
        holder["client"] = FakeSSH(answers)
        return holder["client"]
    return use


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "_DATA_DIR", str(tmp_path))
    rm.init_db()
    sent = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: sent.append(a))
    return sent


# ── Parsers ──────────────────────────────────────────────────────────────────

def test_lease_parsers():
    leases = rm.parse_dnsmasq_leases(OPENWRT["leases"])
    assert leases[0] == {"mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.1.20", "hostname": "laptop", "expires": 1767225600}
    assert leases[1]["hostname"] == "" and leases[1]["expires"] is None
    isc = rm.parse_isc_leases(ISC)
    assert [c["ip"] for c in isc] == ["192.168.10.50"] and isc[0]["hostname"] == "printer"
    kea = rm.parse_kea_csv(KEA)
    assert [(c["ip"], c["hostname"]) for c in kea] == [("10.0.0.20", "nas")]


def test_interface_parsers():
    bsd = rm.parse_bsd_ifconfig(BSD_IFCONFIG)
    assert [(i["name"], i["up"], i["ipv4"]) for i in bsd] == [
        ("igb0", True, ["203.0.113.2/24"]), ("igb1", False, ["192.168.10.1/24"])]
    bb = rm.parse_linux_ifconfig(BUSYBOX_IFCONFIG)
    assert bb == [{"name": "br0", "up": True, "mac": "14:dd:a9:11:22:33", "ipv4": ["192.168.1.1/24"]}]
    ipj = rm.parse_ip_json(IP_JSON)
    assert [(i["name"], i["up"], i["ipv4"]) for i in ipj] == [("eth0", True, ["10.0.0.1/24"]), ("eth1", False, [])]
    ow = rm.parse_openwrt_interfaces(OPENWRT["ifaces"])
    assert [(i["name"], i["device"], i["ipv4"]) for i in ow] == [
        ("lan", "br-lan", ["192.168.1.1/24"]), ("wan", "eth1", ["203.0.113.7/24"])]


def test_update_and_routeros_parsers():
    assert rm.parse_opkg_upgradable(OPKG) == ["luci-base: 24.1.1-r1 → 24.2.0-r1", "openssl-util: 3.0.15-1 → 3.0.16-1"]
    assert rm.parse_opkg_upgradable(APK) == ["dnsmasq-2.90-r4 → dnsmasq-2.91-r1"]
    assert rm.parse_routeros_uptime("2w3d04:05:06") == 2 * 604800 + 3 * 86400 + 4 * 3600 + 5 * 60 + 6
    assert rm.parse_routeros_uptime("1d2h3m4s") == 93784
    assert rm.parse_routeros_size("1024.0MiB") == 1024 ** 3
    rows = rm.parse_routeros_terse(ROS_IFACES)
    assert rows[0]["name"] == "ether1" and rows[0]["_flags"] == "R" and rows[1]["_flags"] == "X"


# ── Drivers against simulated routers ────────────────────────────────────────

def _router(platform, **extra):
    fields = dict(name=f"{platform}-gw", platform=platform, host="192.0.2.1", username="", **extra)
    if platform == "opnsense":
        fields.update(api_key="key", api_secret="secret", port=443)
    return rm.add_router(fields)


def test_openwrt_status_updates_backup(fake_ssh):
    rid = _router("openwrt")
    fake_ssh({"ubus call system board": _sections(OPENWRT), "apk list": OPKG,
                    "sysupgrade -b": b"\x1f\x8b" + b"\x00" * 200})
    st = rm.poll(rid)
    assert st["online"] and st["model"] == "GL.iNet GL-MT6000" and st["firmware"] == "OpenWrt 24.10.0 r28427"
    assert st["uptime"] == 93784 and st["mem_used"] == 1048576000 - 700000000 and len(st["clients"]) == 2
    assert rm.check_updates(rid)["count"] == 2
    name = rm.backup(rid)
    with open(os.path.join(rm._backup_dir(), name), "rb") as fh:
        raw = fh.read()
    assert b"\x1f\x8b" not in raw                       # stored encrypted
    assert rm.read_backup(rid, name)[1].startswith(b"\x1f\x8b")
    assert rm.read_backup(rid, "../" + name) is None


def test_commands_never_contain_router_data(fake_ssh):
    rid = rm.add_router(dict(name="evil; reboot", platform="openwrt", host="192.0.2.9", username="root",
                             notes="$(rm -rf /)"))
    ssh = fake_ssh({"ubus call system board": _sections(OPENWRT)})
    rm.poll(rid)
    assert ssh.commands == [rm._OPENWRT_STATUS]


def test_pfsense_driver(fake_ssh):
    rid = _router("pfsense")
    now = int(time.time())
    fake_ssh({"cat /etc/version": _sections({
        "version": "2.7.2-RELEASE", "uname": "FreeBSD 14.0-CURRENT amd64", "hostname": "fw.lan",
        "boottime": f"{{ sec = {now - 7200}, usec = 0 }} Thu Oct  8 10:00:00 2026", "now": str(now),
        "load": "{ 0.10 0.20 0.30 }", "physmem": "8589934592", "freemem": "1000000\n500000\n4096",
        "model": "Intel(R) Atom(TM) C3558", "ifconfig": BSD_IFCONFIG, "isc": ISC, "kea": ""}),
        "pfSense-upgrade": "2.8.0 version of pfSense is available\n"})
    st = rm.poll(rid)
    assert st["firmware"] == "pfSense 2.7.2-RELEASE" and st["uptime"] == 7200 and st["load"] == [0.1, 0.2, 0.3]
    assert st["mem_used"] == 8589934592 - 1500000 * 4096 and st["clients"][0]["hostname"] == "printer"
    assert rm.check_updates(rid)["items"] == ["pfSense 2.8.0"]


def test_vyos_and_ipfire_drivers(fake_ssh):
    rid = _router("vyos")
    fake_ssh({"/etc/os-release": _sections({"os": 'PRETTY_NAME="Debian GNU/Linux 12"', "vyos": '{"version": "1.4.1"}',
                                            "hostname": "vyos", "uptime": "3600.5 100.0", "load": "0.5 0.4 0.3",
                                            "mem": MEMINFO, "ip": IP_JSON, "kea": KEA}),
              "config.boot": "interfaces {\n ethernet eth0 {\n }\n}\n"})
    st = rm.poll(rid)
    assert st["firmware"] == "VyOS 1.4.1" and st["mem_total"] == 2048000 * 1024 and st["clients"][0]["ip"] == "10.0.0.20"
    assert rm.read_backup(rid, rm.backup(rid))[1].startswith(b"interfaces")
    with pytest.raises(ValueError):
        rm.check_updates(rid)
    rid2 = _router("linux")
    fake_ssh({"/etc/os-release": _sections({"os": "IPFire 2.29 (x86_64) - core188", "hostname": "ipfire",
                                            "uptime": "60", "mem": MEMINFO, "ip": IP_JSON, "isc": ISC})})
    st = rm.poll(rid2)
    assert st["firmware"] == "IPFire 2.29 (x86_64) - core188" and st["clients"][0]["hostname"] == "printer"
    with pytest.raises(ValueError):
        rm.backup(rid2)


def test_ddwrt_and_routeros_drivers(fake_ssh):
    rid = _router("ddwrt")
    fake_ssh({"nvram get DD_BOARD": _sections({"model": "Netgear R7000", "firmware": "DD-WRT v3.0-r58819",
                                               "hostname": "ddwrt", "uptime": "120", "mem": MEMINFO,
                                               "ifconfig": BUSYBOX_IFCONFIG, "leases": OPENWRT["leases"]})})
    st = rm.poll(rid)
    assert st["model"] == "Netgear R7000" and st["interfaces"][0]["name"] == "br0" and len(st["clients"]) == 2

    rid = _router("routeros")
    ssh = fake_ssh({"/system resource print": ROS_RESOURCE, "/system identity print": "  name: core-router\r\n",
                    "/system routerboard print": "  model: RB5009UG+S+IN\r\n", "/ip address print": ROS_ADDR,
                    "/interface print": ROS_IFACES, "/ip dhcp-server lease print": ROS_LEASES,
                    "check-for-updates": "  channel: stable\r\n  installed-version: 7.16.1\r\n  latest-version: 7.16.2\r\n"
                                         "  status: New version is available\r\n"})
    st = rm.poll(rid)
    assert st["hostname"] == "core-router" and st["model"] == "RB5009UG+S+IN" and st["firmware"].startswith("RouterOS 7.16.1")
    assert st["interfaces"][0]["ipv4"] == ["192.168.88.1/24"] and not st["interfaces"][1]["up"]
    assert st["clients"][0]["hostname"] == "phone" and st["load"] == [0.03]
    assert rm.check_updates(rid)["items"] == ["RouterOS 7.16.1 → 7.16.2"]
    rm.reboot(rid)
    assert ssh.stdin == [b"y\n"]


class FakeResponse:
    def __init__(self, status=200, data=None, content=b""):
        self.status_code, self._data, self.content = status, data, content

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_opnsense_api_driver(monkeypatch):
    rid = _router("opnsense")
    calls = []
    answers = {
        "/api/diagnostics/system/system_information": {"name": "opnsense.lan", "versions": ["OPNsense 25.7.4-amd64", "FreeBSD 14.3"]},
        "/api/diagnostics/system/system_time": {"loadavg": "0.20, 0.15, 0.10"},
        "/api/diagnostics/system/system_resources": {"memory": {"total": "8000000000", "used": "2000000000"}},
        "/api/interfaces/overview/interfaces_info": {"rows": [{"identifier": "lan", "description": "LAN", "device": "igc1",
                                                              "status": "up", "addr4": "192.168.1.1/24", "macaddr": "aa:bb"}]},
        "/api/dhcpv4/leases/search_lease": {"rows": [{"address": "192.168.1.30", "mac": "AA:BB:CC:00:00:30", "hostname": "tv"}]},
        "/api/core/firmware/check": {"status": "ok"},
        "/api/core/firmware/status": {"status": "update", "status_msg": "There are 1 updates available.",
                                      "upgrade_packages": [{"name": "opnsense", "current_version": "25.7.4", "new_version": "25.7.5"}]},
    }

    def fake_request(method, url, **kw):
        path = url.split(":443", 1)[1]
        calls.append((method, path, kw.get("auth"), kw.get("verify"), kw.get("allow_redirects")))
        if path == "/api/core/backup/download/this":
            return FakeResponse(content=b"<?xml version='1.0'?><opnsense></opnsense>")
        return FakeResponse(data=answers[path]) if path in answers else FakeResponse(status=404)
    import requests
    monkeypatch.setattr(requests, "request", fake_request)
    monkeypatch.setattr(rm.time, "sleep", lambda s: None)
    st = rm.poll(rid)
    assert st["online"] and st["firmware"] == "OPNsense 25.7.4-amd64" and st["load"] == [0.2, 0.15, 0.1]
    assert st["interfaces"][0]["name"] == "LAN" and st["clients"][0]["mac"] == "aa:bb:cc:00:00:30"
    assert calls[0][2] == ("key", "secret") and calls[0][3] is False and calls[0][4] is False
    assert rm.check_updates(rid)["items"] == ["opnsense: 25.7.4 → 25.7.5"]
    assert rm.read_backup(rid, rm.backup(rid))[1].startswith(b"<?xml")


# ── Storage, validation and notifications ────────────────────────────────────

def test_validation_and_encrypted_secrets(tmp_path):
    for bad in ({"host": "a;reboot"}, {"host": "192.0.2.1", "port": "99999"}, {"host": "x", "username": "root;id"},
                {"host": "x", "platform": "cisco"}):
        with pytest.raises(ValueError):
            rm.add_router(dict({"name": "bad", "platform": "openwrt", "host": "x"}, **bad))
    with pytest.raises(ValueError):
        rm.add_router({"name": "o", "platform": "opnsense", "host": "fw"})     # API key required
    rid = rm.add_router({"name": "sec", "platform": "openwrt", "host": "gw.lan", "password": "wifi-secret-123"})
    con = sqlite3.connect(os.path.join(str(tmp_path), "router_manager.db"))
    raw = con.execute("SELECT * FROM routers").fetchall()
    con.close()
    assert "wifi-secret-123" not in repr(raw)
    assert rm.get_router(rid, secrets=True)["password"] == "wifi-secret-123"
    assert rm.get_router(rid)["password"] == ""


def test_offline_and_back_online_are_reported(fake_ssh, monkeypatch, _db):
    rid = _router("openwrt")
    fake_ssh({"ubus call system board": _sections(OPENWRT)})
    rm.poll(rid)

    def fail(self):
        raise TimeoutError("timed out talking to 192.0.2.1 with password hunter2")
    monkeypatch.setattr(rm._SshDriver, "__enter__", fail)
    st = rm.poll(rid)
    assert not st["online"] and "hunter2" not in st["error"]
    assert any("offline" in a[1] for a in _db)


def test_old_backups_are_pruned(fake_ssh, monkeypatch):
    rid = _router("vyos")
    fake_ssh({"config.boot": "interfaces { }\n" * 3})
    stamps = iter(range(20))

    class Clock:
        @staticmethod
        def now():
            from datetime import datetime
            return datetime(2026, 1, 1, 0, 0, next(stamps))
    monkeypatch.setattr(rm, "datetime", type("D", (), {"now": Clock.now, "strptime": __import__("datetime").datetime.strptime}))
    for _ in range(rm.KEEP_BACKUPS + 3):
        rm.backup(rid)
    assert len(rm.list_backups(rid)) == rm.KEEP_BACKUPS


# ── Web routes and permissions ───────────────────────────────────────────────

def _login(client, name, role):
    user = user_management.get_user(name)
    uid = user["id"] if user else user_management.create_user(name, "router-test-passphrase", None, [role])
    with client.session_transaction() as s:
        s.update(user_id=uid, username=name, pw_tag=fp._password_tag(user_management.get_user_by_id(uid)),
                 sid=account_security.create_session(uid), auth_time=time.time())


def test_router_pages_and_permissions(fake_ssh, monkeypatch):
    fp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    user_management.init_user_db()
    account_security.init_db()
    fake_ssh({"ubus call system board": _sections(OPENWRT), "sysupgrade -b": b"\x1f\x8b" + b"\x00" * 64})
    admin, viewer, operator = fp.app.test_client(), fp.app.test_client(), fp.app.test_client()
    _login(admin, "router_admin", "admin")
    _login(viewer, "router_viewer", "viewer")
    _login(operator, "router_operator", "operator")
    try:
        r = admin.post("/routers/add", data={"name": "home", "platform": "openwrt", "host": "192.168.1.1",
                                             "username": "root", "password": "pw-for-router"})
        rid = int(r.headers["Location"].rsplit("/", 1)[1])
        for c in (admin, viewer, operator):
            assert c.get("/routers").status_code == 200
            page = c.get(f"/routers/{rid}").get_data(as_text=True)
            assert "GL.iNet GL-MT6000" in page and "laptop" in page and "pw-for-router" not in page
        assert viewer.post("/routers/add", data={"name": "x", "platform": "openwrt", "host": "1.2.3.4"}).status_code == 302
        assert len(rm.list_routers()) == 1
        assert viewer.post(f"/routers/{rid}/backup").status_code == 302 and not rm.list_backups(rid)
        operator.post(f"/routers/{rid}/backup")
        name = rm.list_backups(rid)[0]["name"]
        assert operator.get(f"/routers/{rid}/backups/{name}").status_code == 302      # admins only
        r = admin.get(f"/routers/{rid}/backups/{name}")
        assert r.status_code == 200 and r.data.startswith(b"\x1f\x8b") and "attachment" in r.headers["Content-Disposition"]
        assert operator.post(f"/routers/{rid}/reboot", data={"confirm": "home"}).status_code == 302
        admin.post(f"/routers/{rid}/reboot", data={"confirm": "wrong"})
        # A router that was never reached must still render.
        offline = rm.add_router({"name": "never-seen", "platform": "opnsense", "host": "192.0.2.77",
                                 "api_key": "k", "api_secret": "s"})
        rm._save_status(offline, {"online": False, "checked_at": time.time(), "error": "unreachable"})
        assert viewer.get(f"/routers/{offline}").status_code == 200
        never = rm.add_router({"name": "brand-new", "platform": "vyos", "host": "192.0.2.78"})
        assert viewer.get(f"/routers/{never}").status_code == 200
        assert viewer.get("/routers").status_code == 200
        api = [r for r in viewer.get("/api/routers").get_json()["routers"] if r["name"] == "home"][0]
        assert api["name"] == "home" and api["clients"] == 2 and "password" not in json.dumps(api)
        assert "fleetpilot_router_up{" in fp.metrics.render({}, {}, None, None, None, rm)
    finally:
        fp.app.config["WTF_CSRF_ENABLED"] = True


# ── AVM FRITZ!Box / FRITZ!Repeater (TR-064) and other repeaters ──────────────

def _soap(action, values):
    body = "".join(f"<{k}>{v}</{k}>" for k, v in values.items())
    return (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            f'<u:{action}Response xmlns:u="urn:dslforum-org:service:X:1">{body}</u:{action}Response></s:Body></s:Envelope>')


FRITZ_HOSTS = """<?xml version="1.0" encoding="utf-8"?><List>
<Item><Index>1</Index><IPAddress>192.168.178.20</IPAddress><MACAddress>AA:BB:CC:00:00:20</MACAddress>
<Active>1</Active><HostName>laptop</HostName><InterfaceType>802.11</InterfaceType></Item>
<Item><Index>2</Index><IPAddress>192.168.178.21</IPAddress><MACAddress>AA:BB:CC:00:00:21</MACAddress>
<Active>1</Active><HostName>nas</HostName><InterfaceType>Ethernet</InterfaceType></Item>
<Item><Index>3</Index><IPAddress>192.168.178.22</IPAddress><MACAddress>AA:BB:CC:00:00:22</MACAddress>
<Active>0</Active><HostName>old-phone</HostName><InterfaceType>802.11</InterfaceType></Item></List>"""
FRITZ_MESH = json.dumps({"nodes": [
    {"device_name": "fritz.box", "device_model": "FRITZ!Box 7590 AX", "is_meshed": True, "mesh_role": "master",
     "device_firmware_version": "8.02", "node_interfaces": [{"type": "LAN", "node_links": [{"state": "CONNECTED"}]}]},
    {"device_name": "Repeater Flur", "device_model": "FRITZ!Repeater 3000 AX", "is_meshed": True, "mesh_role": "slave",
     "device_firmware_version": "8.02", "node_interfaces": [{"type": "WLAN", "node_links": [{"state": "CONNECTED"}]}]},
    {"device_name": "phone", "is_meshed": False}]})


def test_tr064_messages_and_parsers():
    body = rm.soap_body("X_AVM-DE_GetConfigFile", "urn:dslforum-org:service:DeviceConfig:1",
                        {"NewX_AVM-DE_Password": "a<b&c"})
    assert "<NewX_AVM-DE_Password>a&lt;b&amp;c</NewX_AVM-DE_Password>" in body
    assert rm.parse_soap_response(_soap("GetInfo", {"NewModelName": "FRITZ!Box 7590", "NewUpTime": "100"})) == {
        "NewModelName": "FRITZ!Box 7590", "NewUpTime": "100"}
    clients = rm.parse_fritz_hostlist(FRITZ_HOSTS)
    assert [(c["hostname"], c["connection"]) for c in clients] == [("laptop", "Wi-Fi"), ("nas", "Ethernet")]
    mesh = rm.parse_fritz_mesh(FRITZ_MESH)
    assert [(m["name"], m["role"], m["connection"]) for m in mesh] == [
        ("fritz.box", "Mesh master", "LAN"), ("Repeater Flur", "Mesh repeater", "Wi-Fi")]
    with pytest.raises(ValueError):   # no entity expansion from device XML
        rm.parse_soap_response('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')


class _FakeFritz:
    """Answers TR-064 SOAP calls like a FRITZ!Box 7590 (or a repeater when wan=False)."""

    def __init__(self, wan=True, update=False):
        self.wan, self.update, self.calls = wan, update, []

    def post(self, url, data=None, headers=None, auth=None, verify=None, timeout=None, allow_redirects=None):
        action = headers["SOAPAction"].strip('"').split("#")[1]
        path = url.split(":49443", 1)[1]
        self.calls.append((path, action, type(auth).__name__, verify, allow_redirects))
        answers = {
            ("/upnp/control/deviceinfo", "GetInfo"): {"NewModelName": "FRITZ!Box 7590 AX" if self.wan else "FRITZ!Repeater 3000 AX",
                                                      "NewSoftwareVersion": "8.02", "NewUpTime": "86400",
                                                      "NewSerialNumber": "ABC123", "NewDescription": "FRITZ!Box 7590 AX 8.02"},
            ("/upnp/control/wlanconfig1", "GetInfo"): {"NewEnable": "1", "NewSSID": "Home", "NewChannel": "6",
                                                       "NewBSSID": "AA:00:00:00:00:01", "NewStatus": "Up"},
            ("/upnp/control/wlanconfig1", "GetTotalAssociations"): {"NewTotalAssociations": "5"},
            ("/upnp/control/wlanconfig2", "GetInfo"): {"NewEnable": "0", "NewSSID": "Home-5G", "NewChannel": "36"},
            ("/upnp/control/wlanconfig2", "GetTotalAssociations"): {"NewTotalAssociations": "0"},
            ("/upnp/control/hosts", "X_AVM-DE_GetHostListPath"): {"NewX_AVM-DE_HostListPath": "/devicehostlist.lua?sid=1"},
            ("/upnp/control/hosts", "X_AVM-DE_GetMeshListPath"): {"NewX_AVM-DE_MeshListPath": "/meshlist.lua?sid=1"},
            ("/upnp/control/userif", "GetInfo"): {"NewUpgradeAvailable": "1" if self.update else "0",
                                                  "NewX_AVM-DE_Version": "8.10"},
            ("/upnp/control/deviceconfig", "X_AVM-DE_GetConfigFile"):
                {"NewX_AVM-DE_ConfigFileUrl": "https://192.168.178.1:49443/tmp/config.export?sid=1"},
            ("/upnp/control/deviceconfig", "Reboot"): {},
        }
        if self.wan:
            answers.update({
                ("/upnp/control/wancommonifconfig1", "GetCommonLinkProperties"): {
                    "NewWANAccessType": "DSL", "NewPhysicalLinkStatus": "Up",
                    "NewLayer1DownstreamMaxBitRate": "250000000", "NewLayer1UpstreamMaxBitRate": "40000000"},
                ("/upnp/control/wanpppconn1", "GetInfo"): {"NewConnectionStatus": "Connected", "NewUptime": "3600"},
                ("/upnp/control/wanpppconn1", "GetExternalIPAddress"): {"NewExternalIPAddress": "198.51.100.5"},
            })
        if (path, action) not in answers:
            return FakeResponse(status=500, data=None)
        resp = FakeResponse(data={})
        resp.text = _soap(action, answers[(path, action)])
        return resp

    def get(self, url, auth=None, verify=None, timeout=None, allow_redirects=None):
        resp = FakeResponse()
        if "devicehostlist" in url:
            resp.text = FRITZ_HOSTS
        elif "meshlist" in url:
            resp.text = FRITZ_MESH
        elif "config.export" in url:
            resp.content = b"**** FRITZ!Box Configuration File\n" + b"x" * 100
        return resp


def test_fritzbox_driver(monkeypatch):
    import requests
    fake = _FakeFritz(update=True)
    monkeypatch.setattr(requests, "post", fake.post)
    monkeypatch.setattr(requests, "get", fake.get)
    rid = rm.add_router({"name": "FRITZ!Box", "platform": "fritzbox", "host": "192.168.178.1",
                         "username": "fleetpilot", "password": "box-pass-123"})
    st = rm.poll(rid)
    assert st["online"] and st["model"] == "FRITZ!Box 7590 AX" and st["firmware"] == "FRITZ!OS 8.02"
    assert st["wan"] == {"access": "DSL", "link": "Up", "down_kbps": 250000, "up_kbps": 40000,
                         "status": "Connected", "external_ip": "198.51.100.5", "uptime": 3600}
    assert [(i["name"], i["up"], i["clients"]) for i in st["interfaces"]] == [("Wi-Fi 2.4 GHz", True, 5), ("Wi-Fi 5 GHz", False, 0)]
    assert len(st["clients"]) == 2 and st["mesh"][1]["name"] == "Repeater Flur"
    assert all(c[2] == "HTTPDigestAuth" and c[3] is False and c[4] is False for c in fake.calls)
    assert rm.check_updates(rid)["items"] == ["FRITZ!OS 8.10"]
    name = rm.backup(rid)
    assert rm.read_backup(rid, name)[1].startswith(b"**** FRITZ!Box")
    assert any(c[1] == "X_AVM-DE_GetConfigFile" for c in fake.calls)
    rm.reboot(rid)
    assert fake.calls[-1][1] == "Reboot"


def test_fritz_repeater_without_internet_services(monkeypatch):
    import requests
    fake = _FakeFritz(wan=False)
    monkeypatch.setattr(requests, "post", fake.post)
    monkeypatch.setattr(requests, "get", fake.get)
    rid = rm.add_router({"name": "Repeater", "platform": "fritzrepeater", "host": "192.168.178.30",
                         "password": "rep-pass-123"})
    assert rm.get_router(rid)["role"] == "repeater"
    st = rm.poll(rid)
    assert st["online"] and "wan" not in st and st["model"] == "FRITZ!Repeater 3000 AX"
    assert rm.check_updates(rid)["count"] == 0


def test_fritz_refuses_files_from_other_hosts(monkeypatch):
    import requests
    fake = _FakeFritz()
    monkeypatch.setattr(requests, "post", lambda *a, **k: _redirect_config(fake, *a, **k))
    monkeypatch.setattr(requests, "get", fake.get)
    rid = rm.add_router({"name": "box", "platform": "fritzbox", "host": "192.168.178.1", "password": "x-pass-123"})
    with pytest.raises(ValueError):
        rm.backup(rid)


def _redirect_config(fake, url, **kw):
    resp = fake.post(url, **kw)
    if "X_AVM-DE_GetConfigFile" in kw["headers"]["SOAPAction"]:
        resp.text = _soap("X_AVM-DE_GetConfigFile", {"NewX_AVM-DE_ConfigFileUrl": "https://evil.example/steal"})
    return resp


def test_fritz_needs_a_password_and_rejects_bad_login(monkeypatch):
    with pytest.raises(ValueError):
        rm.add_router({"name": "nopass", "platform": "fritzbox", "host": "192.168.178.1"})
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(status=401))
    rid = rm.add_router({"name": "wrong", "platform": "fritzbox", "host": "192.168.178.1", "password": "wrong-pass"})
    st = rm.poll(rid)
    assert not st["online"] and "rejected" in st["error"]


def test_generic_repeater_availability_check():
    import socket
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    rid = rm.add_router({"name": "TP-Link RE700X", "platform": "generic", "host": "127.0.0.1", "port": port})
    router = rm.get_router(rid)
    assert router["role"] == "repeater" and router["role_label"] == "Repeater"
    st = rm.poll(rid)
    assert st["online"] and st["latency_ms"] >= 0
    server.close()
    st = rm.poll(rid)
    assert not st["online"]
    with pytest.raises(ValueError):
        rm.reboot(rid)
    with pytest.raises(ValueError):
        rm.backup(rid)
    with pytest.raises(ValueError):
        rm.add_router({"name": "bad role", "platform": "generic", "host": "127.0.0.1", "role": "toaster"})


def test_fritz_and_repeater_pages_render(monkeypatch):
    import requests
    fake = _FakeFritz()
    monkeypatch.setattr(requests, "post", fake.post)
    monkeypatch.setattr(requests, "get", fake.get)
    fp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    user_management.init_user_db()
    account_security.init_db()
    client = fp.app.test_client()
    _login(client, "fritz_admin", "admin")
    try:
        box = rm.add_router({"name": "FRITZ!Box 7590", "platform": "fritzbox", "host": "192.168.178.1",
                             "password": "box-pass-123"})
        rm.poll(box)
        page = client.get(f"/routers/{box}").get_data(as_text=True)
        for text in ("198.51.100.5", "Mesh", "Repeater Flur", "Wi-Fi 2.4 GHz", "5 devices", "TR-064"):
            assert text in page, text
        ap = rm.add_router({"name": "Garden AP", "platform": "generic", "host": "192.0.2.60", "role": "access_point"})
        page = client.get(f"/routers/{ap}").get_data(as_text=True)
        assert "Access point" in page and "Restart router" not in page
        listing = client.get("/routers").get_data(as_text=True)
        assert "Repeaters &amp; access points" in listing and "AVM FRITZ!Repeater" in listing
    finally:
        fp.app.config["WTF_CSRF_ENABLED"] = True
