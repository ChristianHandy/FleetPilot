# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for addons/remote_disk_plugin.py: SSH helpers, parsers and web routes."""
import json
import time

import pytest

import account_security
import app as fp
import disktool_core
import ssh_helper
import user_management
import vm_controller
from addons import remote_disk_plugin

SAMPLE_LSBLK = json.dumps({
    "blockdevices": [
        {"name": "sda", "size": "500G", "model": "Samsung SSD 860", "type": "disk"},
        {"name": "sdb", "size": "1T", "model": "WDC WD10EZEX", "type": "disk"},
        {"name": "sda1", "size": "512M", "model": None, "type": "part"},
        {"name": "sr0", "size": "1024M", "model": "DVD-ROM", "type": "rom"},
    ]
})

SAMPLE_SMART = """smartctl 7.3 2022-02-28 r5338 [x86_64-linux-6.1.0]
Device Model:     CT500MX500SSD1
SMART overall-health self-assessment test result: PASSED
"""

REMOTES = [
    {
        "id": 1,
        "name": "backup-host",
        "host": "192.0.2.10",
        "port": 22,
        "ssh_user": "operator_ssh",
    },
    {
        "id": 2,
        "name": "default-user-host",
        "host": "192.0.2.11",
        "port": 2222,
        "ssh_user": "",
    },
]


class FakeChannel:
    def __init__(self, data=b""):
        self._data = data if isinstance(data, bytes) else data.encode("utf-8")

    def read(self):
        return self._data


class FakeSSHClient:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.commands = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def exec_command(self, command, timeout=None):
        self.commands.append(command)
        out = b""
        err = b""
        for key, value in self.answers.items():
            if key in command:
                if isinstance(value, tuple):
                    out_val, err_val = value
                    out = out_val if isinstance(out_val, bytes) else out_val.encode("utf-8")
                    err = err_val if isinstance(err_val, bytes) else err_val.encode("utf-8")
                else:
                    out = value if isinstance(value, bytes) else value.encode("utf-8")
                break
        return None, FakeChannel(out), FakeChannel(err)

    def close(self):
        self.closed = True


def _login(client, username, role):
    user = user_management.get_user(username)
    uid = user["id"] if user else user_management.create_user(username, "testpassphrase123", None, [role])
    with client.session_transaction() as sess:
        user_record = user_management.get_user_by_id(uid)
        sess["user_id"] = uid
        sess["username"] = username
        sess["pw_tag"] = fp._password_tag(user_record)
        sess["sid"] = account_security.create_session(uid, "127.0.0.1", "pytest")
        sess["auth_time"] = time.time()
        sess["login"] = True


@pytest.fixture(autouse=True)
def _setup_app_and_db(tmp_path, monkeypatch):
    fp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    monkeypatch.setattr(disktool_core, "list_remotes", lambda: REMOTES)
    monkeypatch.setattr(vm_controller, "list_endpoints", lambda: [])
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: FakeSSHClient())
    user_management.init_user_db()
    account_security.init_db()


def test_execute_remote_command_success(monkeypatch):
    client = FakeSSHClient({"lsblk": "block device output"})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: client)

    out, err = remote_disk_plugin.execute_remote_command("192.0.2.1", 22, "root", "lsblk")
    assert out == "block device output"
    assert err is None
    assert client.closed is True
    assert client.commands == ["lsblk"]


def test_execute_remote_command_ssh_error(monkeypatch):
    client = FakeSSHClient({"bad_cmd": ("", "command not found")})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: client)

    out, err = remote_disk_plugin.execute_remote_command("192.0.2.1", 22, "root", "bad_cmd")
    assert out is None
    assert err == "command not found"
    assert client.closed is True


def test_execute_remote_command_connection_timeout(monkeypatch):
    def _timeout(*args, **kwargs):
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(ssh_helper, "create_client", _timeout)
    out, err = remote_disk_plugin.execute_remote_command("192.0.2.1", 22, "root", "lsblk")
    assert out is None
    assert "timed out" in err


