"""The emulated network: devices by address, and the log of what FleetPilot did.

FleetPilot's sockets, HTTP calls, SSH sessions, local commands and e-mails arrive
here (see runtime.py) and are answered by the device that owns the address.
"""
import collections
import time
import urllib.parse


class Lab:
    def __init__(self):
        self.devices = []
        self.self_machine = None        # the machine FleetPilot runs on
        self.events = collections.deque(maxlen=300)
        self.outbox = collections.deque(maxlen=40)
        self._seq = 0
        self.background = False         # True while FleetPilot's pollers run (lab tick)

    # ── Inventory ──
    def add(self, device):
        self.devices.append(device)
        device.lab = self
        return device

    @property
    def self_ip(self):
        return self.self_machine.ip

    def find(self, host):
        host = str(host or "").strip().lower().strip("[]")
        for device in self.devices:
            if host in (device.ip, device.name.lower(), (device.dns_name or "").lower()):
                return device
        return None

    def resolve(self, name):
        if name in ("localhost", "127.0.0.1", "::1"):
            return "127.0.0.1"
        device = self.find(name)
        return device.ip if device else None

    def accepts_mail(self, host):
        return True

    # ── Activity log shown in the lab panel ──
    def log(self, device, kind, text, quiet=False):
        self._seq += 1
        self.events.append({"id": self._seq, "t": time.time(), "device": getattr(device, "name", str(device)),
                            "kind": kind, "text": str(text)[:300], "bg": self.background or quiet})

    def deliver(self, channel, to, subject, body):
        self._seq += 1
        if isinstance(to, (list, tuple)):
            to = ", ".join(to)
        self.outbox.append({"id": self._seq, "t": time.time(), "channel": channel, "to": str(to)[:120],
                            "subject": str(subject)[:200], "body": str(body)[:2000]})
        self.log(channel, "notify", f"{channel} to {to}: {subject}")

    # ── Transport ──
    def tcp_open(self, host, port):
        if self.resolve(host) == "127.0.0.1":
            return True
        device = self.find(host)
        return bool(device and device.powered and int(port) in device.ports)

    def udp(self, data, address):
        # Wake-on-LAN: 6 x 0xFF followed by the MAC address 16 times
        if len(data) >= 102 and data[:6] == b"\xff" * 6:
            mac = data[6:12].hex(":")
            for device in self.devices:
                if device.mac and device.mac.lower() == mac:
                    device.wake()
                    return
            self.log("network", "wol", f"Magic packet for {mac}: no device with this MAC")

    def http(self, method, url, headers, body):
        parts = urllib.parse.urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if parts.hostname in ("api.github.com", "github.com", "raw.githubusercontent.com", "ntfy.sh",
                              "discord.com", "hooks.slack.com", "api.pushover.net"):
            return self._internet(method, parts, headers, body)
        device = self.find(parts.hostname)
        if not device or not device.powered or port not in device.ports:
            return None
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        result = device.http(method, port, parts.path or "/", query, headers, body or b"")
        if result is None:
            return (404, {"Content-Type": "text/plain"}, b"Not found")
        status, ctype, payload = result
        if isinstance(payload, str):
            payload = payload.encode()
        self.log(device, "http", f"{method} {parts.path}{'?' + parts.query if parts.query else ''} → {status}")
        return (status, {"Content-Type": ctype}, payload)

    def _internet(self, method, parts, headers, body):
        """Notification services and GitHub: messages land in the lab's outbox."""
        host = parts.hostname
        if method == "POST":
            text = (body or b"").decode(errors="replace")
            title = headers.get("Title") or headers.get("X-Title") or host
            self.deliver(host.split(".")[-2] if host.count(".") else host, host + parts.path, title, text)
            return (200, {"Content-Type": "application/json"}, b'{"ok": true}')
        return None   # the demo has no internet; version checks fail politely

    def ssh_connect(self, host, port, username):
        device = self.find(host)
        if not device or not device.powered:
            raise TimeoutError("timed out")
        if int(port) not in device.ports or not hasattr(device, "shell"):
            raise ConnectionRefusedError(111, "Connection refused")
        self.log(device, "ssh", f"{username}@{device.ip}: connected", quiet=True)
        return device

    def local_exec(self, argv, stdin):
        return self.self_machine.local(argv, stdin)

    # ── Time ──
    def advance(self, seconds):
        for device in self.devices:
            device.advance(seconds)

    def tick(self):
        for device in self.devices:
            device.tick()


lab = Lab()
