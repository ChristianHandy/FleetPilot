# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the example Slack notification plugin."""

import json
import socket
import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from addons import example_host_ping
from addons import example_slack_notify as slack_notify


@pytest.fixture(autouse=True)
def urlopen(monkeypatch):
    opener = Mock(side_effect=AssertionError("Unexpected HTTP request"))
    monkeypatch.setattr(slack_notify.urllib.request, "urlopen", opener)
    return opener


@pytest.mark.parametrize("webhook_url", [None, ""], ids=["unset", "empty"])
def test_send_slack_without_webhook(monkeypatch, urlopen, webhook_url):
    if webhook_url is None:
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    else:
        monkeypatch.setenv("SLACK_WEBHOOK_URL", webhook_url)

    assert slack_notify._send_slack("Update finished") is False
    urlopen.assert_not_called()


@pytest.mark.parametrize(("status", "expected"), [(200, True), (500, False)])
def test_send_slack_posts_json(monkeypatch, urlopen, status, expected):
    webhook_url = "https://example.invalid/slack"
    monkeypatch.setenv("SLACK_WEBHOOK_URL", webhook_url)
    urlopen.side_effect = None
    urlopen.return_value = nullcontext(SimpleNamespace(status=status))
    message = "Update finished for café ✅"

    assert slack_notify._send_slack(message) is expected

    urlopen.assert_called_once()
    request = urlopen.call_args.args[0]
    assert request.full_url == webhook_url
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {"text": message}
    assert urlopen.call_args.kwargs["timeout"] == 5


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(URLError("Connection unavailable"), id="connection"),
        pytest.param(HTTPError("https://example.invalid/slack", 500, "Server error", {}, None), id="http500"),
    ],
)
def test_send_slack_handles_request_errors(monkeypatch, urlopen, error):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.invalid/slack")
    urlopen.side_effect = error

    assert slack_notify._send_slack("Update finished") is False
    urlopen.assert_called_once()


@pytest.mark.parametrize(
    ("host", "result", "name", "status", "packages"),
    [
        pytest.param({"name": "nas"}, {"success": True, "packages_updated": 3}, "nas", "succeeded", 3, id="success"),
        pytest.param({"name": "nas"}, {"success": False, "packages_updated": 0}, "nas", "failed", 0, id="failure"),
        pytest.param({}, {}, "unknown", "failed", 0, id="defaults"),
    ],
)
def test_update_post_message(monkeypatch, host, result, name, status, packages):
    send_slack = Mock(return_value=True)
    monkeypatch.setattr(slack_notify, "_send_slack", send_slack)

    slack_notify._on_update_post(host, result)

    send_slack.assert_called_once()
    message = send_slack.call_args.args[0]
    assert f"`{name}`" in message
    assert status in message
    assert f"Packages updated: *{packages}*" in message


@pytest.mark.parametrize(
    ("data", "version"),
    [pytest.param({"version": "1.2.3"}, "1.2.3", id="version"), pytest.param({}, "?", id="missing-version")],
)
def test_new_version_notification(monkeypatch, data, version):
    send_slack = Mock(return_value=True)
    monkeypatch.setattr(slack_notify, "_send_slack", send_slack)

    slack_notify._on_notification("new_version_available", data)

    send_slack.assert_called_once()
    assert f"*{version}*" in send_slack.call_args.args[0]


def test_other_notifications_are_ignored(monkeypatch):
    send_slack = Mock(return_value=True)
    monkeypatch.setattr(slack_notify, "_send_slack", send_slack)

    slack_notify._on_notification("host_offline", {"name": "nas"})

    send_slack.assert_not_called()


# ---------------------------------------------------------------------------
# Host Ping example plugin (issue #158)
# ---------------------------------------------------------------------------


