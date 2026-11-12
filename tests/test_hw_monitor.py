# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for hw_monitor: collect_metrics parsing of the recorded remote
script output (SSH mocked), the task manager and its APIs, the PWM path
check, and ssh_run error reporting."""
import json

import pytest

import hw_monitor


@pytest.fixture
def db(tmp_path, monkeypatch):
    hw_monitor.init_db(str(tmp_path))
    # Rate computation keeps per-server state in module globals; isolate it.
    monkeypatch.setattr(hw_monitor, "_net_prev", {})
    monkeypatch.setattr(hw_monitor, "_disk_prev", {})
    for name in [n for n in vars(hw_monitor.collect_metrics) if n.startswith("_lh_")]:
        monkeypatch.delattr(hw_monitor.collect_metrics, name, raising=False)
    return tmp_path


def _add_server(name="srv1", ip="10.0.0.9"):
    conn = hw_monitor.get_db()
    cur = conn.execute(
        "INSERT INTO hw_servers (name, ip, ssh_port, ssh_user, ssh_pass) "
        "VALUES (?,?,?,?,?)", (name, ip, 22, "root", hw_monitor._enc("pw")))
    conn.commit()
    sid = cur.lastrowid
    row = conn.execute("SELECT * FROM hw_servers WHERE id=?", (sid,)).fetchone()
    conn.close()
    return dict(row)


def _live_row(sid):
    conn = hw_monitor.get_db()
    row = conn.execute("SELECT * FROM hw_live_metrics WHERE server_id=?", (sid,)).fetchone()
    conn.close()
    return dict(row) if row else None


# Recorded output of the remote collect script: a fully equipped server.
RECORDED = {
    "cpu_pct": 12.5, "cpu_cores": 8, "cpu_temp": 55.0,
    "ram_used_mb": 4096, "ram_total_mb": 16384,
    "swap_used_mb": 0, "swap_total_mb": 2048,
    "net_iface": "eth0", "net_rx_bytes": 1048576, "net_tx_bytes": 2097152,
    "disk_read_sectors": 1000, "disk_write_sectors": 2000,
    "fans": [{"chip": "nct6798", "feature": "fan1", "rpm": 1200, "channel": 0}],
    "gpu_temp": 61.0, "gpu_on_bus": True, "gpu_vendor": "nvidia",
    "gpu_util": 33.0, "gpu_mem_used_mb": 1024, "gpu_mem_total_mb": 8192,
    "stress_running": False, "uptime_s": 3600, "ts": 1000.0,
}


def _fake_ssh(monkeypatch, *results):
    queue = list(results)
    calls = []

    def fake_run_script(ip, port, user, pw, script, timeout=15):
        calls.append((ip, port, user))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(hw_monitor, "ssh_run_script", fake_run_script)
    return calls


# ── collect_metrics: parsing the remote script's output ─────────────────────

def test_collect_metrics_stores_a_full_snapshot(db, monkeypatch):
    server = _add_server()
    calls = _fake_ssh(monkeypatch, (True, json.dumps(RECORDED)))
    hw_monitor.collect_metrics(server)
    assert calls == [("10.0.0.9", 22, "root")]
    row = _live_row(server["id"])
    assert row["reachable"] == 1
    assert row["cpu_pct"] == 12.5
    assert row["cpu_temp"] == 55.0
    assert row["cpu_cores"] == 8
    assert row["ram_used_mb"] == 4096 and row["ram_total_mb"] == 16384
    assert json.loads(row["fans"]) == RECORDED["fans"]
    assert row["gpu_temp"] == 61.0 and row["gpu_vendor"] == "nvidia"
    assert row["gpu_mem_total_mb"] == 8192
    assert row["uptime_s"] == 3600
    # First sample: no previous counters, so no rates yet.
    assert row["net_rx_kbps"] is None and row["disk_read_kbps"] is None


def test_collect_metrics_computes_rates_from_the_previous_sample(db, monkeypatch):
    server = _add_server()
    second = dict(RECORDED, ts=1010.0,
                  net_rx_bytes=RECORDED["net_rx_bytes"] + 1048576,
                  net_tx_bytes=RECORDED["net_tx_bytes"] + 524288,
                  disk_read_sectors=RECORDED["disk_read_sectors"] + 1024,
                  disk_write_sectors=RECORDED["disk_write_sectors"] + 2048)
    _fake_ssh(monkeypatch, (True, json.dumps(RECORDED)), (True, json.dumps(second)))
    hw_monitor.collect_metrics(server)
    hw_monitor.collect_metrics(server)
    row = _live_row(server["id"])
    # 1 MiB in 10 s = 102.4 KiB/s; disk sectors are 512 bytes.
    assert row["net_rx_kbps"] == 102.4
    assert row["net_tx_kbps"] == 51.2
    assert row["disk_read_kbps"] == 51.2
    assert row["disk_write_kbps"] == 102.4


def test_collect_metrics_tolerates_missing_sensors(db, monkeypatch):
    server = _add_server()
    sparse = {"cpu_pct": 3.0, "ts": 1000.0}     # no temps, fans or GPU at all
    _fake_ssh(monkeypatch, (True, json.dumps(sparse)))
    hw_monitor.collect_metrics(server)
    row = _live_row(server["id"])
    assert row["reachable"] == 1
    assert row["cpu_pct"] == 3.0
    assert row["cpu_temp"] is None
    assert row["gpu_temp"] is None
    assert json.loads(row["fans"]) == []


def test_collect_metrics_marks_the_server_unreachable_when_ssh_fails(db, monkeypatch):
    server = _add_server()
    _fake_ssh(monkeypatch, (False, "SSH command failed: the device could not be reached."))
    hw_monitor.collect_metrics(server)
    assert _live_row(server["id"])["reachable"] == 0


def test_collect_metrics_marks_the_server_unreachable_on_bad_output(db, monkeypatch):
    server = _add_server()
    _fake_ssh(monkeypatch, (True, "this is not json"))
    hw_monitor.collect_metrics(server)
    assert _live_row(server["id"])["reachable"] == 0


# ── ssh_run / ssh_run_script ────────────────────────────────────────────────

class _FakeStdout:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeStdin:
    def __init__(self):
        self.written = ""
        self.channel = self

    def write(self, text):
        self.written += text

    def shutdown_write(self):
        pass


class _FakeClient:
    def __init__(self, output=b""):
        self._output = output
        self.stdin = _FakeStdin()
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def exec_command(self, cmd, timeout=None):
        self.commands.append(cmd)
        return self.stdin, _FakeStdout(self._output), None


def test_ssh_run_returns_the_command_output(monkeypatch):
    client = _FakeClient(b"  output line \n")
    monkeypatch.setattr(hw_monitor.ssh_helper, "create_client", lambda **kw: client)
    ok, out = hw_monitor.ssh_run("10.0.0.9", 22, "root", "pw", "uptime")
    assert (ok, out) == (True, "output line")
    assert client.commands == ["uptime"]


def test_ssh_run_reports_connection_errors_instead_of_raising(monkeypatch):
    def refused(**kwargs):
        raise OSError("Connection refused")

    monkeypatch.setattr(hw_monitor.ssh_helper, "create_client", refused)
    ok, out = hw_monitor.ssh_run("10.0.0.9", 22, "root", "pw", "uptime")
    assert ok is False
    assert out == "SSH command failed: the device could not be reached."


def test_ssh_run_script_feeds_the_script_on_stdin(monkeypatch):
    client = _FakeClient(b"42\n")
    monkeypatch.setattr(hw_monitor.ssh_helper, "create_client", lambda **kw: client)
    ok, out = hw_monitor.ssh_run_script("10.0.0.9", 22, "root", "pw", "print(42)")
    assert (ok, out) == (True, "42")
    assert client.commands == ["python3 -"]
    assert client.stdin.written == "print(42)"


# ── Task manager ────────────────────────────────────────────────────────────

def _run_task(server, action_fn, title="Test task"):
    task_id = hw_monitor.start_task(server, action_fn, title)
    hw_monitor._task_threads[task_id].join(timeout=10)
    conn = hw_monitor.get_db()
    row = conn.execute("SELECT * FROM hw_tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row)


def test_task_run_success(db):
    server = _add_server()

    def do_work(srv, log_fn):
        log_fn("step 1")
        log_fn("step 2")
        return "all done"

    row = _run_task(server, do_work)
    assert row["status"] == "success"
    assert row["result"] == "all done"
    assert row["type"] == "do_work"
    assert row["server_name"] == "srv1"
    assert "step 1" in row["log"] and "step 2" in row["log"]
    assert row["finished_ts"] is not None


def test_task_run_failure(db):
    server = _add_server()

    def do_broken(srv, log_fn):
        log_fn("before the crash")
        raise RuntimeError("kaput")

    row = _run_task(server, do_broken)
    assert row["status"] == "failed"
    # The stored message is the sanitized one, without the exception text.
    assert row["result"] == "Task failed. Details are in the FleetPilot log."
    assert "before the crash" in row["log"]
    assert "ERROR: Task failed." in row["log"]


@pytest.fixture
def client(db):
    from flask import Flask
    app = Flask(__name__)
    hw_monitor.register_routes(app, lambda view: view)
    return app.test_client()


def test_task_list_and_detail_apis(db, client):
    server = _add_server()

    def do_work(srv, log_fn):
        log_fn("hello log")
        return "done"

    row = _run_task(server, do_work)
    tasks = client.get("/api/hw/tasks").get_json()
    assert [t["id"] for t in tasks] == [row["id"]]
    assert tasks[0]["status"] == "success" and tasks[0]["title"] == "Test task"

    detail = client.get(f"/api/hw/tasks/{row['id']}").get_json()
    assert detail["result"] == "done"

    log = client.get(f"/api/hw/tasks/{row['id']}/log").get_json()
    assert log == {"lines": ["hello log"], "status": "success"}

    missing = client.get("/api/hw/tasks/nope")
    assert missing.status_code == 404
    assert client.get("/api/hw/tasks/nope/log").get_json() == {
        "lines": [], "status": "not_found"}


def _insert_task(task_id, status):
    conn = hw_monitor.get_db()
    conn.execute("INSERT INTO hw_tasks (id, server_id, server_name, type, title, "
                 "status, started_ts) VALUES (?,?,?,?,?,?,?)",
                 (task_id, 1, "srv1", "do_work", "t", status, "2026-01-01T00:00:00"))
    conn.commit()
    conn.close()


def test_task_cancel_delete_and_clear_apis(db, client):
    _insert_task("run1", "running")
    _insert_task("done1", "success")
    assert client.post("/api/hw/tasks/run1/cancel").get_json() == {"ok": True}
    tasks = {t["id"]: t["status"] for t in client.get("/api/hw/tasks").get_json()}
    assert tasks == {"run1": "cancelled", "done1": "success"}

    assert client.post("/api/hw/tasks/clear").get_json() == {"ok": True}
    assert client.get("/api/hw/tasks").get_json() == []

    _insert_task("run2", "running")
    assert client.post("/api/hw/tasks/run2/delete").get_json() == {"ok": True}
    assert client.get("/api/hw/tasks").get_json() == []


# ── Fan control: the PWM path check ─────────────────────────────────────────

def test_fan_endpoint_rejects_bad_pwm_paths(db, client):
    server = _add_server()
    for path in ("/etc/passwd", "/sys/class/hwmon/hwmon2/fan1_input",
                 "/sys/class/hwmon/hwmon2/../../etc/pwm1", "pwm1", ""):
        resp = client.post(f"/api/hw/server/{server['id']}/fan",
                           json={"pwm_path": path, "value_pct": 50})
        assert resp.status_code == 400, path
        assert resp.get_json()["output"] == "Invalid PWM path"


def test_fan_endpoint_rejects_a_non_numeric_value(db, client):
    server = _add_server()
    resp = client.post(f"/api/hw/server/{server['id']}/fan",
                       json={"pwm_path": "/sys/class/hwmon/hwmon2/pwm1",
                             "value_pct": "fast"})
    assert resp.status_code == 400
    assert resp.get_json()["output"] == "Invalid value"


def test_fan_endpoint_writes_the_pwm_value(db, client, monkeypatch):
    server = _add_server()
    commands = []

    def fake_ssh_run(ip, port, user, pw, cmd, timeout=12):
        commands.append(cmd)
        return True, "255"

    monkeypatch.setattr(hw_monitor, "ssh_run", fake_ssh_run)
    resp = client.post(f"/api/hw/server/{server['id']}/fan",
                       json={"pwm_path": "/sys/class/hwmon/hwmon2/pwm1",
                             "value_pct": 100})
    assert resp.get_json() == {"ok": True, "output": "255"}
    assert "echo 255 > /sys/class/hwmon/hwmon2/pwm1" in commands[0]

    # Percentages are clamped to 0–100 before they reach the remote shell.
    resp = client.post(f"/api/hw/server/{server['id']}/fan",
                       json={"pwm_path": "/sys/class/hwmon/hwmon2/pwm1",
                             "value_pct": 250})
    assert resp.status_code == 200
    assert "echo 255 > " in commands[-1]