def test_execute_remote_command_exception(monkeypatch):
    def _error(*args, **kwargs):
        raise RuntimeError("handshake failed")

    monkeypatch.setattr(ssh_helper, "create_client", _error)
    out, err = remote_disk_plugin.execute_remote_command("192.0.2.1", 22, "root", "lsblk")
    assert out is None
    assert "handshake failed" in err


def test_list_remote_disks_success(monkeypatch):
    monkeypatch.setattr(
        ssh_helper,
        "create_client",
        lambda *a, **k: FakeSSHClient({"lsblk": SAMPLE_LSBLK}),
    )
    disks, err = remote_disk_plugin.list_remote_disks("192.0.2.1", 22, "root")
    assert err is None
    assert disks is not None
    assert [d["name"] for d in disks] == ["sda", "sdb"]


def test_list_remote_disks_command_error(monkeypatch):
    monkeypatch.setattr(
        ssh_helper,
        "create_client",
        lambda *a, **k: FakeSSHClient({"lsblk": ("", "remote failure")}),
    )
    disks, err = remote_disk_plugin.list_remote_disks("192.0.2.1", 22, "root")
    assert disks is None
    assert err == "remote failure"


def test_list_remote_disks_invalid_json(monkeypatch):
    monkeypatch.setattr(
        ssh_helper,
        "create_client",
        lambda *a, **k: FakeSSHClient({"lsblk": "invalid json syntax"}),
    )
    disks, err = remote_disk_plugin.list_remote_disks("192.0.2.1", 22, "root")
    assert disks is None
    assert err is not None


def test_get_remote_smart_success(monkeypatch):
    client = FakeSSHClient({"smartctl": SAMPLE_SMART})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: client)

    out, err = remote_disk_plugin.get_remote_smart("192.0.2.1", 22, "root", "sda")
    assert err is None
    assert "CT500MX500SSD1" in out
    assert client.commands == ["sudo smartctl -a /dev/sda"]


def test_get_remote_smart_invalid_device():
    out, err = remote_disk_plugin.get_remote_smart("192.0.2.1", 22, "root", "sda; reboot")
    assert out is None
    assert err is not None


def test_get_remote_smart_command_error(monkeypatch):
    monkeypatch.setattr(
        ssh_helper,
        "create_client",
        lambda *a, **k: FakeSSHClient({"smartctl": ("", "smartctl read error")}),
    )
    out, err = remote_disk_plugin.get_remote_smart("192.0.2.1", 22, "root", "sda")
    assert out is None
    assert err == "smartctl read error"


@pytest.mark.parametrize(
    "fs_type,expected_fragment",
    [
        ("ext4", "mkfs.ext4 -F /dev/sda"),
        ("xfs", "mkfs.xfs -f /dev/sda"),
        ("fat32", "mkfs.vfat -F 32 /dev/sda"),
    ],
)
def test_format_remote_disk_supported_filesystems(monkeypatch, fs_type, expected_fragment):
    client = FakeSSHClient({expected_fragment.split()[0]: "success"})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: client)

    ok, msg = remote_disk_plugin.format_remote_disk("192.0.2.1", 22, "root", "sda", fs_type)
    assert ok is True
    assert msg == "Format completed successfully"
    assert len(client.commands) == 1
    assert "wipefs -a /dev/sda" in client.commands[0]
    assert expected_fragment in client.commands[0]


def test_format_remote_disk_invalid_filesystem():
    ok, msg = remote_disk_plugin.format_remote_disk("192.0.2.1", 22, "root", "sda", "btrfs")
    assert ok is False
    assert msg == "Invalid filesystem type"


def test_format_remote_disk_invalid_device():
    ok, msg = remote_disk_plugin.format_remote_disk("192.0.2.1", 22, "root", "../sda", "ext4")
    assert ok is False
    assert msg is not None


def test_format_remote_disk_command_error(monkeypatch):
    monkeypatch.setattr(
        ssh_helper,
        "create_client",
        lambda *a, **k: FakeSSHClient({"wipefs": ("", "wipefs failed")}),
    )
    ok, msg = remote_disk_plugin.format_remote_disk("192.0.2.1", 22, "root", "sda", "ext4")
    assert ok is False
    assert msg == "wipefs failed"


