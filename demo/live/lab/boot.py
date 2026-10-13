"""Start FleetPilot inside the emulated lab and answer browser requests.

    start(origin, prefix)   import FleetPilot, build the lab, configure FleetPilot like a homelab owner would
    handle(...)             one HTTP request -> (status, headers, body)
    tick()                  one round of FleetPilot's background polling; returns the lab state
    act(device, action)     a lab control (power, failing disk, new updates, ...)

Works the same in Pyodide (the browser demo) and in CPython (tests, local runs).
"""
import json
import os
import re
import secrets
import sys
import tempfile
import time

from . import inventory, net, runtime, ssh

USERNAME, PASSWORD = "admin", "fleetpilot-demo"
APP_DIR = os.environ.get("FLEETPILOT_APP_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

fp = None
client = None
_base_url = "https://demo.local/"
_prefix = ""
_rewrite = None
_last = {}
_TEXT = ("text/html", "text/css", "application/javascript", "text/javascript", "application/json")


def start(origin="https://demo.local", prefix="", data_dir=None):
    global fp, client, _base_url, _prefix
    data_dir = data_dir or tempfile.mkdtemp(prefix="fleetpilot-lab-")
    home = os.path.join(data_dir, "home")
    os.makedirs(os.path.join(home, ".ssh"), exist_ok=True)
    os.environ.update(
        HOME=home, FLEETPILOT_DATA_DIR=data_dir, DASHBOARD_USERNAME=USERNAME, DASHBOARD_PASSWORD=PASSWORD,
        SECRET_KEY=secrets.token_hex(32), FLEETPILOT_OFFLINE="false", FLEETPILOT_ROUTER_POLL_MINUTES="0",
        FLEETPILOT_AUTO_BACKUP="false", FLEETPILOT_DEMO="true")
    runtime.install()
    inventory.build()
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    os.chdir(APP_DIR)
    import ssh_helper
    ssh_helper.create_client = ssh.create_client
    import app as _app
    fp = _app
    _prefix = prefix.rstrip("/")
    _base_url = origin.rstrip("/") + _prefix + "/"
    fp.app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)
    _make_rewriter()
    from . import seed
    seed.configure(fp)
    runtime.run_pending(500)
    client = fp.app.test_client()
    login()
    return True


def login():
    import account_security
    import user_management
    user = user_management.get_user(USERNAME)
    with client.session_transaction("/", base_url=_base_url) as s:
        s.update(user_id=user["id"], username=USERNAME,
                 pw_tag=fp._password_tag(user_management.get_user_by_id(user["id"])),
                 sid=account_security.create_session(user["id"]), auth_time=time.time())


def _make_rewriter():
    """Templates contain fixed paths like "/api/hosts"; the demo app lives below a prefix."""
    global _rewrite
    if not _prefix:
        _rewrite = None
        return
    segments = sorted({rule.rule.split("/")[1] for rule in fp.app.url_map.iter_rules()
                       if len(rule.rule.split("/")) > 1 and rule.rule.split("/")[1]
                       and not rule.rule.split("/")[1].startswith("<")}, key=len, reverse=True)
    # A quoted path after "+" is a suffix ('/api/fans/' + id + '/status'), not a page of its own.
    path = re.compile(r"""(\+\s*)?(["'`(\s=,])/(%s)(?=[/"'`?#)\s<,]|$)""" % "|".join(map(re.escape, segments)))
    root = re.compile(r"""\b(href|action)=(["'])/\2""")
    prefix = _prefix

    def rewrite(text):
        text = path.sub(lambda m: m.group(0) if m.group(1) else f"{m.group(2)}{prefix}/{m.group(3)}", text)
        return root.sub(lambda m: f"{m.group(1)}={m.group(2)}{prefix}/{m.group(2)}", text)
    _rewrite = rewrite


