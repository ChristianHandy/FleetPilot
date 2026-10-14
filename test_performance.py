# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the performance work: these paths must stay fast and correct."""
import json
import socket
import sqlite3
import time

import pytest

import app as fp
import audit_log
import hw_monitor
import user_management


def test_host_checks_run_in_parallel_and_are_cached(monkeypatch):
    calls = []

    def slow_connect(address, timeout=None):
        calls.append(address)
        time.sleep(0.2)
        raise OSError("unreachable")
    monkeypatch.setattr(fp.socket, "create_connection", slow_connect)
    fp._ONLINE_CACHE.clear()
    hosts = {f"h{i}": {"host": f"192.0.2.{i}", "user": "root", "port": 22} for i in range(20)}
    started = time.perf_counter()
    status = fp.hosts_online(hosts)
    assert time.perf_counter() - started < 1.5          # 20 x 0.2 s would be 4 s in a row
    assert set(status) == set(hosts) and not any(status.values())
    fp.hosts_online(hosts)
    assert len(calls) == 20                             # second call answered from the cache


def test_online_check_does_not_log_in(monkeypatch):
    """A port check only; an SSH login attempt would show up in the host's auth log."""
    server = socket.socket()
    server.bind(("127.0.0.2", 0))
    server.listen(1)
    monkeypatch.setattr(fp.ssh_helper, "create_client", lambda *a, **k: pytest.fail("SSH login attempted"))
    fp._ONLINE_CACHE.clear()
    assert fp.is_online("127.0.0.2", "root", server.getsockname()[1])
    server.close()


def test_hw_monitor_imports_hosts_json_and_encrypts_passwords(tmp_path, recwarn):
    data = tmp_path / "data"
    data.mkdir()
    (data / "hosts.json").write_text(json.dumps({"web1": {"host": "192.0.2.10", "user": "admin", "password": "s3cret-pw"}}))
    previous = hw_monitor._DB_PATH
    try:
        hw_monitor.init_db(str(data))          # imports hosts.json
    finally:
        hw_monitor._DB_PATH = previous
    con = sqlite3.connect(data / "hw_monitor.db")
    row = con.execute("SELECT name, ip, ssh_user, ssh_pass FROM hw_servers").fetchone()
    con.close()
    assert row[:3] == ("web1", "192.0.2.10", "admin")
    assert row[3] != "s3cret-pw" and hw_monitor._pw({"ssh_pass": row[3]}) == "s3cret-pw"
    assert not [w for w in recwarn if "Auto-import" in str(w.message)]


def test_roles_are_read_once_per_request(monkeypatch):
    calls = []
    real = user_management.get_user_role_names
    monkeypatch.setattr(user_management, "get_user_role_names", lambda uid: calls.append(uid) or real(uid))
    user = user_management.get_user("perf_admin")
    uid = user["id"] if user else user_management.create_user("perf_admin", "perf-pass-phrase-77", None, ["admin"])
    with fp.app.test_request_context("/"):
        fp.session["user_id"] = uid
        for _ in range(5):
            assert fp.current_user_has_role("admin")
    assert len(calls) == 1
    assert "admin" in user_management.roles_by_user()[uid]


def test_audit_chain_check_is_cached(monkeypatch):
    audit_log._chain_cache.update(at=0.0, result=None)
    runs = []
    monkeypatch.setattr(audit_log, "verify_chain", lambda: runs.append(1) or {"ok": True, "checked": 0, "first_bad_id": None})
    for _ in range(3):
        audit_log.verify_chain_cached()
    assert len(runs) == 1


def test_registry_sync_writes_once(tmp_path):
    import server_registry
    registry = server_registry.ServerRegistry(str(tmp_path))
    commits = []
    conn = registry._conn()

    class Counting:
        def __getattr__(self, name):
            return getattr(conn, name)

        def commit(self):
            commits.append(1)
            conn.commit()
    registry._local.conn = Counting()
    hosts = {f"h{i}": {"host": f"192.0.2.{i}", "user": "root", "tags": []} for i in range(25)}
    with registry.batch():
        fp._sync_hosts_into(registry, hosts)
    assert len(commits) == 1
    assert len(registry.list_servers()) == 25
    conn.close()
