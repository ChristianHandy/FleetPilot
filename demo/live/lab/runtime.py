"""Make FleetPilot run in one browser thread, talking only to the emulated lab.

The browser has no threads, sockets, processes or SMTP. Everything FleetPilot
uses for those is replaced here, before the app is imported:

- threads: background work runs right after the current request (cooperative);
  the endless polling loops are not started, the lab's tick runs one round instead
- sleeping inside background work advances a virtual clock instead of blocking
- sockets, HTTP (urllib and requests), SSH, subprocess and SMTP go to lab.net
"""
import concurrent.futures
import io
import subprocess
import sys
import threading
import time
import traceback
import types

from . import net

# ── Threads ──────────────────────────────────────────────────────────────────

# Endless loops (pollers, schedulers). The lab's tick does their work instead.
ENDLESS = {"_poll_loop", "_poll_all", "_polling_loop", "_poll_worker", "loop", "_sync_loop",
           "_scheduler_loop", "auto_mode_worker", "version_check_worker", "_main_loop", "_schedule_loop"}
_pending = []


def _target_name(thread):
    target = getattr(thread, "_target", None)
    return getattr(target, "__name__", "") if target else type(thread).__name__


def _start(self):
    if _target_name(self) in ENDLESS:
        return
    self._fp_pending = True
    _pending.append(self)


def _run_thread(thread):
    if not getattr(thread, "_fp_pending", False):
        return
    thread._fp_pending = False
    started = _clock.offset
    try:
        thread.run()
    except Exception:
        traceback.print_exc()
    finally:
        _clock.offset = started


def _join(self, timeout=None):
    _run_thread(self)


def _is_alive(self):
    return bool(getattr(self, "_fp_pending", False))


def run_pending(limit=50):
    """Run background work queued by the last request (and work that work queued)."""
    done = 0
    while _pending and done < limit:
        _run_thread(_pending.pop(0))
        done += 1
    return done


class SyncExecutor(concurrent.futures.Executor):
    """ThreadPoolExecutor stand-in: runs each job when it is submitted."""

    def __init__(self, *args, **kwargs):
        pass

    def submit(self, fn, /, *args, **kwargs):
        future = concurrent.futures.Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - handed to the caller like a real executor
            future.set_exception(exc)
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        pass


# ── Virtual clock ────────────────────────────────────────────────────────────

class _Clock:
    """time.sleep() in background work moves this clock forward instead of blocking.

    The offset is reset after each job, so waits like "reboot, then poll until the
    host is back" finish at once without leaving the clock in the future.
    """
    offset = 0.0


_clock = _Clock()
_real_time, _real_monotonic = time.time, time.monotonic


def _sleep(seconds):
    _clock.offset += max(0.0, float(seconds or 0))
    net.lab.advance(max(0.0, float(seconds or 0)))


# ── Sockets ──────────────────────────────────────────────────────────────────

import socket as _socket_mod  # noqa: E402


class LabSocket:
    """A socket that only reaches devices of the emulated lab."""

    def __init__(self, family=_socket_mod.AF_INET, type=_socket_mod.SOCK_STREAM, proto=0, fileno=None):
        self.family, self.type, self.timeout, self.peer = family, type, None, None

    def settimeout(self, value):
        self.timeout = value

    def setsockopt(self, *args):
        pass

    def setblocking(self, flag):
        pass

    def bind(self, address):
        pass

    def connect(self, address):
        if self.type == _socket_mod.SOCK_DGRAM:
            self.peer = address
            return
        host, port = address[0], int(address[1])
        if not net.lab.tcp_open(host, port):
            if net.lab.find(host) is None or not net.lab.find(host).powered:
                raise _socket_mod.timeout("timed out")
            raise ConnectionRefusedError(111, "Connection refused")
        self.peer = (host, port)

    def connect_ex(self, address):
        try:
            self.connect(address)
            return 0
        except _socket_mod.timeout:
            return 11
        except OSError as exc:
            return exc.errno or 111

    def getsockname(self):
        return (net.lab.self_ip, 40000)

    def getpeername(self):
        return self.peer

    def sendto(self, data, address):
        net.lab.udp(bytes(data), address)
        return len(data)

    def send(self, data):
        return len(data)

    sendall = send

    def recv(self, size):
        return b""

    def close(self):
        pass

    def shutdown(self, how):
        pass

    def fileno(self):
        return -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _create_connection(address, timeout=None, source_address=None, **kwargs):
    sock = LabSocket()
    sock.settimeout(timeout)
    sock.connect(address)
    return sock


def _gethostbyname(name):
    ip = net.lab.resolve(name)
    if ip is None:
        raise _socket_mod.gaierror(-2, "Name or service not known")
    return ip


def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    ip = _gethostbyname(host) if host else net.lab.self_ip
    return [(_socket_mod.AF_INET, _socket_mod.SOCK_STREAM, 6, "", (ip, int(port or 0)))]


