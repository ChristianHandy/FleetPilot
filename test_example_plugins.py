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


# ---------------------------------------------------------------------------
# End-to-end plugin hooks: update_pre, update_post, notification (issue #145)
# ---------------------------------------------------------------------------


class _FakeChannel:
    def __init__(self, raw=b"", exit_status=0):
        import io

        self._raw = raw
        self._exit_status = exit_status
        self._io = io

    def makefile(self, mode="rb"):
        return self._io.BytesIO(self._raw)

    def recv_exit_status(self):
        return self._exit_status


class _FakeStream:
    def __init__(self, text="", exit_status=0):
        self._raw = text.encode("utf-8")
        self.channel = _FakeChannel(raw=self._raw, exit_status=exit_status)

    def read(self):
        return self._raw


class _FakeLinuxSSH:
    def __init__(self, upgrade_output="3 upgraded, 1 newly installed, 0 to remove and 0 not upgraded.", exit_status=0):
        self.upgrade_output = upgrade_output
        self.exit_status = exit_status
        self.closed = False

    def exec_command(self, command, timeout=None, get_pty=False):
        import linux_distro
        import updater

        if command == updater.WINDOWS_DETECTION_COMMAND:
            return None, _FakeStream("linux"), _FakeStream("")
        if command == linux_distro.OS_RELEASE_COMMAND:
            return None, _FakeStream('ID=ubuntu\nPRETTY_NAME="Ubuntu 24.04 LTS"\n'), _FakeStream("")
        if "apt-get" in command:
            return None, _FakeStream(self.upgrade_output, exit_status=self.exit_status), _FakeStream("apt error")
        return None, _FakeStream(""), _FakeStream("")

    def close(self):
        self.closed = True


def test_update_and_notification_hooks_are_called_with_documented_arguments(tmp_path, monkeypatch):
    import addon_loader
    import email_config
    import email_notifier
    import notify
    import updater
    import version_manager
    from flask import Flask

    addon_dir = tmp_path / "addons"
    tpl_dir = tmp_path / "templates"
    addon_dir.mkdir()
    tpl_dir.mkdir()

    calls = {"pre": [], "post": [], "notify": []}
    log_snapshots = {}

    app = Flask(__name__)
    mgr = addon_loader.AddonManager(app, None)
    plugin_file = addon_dir / "recorder_plugin.py"
    plugin_file.write_text(
        "addon_meta = {\n"
        '    "name": "Recorder",\n'
        '    "version": "1.0.0",\n'
        '    "update_pre": lambda host: None,\n'
        '    "update_post": lambda host, result: None,\n'
        '    "notification": lambda event, data: None,\n'
        "}\n",
        encoding="utf-8",
    )
    mgr.load_addons(str(addon_dir), str(tpl_dir))

    log_list = []
    mgr.hooks["update_pre_hook"] = [
        lambda host: (
            calls["pre"].append(dict(host)),
            log_snapshots.setdefault("pre_len", len(log_list)),
        )
    ]
    mgr.hooks["update_post_hook"] = [
        lambda host, result: (
            calls["post"].append((dict(host), dict(result))),
            log_snapshots.setdefault("post_logs", list(log_list)),
        )
    ]
    mgr.hooks["notification_hook"] = [
        lambda event, data: calls["notify"].append((event, dict(data)))
    ]

    ssh = _FakeLinuxSSH()
    monkeypatch.setattr(updater.ssh_helper, "create_client", lambda *a, **k: ssh)
    monkeypatch.setattr(email_config, "get_error_notifications_enabled", lambda: False)

    with app.app_context():
        res = updater.run_update("192.0.2.10", "ubuntu", "web-1", log_list)

        assert calls["pre"] == [
            {"name": "web-1", "host": "192.0.2.10", "user": "ubuntu"}
        ]
        assert log_snapshots["pre_len"] == 0
        assert any("Update completed successfully for web-1" in line for line in log_snapshots["post_logs"])
        assert len(calls["post"]) == 1
        post_host, post_result = calls["post"][0]
        assert post_host == calls["pre"][0]
        assert post_result == {
            "success": True,
            "packages_updated": 0,
            "name": "web-1",
            "host": "192.0.2.10",
            "error": "",
        }
        assert res == post_result

        # Version check firing new_version_available
        monkeypatch.setattr(version_manager, "VERSION_CHECK_FILE", str(tmp_path / "version_check.json"))
        monkeypatch.setattr(version_manager, "get_current_commit_sha", lambda: "aaaa111")
        monkeypatch.setattr(version_manager, "get_current_branch", lambda: "main")
        monkeypatch.delenv("FLEETPILOT_OFFLINE", raising=False)
        monkeypatch.setattr(
            version_manager.requests,
            "get",
            lambda url, timeout=10: SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "target_commitish": "bbbb222",
                    "tag_name": "v2.5.0",
                    "html_url": "https://github.com/ChristianHandy/fleetpilot/releases/tag/v2.5.0",
                    "name": "Release 2.5.0",
                },
            ),
        )

        version_manager.check_for_updates()
        assert any(ev == "new_version_available" and data.get("version") == "v2.5.0" for ev, data in calls["notify"])

        # notify.send and email_notifier also fire notification_hook
        monkeypatch.setenv("FLEETPILOT_DATA_DIR", str(tmp_path))
        notify.send("security", "FleetPilot: sign-in locked", "Too many attempts", "warning")
        assert ("security", {"title": "FleetPilot: sign-in locked", "message": "Too many attempts", "level": "warning"}) in calls["notify"]

        email_notifier.send_error_notification("web-1", "apt failed")
        assert ("update_error", {"host": "web-1", "error": "apt failed"}) in calls["notify"]


