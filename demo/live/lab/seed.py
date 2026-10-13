"""Configure the demo FleetPilot the way a homelab owner would, through FleetPilot's own functions.

Everything shown afterwards (status, disks, VMs, router details) is read from the
emulated devices by FleetPilot itself; nothing is written into its databases by hand
except older history, so the charts are not empty on the first visit.
"""
import datetime
import json
import random
import time

from .net import lab

HOSTS = {
    "pve-01": ("192.0.2.10", "root", "Proxmox VE node 1", "Virtualisation", "Production", "High",
               ["Server", "proxmox"], "Rack"),
    "pve-02": ("192.0.2.11", "root", "Proxmox VE node 2", "Virtualisation", "Production", "High",
               ["Server", "proxmox"], "Rack"),
    "nas": ("192.0.2.20", "root", "TrueNAS SCALE storage", "Storage", "Production", "Critical", ["NAS", "zfs"],
            "Rack"),
    "docker-01": ("192.0.2.30", "root", "Debian 13 · Docker host (VM 100)", "Services", "Production", "Medium",
                  ["VM", "docker"], "Rack"),
    "web-01": ("192.0.2.31", "admin", "Ubuntu 24.04 · nginx", "Services", "Production", "Medium",
               ["Web Server"], "Cloud"),
    "pihole": ("192.0.2.53", "pi", "Raspberry Pi 5 · DNS", "Network", "Production", "Medium",
               ["Raspberry Pi"], "Office"),
    "backup": ("192.0.2.40", "root", "Proxmox Backup Server", "Storage", "Production", "High", ["Backup"],
               "Basement"),
    "lab-01": ("192.0.2.60", "root", "Fedora 42 · test box (switched off)", "Lab", "Testing", "Low", ["PC"],
               "Office"),
    "win-desk": ("192.0.2.70", "admin", "Windows 11 workstation", "Clients", "Production", "Low", ["Workstation"],
                 "Office"),
}


def configure(fp):
    import backup_controller
    import email_config
    import fan_controller
    import notify
    import router_manager
    import storage_controller
    import user_management
    import vm_controller

    hosts = {}
    for name, (ip, user, desc, group, env, crit, tags, location) in HOSTS.items():
        device = lab.find(ip)
        hosts[name] = fp.normalize_host({
            "host": ip, "user": user, "mac": device.mac, "description": desc, "group": group,
            "location": location, "environment": env, "criticality": crit, "tags": tags,
            "os_type": {"pve-01": "proxmox", "pve-02": "proxmox", "win-desk": "windows"}.get(name, "linux"),
            "last_update": (datetime.datetime.now() - datetime.timedelta(days=random.randint(3, 20)))
            .strftime("%Y-%m-%d %H:%M:%S")})
    fp.save_hosts(hosts, discover_names=list(hosts))

    for fields in [
        {"name": "FRITZ!Box", "platform": "fritzbox", "host": "192.0.2.1", "port": 49443,
         "username": "fleetpilot", "password": "demo-password"},
        {"name": "Repeater upstairs", "platform": "fritzrepeater", "host": "192.0.2.2", "port": 49443,
         "username": "fleetpilot", "password": "demo-password", "role": "repeater"},
        {"name": "GL.iNet travel router", "platform": "openwrt", "host": "192.0.2.3", "port": 22,
         "username": "root", "password": "demo-password"},
        {"name": "OPNsense", "platform": "opnsense", "host": "192.0.2.254", "port": 443,
         "api_key": "demo-key", "api_secret": "demo-secret"},
    ]:
        router_id = router_manager.add_router(fields)
        router_manager.poll(router_id)

    vm_controller.add_endpoint("Proxmox cluster", "proxmox", "192.0.2.10", 8006, "root@pam", "demo-password")
    pbs = backup_controller.add_server("Proxmox Backup Server", "pbs", "192.0.2.40", 8007, "https",
                                       username="root@pam", password="demo-password")
    backup_controller.poll_server(pbs)
    storage_controller.add_endpoint("TrueNAS", "truenas", "192.0.2.20", 443, "1-demo-api-key")
    for name, ip in (("pve-01 case fans", "192.0.2.10"), ("nas fans", "192.0.2.20")):
        fan_controller.add_device(name, "lm_sensors", ip)

    notify.add_channel("Phone (ntfy)", "ntfy", "https://ntfy.sh/fleetpilot-demo",
                       ["smart", "security", "backup", "router", "vulnerability"], "info")
    email = email_config.load_email_settings()
    email.update(email_enabled=True, smtp_server="mail.lab.example", smtp_port=587, sender_email="fleetpilot@lab.example",
                 recipient_emails=["admin@lab.example"], smtp_username="fleetpilot", smtp_password="demo-password")
    email_config.save_email_settings(email)

    try:
        user_management.create_user("viewer", "viewer-demo-2026", roles=["viewer"])
    except Exception as exc:  # roles differ between versions; the demo works without this user
        print("[lab] viewer user:", exc)

    import hw_info
    for name, host in hosts.items():          # what "Refresh" on Hardware overview does
        if lab.find(host["host"]).powered and hw_info._collector:
            hw_info._collector.collect(host=host["host"], port=22, user=host["user"], server_name=name)

    smart_round()
    _history()

    import vuln_scanner                        # a first CVE scan, as if the owner had clicked "Scan now"
    vuln_scanner.set_setting("auto_scan", "1")
    vuln_scanner.scan_all(fp.load_hosts(), router_manager.list_routers())


