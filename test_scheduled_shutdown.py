# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduled shutdown: passwords stay secret, input is validated, failures are logged."""
import sqlite3
import time
import uuid

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