def test_slack_example_plugin_sends_webhook_on_update_and_new_version(tmp_path, monkeypatch, urlopen):
    import addon_loader
    import email_config
    import updater
    import version_manager
    from flask import Flask

    webhook_url = "https://example.invalid/slack-hook"
    monkeypatch.setenv("SLACK_WEBHOOK_URL", webhook_url)
    urlopen.side_effect = None
    urlopen.return_value = nullcontext(SimpleNamespace(status=200))

    app = Flask(__name__)
    mgr = addon_loader.AddonManager(app, None)
    mgr._load_one("example_slack_notify.py", "addons", str(tmp_path))

    monkeypatch.setattr(
        updater.ssh_helper,
        "create_client",
        lambda *a, **k: _FakeLinuxSSH("3 upgraded, 0 newly installed, 0 to remove and 0 not upgraded."),
    )
    monkeypatch.setattr(email_config, "get_error_notifications_enabled", lambda: False)

    with app.app_context():
        log_list = []
        updater.run_update("192.0.2.25", "ubuntu", "nas", log_list)

        assert urlopen.call_count == 1
        req1 = urlopen.call_args_list[0].args[0]
        body1 = json.loads(req1.data.decode("utf-8"))["text"]
        assert "`nas`" in body1
        assert "succeeded" in body1
        assert "Packages updated: *0*" in body1

        monkeypatch.setattr(version_manager, "VERSION_CHECK_FILE", str(tmp_path / "version_check.json"))
        monkeypatch.setattr(version_manager, "get_current_commit_sha", lambda: "1111111")
        monkeypatch.setattr(version_manager, "get_current_branch", lambda: "main")
        monkeypatch.delenv("FLEETPILOT_OFFLINE", raising=False)
        monkeypatch.setattr(
            version_manager.requests,
            "get",
            lambda url, timeout=10: SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "target_commitish": "2222222",
                    "tag_name": "v3.1.0",
                    "html_url": "https://github.com/ChristianHandy/fleetpilot/releases/tag/v3.1.0",
                    "name": "v3.1.0",
                },
            ),
        )

        version_manager.check_for_updates()

        assert urlopen.call_count == 2
        req2 = urlopen.call_args_list[1].args[0]
        body2 = json.loads(req2.data.decode("utf-8"))["text"]
        assert "*v3.1.0*" in body2


def test_raising_hooks_do_not_stop_update_and_are_logged(monkeypatch, caplog):
    import logging
    import addon_loader
    import email_config
    import updater
    from flask import Flask

    app = Flask(__name__)
    mgr = addon_loader.AddonManager(app, None)
    post_called = []

    def bad_pre(host):
        raise RuntimeError("pre-hook boom")

    def bad_post(host, result):
        raise ValueError("post-hook boom")

    def good_post(host, result):
        post_called.append(result)

    mgr.hooks["update_pre_hook"] = [bad_pre]
    mgr.hooks["update_post_hook"] = [bad_post, good_post]

    monkeypatch.setattr(updater.ssh_helper, "create_client", lambda *a, **k: _FakeLinuxSSH())
    monkeypatch.setattr(email_config, "get_error_notifications_enabled", lambda: False)

    log_list = []
    with app.app_context(), caplog.at_level(logging.ERROR, logger="addon_loader"):
        result = updater.run_update("192.0.2.99", "ubuntu", "db-1", log_list)

    assert result["success"] is True
    assert result["packages_updated"] == 0
    assert any("Update completed successfully for db-1" in line for line in log_list)
    assert post_called == [
        {"success": True, "packages_updated": 0, "name": "db-1", "host": "192.0.2.99", "error": ""}
    ]
    assert "pre-hook boom" in caplog.text
    assert "post-hook boom" in caplog.text


def test_failed_update_and_localhost_update_fire_pre_and_post_hooks(monkeypatch):
    import addon_loader
    import email_config
    import updater
    from flask import Flask

    app = Flask(__name__)
    mgr = addon_loader.AddonManager(app, None)
    events = []
    mgr.hooks["update_pre_hook"] = [lambda host: events.append(("pre", host["name"]))]
    mgr.hooks["update_post_hook"] = [
        lambda host, result: events.append(("post", host["name"], result["success"], result["packages_updated"]))
    ]

    monkeypatch.setattr(
        updater.ssh_helper,
        "create_client",
        lambda *a, **k: _FakeLinuxSSH("E: dpkg was interrupted", exit_status=100),
    )
    monkeypatch.setattr(email_config, "get_error_notifications_enabled", lambda: False)

    with app.app_context():
        res_fail = updater.run_update("192.0.2.55", "ubuntu", "broken-host", [], repo_only=True)
    assert res_fail["success"] is False
    assert res_fail["packages_updated"] == 0
    assert "exit code 100" in res_fail["error"]
    assert events == [
        ("pre", "broken-host"),
        ("post", "broken-host", False, 0),
    ]


def test_plugin_docs_documents_notification_and_update_payloads():
    from pathlib import Path

    docs_html = Path("templates/plugin_docs.html").read_text(encoding="utf-8")
    assert "new_version_available" in docs_html
    assert "packages_updated" in docs_html
    assert "update_pre" in docs_html
    assert "update_post" in docs_html
