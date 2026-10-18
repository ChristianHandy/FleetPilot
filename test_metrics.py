# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for metrics.render(): the Prometheus text page served at /metrics."""
from unittest.mock import Mock

import pytest

import metrics


@pytest.fixture
def managers():
    """A SMART manager and system monitor that scrape cleanly with no data."""
    smart = Mock()
    smart.get_health_summary.return_value = {"counts": {}, "active_alerts": 0}
    smart.get_all_disks.return_value = []
    system = Mock()
    system.get_latest.return_value = {}
    return smart, system


def _metric_lines(text, name):
    prefix = name + "{"
    return [line for line in text.splitlines() if line.startswith(prefix)]


def test_info_metric_carries_version_label(managers):
    smart, system = managers
    text = metrics.render({"version": "9.9.9"}, {}, smart, system)
    assert 'fleetpilot_info{version="9.9.9"} 1' in text


def test_hosts_count_and_one_update_age_per_host(managers):
    smart, system = managers
    hosts = {
        "h1": {"last_update": "2020-01-01T00:00:00Z"},
        "h2": {"last_update": "2020-01-01T00:00:00+00:00"},
    }
    text = metrics.render({"version": "x"}, hosts, smart, system)
    assert "fleetpilot_hosts 2" in text
    assert len(_metric_lines(text, "fleetpilot_host_last_update_age_seconds")) == 2


def test_host_without_timestamps_skips_age_lines(managers):
    smart, system = managers
    text = metrics.render({"version": "x"}, {"bare": {}}, smart, system)
    assert "fleetpilot_hosts 1" in text
    assert "fleetpilot_host_last_update_age_seconds" not in text
    assert "fleetpilot_host_last_seen_age_seconds" not in text


def test_optional_collectors_omitted_when_none(managers):
    smart, system = managers
    text = metrics.render({"version": "x"}, {}, smart, system)
    for name in ("fleetpilot_disk_tasks_running", "fleetpilot_router_up",
                 "fleetpilot_vulnerabilities", "fleetpilot_vulnerability_scan_age_seconds"):
        assert name not in text


def test_label_values_are_escaped(managers):
    smart, system = managers
    hosts = {'a"b\\c\nd': {"last_update": "2020-01-01T00:00:00Z"}}
    text = metrics.render({"version": "x"}, hosts, smart, system)
    assert 'host="a\\"b\\\\c\\nd"' in text


def test_help_and_type_written_once_for_many_hosts(managers):
    smart, system = managers
    hosts = {f"host-{i}": {"last_update": "2020-01-01T00:00:00Z"} for i in range(50)}
    text = metrics.render({"version": "x"}, hosts, smart, system)
    assert text.count("# HELP fleetpilot_host_last_update_age_seconds ") == 1
    assert text.count("# TYPE fleetpilot_host_last_update_age_seconds ") == 1
    assert len(_metric_lines(text, "fleetpilot_host_last_update_age_seconds")) == 50


def test_collector_failures_become_scrape_errors(managers):
    smart, system = managers
    smart.get_health_summary.side_effect = RuntimeError("smart boom")
    system.get_latest.side_effect = RuntimeError("system boom")
    text = metrics.render({"version": "x"}, {}, smart, system)
    assert 'fleetpilot_scrape_error{collector="smart"} 1' in text
    assert 'fleetpilot_scrape_error{collector="system"} 1' in text