def _gethostbyaddr(ip):
    device = net.lab.find(ip)
    if device is None or not device.dns_name:
        raise _socket_mod.herror(1, "Unknown host")
    return (device.dns_name, [], [ip])


# ── HTTP: urllib ─────────────────────────────────────────────────────────────

import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from email.message import Message  # noqa: E402


class LabHTTPResponse(io.BytesIO):
    def __init__(self, url, status, headers, body):
        super().__init__(body)
        self.url, self.status, self.code, self.reason = url, status, status, "OK"
        self.headers = self.msg = Message()
        for key, value in headers.items():
            self.headers[key] = value

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def info(self):
        return self.headers

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def getheaders(self):
        return list(self.headers.items())


def _urlopen(url, data=None, timeout=None, *args, context=None, **kwargs):
    req = url if isinstance(url, urllib.request.Request) else urllib.request.Request(url, data=data)
    if data is not None and req.data is None:
        req.data = data
    headers = {k.title(): v for k, v in req.header_items()}
    body = req.data if isinstance(req.data, (bytes, bytearray)) else (req.data or b"")
    result = net.lab.http(req.get_method(), req.full_url, headers, bytes(body))
    if result is None:
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    status, rheaders, rbody = result
    if status >= 400:
        msg = Message()
        for key, value in rheaders.items():
            msg[key] = value
        raise urllib.error.HTTPError(req.full_url, status, "Error", msg, io.BytesIO(rbody))
    return LabHTTPResponse(req.full_url, status, rheaders, rbody)


# ── HTTP: requests ───────────────────────────────────────────────────────────

def _patch_requests():
    import requests
    from requests.adapters import HTTPAdapter
    from requests.structures import CaseInsensitiveDict

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        body = request.body or b""
        if isinstance(body, str):
            body = body.encode()
        if not isinstance(body, (bytes, bytearray)):
            body = b"".join(body)
        result = net.lab.http(request.method, request.url, dict(request.headers), bytes(body))
        if result is None:
            raise requests.exceptions.ConnectionError(f"Could not connect to {request.url.split('/')[2]}")
        status, headers, content = result
        resp = requests.models.Response()
        resp.status_code, resp._content, resp._content_consumed = status, content, True
        resp.headers = CaseInsensitiveDict(headers)
        resp.url, resp.request, resp.encoding = request.url, request, "utf-8"
        resp.reason = "OK" if status < 400 else "Error"
        resp.raw = io.BytesIO(content)
        resp.connection = self
        return resp

    HTTPAdapter.send = send


# ── subprocess ───────────────────────────────────────────────────────────────

def _argv(args, shell=False):
    if isinstance(args, (list, tuple)):
        return [str(a) for a in args]
    return ["/bin/sh", "-c", args] if shell else str(args).split()


def _decode(value, text):
    return value if text else value.encode()


def _run(args, *a, input=None, capture_output=False, text=None, universal_newlines=None,
         check=False, shell=False, **kwargs):
    text = bool(text or universal_newlines or kwargs.get("encoding"))
    argv = _argv(args, shell)
    if isinstance(input, bytes):
        input = input.decode(errors="replace")
    rc, out, err = net.lab.local_exec(argv, input or "")
    if rc == 127 and not shell:          # like a missing program on a real system
        raise FileNotFoundError(2, "No such file or directory", argv[0])
    result = subprocess.CompletedProcess(argv, rc, _decode(out, text), _decode(err, text))
    if check and rc:
        raise subprocess.CalledProcessError(rc, argv, result.stdout, result.stderr)
    return result


def _check_output(args, *a, **kwargs):
    kwargs.pop("stderr", None)
    return _run(args, *a, check=True, **kwargs).stdout


def _call(args, *a, **kwargs):
    return _run(args, *a, **kwargs).returncode


class LabPopen:
    def __init__(self, args, *a, stdin=None, stdout=None, stderr=None, text=None,
                 universal_newlines=None, shell=False, **kwargs):
        self.args = _argv(args, shell)
        self._text = bool(text or universal_newlines or kwargs.get("encoding"))
        self.returncode, out, err = net.lab.local_exec(self.args, "")
        self.pid = 4242
        self.stdout = (io.StringIO(out) if self._text else io.BytesIO(out.encode())) if stdout is not None else None
        self.stderr = (io.StringIO(err) if self._text else io.BytesIO(err.encode())) if stderr is not None else None
        self.stdin = io.StringIO() if stdin is not None else None

    def communicate(self, input=None, timeout=None):
        return (self.stdout.read() if self.stdout else None, self.stderr.read() if self.stderr else None)

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass

    terminate = kill

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ── SMTP ─────────────────────────────────────────────────────────────────────

def _mail_text(msg):
    """The plain-text part of an e-mail (or the HTML part without tags)."""
    import re as _re
    parts = list(msg.walk()) if msg.is_multipart() else [msg]
    for wanted in ("text/plain", "text/html"):
        for part in parts:
            if part.get_content_type() == wanted:
                raw = part.get_payload(decode=True) or b""
                text = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
                return _re.sub(r"<[^>]+>", " ", text) if wanted == "text/html" else text
    return ""


