# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduled shutdown: passwords stay secret, input is validated, failures are logged."""
import sqlite3
import time
import uuid
from datetime import datetime

import pytest

import account_security
import app as fp
import scheduled_shutdown as ss
import user_management


def _client(role):
    name = f'sched_{role}'
    user_management.init_user_db()
    user = user_management.get_user(name)
    uid = user['id'] if user else user_management.create_user(name, 'sched-test-pass', None, [role])
    client = fp.app.test_client()
    with client.session_transaction() as s:
        s.update(user_id=uid, username=name, auth_time=time.time(),
                 pw_tag=fp._password_tag(user_management.get_user_by_id(uid)),
                 sid=account_security.create_session(uid, '127.0.0.1', 'pytest'))
    return client


@pytest.fixture
def csrf_off():
    before = fp.app.config.get('WTF_CSRF_ENABLED', True)
    fp.app.config['WTF_CSRF_ENABLED'] = False
    yield
    fp.app.config['WTF_CSRF_ENABLED'] = before


def _add(password='Pw-' + uuid.uuid4().hex):
    name = 'sched-' + uuid.uuid4().hex[:8]
    sid = ss.add_schedule(name, '192.0.2.70', 22, 'root', password, '', '23:00', ['Mon', 'Fri'], True, 5, 'shutdown')
    return sid, name, password


def _stored_password(sid):
    con = sqlite3.connect(str(ss._DB_FILE))
    try:
        return con.execute('SELECT password FROM schedules WHERE id=?', (sid,)).fetchone()[0]
    finally:
        con.close()


def test_password_is_encrypted_and_never_returned():
    sid, name, password = _add()
    assert _stored_password(sid).startswith('gAAAAA') and password not in _stored_password(sid)
    assert 'password' not in ss.get_schedule(sid) and ss.get_schedule(sid)['has_password'] is True
    for role in ('viewer', 'admin'):
        client = _client(role)
        for url in ('/api/shutdown_schedule', '/shutdown_schedule'):
            body = client.get(url).get_data(as_text=True)
            assert name in body and password not in body, (role, url)


def test_plain_text_passwords_from_older_versions_are_encrypted_on_start():
    sid, _, _ = _add()
    con = sqlite3.connect(str(ss._DB_FILE))
    con.execute("UPDATE schedules SET password='old-plain-pw' WHERE id=?", (sid,))
    con.commit()
    con.close()
    ss.init_db(str(ss._DB_FILE.parent))
    assert _stored_password(sid).startswith('gAAAAA') and ss._password(sid) == 'old-plain-pw'


def test_action_uses_the_decrypted_password_and_reports_unreachable_hosts(monkeypatch):
    sid, _, password = _add()
    seen = {}

    class Channel:
        def read(self):
            return b''

    class Client:
        def exec_command(self, cmd, timeout):
            seen['cmd'] = cmd
            return None, Channel(), Channel()

        def close(self):
            seen['closed'] = True

    monkeypatch.setattr(ss.ssh_helper, 'create_client', lambda **kw: seen.update(kw) or Client())
    ok, _ = ss._execute_action(ss.get_schedule(sid))
    assert ok and seen['password'] == password and seen['cmd'] == 'shutdown -h now' and seen['closed']

    def unreachable(**kw):
        raise OSError('no route to host')
    monkeypatch.setattr(ss.ssh_helper, 'create_client', unreachable)
    ok, message = ss._execute_action(ss.get_schedule(sid))      # used to raise UnboundLocalError
    assert not ok and message
    assert ss._execute_action(dict(ss.get_schedule(sid), action='format-disk')) == (False, "Unknown action 'format-disk'")


def test_edit_keeps_the_password_unless_a_new_one_is_given(csrf_off):
    sid, name, password = _add()
    client = _client('operator')
    form = {'name': name, 'host': '192.0.2.71', 'port': '22', 'shutdown_time': '22:30', 'days': ['Sat'],
            'action': 'reboot', 'warn_minutes': '3', 'password': ''}
    assert client.post(f'/shutdown_schedule/{sid}/edit', data=form).status_code == 302
    assert ss._password(sid) == password and ss.get_schedule(sid)['host'] == '192.0.2.71'
    client.post(f'/shutdown_schedule/{sid}/edit', data=dict(form, password='new-pw'))
    assert ss._password(sid) == 'new-pw'
    assert client.post('/shutdown_schedule/999999/edit', data=form).status_code == 404


@pytest.mark.parametrize('change', [
    {'name': ''}, {'host': 'a;reboot'}, {'port': 'x'}, {'port': '70000'}, {'shutdown_time': '25:00'},
    {'days': []}, {'days': ['Someday']}, {'action': 'format-disk'}, {'warn_minutes': '-1'},
])
def test_invalid_schedules_are_refused(csrf_off, change):
    client = _client('operator')
    name = 'bad-' + uuid.uuid4().hex[:8]
    form = dict({'name': name, 'host': '192.0.2.72', 'port': '22', 'shutdown_time': '23:00', 'days': ['Mon'],
                 'action': 'shutdown', 'warn_minutes': '5'}, **change)
    page = client.post('/shutdown_schedule/add', data=form, follow_redirects=True)
    assert page.status_code == 200
    assert not any(s['name'] == name for s in ss.list_schedules())


