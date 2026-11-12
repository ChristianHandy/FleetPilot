# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for vm_controller: the _http helper, the Proxmox client (against a
fake _http returning recorded Proxmox responses) and endpoint storage."""
import io
import time
import urllib.error
import urllib.request

import pytest

import vm_controller


@pytest.fixture
def db(tmp_path):
    vm_controller.init_db(str(tmp_path))
    return tmp_path


# ── _http ───────────────────────────────────────────────────────────────────

class _FakeHTTPResponse:
    def __init__(self, body, status=200):
        self._body = body.encode() if isinstance(body, str) else body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_urlopen(monkeypatch, handler):
    calls = []

    def fake_urlopen(req, context=None, timeout=None):
        calls.append(req)
        return handler(req, len(calls))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def test_http_parses_json_answers(monkeypatch):
    _patch_urlopen(monkeypatch, lambda req, n: _FakeHTTPResponse('{"data": [1, 2]}'))
    result = vm_controller._http("GET", "https://pve.local:8006/api2/json/nodes")
    assert result == {"ok": True, "status": 200, "data": {"data": [1, 2]}}


def test_http_returns_non_json_answers_as_text(monkeypatch):
    _patch_urlopen(monkeypatch, lambda req, n: _FakeHTTPResponse("plain answer"))
    result = vm_controller._http("GET", "https://pve.local:8006/api2/json/version")
    assert result == {"ok": True, "status": 200, "data": "plain answer"}


def test_http_sends_dict_bodies_as_json(monkeypatch):
    seen = {}

    def handler(req, n):
        seen["data"] = req.data
        seen["content_type"] = req.get_header("Content-type")
        return _FakeHTTPResponse("{}")

    _patch_urlopen(monkeypatch, handler)
    vm_controller._http("POST", "https://pve.local:8006/api2/json/nodes", body={"a": 1})
    assert seen["data"] == b'{"a": 1}'
    assert seen["content_type"] == "application/json"


def test_http_errors_are_not_retried(monkeypatch):
    def handler(req, n):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                     io.BytesIO(b"permission denied"))

    calls = _patch_urlopen(monkeypatch, handler)
    result = vm_controller._http("GET", "https://pve.local:8006/api2/json/nodes")
    assert result == {"ok": False, "status": 403, "error": "permission denied"}
    assert len(calls) == 1


def test_http_retries_timeouts_with_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)

    def handler(req, n):
        if n < 3:
            raise TimeoutError("timed out")
        return _FakeHTTPResponse('{"data": []}')

    calls = _patch_urlopen(monkeypatch, handler)
    result = vm_controller._http("GET", "https://pve.local:8006/api2/json/nodes",
                                 retries=3, backoff=1.0)
    assert result["ok"] is True
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_http_gives_up_after_the_retries(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda delay: None)

    def handler(req, n):
        raise ConnectionResetError("connection reset by peer")

    calls = _patch_urlopen(monkeypatch, handler)
    result = vm_controller._http("GET", "https://pve.local:8006/api2/json/nodes",
                                 retries=2, backoff=0.5)
    assert result["ok"] is False
    assert result["status"] == 0
    assert result["error"]
    assert len(calls) == 3     # first attempt + 2 retries


def test_http_does_not_retry_other_errors(monkeypatch):
    def handler(req, n):
        raise ValueError("boom")

    calls = _patch_urlopen(monkeypatch, handler)
    result = vm_controller._http("GET", "https://pve.local:8006/api2/json/nodes")
    assert result["ok"] is False
    assert len(calls) == 1


# ── ProxmoxClient ───────────────────────────────────────────────────────────

_NODES = [{"node": "pve1"}, {"node": "pve2"}]


def _fake_proxmox_http(monkeypatch, fail_login=False):
    calls = []

    def fake_http(method, url, headers=None, body=None, verify_ssl=False, **kwargs):
        calls.append({"method": method, "url": url, "headers": headers or {}, "body": body})
        if url.endswith("/access/ticket"):
            if fail_login:
                return {"ok": False, "status": 401, "error": "bad credentials"}
            return {"ok": True, "status": 200,
                    "data": {"data": {"ticket": "TICKET", "CSRFPreventionToken": "CSRF"}}}
        path = url.split("/api2/json", 1)[1]
        if path == "/nodes":
            return {"ok": True, "status": 200, "data": {"data": [dict(n) for n in _NODES]}}
        if path == "/nodes/pve1/qemu":
            return {"ok": True, "status": 200, "data": {"data": [{"vmid": 100, "name": "web"}]}}
        if path == "/nodes/pve1/lxc":
            return {"ok": True, "status": 200, "data": {"data": [{"vmid": 200, "name": "db-ct"}]}}
        if path.endswith("/status/current"):
            return {"ok": True, "status": 200, "data": {"data": {"status": "running", "uptime": 42}}}
        if "/status/" in path:
            return {"ok": True, "status": 200, "data": "UPID:pve1:123"}
        if path.endswith("/snapshot"):
            if method == "POST":
                return {"ok": True, "status": 200, "data": "UPID:snap"}
            return {"ok": True, "status": 200, "data": {"data": [{"name": "before-upgrade"}]}}
        if path.endswith("/storage"):
            return {"ok": True, "status": 200, "data": {"data": [{"storage": "local-lvm"}]}}
        if path.endswith("/disks/list"):
            return {"ok": True, "status": 200, "data": {"data": [{"devpath": "/dev/sda"}]}}
        return {"ok": True, "status": 200, "data": {"data": []}}

    monkeypatch.setattr(vm_controller, "_http", fake_http)
    return calls


@pytest.fixture
def proxmox(monkeypatch):
    calls = _fake_proxmox_http(monkeypatch)
    client = vm_controller.ProxmoxClient("pve.local", 8006, "root@pam", "secret")
    return client, calls


def test_login_stores_ticket_and_csrf(proxmox):
    client, calls = proxmox
    assert client._ticket == "TICKET"
    assert client._csrf == "CSRF"
    login = calls[0]
    assert login["method"] == "POST"
    assert login["body"] == "username=root%40pam&password=secret"
    assert login["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_login_failure_raises(monkeypatch):
    _fake_proxmox_http(monkeypatch, fail_login=True)
    with pytest.raises(ConnectionError, match="Proxmox login failed"):
        vm_controller.ProxmoxClient("pve.local", 8006, "root@pam", "wrong")


def test_get_nodes(proxmox):
    client, _ = proxmox
    assert client.get_nodes() == _NODES


def test_get_vms_covers_qemu_and_lxc_on_all_nodes(proxmox):
    client, _ = proxmox
    vms = client.get_vms()
    assert [(v["name"], v["node"], v["type"], v["platform"]) for v in vms] == [
        ("web", "pve1", "qemu", "proxmox"),
        ("db-ct", "pve1", "lxc", "proxmox"),
    ]


def test_node_and_guest_type_validation(proxmox):
    client, _ = proxmox
    assert client._node("pve2") == "pve2"
    with pytest.raises(ValueError, match="does not know this node"):
        client._node("nope")
    assert vm_controller.ProxmoxClient._guest("lxc") == "lxc"
    with pytest.raises(ValueError, match="Unknown guest type"):
        vm_controller.ProxmoxClient._guest("docker")


def test_vm_action_only_allows_the_known_power_actions(proxmox):
    client, calls = proxmox
    with pytest.raises(ValueError, match="Unknown power action"):
        client.vm_action("pve1", 100, "explode")
    assert not any("/status/explode" in c["url"] for c in calls)


def test_vm_action_posts_to_the_status_endpoint(proxmox):
    client, calls = proxmox
    result = client.vm_action("pve1", 100, "start")
    assert result["ok"] is True
    posts = [c for c in calls if c["method"] == "POST" and "/status/start" in c["url"]]
    assert len(posts) == 1
    assert posts[0]["url"].endswith("/nodes/pve1/qemu/100/status/start")
    assert posts[0]["headers"]["CSRFPreventionToken"] == "CSRF"
    assert posts[0]["headers"]["Cookie"] == "PVEAuthCookie=TICKET"


def test_get_vm_status(proxmox):
    client, _ = proxmox
    assert client.get_vm_status("pve1", 100) == {"status": "running", "uptime": 42}


def test_snapshots(proxmox):
    client, calls = proxmox
    assert client.get_snapshots("pve1", 100) == [{"name": "before-upgrade"}]
    result = client.create_snapshot("pve1", 100, "s1", "before change")
    assert result["ok"] is True
    posts = [c for c in calls if c["method"] == "POST" and c["url"].endswith("/snapshot")]
    assert posts[0]["body"] == {"snapname": "s1", "description": "before change"}


def test_storage_and_disk_lists(proxmox):
    client, _ = proxmox
    assert client.get_storage("pve1") == [{"storage": "local-lvm"}]
    assert client.get_disks("pve1") == [{"devpath": "/dev/sda"}]
    with pytest.raises(ValueError, match="does not know this node"):
        client.get_storage("nope")


# ── Endpoint storage ────────────────────────────────────────────────────────

def test_add_and_list_endpoints_never_expose_the_password(db):
    ep_id = vm_controller.add_endpoint("pve", "proxmox", "10.0.0.5", 8006,
                                       "root@pam", "topsecret", verify_ssl=True,
                                       notes="lab")
    assert isinstance(ep_id, int)
    with vm_controller.get_db() as conn:
        stored = conn.execute("SELECT password FROM vm_endpoints WHERE id=?",
                              (ep_id,)).fetchone()[0]
    assert stored != "topsecret"                       # stored encrypted

    endpoints = vm_controller.list_endpoints()
    assert len(endpoints) == 1
    assert "password" not in endpoints[0]
    assert endpoints[0]["name"] == "pve"
    assert endpoints[0]["verify_ssl"] == 1


def test_get_endpoint_decrypts_the_password(db):
    ep_id = vm_controller.add_endpoint("veeam", "veeam", "10.0.0.6", 9419,
                                       "admin", "backup-pw")
    endpoint = vm_controller.get_endpoint(ep_id)
    assert endpoint["password_plain"] == "backup-pw"
    assert vm_controller.get_endpoint(999999) is None


def test_delete_endpoint(db):
    ep_id = vm_controller.add_endpoint("pve", "proxmox", "10.0.0.5", 8006,
                                       "root@pam", "topsecret")
    vm_controller.delete_endpoint(ep_id)
    assert vm_controller.list_endpoints() == []
    assert vm_controller.get_endpoint(ep_id) is None


def test_log_event_and_get_events(db):
    ep_id = vm_controller.add_endpoint("pve", "proxmox", "10.0.0.5", 8006,
                                       "root@pam", "topsecret")
    vm_controller.log_event(ep_id, "100", "web", "START", "ok", "started")
    vm_controller.log_event(ep_id, "100", "web", "STOP", "error", "timed out")
    events = vm_controller.get_events()
    assert len(events) == 2
    by_action = {e["action"]: e for e in events}   # both rows share a 1-second timestamp
    assert by_action["START"]["status"] == "ok"
    assert by_action["STOP"]["status"] == "error"
    assert by_action["START"]["endpoint_name"] == "pve"
    assert by_action["START"]["platform"] == "proxmox"
    assert len(vm_controller.get_events(limit=1)) == 1