def smart_round():
    """One SMART poll over every source, like FleetPilot's poll worker."""
    import smart_manager
    import storage_controller
    import vm_controller
    smart_manager.collect_all_local_disks()
    smart_manager.collect_all_ssh_hosts()
    for ep in vm_controller.list_endpoints():
        if ep.get("platform") == "proxmox":
            client = vm_controller.connect(ep["id"])
            for node in client.get_nodes():
                if node.get("status") == "online":
                    smart_manager.collect_proxmox_disks(ep["id"], node["node"])
    for ep in storage_controller.list_endpoints():
        smart_manager.collect_remote_storage_disks(ep["id"])


def _history():
    """Six hours of older samples, so the charts have a past."""
    import hw_monitor
    import system_monitor
    now = time.time()
    conn = hw_monitor.get_db()
    servers = [dict(r) for r in conn.execute("SELECT id, ip FROM hw_servers").fetchall()]
    for server in servers:
        machine = lab.find(server["ip"])
        if machine is None or not hasattr(machine, "cpu_pct") or not machine.powered:
            continue
        for i in range(72, 0, -1):
            t = now - i * 300
            wave = 1 + 0.5 * __import__("math").sin(t / 2400 + server["id"])
            cpu = round(min(99, machine.base_load * wave + random.uniform(-2, 2)), 1)
            conn.execute("INSERT INTO hw_history (server_id,ts,cpu_pct,cpu_temp,ram_used_mb,ram_total_mb,"
                         "net_rx_kbps,net_tx_kbps,disk_read_kbps,disk_write_kbps,gpu_temp) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (server["id"], datetime.datetime.fromtimestamp(t).isoformat(), cpu,
                          round(31 + cpu * 0.42 + 8, 1), int(machine.ram_mb * machine.ram_base),
                          machine.ram_mb, round(400 * wave, 1), round(160 * wave, 1),
                          round(900 * wave, 1), round(1400 * wave, 1), None))
    conn.commit()
    conn.close()
    me = lab.self_machine
    for i in range(72, 0, -1):
        t = int(now - i * 300)
        cpu = round(me.base_load * (1 + 0.4 * __import__("math").sin(t / 1800)) + random.uniform(-1, 1), 1)
        try:
            system_monitor._save({"ts": t, "cpu_pct": cpu, "cpu_freq": 2400.0, "ram_total": me.ram_mb * 2**20,
                                  "ram_used": int(me.ram_mb * 2**20 * 0.41), "ram_pct": 41.0,
                                  "swap_total": 2 * 2**30, "swap_used": 64 * 2**20,
                                  "disk_json": json.dumps([{"device": "/dev/vda1", "mountpoint": "/",
                                                            "fstype": "ext4", "total": 256 * 10**9,
                                                            "used": 41 * 10**9, "free": 215 * 10**9, "pct": 16.0}]),
                                  "net_json": json.dumps({}), "temp_json": json.dumps({})})
        except Exception as exc:
            print("[lab] system history:", exc)
            break