class LabSMTP:
    def __init__(self, host="", port=0, *args, **kwargs):
        self.host = host
        if host and net.lab.resolve(host) is None and not net.lab.accepts_mail(host):
            raise OSError(f"Could not connect to the mail server {host}.")

    def ehlo(self, *a, **k):
        return (250, b"ok")

    helo = ehlo

    def starttls(self, *a, **k):
        return (220, b"ready")

    def login(self, user, password):
        return (235, b"ok")

    def send_message(self, msg, from_addr=None, to_addrs=None, **kwargs):
        net.lab.deliver("email", msg.get("To") or to_addrs or "", msg.get("Subject", ""), _mail_text(msg))
        return {}

    def sendmail(self, from_addr, to_addrs, msg, *a, **k):
        import email
        parsed = email.message_from_string(msg if isinstance(msg, str) else msg.decode(errors="replace"))
        net.lab.deliver("email", to_addrs, parsed.get("Subject", ""), _mail_text(parsed))
        return {}

    def quit(self):
        pass

    close = quit

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ── psutil (the FleetPilot machine itself) ───────────────────────────────────

def _psutil_module():
    from collections import namedtuple
    mod = types.ModuleType("psutil")
    vmem = namedtuple("svmem", "total available percent used free")
    swap = namedtuple("sswap", "total used free percent sin sout")
    part = namedtuple("sdiskpart", "device mountpoint fstype opts")
    usage = namedtuple("sdiskusage", "total used free percent")
    nio = namedtuple("snetio", "bytes_sent bytes_recv packets_sent packets_recv errin errout dropin dropout")
    temp = namedtuple("shwtemp", "label current high critical")
    freq = namedtuple("scpufreq", "current min max")
    me = lambda: net.lab.self_machine  # noqa: E731

    def virtual_memory():
        total = me().ram_mb * 2**20
        used = int(total * me().ram_pct() / 100)
        return vmem(total, total - used, round(used * 100 / total, 1), used, total - used)

    def disk_usage(path):
        total, used = 256 * 10**9, 41 * 10**9
        return usage(total, used, total - used, round(used * 100 / total, 1))

    def net_io_counters(pernic=False):
        sent, recv = me().net_counters()
        return nio(sent, recv, sent // 900, recv // 1100, 0, 0, 0, 0)

    mod.cpu_percent = lambda interval=None, percpu=False: me().cpu_pct()
    mod.cpu_count = lambda logical=True: me().cores
    mod.cpu_freq = lambda percpu=False: freq(2400.0 + me().cpu_pct() * 8, 800.0, 3600.0)
    mod.virtual_memory = virtual_memory
    mod.swap_memory = lambda: swap(2 * 2**30, 64 * 2**20, 2 * 2**30 - 64 * 2**20, 3.1, 0, 0)
    mod.disk_partitions = lambda all=False: [part("/dev/vda1", "/", "ext4", "rw,relatime")]
    mod.disk_usage = disk_usage
    mod.net_io_counters = net_io_counters
    mod.sensors_temperatures = lambda fahrenheit=False: {"cpu_thermal": [temp("CPU", me().cpu_temp(), 85.0, 95.0)]}
    mod.boot_time = lambda: _real_time() - me().uptime()
    mod.getloadavg = lambda: tuple(me().loadavg())
    return mod


# ── Install ──────────────────────────────────────────────────────────────────

def install():
    """Patch everything before FleetPilot is imported."""
    threading.Thread.start = _start
    threading.Thread.join = _join
    threading.Thread.is_alive = _is_alive
    concurrent.futures.ThreadPoolExecutor = SyncExecutor
    import concurrent.futures.thread as _cft
    _cft.ThreadPoolExecutor = SyncExecutor

    time.sleep = _sleep
    time.time = lambda: _real_time() + _clock.offset
    time.monotonic = lambda: _real_monotonic() + _clock.offset

    _socket_mod.socket = LabSocket
    _socket_mod.create_connection = _create_connection
    _socket_mod.gethostbyname = _gethostbyname
    _socket_mod.getaddrinfo = _getaddrinfo
    _socket_mod.gethostbyaddr = _gethostbyaddr
    _socket_mod.gethostname = lambda: net.lab.self_machine.name
    _socket_mod.getfqdn = lambda name="": net.lab.self_machine.name

    urllib.request.urlopen = _urlopen
    urllib.request.OpenerDirector.open = lambda self, fullurl, data=None, timeout=None: _urlopen(fullurl, data)
    _patch_requests()

    subprocess.run = _run
    subprocess.check_output = _check_output
    subprocess.call = _call
    subprocess.Popen = LabPopen

    import smtplib
    smtplib.SMTP = smtplib.SMTP_SSL = LabSMTP

    sys.modules["psutil"] = _psutil_module()
    import os
    if not hasattr(os, "geteuid"):          # Pyodide: FleetPilot runs as its unprivileged service user
        os.geteuid = os.getuid = lambda: 999
