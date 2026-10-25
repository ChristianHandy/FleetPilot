# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the system resource monitor."""
import json
import sqlite3
import sys
import threading
from types import SimpleNamespace

import pytest

import system_monitor


@pytest.fixture
def monitor_db(tmp_path, monkeypatch):
    """Initialise an isolated monitor database and clean up any poller."""
    system_monitor.stop_polling()
    previous_thread = system_monitor._poll_thread
    if previous_thread and previous_thread.is_alive():
        previous_thread.join(timeout=1)

    monkeypatch.setattr(system_monitor, "_DB_PATH", None)
    system_monitor.init_db(str(tmp_path))
    yield

    system_monitor.stop_polling()
    thread = system_monitor._poll_thread
    if thread and thread.is_alive():
        thread.join(timeout=1)


def _fake_psutil(cpu_freq=None, temperatures=None):
    """Return a small psutil substitute with representative readings."""
    return SimpleNamespace(
        cpu_percent=lambda interval: 12.345,
        cpu_freq=lambda: cpu_freq,
        virtual_memory=lambda: SimpleNamespace(total=16_000, used=6_000, percent=37.456),
        swap_memory=lambda: SimpleNamespace(total=4_000, used=500),
        disk_partitions=lambda all=False: [
            SimpleNamespace(device="/dev/sda1", mountpoint="/", fstype="ext4"),
        ],
        disk_usage=lambda mountpoint: SimpleNamespace(total=1_000, used=250, free=750, percent=25.0),
        net_io_counters=lambda pernic=False: SimpleNamespace(
            bytes_sent=10, bytes_recv=20, packets_sent=3, packets_recv=4
        ),
        sensors_temperatures=lambda: temperatures,
    )


def _sample(ts, marker):
    """Build a database sample whose payload can be identified in assertions."""
    return {
        "ts": ts,
        "cpu_pct": marker,
        "cpu_freq": 2400.0,
        "ram_total": 16_000,
        "ram_used": 6_000,
        "ram_pct": 37.5,
        "swap_total": 4_000,
        "swap_used": 500,
        "disk_json": json.dumps([{"device": f"disk-{marker}"}]),
        "net_json": json.dumps({"bytes_sent": marker}),
        "temp_json": json.dumps({"cpu": [{"current": marker}]}),
    }


def test_init_db_creates_tables(tmp_path):
    system_monitor.init_db(str(tmp_path))

    db_path = tmp_path / "system_monitor.db"
    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    try:
        objects = conn.execute(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE name IN ('monitor_samples', 'idx_monitor_ts')
            """
        ).fetchall()
    finally:
        conn.close()

    assert ("table", "monitor_samples") in objects
    assert ("index", "idx_monitor_ts") in objects


def test_collect_rounds_and_serialises_readings(monkeypatch):
    psutil = _fake_psutil(
        cpu_freq=SimpleNamespace(current=2345.678),
        temperatures={
            "coretemp": [SimpleNamespace(label="Core 0", current=48.234, high=90.0, critical=100.0)],
        },
    )
    monkeypatch.setitem(sys.modules, "psutil", psutil)
    monkeypatch.setattr(system_monitor.time, "time", lambda: 1_700_000_000)

    sample = system_monitor._collect()

    assert sample["ts"] == 1_700_000_000
    assert sample["cpu_pct"] == 12.3
    assert sample["cpu_freq"] == 2345.7
    assert sample["ram_total"] == 16_000
    assert sample["ram_used"] == 6_000
    assert sample["ram_pct"] == 37.5
    assert sample["swap_total"] == 4_000
    assert sample["swap_used"] == 500
    assert json.loads(sample["disk_json"]) == [{
        "device": "/dev/sda1", "mountpoint": "/", "fstype": "ext4", "total": 1_000,
        "used": 250, "free": 750, "pct": 25.0,
    }]
    assert json.loads(sample["net_json"]) == {
        "bytes_sent": 10, "bytes_recv": 20, "packets_sent": 3, "packets_recv": 4,
    }
    assert json.loads(sample["temp_json"]) == {
        "coretemp": [{"label": "Core 0", "current": 48.234, "high": 90.0, "critical": 100.0}],
    }


def test_collect_returns_none_without_psutil(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)

    assert system_monitor._collect() is None


@pytest.mark.parametrize("cpu_freq, temperatures", [(None, None), (None, {})])
def test_collect_handles_missing_optional_sensor_data(monkeypatch, cpu_freq, temperatures):
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(cpu_freq=cpu_freq, temperatures=temperatures))

    sample = system_monitor._collect()

    assert sample["cpu_freq"] is None
    assert json.loads(sample["temp_json"]) == {}


def test_queries_return_latest_history_and_paginated_log(monitor_db, monkeypatch):
    now = 1_700_000_000
    monkeypatch.setattr(system_monitor.time, "time", lambda: now)
    for seconds_ago, marker in ((20, 1), (10, 2), (0, 3)):
        system_monitor._save(_sample(now - seconds_ago, marker))

    latest = system_monitor.get_latest()
    history = system_monitor.get_history(hours=1, limit=2)
    log = system_monitor.get_log(page=2, per_page=2)

    assert latest["cpu_pct"] == 3
    assert latest["disk"] == [{"device": "disk-3"}]
    assert [sample["cpu_pct"] for sample in history] == [1, 2]
    assert log["total"] == 3
    assert log["pages"] == 2
    assert [sample["cpu_pct"] for sample in log["items"]] == [1]


def test_purge_old_removes_expired_samples(monitor_db, monkeypatch):
    now = 1_700_000_000
    monkeypatch.setattr(system_monitor.time, "time", lambda: now)
    system_monitor._save(_sample(now - system_monitor._RETENTION_DAYS * 86400 - 1, 1))
    system_monitor._save(_sample(now - system_monitor._RETENTION_DAYS * 86400, 2))
    system_monitor._save(_sample(now, 3))

    system_monitor._purge_old()

    assert [sample["cpu_pct"] for sample in system_monitor.get_history(hours=24 * 365)] == [2, 3]


def test_start_and_stop_polling_runs_a_thread(monkeypatch, monitor_db):
    collected = threading.Event()

    def collect_once():
        collected.set()
        return None

    monkeypatch.setattr(system_monitor, "_collect", collect_once)
    monkeypatch.setattr(system_monitor, "_POLL_INTERVAL", 60)

    system_monitor.start_polling()

    assert collected.wait(timeout=1)
    thread = system_monitor._poll_thread
    assert thread is not None and thread.is_alive()

    system_monitor.stop_polling()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert not system_monitor._poll_running
