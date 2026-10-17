# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the example Slack notification plugin."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

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
