# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for automatic update settings and scheduled host updates."""

import importlib.util
import json
from pathlib import Path
import time
from unittest.mock import Mock, call

from apscheduler.schedulers import background
import pytest


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / "data"
    monkeypatch.setenv("FLEETPILOT_DATA_DIR", str(path))
    return path


@pytest.fixture
def scheduler_module(data_dir, monkeypatch):
    # Load a separate module so the real scheduler never starts for these tests.
    monkeypatch.setattr(background, "BackgroundScheduler", Mock(return_value=Mock()))
    spec = importlib.util.spec_from_file_location("scheduler_under_test", Path(__file__).with_name("scheduler.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "run_update", Mock(side_effect=AssertionError("Unexpected host update")))
    return module


def test_missing_settings_use_defaults(scheduler_module, data_dir):
    assert not data_dir.exists()
    assert scheduler_module.load_update_settings() == {
        "automatic_updates_enabled": False,
        "update_frequency": "daily",
        "last_auto_update": None,
        "notification_enabled": True,
    }
    assert data_dir.is_dir()
    assert not (data_dir / "update_settings.json").exists()


def test_save_and_load_settings(scheduler_module, data_dir):
    settings = {
        "automatic_updates_enabled": True,
        "update_frequency": "weekly",
        "last_auto_update": "Fri Oct 16 09:00:00 2026",
        "notification_enabled": False,
    }
    scheduler_module.save_update_settings(settings)

    assert json.loads((data_dir / "update_settings.json").read_text()) == settings
    assert scheduler_module.load_update_settings() == settings


def test_invalid_settings_use_defaults(scheduler_module, data_dir):
    defaults = scheduler_module.load_update_settings()
    (data_dir / "update_settings.json").write_text("{invalid JSON", encoding="utf-8")

    assert scheduler_module.load_update_settings() == defaults


@pytest.mark.parametrize("settings", [{"automatic_updates_enabled": False}, {}], ids=["disabled", "unset"])
def test_disabled_updates_leave_hosts_and_settings_alone(scheduler_module, data_dir, settings):
    scheduler_module.save_update_settings(settings)
    (data_dir / "hosts.json").write_text(
        json.dumps({"nas": {"host": "nas.invalid", "user": "admin"}}), encoding="utf-8"
    )
    before = (data_dir / "update_settings.json").read_text()

    scheduler_module.scheduled_updates()

    scheduler_module.run_update.assert_not_called()
    assert (data_dir / "update_settings.json").read_text() == before


def test_enabled_updates_run_once_per_host_and_save_the_time(scheduler_module, data_dir, monkeypatch):
    settings = {
        "automatic_updates_enabled": True,
        "update_frequency": "weekly",
        "last_auto_update": "previous run",
        "notification_enabled": False,
    }
    scheduler_module.save_update_settings(settings)
    hosts = {
        "nas": {"host": "nas.invalid", "user": "storage_admin"},
        "web": {"host": "web.invalid", "user": "web_admin"},
    }
    (data_dir / "hosts.json").write_text(json.dumps(hosts), encoding="utf-8")
    scheduler_module.run_update.side_effect = None
    timestamp = "Sat Oct 17 09:00:00 2026"
    monkeypatch.setattr(time, "ctime", lambda: timestamp)

    scheduler_module.scheduled_updates()

    assert scheduler_module.run_update.call_args_list == [
        call("nas.invalid", "storage_admin", "nas", []),
        call("web.invalid", "web_admin", "web", []),
    ]
    assert scheduler_module.load_update_settings() == {**settings, "last_auto_update": timestamp}


@pytest.mark.parametrize("content", [None, "{invalid JSON"], ids=["missing", "invalid"])
def test_missing_or_invalid_hosts_do_not_run_updates(scheduler_module, data_dir, content):
    settings = {"automatic_updates_enabled": True, "last_auto_update": "previous run"}
    scheduler_module.save_update_settings(settings)
    if content is not None:
        (data_dir / "hosts.json").write_text(content, encoding="utf-8")

    scheduler_module.scheduled_updates()

    scheduler_module.run_update.assert_not_called()
    assert scheduler_module.load_update_settings() == settings