def handle(method, path, query, headers, body):
    """Answer one request from the browser. Returns (status, [(name, value)], body bytes)."""
    if path.startswith(_prefix):
        path = path[len(_prefix):] or "/"
    headers = {k: v for k, v in dict(headers).items() if k.lower() not in ("cookie", "host", "content-length")}
    resp = client.open(path, method=method, query_string=query, headers=headers, data=body or None,
                       base_url=_base_url, environ_base={"REMOTE_ADDR": "192.0.2.100"})
    data = resp.get_data()
    out_headers = []
    for name, value in resp.headers.items():
        lname = name.lower()
        if lname in ("set-cookie", "content-length", "content-encoding", "transfer-encoding"):
            continue
        if lname == "location" and _rewrite and value.startswith("/") and not value.startswith(_prefix + "/"):
            value = _prefix + value
        # FleetPilot refuses to be framed; the demo page frames it from the same origin.
        if lname == "x-frame-options":
            value = "SAMEORIGIN"
        if lname == "content-security-policy":
            value = value.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
        out_headers.append((name, value))
    if _rewrite and resp.mimetype in _TEXT and data:
        data = _rewrite(data.decode("utf-8", errors="replace")).encode()
    resp.close()
    return resp.status_code, out_headers, data


def after_request():
    """Run the background work the last request started (updates, discovery, ...)."""
    return runtime.run_pending()


def _every(name, seconds):
    now = time.time()
    if now - _last.get(name, 0) >= seconds:
        _last[name] = now
        return True
    return False


def _safely(fn, *args):
    try:
        fn(*args)
    except Exception as exc:  # one failing poller must not stop the others
        print(f"[lab] {getattr(fn, '__name__', fn)}: {exc}")


def tick(since=0):
    """One round of what FleetPilot's background threads would do."""
    net.lab.tick()
    net.lab.background = True
    try:
        _poll_round()
    finally:
        net.lab.background = False
    runtime.run_pending()
    return state(since)


def _poll_round():
    import backup_controller
    import fan_controller
    import hw_monitor
    import router_manager
    import system_monitor
    if _every("hw", 5):
        conn = hw_monitor.get_db()
        servers = [dict(r) for r in conn.execute("SELECT * FROM hw_servers WHERE enabled=1").fetchall()]
        conn.close()
        for server in servers:
            _safely(hw_monitor.collect_metrics, server)
    if _every("system", 10):
        sample = system_monitor._collect()
        if sample:
            _safely(system_monitor._save, sample)
    if _every("fans", 20):
        for dev in fan_controller.list_devices():
            if dev.get("enabled"):
                full = fan_controller.get_device(dev["id"])
                _safely(lambda d=full: fan_controller._store_sample(d["id"], fan_controller.fetch_status(d)))
    if _every("routers", 60):
        for router in router_manager.list_routers():
            _safely(router_manager.poll, router["id"])
    if _every("backup", 90):
        for srv in backup_controller.list_servers():
            _safely(backup_controller.poll_server, srv["id"])
    if _every("smart", 180):
        from . import seed
        _safely(seed.smart_round)


def state(since=0):
    return {
        "devices": [d.summary() for d in net.lab.devices if getattr(d, "listed", True)],
        "events": [e for e in net.lab.events if e["id"] > since],
        "outbox": list(net.lab.outbox),
        "credentials": {"username": USERNAME, "password": PASSWORD},
    }


def act(device_name, action):
    device = next((d for d in net.lab.devices if d.name == device_name), None)
    ok = bool(device and device.act(action))
    if ok:
        _last.clear()          # let FleetPilot notice the change on the next tick
    return ok


# ── Entry points for worker.js (plain strings and bytes cross the JS boundary easily) ──

def handle_js(method, path, query, headers_json, body):
    data = bytes(body.to_py()) if body is not None else b""
    status, headers, payload = handle(method, path, query, json.loads(headers_json), data)
    return status, json.dumps(headers), payload


def state_json(since=0):
    return json.dumps(state(since))


def tick_json(since=0):
    return json.dumps(tick(since))


def act_json(device_name, action, since=0):
    act(device_name, action)
    return json.dumps(tick(since))