@pytest.mark.parametrize("mode", ["short", "long"])
def test_start_remote_smart_test_modes(monkeypatch, mode):
    client = FakeSSHClient({"smartctl": "started"})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: client)

    ok, msg = remote_disk_plugin.start_remote_smart_test("192.0.2.1", 22, "root", "sda", mode)
    assert ok is True
    assert msg == f"SMART {mode} test started successfully"
    assert client.commands == [f"sudo smartctl -t {mode} /dev/sda"]


def test_start_remote_smart_test_invalid_mode():
    ok, msg = remote_disk_plugin.start_remote_smart_test("192.0.2.1", 22, "root", "sda", "offline")
    assert ok is False
    assert msg == "Invalid SMART test mode"


def test_start_remote_smart_test_invalid_device():
    ok, msg = remote_disk_plugin.start_remote_smart_test("192.0.2.1", 22, "root", "sda|rm", "short")
    assert ok is False
    assert msg is not None


def test_start_remote_smart_test_command_error(monkeypatch):
    monkeypatch.setattr(
        ssh_helper,
        "create_client",
        lambda *a, **k: FakeSSHClient({"smartctl": ("", "device busy")}),
    )
    ok, msg = remote_disk_plugin.start_remote_smart_test("192.0.2.1", 22, "root", "sda", "short")
    assert ok is False
    assert msg == "device busy"


@pytest.mark.parametrize(
    "path,method",
    [
        ("/disks/remote/list/1", "GET"),
        ("/disks/remote/sync/1", "GET"),
        ("/disks/remote/smart/1/sda", "GET"),
        ("/disks/remote/format/1/sda", "GET"),
        ("/disks/remote/format/1/sda", "POST"),
        ("/disks/remote/smart_test/1/sda/short", "GET"),
    ],
)
def test_routes_require_login(path, method):
    client = fp.app.test_client()
    resp = client.open(path, method=method)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert location in ("/", "/login") or location.startswith(("/?next=", "/login?next="))


@pytest.mark.parametrize(
    "path,method",
    [
        ("/disks/remote/sync/1", "GET"),
        ("/disks/remote/format/1/sda", "GET"),
        ("/disks/remote/format/1/sda", "POST"),
        ("/disks/remote/smart_test/1/sda/short", "GET"),
    ],
)
def test_routes_refuse_viewer_role(path, method):
    client = fp.app.test_client()
    _login(client, "viewer_user", "viewer")

    resp = client.open(path, method=method)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/disks")


@pytest.mark.parametrize(
    "path,method",
    [
        ("/disks/remote/list/999", "GET"),
        ("/disks/remote/smart/999/sda", "GET"),
        ("/disks/remote/format/999/sda", "GET"),
        ("/disks/remote/format/999/sda", "POST"),
        ("/disks/remote/smart_test/999/sda/short", "GET"),
    ],
)
def test_routes_redirect_unknown_remote(path, method):
    client = fp.app.test_client()
    _login(client, "admin_user", "admin")

    resp = client.open(path, method=method)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/disks")


def test_remote_disk_list_route_success(monkeypatch):
    client = fp.app.test_client()
    _login(client, "operator_user", "operator")

    ssh_client = FakeSSHClient({"lsblk": SAMPLE_LSBLK})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: ssh_client)

    resp = client.get("/disks/remote/list/1")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "backup-host" in html
    assert "Samsung SSD 860" in html
    assert "sda" in html


def test_remote_disk_list_route_error(monkeypatch):
    client = fp.app.test_client()
    _login(client, "admin_user", "admin")

    ssh_client = FakeSSHClient({"lsblk": ("", "SSH authentication failed")})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: ssh_client)

    resp = client.get("/disks/remote/list/1")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "backup-host" in html


def test_remote_disk_list_route_default_username(monkeypatch):
    client = fp.app.test_client()
    _login(client, "admin_user", "admin")

    captured_usernames = []

    def _client(host, port=22, username="root", timeout=10):
        captured_usernames.append(username)
        return FakeSSHClient({"lsblk": SAMPLE_LSBLK})

    monkeypatch.setattr(ssh_helper, "create_client", _client)

    resp = client.get("/disks/remote/list/2")
    assert resp.status_code == 200
    assert captured_usernames == ["root"]