class FakeCreateConnection:
    """
    Stands in for ``socket.create_connection``

    ``outcomes`` maps a port to what happens there: ``"open"``, ``"refused"``,
    ``"timeout"``, ``"unreachable"`` or ``"dns"``. ``delays`` adds a real sleep
    before the outcome, so a test can tell whether a failed attempt's time was
    counted.
    """

    def __init__(self, outcomes, delays=None):
        self.outcomes = outcomes
        self.delays = delays or {}
        self.attempts = []

    def __call__(self, address, timeout=None):
        port = address[1]
        self.attempts.append(port)
        time.sleep(self.delays.get(port, 0))
        outcome = self.outcomes.get(port, "timeout")
        if outcome == "open":
            return nullcontext(None)
        if outcome == "refused":
            raise ConnectionRefusedError(111, "Connection refused")
        if outcome == "timeout":
            raise socket.timeout("timed out")
        if outcome == "dns":
            raise socket.gaierror(-2, "Name or service not known")
        raise OSError(113, "No route to host")


@pytest.fixture
def create_connection(monkeypatch):
    """Replace socket.create_connection and return the recording fake."""

    def install(outcomes, delays=None):
        fake = FakeCreateConnection(outcomes, delays)
        monkeypatch.setattr(example_host_ping.socket, "create_connection", fake)
        return fake

    return install


def test_ping_uses_the_first_port_that_answers(create_connection):
    fake = create_connection({80: "open", 22: "open"})

    result = example_host_ping.probe_host("10.0.0.5")

    assert result["ok"] is True
    assert result["port"] == 80
    assert result["error"] is None
    assert result["ms"] >= 0
    assert fake.attempts == [80]  # 22 不用再试


def test_slow_failed_attempt_is_not_counted(create_connection):
    """
    Regression test: the time of a failed attempt must not be charged

    The timer used to start before the port 80 attempt, so a host without a
    web server was reported with the port 80 timeout added (up to 2000 ms)
    even when SSH answered in a millisecond.
    """
    fake = create_connection({80: "timeout", 22: "open"}, delays={80: 0.3})

    result = example_host_ping.probe_host("10.0.0.5")

    assert result["ok"] is True
    assert result["port"] == 22
    assert fake.attempts == [80, 22]
    assert result["ms"] < 200, "the port 80 timeout leaked into the reported time"


def test_refused_connection_means_the_host_is_up(create_connection):
    """
    Regression test: a refused connection is an answer, not a timeout

    A host that answers with an RST is reachable; only the port is closed.
    """
    create_connection({80: "refused", 22: "refused"})

    result = example_host_ping.probe_host("10.0.0.5")

    assert result["ok"] is True
    assert result["error"] == "port closed"
    assert result["ms"] >= 0


def test_refused_port_80_still_looks_for_an_open_port(create_connection):
    """A refused port proves the host is up, but an open port is a better answer"""
    fake = create_connection({80: "refused", 22: "open"})

    result = example_host_ping.probe_host("10.0.0.5")

    assert result["ok"] is True
    assert result["port"] == 22
    assert result["error"] is None
    assert fake.attempts == [80, 22]


@pytest.mark.parametrize(
    ("outcome", "error"),
    [("timeout", "timeout"), ("unreachable", "unreachable"), ("dns", "dns")],
    ids=["timeout", "no-route", "dns"],
)
def test_unanswered_probe_reports_the_reason(create_connection, outcome, error):
    """
    Regression test: a failed probe says why, instead of a bare "Timeout"
    """
    create_connection({80: outcome, 22: outcome})

    result = example_host_ping.probe_host("10.0.0.5")

    assert result == {"ok": False, "ms": None, "port": None, "error": error}


@pytest.fixture
def ping_client():
    """A Flask app with the plugin's route registered and a signed-in session"""
    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "test"
    example_host_ping.register(app, None)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    return client


def test_ping_route_returns_port_and_time(ping_client, create_connection):
    create_connection({80: "refused", 22: "open"})

    response = ping_client.get("/plugins/ping?ip=10.0.0.5")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["port"] == 22
    assert data["ip"] == "10.0.0.5"
    assert isinstance(data["ms"], int)


def test_ping_route_without_ip_is_rejected(ping_client, create_connection):
    fake = create_connection({})

    response = ping_client.get("/plugins/ping")

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "no ip"}
    assert fake.attempts == []