def test_viewers_cannot_change_schedules(csrf_off):
    sid, _, _ = _add()
    client = _client('viewer')
    assert client.post(f'/shutdown_schedule/{sid}/run_now').status_code in (302, 403)
    assert client.post(f'/shutdown_schedule/{sid}/delete').status_code in (302, 403)
    assert ss.get_schedule(sid) is not None


def _use_tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(ss, '_DB_FILE', tmp_path / 'scheduled_shutdown.db')
    ss.init_db(str(tmp_path))


def test_run_due_fires_only_on_matching_weekday_and_time(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    sid = ss.add_schedule('mon-fri', '192.0.2.80', 22, 'root', 'pw', '', '23:00', ['Mon', 'Fri'], True, 5, 'shutdown')
    calls = []
    monkeypatch.setattr(ss, '_execute_action', lambda s: calls.append(s['id']) or (True, 'ok'))

    # Wrong time on listed weekday (Monday 2026-01-05 22:59)
    ss._run_due(datetime(2026, 1, 5, 22, 59))
    assert calls == []

    # Listed time on unlisted weekday (Tuesday 2026-01-06 23:00)
    ss._run_due(datetime(2026, 1, 6, 23, 0))
    assert calls == []

    # Listed time on listed weekday (Monday 2026-01-05 23:00)
    ss._run_due(datetime(2026, 1, 5, 23, 0))
    assert calls == [sid]
    logs = ss.get_log(sid)
    assert len(logs) == 1 and logs[0]['status'] == 'success'


def test_disabled_schedules_do_not_fire(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    ss.add_schedule('disabled-job', '192.0.2.81', 22, 'root', 'pw', '', '23:00', ['Mon'], False, 5, 'shutdown')
    calls = []
    monkeypatch.setattr(ss, '_execute_action', lambda s: calls.append(s['id']) or (True, 'ok'))

    ss._run_due(datetime(2026, 1, 5, 23, 0))
    assert calls == []


def test_schedule_fires_only_once_within_the_same_minute(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    sid = ss.add_schedule('once-per-min', '192.0.2.82', 22, 'root', 'pw', '', '23:00', ['Mon'], True, 5, 'shutdown')
    calls = []
    monkeypatch.setattr(ss, '_execute_action', lambda s: calls.append(s['id']) or (True, 'ok'))

    ss._run_due(datetime(2026, 1, 5, 23, 0, 5))
    ss._run_due(datetime(2026, 1, 5, 23, 0, 35))
    assert calls == [sid]

    # Next week at the same time fires again
    ss._run_due(datetime(2026, 1, 12, 23, 0, 5))
    assert calls == [sid, sid]


def test_broken_days_json_falls_back_to_every_day(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    sid = ss.add_schedule('bad-json', '192.0.2.83', 22, 'root', 'pw', '', '08:15', '{not-valid-json', True, 5, 'reboot')
    calls = []
    monkeypatch.setattr(ss, '_execute_action', lambda s: calls.append(s['id']) or (True, 'ok'))

    # Wednesday 2026-01-07 08:15
    ss._run_due(datetime(2026, 1, 7, 8, 15))
    assert calls == [sid]


def test_failing_action_is_logged_with_error_status(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    sid = ss.add_schedule('fail-host', '192.0.2.84', 22, 'root', 'pw', '', '03:30', ['Sun'], True, 5, 'shutdown')
    monkeypatch.setattr(ss, '_execute_action', lambda s: (False, 'SSH timeout'))

    # Sunday 2026-01-11 03:30
    ss._run_due(datetime(2026, 1, 11, 3, 30))
    logs = ss.get_log(sid)
    assert len(logs) == 1
    assert logs[0]['status'] == 'error'
    assert logs[0]['message'] == 'SSH timeout'
    assert ss.get_schedule(sid)['last_status'] == 'error'


@pytest.mark.parametrize(('action', 'expected_cmd'), [
    ('shutdown', 'shutdown -h now'),
    ('reboot', 'shutdown -r now'),
    ('suspend', 'systemctl suspend'),
    ('hibernate', 'systemctl hibernate'),
])
def test_execute_action_sends_expected_command_for_each_action(monkeypatch, tmp_path, action, expected_cmd):
    _use_tmp_db(monkeypatch, tmp_path)
    sid = ss.add_schedule(f'act-{action}', '192.0.2.85', 22, 'root', 'pw', '', '23:00', ['Mon'], True, 5, action)
    seen = {}

    class Channel:
        def read(self):
            return b'done'

    class Client:
        def exec_command(self, cmd, timeout):
            seen['cmd'] = cmd
            return None, Channel(), Channel()

        def close(self):
            seen['closed'] = True

    monkeypatch.setattr(ss.ssh_helper, 'create_client', lambda **kw: Client())
    ok, msg = ss._execute_action(ss.get_schedule(sid))
    assert ok is True
    assert seen['cmd'] == expected_cmd
    assert seen['closed'] is True
    assert expected_cmd in msg