def test_remote_disk_sync_route_operator():
    client = fp.app.test_client()
    _login(client, "operator_user", "operator")

    resp = client.get("/disks/remote/sync/1")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/disks/remote/list/1")


def test_remote_disk_smart_route_success(monkeypatch):
    client = fp.app.test_client()
    _login(client, "viewer_user", "viewer")

    ssh_client = FakeSSHClient({"smartctl": SAMPLE_SMART})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: ssh_client)

    resp = client.get("/disks/remote/smart/1/sda")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "CT500MX500SSD1" in html
    assert "PASSED" in html


def test_remote_disk_smart_route_error(monkeypatch):
    client = fp.app.test_client()
    _login(client, "admin_user", "admin")

    ssh_client = FakeSSHClient({"smartctl": ("", "Device open failed")})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: ssh_client)

    resp = client.get("/disks/remote/smart/1/sda")
    assert resp.status_code == 200


def test_remote_disk_format_route_get():
    client = fp.app.test_client()
    _login(client, "operator_user", "operator")

    resp = client.get("/disks/remote/format/1/sda")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "sda" in html
    assert "Format Remote Disk" in html


def test_remote_disk_format_route_post_success(monkeypatch):
    client = fp.app.test_client()
    _login(client, "operator_user", "operator")

    ssh_client = FakeSSHClient({"wipefs": "Done"})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: ssh_client)

    resp = client.post("/disks/remote/format/1/sda", data={"fs": "ext4"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/disks/remote/list/1")
    assert any("mkfs.ext4" in cmd for cmd in ssh_client.commands)


def test_remote_disk_format_route_post_failure(monkeypatch):
    client = fp.app.test_client()
    _login(client, "admin_user", "admin")

    ssh_client = FakeSSHClient({"wipefs": ("", "wipefs lock failed")})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: ssh_client)

    resp = client.post("/disks/remote/format/1/sda", data={"fs": "xfs"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/disks/remote/list/1")


def test_remote_disk_smart_test_route_success(monkeypatch):
    client = fp.app.test_client()
    _login(client, "operator_user", "operator")

    ssh_client = FakeSSHClient({"smartctl": "Test initiated"})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: ssh_client)

    resp = client.get("/disks/remote/smart_test/1/sda/short")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/disks/remote/list/1")
    assert any("smartctl -t short" in cmd for cmd in ssh_client.commands)


def test_remote_disk_smart_test_route_failure(monkeypatch):
    client = fp.app.test_client()
    _login(client, "admin_user", "admin")

    ssh_client = FakeSSHClient({"smartctl": ("", "Drive self-test in progress")})
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: ssh_client)

    resp = client.get("/disks/remote/smart_test/1/sda/long")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/disks/remote/list/1")


def test_register_and_role_helper_edge_cases(monkeypatch):
    class DummyApp:
        def __init__(self):
            self.routes = {}

        def route(self, rule, **options):
            def decorator(f):
                self.routes[rule] = f
                return f
            return decorator

    class DummyCore:
        def list_remotes(self):
            return [{"id": 42, "name": "sample", "host": "192.0.2.99", "port": 22, "ssh_user": "tester"}]

    dummy_app = DummyApp()
    dummy_core = DummyCore()
    remote_disk_plugin.register(dummy_app, dummy_core)
    assert "/disks/remote/list/<int:remote_id>" in dummy_app.routes

    sync_func = dummy_app.routes["/disks/remote/sync/<int:remote_id>"]

    with fp.app.test_request_context():
        resp = sync_func(42)
        assert resp.status_code == 302

    with fp.app.test_request_context():
        fp.session["user_id"] = 999999
        monkeypatch.setattr(
            user_management,
            "get_user_role_names",
            lambda uid: (_ for _ in ()).throw(RuntimeError("db error")),
        )
        resp = sync_func(42)
        assert resp.status_code == 302
