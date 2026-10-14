# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Controls required by strict environments (NIST SP 800-53/800-63B, BSI, DISA STIG, FIPS 140-3)."""
import pathlib
import glob
import re
import sqlite3
import time

import pytest

import account_security
import app as fp
import audit_log
import user_management

PASSWORD = 'strict-test-passphrase-7'


def _user(name, roles=('admin',)):
    user = user_management.get_user(name)
    if user:
        user_management.update_user(user['id'], active=1, password=PASSWORD)
        user_management.set_user_roles(user['id'], list(roles))
        return user['id']
    return user_management.create_user(name, PASSWORD, None, list(roles))


@pytest.fixture(autouse=True)
def _setup():
    fp.app.config['TESTING'] = True
    fp.app.config['WTF_CSRF_ENABLED'] = False
    user_management.init_user_db()
    account_security.init_db()
    account_security.save_settings(dict(account_security.DEFAULT_SETTINGS))
    yield
    account_security.save_settings(dict(account_security.DEFAULT_SETTINGS))
    fp.app.config['WTF_CSRF_ENABLED'] = True


def _sign_in(client, name, roles=('admin',), **form):
    uid = _user(name, roles)
    fp._clear_login_attempts('127.0.0.1', name)
    r = client.post('/', data=dict({'user': name, 'pass': PASSWORD}, **form))
    return uid, r


def test_password_policy_follows_nist_800_63b():
    bad = ['short', 'aaaaaaaaaaaaaa', 'abcabcabcabcabc', 'my-123456-secret', 'Password2026!!', 'FleetPilot2026!',
           'qwertz-garden-77']
    for pw in bad:
        assert fp._password_problem(pw), pw
    assert fp._password_problem('maria-likes-tea-99', 'maria')
    for pw in ('correct horse battery staple', 'Tr0ub4dor&3-xkcd-long', 'violet-harbour-lantern'):
        assert fp._password_problem(pw, 'someone') is None, pw


def test_fips_mode_rehashes_passwords_with_pbkdf2(monkeypatch):
    uid = _user('fips_user', ('viewer',))
    with user_management.get_user_db() as db:
        db.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                   (user_management._werkzeug_hash(PASSWORD, method='scrypt'), uid))
    monkeypatch.setattr(user_management, 'PASSWORD_METHOD', 'pbkdf2:sha256:600000')
    assert user_management.verify_password('fips_user', PASSWORD, upgrade_hash=True) == uid
    assert user_management.get_user_by_id(uid)['password_hash'].startswith('pbkdf2:sha256:600000$')
    assert user_management.verify_password('fips_user', PASSWORD) == uid


def test_sessions_have_an_absolute_lifetime():
    c = fp.app.test_client()
    uid, _ = _sign_in(c, 'abs_user', ('viewer',))
    assert c.get('/index').status_code == 200
    with user_management.get_user_db() as db:
        db.execute('UPDATE user_sessions SET created_at = ? WHERE user_id = ?', (time.time() - 13 * 3600, uid))
    assert c.get('/index').status_code == 302


def test_login_banner_must_be_accepted():
    account_security.save_settings({'login_banner': 'Authorised use only. Activity is monitored.'})
    c = fp.app.test_client()
    page = c.get('/').get_data(as_text=True)
    assert 'Authorised use only' in page and 'name="banner_ack"' in page
    _, r = _sign_in(c, 'banner_user', ('viewer',))
    assert r.status_code == 400
    _, r = _sign_in(c, 'banner_user', ('viewer',), banner_ack='1')
    assert r.status_code == 302


def test_lockout_threshold_is_configurable():
    account_security.save_settings({'lockout_attempts': 3, 'lockout_minutes': 15})
    _user('lock3_user', ('viewer',))
    fp._clear_login_attempts('203.0.113.9', 'lock3_user')
    c = fp.app.test_client()
    for _ in range(3):
        c.post('/', data={'user': 'lock3_user', 'pass': 'wrong-password-x'}, environ_base={'REMOTE_ADDR': '203.0.113.9'})
    r = c.post('/', data={'user': 'lock3_user', 'pass': PASSWORD}, environ_base={'REMOTE_ADDR': '203.0.113.9'})
    assert r.status_code == 429
    fp._clear_login_attempts('203.0.113.9', 'lock3_user')


def test_audit_chain_detects_changes():
    for n in range(3):
        audit_log.record_event(actor_id=None, actor='chain-test', event_type='chain_probe', target=str(n))
    assert audit_log.verify_chain()['ok']
    con = sqlite3.connect(audit_log.DB_PATH)
    try:
        row_id = con.execute("SELECT id FROM audit_events WHERE event_type='chain_probe' ORDER BY id DESC LIMIT 1 OFFSET 1").fetchone()[0]
        con.execute("UPDATE audit_events SET target='tampered' WHERE id=?", (row_id,))
        con.commit()
        result = audit_log.verify_chain()
        assert not result['ok'] and result['first_bad_id'] == row_id
    finally:
        con.execute("UPDATE audit_events SET target=? WHERE id=?",
                    (str(1), row_id))
        con.commit()
        con.close()
    assert audit_log.verify_chain()['ok']


def test_changing_two_factor_requires_the_password_again():
    c = fp.app.test_client()
    _sign_in(c, 'mfa_user', ('viewer',))
    with c.session_transaction() as s:
        s['auth_time'] = 0
    for url in ('/2fa/totp/disable', '/2fa/backup/regenerate', '/2fa/webauthn/1/delete', '/2fa/yubikey/1/delete'):
        r = c.post(url)
        assert r.status_code == 302 and '/reauth' in r.headers['Location'], url


def test_no_version_disclosure_and_no_third_party_requests():
    r = fp.app.test_client().get('/healthz')
    assert r.get_json() == {'status': 'ok'}
    csp = r.headers['Content-Security-Policy']
    assert 'https:' not in csp.replace("img-src 'self' data:", '') and "default-src 'self'" in csp
    external = re.compile(r'(src|href)=["\']https?://(?!github\.com)[^"\']+\.(js|css|woff2?)')
    offenders = [p for p in glob.glob('templates/**/*.html', recursive=True) if external.search(pathlib.Path(p).read_text())]
    assert not offenders, offenders
    assert not any('fonts.googleapis' in pathlib.Path(p).read_text() for p in glob.glob('templates/**/*.html', recursive=True))


def test_session_cookies_are_signed_with_sha256():
    import hashlib
    assert fp.app.session_interface.digest_method() .name == hashlib.sha256().name


def test_offline_mode_blocks_internet_lookups(monkeypatch):
    monkeypatch.setenv('FLEETPILOT_OFFLINE', 'true')
    monkeypatch.setattr(fp.requests, 'get', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network used')))
    c = fp.app.test_client()
    _sign_in(c, 'offline_admin')
    assert c.get('/plugins/repository.json').get_json() == {'plugins': [], 'offline': True}
    import version_manager
    monkeypatch.setattr(version_manager.requests, 'get', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network used')))
    version_manager.check_for_updates()


def test_strict_ssh_mode_rejects_unknown_hosts(monkeypatch):
    import paramiko
    import ssh_helper
    monkeypatch.setenv('FLEETPILOT_SSH_STRICT_HOST_KEYS', 'true')
    captured = {}
    monkeypatch.setattr(paramiko.SSHClient, 'connect', lambda self, **kw: captured.setdefault('policy', self._policy))
    ssh_helper.create_client('192.0.2.1', username='root', password='x')
    assert isinstance(captured['policy'], paramiko.RejectPolicy)
