# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The update_pre / update_post / notification plugin hooks are actually fired.

addon_loader registers all three and the plugin docs describe them, but
AddonManager.fire_hooks() had no caller, so a plugin built on them (the
bundled Slack example included) silently did nothing at all.
"""
import io
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import flask
import pytest

import addon_loader
import email_config
import email_notifier
import linux_distro
import notify
import ssh_helper
import updater
import version_manager
from addons import example_slack_notify as slack_notify


class _Channel:
    """The bits of a paramiko channel that the update code uses."""

    def __init__(self, payload, status=0):
        self._payload = payload
        self._status = status

    def makefile(self, mode):
        return io.BytesIO(self._payload)

    def recv_exit_status(self):
        return self._status


class _Stream:
    def __init__(self, payload, status=0):
        self._payload = payload
        self.channel = _Channel(payload, status)

    def read(self):
        return self._payload


class LinuxHost:
    """Answers the update commands like a Debian host."""

    def __init__(self, os_release="ID=debian\nVERSION_ID=12\n", exit_status=0, output=""):
        self.os_release = os_release
        self.exit_status = exit_status
        self.output = output
        self.commands = []
        self.closed = False

    def exec_command(self, command, timeout=None, get_pty=False):
        self.commands.append(command)
        if command == linux_distro.OS_RELEASE_COMMAND:
            return None, _Stream(self.os_release.encode()), _Stream(b"")
        return None, _Stream(self.output.encode(), self.exit_status), _Stream(b"")

    def close(self):
        self.closed = True


class _Release:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def hook_app():
    """A Flask app with an addon manager, entered into its app context."""
    app = flask.Flask("fleetpilot-hook-test")
    app.addon_mgr = addon_loader.AddonManager(app, None)
    with app.app_context():
        yield app


def record_hooks(app):
    """Record every hook call as (hook name, arguments)."""
    calls = []
    for name in ("update_pre_hook", "update_post_hook", "notification_hook"):
        app.addon_mgr.hooks[name].append(
            (lambda hook: lambda *args: calls.append((hook, args)))(name))
    return calls


def install_host(monkeypatch, **kwargs):
    monkeypatch.setattr(ssh_helper, "create_client", lambda *a, **k: LinuxHost(**kwargs))


def test_update_pre_and_post_receive_the_documented_arguments(monkeypatch, hook_app):
    calls = record_hooks(hook_app)
    install_host(monkeypatch)

    result = updater.run_update('192.0.2.10', 'ops', 'nas', [])

    assert [name for name, _ in calls] == ['update_pre_hook', 'update_post_hook']
    assert calls[0][1][0] == {'name': 'nas', 'host': '192.0.2.10', 'user': 'ops'}
    # The post hook gets the same dict the caller gets back.
    assert calls[1][1][1] == result
    assert result['success'] is True
    assert result['error'] == ''
    assert result == {'success': True, 'packages_updated': 0, 'name': 'nas',
                      'host': '192.0.2.10', 'error': ''}


def test_a_failed_update_is_reported_as_a_failure(monkeypatch, hook_app):
    calls = record_hooks(hook_app)
    install_host(monkeypatch, exit_status=1)

    result = updater.run_update('192.0.2.10', 'ops', 'nas', [])

    assert result['success'] is False
    assert 'exit code 1' in result['error']
    assert calls[1][1][1]['success'] is False


def test_a_hook_that_raises_does_not_break_the_update(monkeypatch, hook_app):
    """
    Regression test: a notification must never stop the update it reports on

    Hooks are registered by third parties, so one that raises cannot be
    allowed to fail the update (or to keep the post hook from running).
    """
    calls = record_hooks(hook_app)

    def boom(*args):
        raise RuntimeError('plugin is broken')

    hook_app.addon_mgr.hooks['update_pre_hook'].append(boom)
    hook_app.addon_mgr.hooks['update_post_hook'].insert(0, boom)
    install_host(monkeypatch)

    result = updater.run_update('192.0.2.10', 'ops', 'nas', [])

    assert result['success'] is True
    # The raising hook did not stop the other one from being called.
    assert [name for name, _ in calls] == ['update_pre_hook', 'update_post_hook']


def test_new_version_available_is_announced_once_per_version(monkeypatch, hook_app, tmp_path):
    """
    Regression test: the notification hook fires when a new version appears

    The 24-hour check would otherwise make every plugin that forwards to
    Slack or mail repeat the same "new version" message every single day.
    """
    calls = record_hooks(hook_app)
    monkeypatch.setattr(version_manager, 'VERSION_CHECK_FILE',
                        str(tmp_path / 'version_check.json'))
    monkeypatch.setattr(version_manager, 'get_current_commit_sha', lambda: 'aaa')
    monkeypatch.setattr(version_manager, 'get_current_branch', lambda: 'main')
    monkeypatch.setattr(version_manager.requests, 'get', lambda *a, **k: _Release({
        'target_commitish': 'bbb', 'tag_name': 'v1.9.0',
        'html_url': 'https://example.invalid/release', 'name': 'FleetPilot 1.9.0'}))

    version_manager.check_for_updates()
    version_manager.check_for_updates()

    notifications = [args for name, args in calls if name == 'notification_hook']
    assert len(notifications) == 1
    event, data = notifications[0]
    assert event == 'new_version_available'
    assert data['version'] == 'v1.9.0'
    assert data['url'] == 'https://example.invalid/release'
    assert data['type'] == 'release'


def test_slack_example_sends_a_message_after_an_update(monkeypatch, hook_app):
    """
    Regression test: the bundled Slack plugin reaches Slack during an update

    Its hooks were registered and its functions were already tested, but
    nothing ever fired them, so SLACK_WEBHOOK_URL alone sent nothing.
    """
    urlopen = Mock(return_value=nullcontext(SimpleNamespace(status=200)))
    monkeypatch.setattr(slack_notify.urllib.request, 'urlopen', urlopen)
    monkeypatch.setenv('SLACK_WEBHOOK_URL', 'https://example.invalid/slack')
    hook_app.addon_mgr.hooks['update_post_hook'].append(slack_notify._on_update_post)
    install_host(monkeypatch)

    updater.run_update('192.0.2.10', 'ops', 'nas', [])

    message = json.loads(urlopen.call_args.args[0].data.decode('utf-8'))['text']
    assert '`nas`' in message
    assert 'succeeded' in message


def test_updater_without_an_app_context_fires_nothing(monkeypatch):
    """Modules imported outside Flask (scheduler, CLI, unit tests) stay silent."""
    install_host(monkeypatch)

    assert updater.run_update('192.0.2.10', 'ops', 'nas', [])['success'] is True


def test_email_notifier_and_notify_fire_notification_hook(monkeypatch, hook_app, tmp_path):
    """email_notifier (update_report, update_error) and notify.send reach notification_hook."""
    calls = record_hooks(hook_app)
    monkeypatch.setattr(email_config, 'get_report_enabled', lambda: False)
    monkeypatch.setattr(email_config, 'get_error_notifications_enabled', lambda: False)
    monkeypatch.setenv('FLEETPILOT_DATA_DIR', str(tmp_path))

    email_notifier.send_update_report({'nas': {'status': 'ok'}}, [{'host': 'nas'}])
    email_notifier.send_error_notification('nas', 'apt failed')
    notify.send('security', 'FleetPilot: sign-in locked', 'Too many attempts', 'warning')

    notifications = [args for name, args in calls if name == 'notification_hook']
    assert notifications == [
        ('update_report', {'hosts_status': {'nas': {'status': 'ok'}}, 'history': [{'host': 'nas'}]}),
        ('update_error', {'host': 'nas', 'error': 'apt failed'}),
        ('security', {'title': 'FleetPilot: sign-in locked', 'message': 'Too many attempts', 'level': 'warning'}),
    ]

