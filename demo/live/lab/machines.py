# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Emulated machines: Linux and Windows servers with disks, packages, sensors and fans.

A machine answers the shell commands FleetPilot sends over SSH (or runs locally, for
the FleetPilot machine itself) with output in the format of the real tools.
"""
import base64
import json
import math
import random
import re
import shlex
import time


def _now():
    return time.time()


class Device:
    kind = "device"
    icon = "hdd-network"

    def __init__(self, name, ip, mac="", ports=(), dns_name=None, label="", uptime_days=12.0):
        self.name, self.ip, self.mac = name, ip, mac.lower()
        self.ports = set(ports)
        self.dns_name = dns_name or name
        self.label = label or name
        self.lab = None
        self.files = {}
        self._on = True
        self._down_until = 0.0
        self.booted_at = _now() - uptime_days * 86400
        self.rand = random.Random(sum(map(ord, name)))

    # ── Power ──
    @property
    def powered(self):
        return self._on and _now() >= self._down_until

    @property
    def state(self):
        if not self._on:
            return "off"
        return "booting" if _now() < self._down_until else "on"

    def uptime(self):
        return max(0.0, _now() - self.booted_at)

    def power_off(self, why="shut down"):
        if self._on:
            self._on = False
            self._log("power", f"{self.label} {why}")

    def power_on(self, why="powered on", boot_seconds=20):
        if not self._on:
            self._on = True
            self._down_until = _now() + boot_seconds
            self.booted_at = self._down_until
            self._log("power", f"{self.label} {why}, booting")

    def wake(self):
        if self._on:
            self._log("wol", f"Magic packet for {self.label}: already running")
        else:
            self.power_on("woken by Wake-on-LAN")

    def reboot(self, boot_seconds=25):
        self._down_until = _now() + boot_seconds
        self.booted_at = self._down_until
        self._log("power", f"{self.label} is rebooting")

    def _log(self, kind, text, quiet=False):
        if self.lab:
            self.lab.log(self, kind, text, quiet)

    # ── Lab hooks ──
    def advance(self, seconds):
        pass

    def tick(self):
        pass

    def http(self, method, port, path, query, headers, body):
        return None

    def summary(self):
        return {"name": self.name, "label": self.label, "ip": self.ip, "kind": self.kind, "icon": self.icon,
                "state": self.state, "facts": self.facts(), "actions": self.actions()}

    def facts(self):
        return []

    def actions(self):
        return [{"id": "off", "label": "Power off"}] if self._on else [{"id": "on", "label": "Power on"}]

    def act(self, action):
        if action == "off":
            self.power_off("was switched off in the lab")
        elif action == "on":
            self.power_on()
        else:
            return False
        return True


# ── Disks ────────────────────────────────────────────────────────────────────

class Disk:
    def __init__(self, dev, model, serial, size_gb, temp=35, poh=8000, realloc=0, pending=0, nvme=False,
                 rotational=None, firmware="1.0"):
        self.dev, self.model, self.serial, self.size_gb = dev, model, serial, size_gb
        self.temp, self.poh, self.realloc, self.pending = temp, poh, realloc, pending
        self.nvme = nvme
        self.rotational = (not nvme and "SSD" not in model) if rotational is None else rotational
        self.firmware = firmware
        self.failed = False

    @property
    def bytes(self):
        return int(self.size_gb * 10**9)

    def size_text(self):
        return f"{self.size_gb / 1000:.1f}T" if self.size_gb >= 1000 else f"{self.size_gb}G"

    def health(self):
        if self.failed:
            return "FAILED"
        return "worn" if self.realloc or self.pending else "healthy"

    def degrade(self):
        self.realloc += 24 + self.pending
        self.pending += 8

    def smartctl_i(self):
        head = ["smartctl 7.4 2023-08-01 r5530 [x86_64-linux-6.8.12-4-pve] (local build)",
                "Copyright (C) 2002-23, Bruce Allen, Christian Franke, www.smartmontools.org", "",
                "=== START OF INFORMATION SECTION ==="]
        if self.nvme:
            head += [f"Model Number:                       {self.model}",
                     f"Serial Number:                      {self.serial}",
                     f"Firmware Version:                   {self.firmware}",
                     f"Total NVM Capacity:                 {self.bytes:,} [{self.size_gb / 1000:.2f} TB]"]
        else:
            head += [f"Device Model:     {self.model}",
                     f"Serial Number:    {self.serial}",
                     f"Firmware Version: {self.firmware}",
                     f"User Capacity:    {self.bytes:,} bytes [{self.size_gb / 1000:.2f} TB]",
                     "Sector Sizes:     512 bytes logical, 4096 bytes physical",
                     f"Rotation Rate:    {'7200 rpm' if self.rotational else 'Solid State Device'}",
                     "SMART support is: Available - device has SMART capability.",
                     "SMART support is: Enabled"]
        return "\n".join(head) + "\n"

    def smartctl_a(self, ambient=0.0):
        temp = round(self.temp + ambient)
        verdict = "FAILED!" if self.failed else "PASSED"
        out = self.smartctl_i() + "\n=== START OF READ SMART DATA SECTION ===\n"
        out += f"SMART overall-health self-assessment test result: {verdict.rstrip('!')}\n\n"
        if self.nvme:
            out += ("SMART/Health Information (NVMe Log 0x02)\n"
                    f"Critical Warning:                   0x00\n"
                    f"Temperature:                        {temp} Celsius\n"
                    f"Available Spare:                    100%\n"
                    f"Percentage Used:                    {min(99, self.poh // 900)}%\n"
                    f"Data Units Written:                 {self.poh * 9_100:,} [{self.poh * 4.6 / 1000:.1f} TB]\n"
                    f"Power Cycles:                       {60 + self.poh // 400}\n"
                    f"Power On Hours:                     {self.poh:,}\n"
                    f"Unsafe Shutdowns:                   7\n"
                    f"Media and Data Integrity Errors:    {self.realloc}\n")
            return out
        value = lambda base, bad: max(1, base - bad)  # noqa: E731
        rows = [
            (1, "Raw_Read_Error_Rate", "0x002f", 200, 200, 51, "Pre-fail", 0),
            (3, "Spin_Up_Time", "0x0027", 178, 175, 21, "Pre-fail", 6091),
            (4, "Start_Stop_Count", "0x0032", 100, 100, 0, "Old_age", 112),
            (5, "Reallocated_Sector_Ct", "0x0033", value(200, self.realloc // 4), value(200, self.realloc // 4),
             140, "Pre-fail", self.realloc),
            (9, "Power_On_Hours", "0x0032", max(1, 100 - self.poh // 1000), max(1, 100 - self.poh // 1000), 0,
             "Old_age", self.poh),
            (12, "Power_Cycle_Count", "0x0032", 100, 100, 0, "Old_age", 60 + self.poh // 400),
            (194, "Temperature_Celsius", "0x0022", 120 - temp, 100, 0, "Old_age", temp),
            (197, "Current_Pending_Sector", "0x0032", 200, 200, 0, "Old_age", self.pending),
            (198, "Offline_Uncorrectable", "0x0030", 100, 253, 0, "Old_age", 0),
            (199, "UDMA_CRC_Error_Count", "0x0032", 200, 200, 0, "Old_age", 0),
        ]
        out += ("SMART Attributes Data Structure revision number: 16\n"
                "Vendor Specific SMART Attributes with Thresholds:\n"
                "ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE\n")
        for rid, name, flag, val, worst, thresh, typ, raw in rows:
            out += f"{rid:3d} {name:<23} {flag}   {val:03d}   {worst:03d}   {thresh:03d}    {typ:<9} Always       -       {raw}\n"
        return out


# ── Machines ─────────────────────────────────────────────────────────────────

OS_RELEASE = {
    "debian": ('Debian GNU/Linux 13 (trixie)', "debian", "13"),
    "ubuntu": ('Ubuntu 24.04.3 LTS', "ubuntu", "24.04"),
    "fedora": ('Fedora Linux 42 (Server Edition)', "fedora", "42"),
    "arch": ('Arch Linux', "arch", ""),
    "raspbian": ('Debian GNU/Linux 12 (bookworm)', "debian", "12"),
}


# Installed source packages (what `dpkg-query -W -f='${source:Package} ${source:Version}'` lists), already
# patched. Machines with pending updates run the older versions in their update list until they are updated.
PACKAGES = {
    "debian": {"openssl": "3.5.4-1~deb13u2", "curl": "8.14.1-2+deb13u2", "openssh": "1:10.0p1-7+deb13u1",
               "glibc": "2.41-12+deb13u1", "systemd": "257.9-1~deb13u1", "sudo": "1.9.16p2-3+deb13u1",
               "bash": "5.2.37-2", "tzdata": "2025c-0+deb13u1", "python3.13": "3.13.5-2+deb13u1",
               "sqlite3": "3.46.1-7", "zlib": "1:1.3.dfsg+really1.3.1-1", "git": "1:2.47.3-0+deb13u1",
               "coreutils": "9.7-3", "gnupg2": "2.4.7-21"},
    "raspbian": {"openssl": "3.0.17-1~deb12u2", "curl": "7.88.1-10+deb12u14", "openssh": "1:9.2p1-2+deb12u7",
                 "glibc": "2.36-9+deb12u13", "systemd": "252.39-1~deb12u1", "sudo": "1.9.13p3-1+deb12u2",
                 "bash": "5.2.15-2", "tzdata": "2025b-0+deb12u1", "python3.11": "3.11.2-6+deb12u6",
                 "sqlite3": "3.40.1-2+deb12u2", "zlib": "1:1.2.13.dfsg-1", "git": "1:2.39.5-0+deb12u2"},
    "ubuntu": {"openssl": "3.0.13-0ubuntu3.6", "curl": "8.5.0-2ubuntu10.6", "openssh": "1:9.6p1-3ubuntu13.14",
               "glibc": "2.39-0ubuntu8.6", "systemd": "255.4-1ubuntu8.11", "sudo": "1.9.15p5-3ubuntu5.24.04.1",
               "bash": "5.2.21-2ubuntu4", "tzdata": "2025b-0ubuntu0.24.04.1", "python3.12": "3.12.3-1ubuntu0.8",
               "sqlite3": "3.45.1-1ubuntu2.5", "nginx": "1.24.0-2ubuntu7.5", "zlib": "1:1.3.dfsg-3.1ubuntu2.1",
               "git": "1:2.43.0-1ubuntu7.3"},
}
# Older, vulnerable versions used by "Release updates" in the lab panel.
OLDER = {
    "debian": {"openssl": "3.5.1-1", "curl": "8.14.1-2", "openssh": "1:10.0p1-7", "glibc": "2.41-12",
               "sudo": "1.9.16p2-3", "python3.13": "3.13.5-2"},
    "raspbian": {"openssl": "3.0.15-1~deb12u1", "openssh": "1:9.2p1-2+deb12u3", "glibc": "2.36-9+deb12u7"},
    "ubuntu": {"openssl": "3.0.13-0ubuntu3.4", "nginx": "1.24.0-2ubuntu7.1", "openssh": "1:9.6p1-3ubuntu13.5"},
}
# Container images (Debian 12 based) and the packages inside them, for the emulated `trivy image`.
IMAGES = {
    "nginx:1.27.0": {"openssl": "3.0.11-1~deb12u2", "curl": "7.88.1-10+deb12u5", "glibc": "2.36-9+deb12u4",
                     "zlib": "1:1.2.13.dfsg-1", "nginx": "1.27.0-1~bookworm"},
    "nextcloud:29.0.4-apache": {"openssl": "3.0.13-1~deb12u1", "curl": "7.88.1-10+deb12u6",
                                "glibc": "2.36-9+deb12u7", "apache2": "2.4.61-1~deb12u1", "libxml2": "2.9.14+dfsg-1.3~deb12u1"},
}


class Machine(Device):
    """A Linux server (or, with os='windows', a Windows PC reached through OpenSSH)."""
    kind = "server"
    icon = "server"

    def __init__(self, name, ip, mac="", os="debian", pretty=None, kernel="6.12.48+deb13-amd64",
                 cpu="Intel(R) Xeon(R) E-2236 CPU @ 3.40GHz", cores=6, ram_mb=32768, disks=(), updates=(),
                 base_load=12.0, ports=(22,), fans=2, board=("Supermicro", "X11SCH-F"), virt="none", **kw):
        super().__init__(name, ip, mac, ports, **kw)
        self.os, self.kernel, self.cpu, self.cores, self.ram_mb = os, kernel, cpu, cores, ram_mb
        self.pretty = pretty or OS_RELEASE.get(os, (os.title(), os, ""))[0]
        self.disks = list(disks)
        self.updates = list(updates)   # (package, installed, candidate)
        self.base_load, self.stress_until = base_load, 0.0
        self.board, self.virt = board, virt
        self.pwm = {f"pwm{i + 1}": 128 for i in range(fans)}
        self.pwm_enable = {k: 2 for k in self.pwm}
        self.fan_max_rpm = {k: 1800 + 300 * i for i, k in enumerate(self.pwm)}
        self.installed_packages = 1400 + self.rand.randint(0, 300)
        self.ram_base = 0.25 + self.rand.random() * 0.35
        self.authorized_keys = []
        self.packages = dict(PACKAGES.get(os, {}))
        self._use_latest()
        for pkg, installed, _ in self.updates:
            if pkg in self.packages:
                self.packages[pkg] = installed
        self.containers = []          # (name, image); the images' packages are in IMAGES
        self.trivy = False

    def _use_latest(self):
        """Up-to-date packages run the newest fixed version known to the demo's OSV snapshot."""
        from . import osv
        eco = osv.ECOSYSTEMS.get(self.os)
        if not eco:
            return
        for pkg, version in list(self.packages.items()):
            newest = osv.latest(eco, pkg)
            if newest and osv.compare_versions(newest, version) > 0:
                self.packages[pkg] = newest
        self.updates = [(p, old, self.packages.get(p, new)) for p, old, new in self.updates]

    # ── Live values ──
    def _wave(self, period, phase=0.0):
        return math.sin(_now() / period + phase)

    def cpu_pct(self):
        if not self.powered:
            return 0.0
        if _now() < self.stress_until:
            return round(96 + self._wave(7) * 3, 1)
        load = self.base_load * (1 + 0.5 * self._wave(90, len(self.name))) + random.uniform(-3, 3)
        return round(min(99.0, max(0.5, load)), 1)

    def fan_ratio(self):
        if not self.pwm:
            return 0.5
        return sum(self.pwm.values()) / (255 * len(self.pwm))

    def cpu_temp(self):
        return round(31 + self.cpu_pct() * 0.42 + (1 - self.fan_ratio()) * 16 + random.uniform(-0.6, 0.6), 1)

    def ram_pct(self):
        return round(100 * min(0.95, self.ram_base + 0.04 * self._wave(300)), 1)

    def loadavg(self):
        load = self.cpu_pct() * self.cores / 100
        return [round(load, 2), round(load * 0.9, 2), round(load * 0.8, 2)]

    def net_counters(self):
        up = self.uptime()
        return int(up * (180_000 + self.base_load * 9000)), int(up * (420_000 + self.base_load * 20_000))

    def fan_rpm(self, key):
        return int(self.fan_max_rpm[key] * (0.25 + 0.75 * self.pwm[key] / 255) + random.uniform(-15, 15))

    # ── Lab panel ──
    def facts(self):
        facts = [self.pretty, f"{self.cores} cores · {self.ram_mb // 1024} GB"]
        if getattr(self, "hint", ""):
            facts.insert(0, self.hint)
        if self.updates:
            facts.append(f"{len(self.updates)} updates pending")
        bad = [d.dev for d in self.disks if d.realloc or d.pending or d.failed]
        if bad:
            facts.append(f"failing disk: {', '.join(bad)}")
        if _now() < self.stress_until:
            facts.append("under full load")
        return facts

    def actions(self):
        acts = super().actions()
        if self._on:
            acts += [{"id": "updates", "label": "Release updates"}, {"id": "load", "label": "Full CPU load"}]
            if any(not d.realloc for d in self.disks if not d.nvme):
                acts.append({"id": "disk", "label": "Let a disk fail"})
        return acts

    def act(self, action):
        if action == "updates":
            self.release_updates()
        elif action == "load":
            self.stress_until = _now() + 120
            self._log("lab", f"{self.label}: CPU under full load for 2 minutes")
        elif action == "disk":
            disk = next((d for d in self.disks if not d.nvme and not d.realloc), None)
            if disk:
                disk.degrade()
                self._log("lab", f"{self.label}: {disk.dev} ({disk.model}) is reallocating sectors")
        else:
            return super().act(action)
        return True

    def release_updates(self):
        """New package versions with security fixes appear for this machine."""
        older = OLDER.get(self.os, {})
        have = {u[0] for u in self.updates}
        candidates = [p for p in older if p not in have and p in self.packages]
        self.rand.shuffle(candidates)
        new = [(p, older[p], self.packages[p]) for p in candidates[:self.rand.randint(2, 3)]]
        for pkg, installed, _ in new:
            self.packages[pkg] = installed
        self.updates += new
        self._log("lab", f"{self.label}: {len(new)} security updates published ({', '.join(p for p, _, _ in new)})")

    # ── Shell ──
    def shell(self, command, stdin="", user="root"):
        rc, out, err = self._shell(command.strip(), stdin, user)
        short = command.strip().split("\n")[0]
        routine = re.match(r"(python3 -|sensors|for f in /sys/class/hwmon|cat /proc/|lsblk|uptime|hostname)", short)
        self._log("ssh", f"$ {short[:140]}" + ("" if rc in (0, None) else f"  (exit {rc})"), quiet=bool(routine))
        return rc, out, err

    def local(self, argv, stdin):
        command = argv[2] if argv[:2] == ["/bin/sh", "-c"] else " ".join(shlex.quote(a) for a in argv)
        if argv and argv[0] in ("sudo",):
            command = " ".join(shlex.quote(a) for a in argv[1:] if a not in ("-S", "-n"))
        return self._shell(command, stdin, "fleetpilot")

    def _shell(self, cmd, stdin, user):
        windows = self.os == "windows"
        if windows:
            return self._windows(cmd)
        if cmd.startswith("powershell.exe"):
            return 127, "", "bash: powershell.exe: command not found\n"
        if "@@fp:pkg" in cmd and "dpkg-query" in cmd:
            return 0, self._inventory(), ""
        m = re.match(r"trivy image .*?'?([\w./:-]+)'? 2>/dev/null$", cmd)
        if m and self.trivy:
            return 0, json.dumps(self._trivy(m.group(1))), ""
        if cmd.startswith("python3 -c") and "cpu_pct()" in cmd:
            up = int(self.uptime())
            h, m = up // 3600, (up % 3600) // 60
            load = " ".join(str(x) for x in self.loadavg())
            return 0, f"{self.cpu_pct()}|{self.ram_pct()}|{f'{h}h {m}m' if h else f'{m}m'}|{load}\n", ""
        if cmd.startswith("python3 -"):
            return self._python(stdin)
        if "cat /etc/os-release | grep '^ID='" in cmd:
            return 0, OS_RELEASE.get(self.os, ("", self.os, ""))[1] + "\n", ""
        if re.search(r"apt-get (?:-\S+ )*(dist-)?upgrade|apt upgrade|dnf upgrade|yum update|pacman -Syu", cmd):
            return self._upgrade(cmd)
        if re.match(r"(sudo )?apt-get (?:-\S+ )*update\b", cmd):
            return 0, ("Hit:1 http://deb.debian.org/debian trixie InRelease\n"
                       "Hit:2 http://security.debian.org/debian-security trixie-security InRelease\n"
                       "Reading package lists...\n"), ""
        if re.match(r"(sudo )?apt-get (?:-\S+ )*autoremove\b", cmd):
            return 0, "Reading package lists...\n0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n", ""
        if cmd in ("ip neigh", "arp -n", "arp -a"):
            return 0, self._neighbours(cmd), ""
        m = re.match(r"(?:/\S*/)?ping (?:-\S+ \S+ )*(\d+\.\d+\.\d+\.\d+)$", cmd)
        if m:
            device = self.lab.find(m.group(1)) if self.lab else None
            up = bool(device and device.powered)
            return (0, f"64 bytes from {m.group(1)}: icmp_seq=1 ttl=64 time=0.4 ms\n", "") if up else \
                (1, f"From {self.ip} icmp_seq=1 Destination Host Unreachable\n", "")
        if "apt-get install" in cmd or "apt install" in cmd:
            pkgs = [p for p in cmd.split("install", 1)[1].split() if not p.startswith("-")]
            return 0, "".join(f"Setting up {p} ...\n" for p in pkgs) or "0 upgraded, 0 newly installed.\n", ""
        if cmd.startswith("lsblk"):
            return 0, self._lsblk(cmd), ""
        m = re.search(r"smartctl\s+(-a|-i|-H|--all|--info)\s+/dev/(\S+)", cmd)
        if m:
            disk = next((d for d in self.disks if d.dev == m.group(2)), None)
            if not disk:
                return 2, f"/dev/{m.group(2)}: Unable to detect device type\n", ""
            ambient = (self.cpu_temp() - 40) * 0.15
            return (0 if not disk.failed else 8), disk.smartctl_a(ambient) if m.group(1) in ("-a", "--all", "-H") \
                else disk.smartctl_i(), ""
        if re.search(r"\b(reboot|shutdown -r|systemctl reboot)\b", cmd):
            self.reboot()
            return 0, "", ""
        if re.search(r"\b(poweroff|shutdown -h|shutdown -P|halt|systemctl poweroff)\b", cmd):
            self.power_off("shut down by FleetPilot")
            return 0, "", ""
        if cmd.startswith("sensors -j") or cmd == "sensors -j":
            return 0, json.dumps(self._sensors()), ""
        if cmd.startswith("sensors"):
            return 0, self._sensors_text(), ""
        if "/sys/class/hwmon/hwmon*/pwm[0-9]" in cmd:
            return 0, "".join(f"/sys/class/hwmon/hwmon2/{k}:{v}\n" for k, v in self.pwm.items()), ""
        m = re.search(r"echo (\d+) \| (?:sudo )?tee '?(/sys/class/hwmon/hwmon\d+/(pwm\d)(_enable)?)'?", cmd)
        if m:
            value, key = int(m.group(1)), m.group(3)
            if key not in self.pwm:
                return 1, "", f"tee: {m.group(2)}: No such file or directory\n"
            if m.group(4):
                self.pwm_enable[key] = value
            else:
                self.pwm[key] = max(0, min(255, value))
                self._log("fan", f"{self.label}: {key} set to {value}/255 ({round(value * 100 / 255)}%)")
            return 0, f"{value}\n", ""
        m = re.search(r"find /sys/class/hwmon -name '?(pwm\d)'?", cmd)
        if m:
            return 0, (f"/sys/class/hwmon/hwmon2/{m.group(1)}\n" if m.group(1) in self.pwm else ""), ""
        if "ls /sys/class/hwmon" in cmd or "for h in /sys/class/hwmon/hwmon*" in cmd:
            out = "=== /sys/class/hwmon/hwmon2 ===\nnct6798\n" + "".join(
                f"/sys/class/hwmon/hwmon2/{k}\n/sys/class/hwmon/hwmon2/{k}_enable\n" for k in self.pwm)
            return 0, out, ""
        if cmd.startswith("cat /etc/os-release") or "/etc/os-release" in cmd and "@@fp" not in cmd:
            return 0, self._os_release(), ""
        if cmd.startswith("/usr/local/lib/fleetpilot/"):     # FleetPilot's root helpers (via sudo)
            return self._helper(cmd.split()[0].rsplit("/", 1)[1], cmd.split()[1:])
        simple = self._simple(cmd)
        if simple is not None:
            return 0, simple, ""
        if re.match(r"^(ipmitool|liquidctl|nbfc|nvidia-smi|rocm-smi|pvesh|zpool|git)\b", cmd):
            return 127, "", f"bash: {cmd.split()[0]}: command not found\n"
        if re.match(r"^(echo|true|test|mkdir|chmod|touch|systemctl (restart|start|enable|daemon-reload))\b", cmd):
            return 0, "", ""
        self._log("ssh", f"(unknown to the demo) {cmd[:80]}")
        return 127, "", f"bash: {cmd.split()[0] if cmd else ''}: command not found\n"

    def _simple(self, cmd):
        up = self.uptime()
        table = {
            "hostname": f"{self.name}\n", "hostname -f": f"{self.name}.lab.example\n",
            "uname -r": f"{self.kernel}\n", "uname -m": "x86_64\n",
            "uname -a": f"Linux {self.name} {self.kernel} #1 SMP PREEMPT_DYNAMIC x86_64 GNU/Linux\n",
            "cat /proc/uptime": f"{up:.2f} {up * self.cores * 0.8:.2f}\n",
            "cat /proc/loadavg": " ".join(str(x) for x in self.loadavg()) + " 2/412 18231\n",
            "uptime": f" {time.strftime('%H:%M:%S')} up {int(up // 86400)} days, load average: "
                      + ", ".join(str(x) for x in self.loadavg()) + "\n",
            "cat /proc/meminfo": self._meminfo(),
            "whoami": "root\n", "id -u": "0\n", "nproc": f"{self.cores}\n",
        }
        return table.get(cmd)

    def _inventory(self):
        out = self._os_release() + "@@fp:pkg\n"
        if self.packages:
            out += "dpkg\n" + "".join(f"{p}\t{v}\n" for p, v in sorted(self.packages.items()))
        out += "@@fp:docker\n" + "".join(f"{n}\t{i}\n" for n, i in self.containers)
        return out + "@@fp:trivy\n" + ("/usr/bin/trivy\n" if self.trivy else "")

    def _trivy(self, image):
        """A Trivy report built from the OSV records the lab knows for the image's packages."""
        from . import osv
        vulns = []
        for pkg, version in sorted(IMAGES.get(image, {}).items()):
            for record in osv.lookup("Debian:12", pkg, version):
                fixed = ""
                for affected in record.get("affected") or []:
                    if (affected.get("package") or {}).get("ecosystem") == "Debian:12":
                        for rng in affected.get("ranges") or []:
                            fixed = next((e["fixed"] for e in rng.get("events", []) if e.get("fixed")), fixed)
                score, level = osv.score_and_level(record, pkg)
                cve = next((a for a in [record["id"]] + record.get("aliases", []) + record.get("upstream", [])
                            if a.startswith("CVE-")), record["id"])
                vulns.append({"VulnerabilityID": cve, "PkgName": pkg, "InstalledVersion": version,
                              "FixedVersion": fixed, "Severity": level.upper(),
                              "Title": (record.get("summary") or record.get("details") or "")[:200],
                              "CVSS": {"nvd": {"V3Score": score}} if score else {},
                              "PublishedDate": record.get("published", "")})
        return {"SchemaVersion": 2, "ArtifactName": image,
                "Results": [{"Target": f"{image} (debian 12)", "Class": "os-pkgs", "Type": "debian",
                             "Vulnerabilities": vulns}]}

    def _helper(self, name, args):
        if name == "proxy-apply" and args[:1] == ["status"]:
            return 0, "HAProxy is active and its FleetPilot-managed configuration is valid.\n", ""
        if name == "proxy-apply":
            return 0, "HAProxy configuration applied.\n", ""
        if name == "update":
            return 0, "FleetPilot is up to date.\n", ""
        return 0, "", ""

    def _neighbours(self, cmd):
        lines = []
        for device in self.lab.devices if self.lab else []:
            if device is self or not device.mac or not device.powered:
                continue
            if cmd == "ip neigh":
                lines.append(f"{device.ip} dev eth0 lladdr {device.mac} REACHABLE")
            else:
                lines.append(f"{device.ip:<16} ether   {device.mac}   C   eth0")
        return "\n".join(lines) + "\n"

    def _os_release(self):
        pretty, ident, version = OS_RELEASE.get(self.os, (self.pretty, self.os, ""))
        if self.pretty:
            pretty = self.pretty
        return (f'PRETTY_NAME="{pretty}"\nNAME="{pretty.split(" ")[0]}"\nVERSION_ID="{version}"\n'
                f'ID={ident}\nHOME_URL="https://www.{ident}.org/"\n')

    def _meminfo(self):
        total = self.ram_mb * 1024
        avail = int(total * (1 - self.ram_pct() / 100))
        return (f"MemTotal:       {total} kB\nMemFree:        {avail // 2} kB\nMemAvailable:   {avail} kB\n"
                f"Buffers:          182044 kB\nCached:          {avail // 3} kB\n"
                f"SwapTotal:       8388604 kB\nSwapFree:        8126460 kB\n")

    def _lsblk(self, cmd):
        devices = []
        for d in self.disks:
            devices.append({"name": d.dev, "size": d.size_text(), "model": d.model, "type": "disk",
                            "rota": "1" if d.rotational else "0", "tran": "nvme" if d.nvme else "sata",
                            "vendor": None, "rev": d.firmware, "serial": d.serial, "mountpoint": None})
        if "ROTA" not in cmd:
            devices = [{k: v for k, v in d.items() if k in ("name", "size", "model", "type")} for d in devices]
        return json.dumps({"blockdevices": devices}, indent=3) + "\n"

    def _sensors(self):
        temp = self.cpu_temp()
        chips = {"coretemp-isa-0000": {"Adapter": "ISA adapter",
                                       "Package id 0": {"temp1_input": temp, "temp1_max": 84.0, "temp1_crit": 100.0}}}
        for i in range(min(self.cores, 4)):
            chips["coretemp-isa-0000"][f"Core {i}"] = {f"temp{i + 2}_input": round(temp - 1.5 + i * 0.7, 1)}
        nct = {"Adapter": "ISA adapter"}
        for i, key in enumerate(self.pwm):
            nct[f"fan{i + 1}"] = {f"fan{i + 1}_input": self.fan_rpm(key), f"fan{i + 1}_min": 0}
        nct["in0"] = {"in0_input": 1.016}
        nct["SYSTIN"] = {"temp1_input": round(27 + self.cpu_pct() * 0.05, 1)}
        chips["nct6798-isa-0290"] = nct
        if any(d.nvme for d in self.disks):
            chips["nvme-pci-0100"] = {"Adapter": "PCI adapter",
                                      "Composite": {"temp1_input": round(38 + self.cpu_pct() * 0.1, 1)}}
        return chips

    def _sensors_text(self):
        lines = []
        for chip, data in self._sensors().items():
            lines.append(chip)
            for feature, values in data.items():
                if isinstance(values, dict):
                    v = next(iter(values.values()))
                    unit = " RPM" if feature.startswith("fan") else ("°C" if "temp" in next(iter(values)) else " V")
                    lines.append(f"{feature}:  +{v}{unit}")
            lines.append("")
        return "\n".join(lines)

    def _upgrade(self, cmd):
        lines = []
        if "apt" in cmd:
            lines += ["Hit:1 http://deb.debian.org/debian trixie InRelease",
                      "Get:2 http://security.debian.org/debian-security trixie-security InRelease [43.4 kB]",
                      "Fetched 43.4 kB in 1s (52.1 kB/s)", "Reading package lists...",
                      "Reading package lists...", "Building dependency tree...", "Reading state information...",
                      "Calculating upgrade..."]
            if self.updates:
                lines.append("The following packages will be upgraded:")
                lines.append("  " + " ".join(p for p, _, _ in self.updates))
            lines.append(f"{len(self.updates)} upgraded, 0 newly installed, 0 to remove and 0 not upgraded.")
            for pkg, old, new in self.updates:
                lines += [f"Preparing to unpack .../{pkg}_{new}_amd64.deb ...",
                          f"Unpacking {pkg} ({new}) over ({old}) ...", f"Setting up {pkg} ({new}) ..."]
            if self.updates:
                lines.append("Processing triggers for man-db (2.13.1-1) ...")
        elif "dnf" in cmd or "yum" in cmd:
            lines += ["Updating and loading repositories:", " Fedora 42 - x86_64 - Updates   100% |  41.2 KiB/s",
                      "Repositories loaded."]
            if self.updates:
                lines.append("Package                Arch    Version            Repository   Size")
                lines += [f" {p:<22} x86_64  {n:<18} updates      1.2 MiB" for p, _, n in self.updates]
                lines += [f"[{i + 1}/{len(self.updates)}] Upgrading {p}  100%" for i, (p, _, _) in
                          enumerate(self.updates)]
                lines.append("Complete!")
            else:
                lines.append("Nothing to do.")
        else:
            lines += [":: Synchronizing package databases...", " core is up to date", " extra is up to date",
                      ":: Starting full system upgrade..."]
            lines += [f"upgrading {p}..." for p, _, _ in self.updates] or [" there is nothing to do"]
        count = len(self.updates)
        for pkg, _, candidate in self.updates:
            if pkg in self.packages:
                self.packages[pkg] = candidate
        self.updates = []
        self._log("update", f"{self.label}: {count} packages upgraded")
        return 0, "\n".join(lines) + "\n", ""

    WINDOWS_UPDATES = [
        ("2026-10 Cumulative Update for Windows 11 Version 24H2 for x64-based Systems (KB5066835)", "5066835", True),
        ("2026-10 .NET 8.0.21 Security Update for x64 Client (KB5066970)", "5066970", True),
        ("Security Intelligence Update for Microsoft Defender Antivirus - KB2267602 (Version 1.439.211.0)",
         "2267602", False),
    ]

    def _powershell(self, script):
        """Windows PowerShell scripts FleetPilot sends (-EncodedCommand), recognised by their first line."""
        marker = script.split("\n", 1)[0].strip()
        if marker == "# fleetpilot:detect":
            return 0, "windows\r\n", ""
        if marker == "# fleetpilot:windows-info":
            return 0, json.dumps({"caption": "Microsoft Windows 11 Pro", "edition": "Professional",
                                  "display_version": "24H2", "release_id": "2009", "build": 26100, "ubr": 6899,
                                  "installation": "Client", "arch": "64-Bit", "hostname": self.name.upper(),
                                  "last_boot": "2026-10-14T07:12:03.0000000+02:00"}) + "\r\n", ""
        if marker == "# fleetpilot:upload":
            return 0, "", ""
        if marker == "# fleetpilot:run-as-system":
            pending = getattr(self, "windows_updates", list(self.WINDOWS_UPDATES))
            install = "-Mode install" in script
            lines = ["Searching for updates...", f"Found {len(pending)} update(s)."] + [f"  {t}" for t, _, _ in pending]
            if install and pending:
                lines += ["Downloading...", "Installing..."] + [f"{t}: installed" for t, _, _ in pending]
                self._log("update", f"{self.label}: {len(pending)} Windows updates installed")
            result = {"ok": True, "mode": "install" if install else "check", "installed": len(pending) if install else 0,
                      "failed": 0, "reboot": bool(install and pending), "error": None,
                      "updates": [{"title": t, "kb": kb, "severity": "Important" if sec else "", "security": sec,
                                   "size": 0} for t, kb, sec in pending]}
            if install:
                self.windows_updates = []
            return 0, "\r\n".join(lines + ["@@fp:result " + json.dumps(result)]) + "\r\n", ""
        if marker == "# fleetpilot:winget":
            return self._windows("winget upgrade --all")
        if marker == "# fleetpilot:windows-hw":
            hw = self._hw_info()
            hw.update({"platform": "windows", "os": "Windows 11 Pro", "kernel": "10.0.26100", "arch": "64-Bit",
                       "hostname": self.name.upper(), "gpus_lspci": "", "pcie_devices": "", "packages": "",
                       "shell": "", "network": [dict(hw["network"][0], name="Ethernet", driver="Realtek PCIe 2.5GbE")],
                       "disks": [dict(d, name=f"PhysicalDrive{i}") for i, d in enumerate(hw["disks"])]})
            return 0, json.dumps(hw) + "\r\n", ""
        if marker == "# fleetpilot:smartctl-scan":
            return 0, "", ""        # smartmontools is not installed on this PC
        return 1, "", "The term is not recognized as the name of a cmdlet.\r\n"

    def _windows(self, cmd):
        if cmd.startswith("powershell.exe") and "-EncodedCommand " in cmd:
            encoded = cmd.rsplit(" ", 1)[1]
            return self._powershell(base64.b64decode(encoded).decode("utf-16-le"))
        if "winget upgrade" in cmd or "Get-WindowsUpdate" in cmd:
            lines = ["Name                         Id                          Version   Available Source",
                     "-" * 86]
            lines += [f"{p:<28} {p.replace(' ', '.'):<27} {o:<9} {n:<9} winget" for p, o, n in self.updates]
            lines += [f"Successfully installed {p}" for p, _, _ in self.updates]
            lines.append(f"{len(self.updates)} upgrades installed." if self.updates else "No installed package found "
                                                                                          "matching input criteria.")
            self._log("update", f"{self.label}: {len(self.updates)} apps upgraded with winget")
            self.updates = []
            return 0, "\n".join(lines) + "\n", ""
        if cmd.startswith("shutdown /r"):
            self.reboot(40)
            return 0, "", ""
        if cmd.startswith("shutdown /s"):
            self.power_off("shut down by FleetPilot")
            return 0, "", ""
        if "os-release" in cmd:
            return 1, "", "'cat' is not recognized as an internal or external command\n"
        return 1, "", f"'{cmd.split()[0]}' is not recognized as an internal or external command\n"

    def _python(self, script):
        if "d['cpu_pct']" in script:
            return 0, json.dumps(self._metrics()) + "\n", ""
        if "fans.append" in script and "pwm" in script:
            return 0, json.dumps(self._fan_detect()) + "\n", ""
        if "info['cpu']" in script or "info['motherboard']" in script:
            return 0, json.dumps(self._hw_info()) + "\n", ""
        return 0, "{}\n", ""

    def _metrics(self):
        sent, recv = self.net_counters()
        temp = self.cpu_temp()
        d = {"cpu_pct": self.cpu_pct(), "cpu_cores": self.cores,
             "ram_total_mb": self.ram_mb, "ram_used_mb": int(self.ram_mb * self.ram_pct() / 100),
             "swap_total_mb": 8191, "swap_used_mb": 256, "uptime_s": int(self.uptime()),
             "net_iface": "eno1", "net_rx_bytes": recv, "net_tx_bytes": sent,
             "disk_read_sectors": int(self.uptime() * 900), "disk_write_sectors": int(self.uptime() * 1400),
             "cpu_temp": temp, "gpu_on_bus": False,
             "fans": [{"name": f"Fan {i + 1}", "rpm": self.fan_rpm(k), "pwm": self.pwm[k]}
                      for i, k in enumerate(self.pwm)],
             "ts": _now()}
        if _now() < self.stress_until:
            d.update(stress_running=True, stress_phase="CPU",
                     stress_log="[TEST] === CPU START ===\n[MONITOR] all cores at 100%\n")
        return d

    def _fan_detect(self):
        fans = []
        for i, key in enumerate(self.pwm):
            base = "/sys/class/hwmon/hwmon2"
            fans.append({"hwmon": base, "name": "nct6798", "channel": i + 1, "path": f"{base}/{key}",
                         "enable_path": f"{base}/{key}_enable", "current": self.pwm[key], "max": 255,
                         "enable": self.pwm_enable[key]})
            fans.append({"hwmon": base, "name": "nct6798", "type": "rpm", "channel": i + 1,
                         "rpm": self.fan_rpm(key), "path": f"{base}/fan{i + 1}_input"})
        return fans

    def _hw_info(self):
        up = int(self.uptime())
        total = self.ram_mb * 1024
        used = int(total * self.ram_pct() / 100)
        return {
            "platform": "proxmox" if "Proxmox" in self.pretty else "linux", "os": self.pretty,
            "kernel": self.kernel, "hostname": f"{self.name}.lab.example", "arch": "x86_64",
            "uptime": f"{up // 86400}d {up % 86400 // 3600}h {up % 3600 // 60}m",
            "cpu": {"model": self.cpu, "cores": str(self.cores), "threads": str(self.cores * 2),
                    "freq_mhz": "3400", "max_freq_mhz": "4800", "temp_c": str(self.cpu_temp()),
                    "usage_pct": str(self.cpu_pct())},
            "memory": {"total_kb": str(total), "used_kb": str(used), "free_kb": str(total - used),
                       "used_pct": str(round(used * 100 / total, 1)), "swap_total_kb": "8388604",
                       "swap_free_kb": "8126460",
                       "slots_raw": "\n".join(f"Size: {self.ram_mb // 2048} GB\nType: DDR4\nSpeed: 2666 MT/s"
                                              for _ in range(2))},
            "motherboard": {"manufacturer": self.board[0], "product": self.board[1], "version": "1.02",
                            "bios_vendor": "American Megatrends Inc.", "bios_version": "2.1",
                            "bios_date": "06/12/2024"},
            "gpus": [], "gpus_lspci": "00:02.0 VGA compatible controller: ASPEED Graphics Family (rev 41)",
            "network": [{"name": "eno1", "mac": self.mac, "speed_mbps": "1000", "state": "up",
                         "driver": "igb", "ipv4": f"{self.ip}/24", "ipv6": ""}],
            "disks": [{"name": d.dev, "size": d.size_text(), "model": d.model, "rotational": d.rotational,
                       "transport": "nvme" if d.nvme else "sata", "serial": d.serial,
                       "type": "HDD" if d.rotational else ("NVMe" if d.nvme else "SSD")} for d in self.disks],
            "pcie_devices": "01:00.0 Ethernet controller: Intel Corporation I210 Gigabit Network Connection",
            "virtualization": self.virt if self.virt != "none" else "bare-metal",
            "packages": str(self.installed_packages), "shell": "/bin/bash",
        }

    def tick(self):
        # Disks warm up a little under load; a degrading disk keeps getting worse.
        for d in self.disks:
            if d.realloc and self.rand.random() < 0.3:
                d.realloc += self.rand.randint(1, 4)
