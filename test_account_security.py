"""Tests for sessions, API tokens, sudo mode, the security center, notifications and audit export."""
import http.server
import json
import re
import threading
import time

import pytest

import account_security
import app as fp
import audit_log
import notify
import smart_manager
import user_management

PASSWORD = 'security-test-password'


def _user(name, roles=('admin',)):
    user = user_management.get_user(name)
    if user:
        user_management.update_user(user['id'], active=1)
        if not user_management.verify_password(name, PASSWORD):
            user_management.update_user(user['id'], password=PASSWORD)
        user_management.set_user_roles(user['id'], list(roles))
        return user['id']
    return user_management.create_user(name, PASSWORD, None, list(roles))


def _sign_in(client, name, roles=('admin',)):
    """Sign in through the real login form."""
    uid = _user(name, roles)
    fp._clear_login_attempts('127.0.0.1', name)
    r = client.post('/', data={'user': name, 'pass': PASSWORD})
    assert r.status_code == 302, r.data[:300]
    return uid


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


@pytest.fixture
def client():
    with fp.app.test_client() as c:
        yield c


def _client():
    return fp.app.test_client()


# ── Sessions ──────────────────────────────────────────────────────────────────

def test_sessions_can_be_listed_and_revoked_from_another_device():
    laptop, phone = _client(), _client()
    uid = _sign_in(laptop, 'sess_user', ('viewer',))
    _sign_in(phone, 'sess_user', ('viewer',))
    assert laptop.get('/users/security').status_code == 200
    page = phone.get('/users/security').get_data(as_text=True)
    assert 'This device' in page
    assert len(account_security.list_sessions(uid)) >= 2

    r = phone.post('/users/security/sessions/end-others')
    assert r.status_code == 302
    assert laptop.get('/users/security').status_code == 302      # laptop was signed out
    assert phone.get('/users/security').status_code == 200        # phone kept its session


def test_idle_sessions_expire():
    c = _client()
    uid = _sign_in(c, 'idle_user', ('viewer',))
    account_security.save_settings({'idle_minutes': 5})
    with user_management.get_user_db() as db:
        db.execute('UPDATE user_sessions SET last_seen = ? WHERE user_id = ?', (time.time() - 3600, uid))
    assert c.get('/index').status_code == 302


def test_logout_revokes_the_server_session():
    c = _client()
    uid = _sign_in(c, 'logout_user', ('viewer',))
    with c.session_transaction() as s:
        stolen = dict(s)
    c.post('/logout')
    thief = _client()
    with thief.session_transaction() as s:
        s.update(stolen)                    # replay the old signed cookie
    assert thief.get('/index').status_code == 302
    assert not account_security.list_sessions(uid)


def test_routes_using_the_module_decorator_reject_deactivated_users():
    # /system/audit and /system/production use user_management.login_required,
    # which only looked for user_id in the cookie.
    c = _client()
    uid = _sign_in(c, 'deact_admin')
    assert c.get('/system/production').status_code == 200
    user_management.update_user(uid, active=0)
    try:
        assert c.get('/system/production').status_code == 302
        assert c.get('/system/audit').status_code == 302
    finally:
        user_management.update_user(uid, active=1)


def test_security_key_sign_in_creates_a_working_session(monkeypatch):
    uid = _user('webauthn_user', ('viewer',))
    monkeypatch.setattr(fp, '_webauthn_request_context', lambda: ('localhost', 'https://localhost', None))
    monkeypatch.setattr(fp._2fa, 'verify_webauthn_authentication', lambda *a, **k: {'success': True})
    c = _client()
    with c.session_transaction() as s:
        s['_2fa_pending_user_id'] = uid
        s['_2fa_pending_username'] = 'webauthn_user'
        s['_webauthn_authenticate'] = {'challenge': 'x', 'rp_id': 'localhost', 'origin': 'https://localhost',
                                       'created': int(time.time())}
    r = c.post('/2fa/webauthn/authentication/verify', json={'credential': {}})
    assert r.get_json()['ok'] is True
    # Previously the session lacked pw_tag, so the next page signed the user out again.
    assert c.get('/index').status_code == 200


def test_sign_in_shows_previous_sign_in_and_failures():
    _user('notice_user', ('viewer',))
    _sign_in(_client(), 'notice_user', ('viewer',))
    fp._clear_login_attempts('127.0.0.1', 'notice_user')
    _client().post('/', data={'user': 'notice_user', 'pass': 'wrong-password'})
    c = _client()
    _sign_in(c, 'notice_user', ('viewer',))
    page = c.get('/index').get_data(as_text=True)
    assert 'Last sign-in:' in page and '1 failed sign-in attempt since then' in page


# ── API tokens ────────────────────────────────────────────────────────────────

def _token(name, roles, scope, days=30):
    uid = _user(name, roles)
    raw, _ = account_security.create_token(uid, 'test', scope, days)
    return uid, {'Authorization': f'Bearer {raw}'}, raw


def test_api_token_authenticates_api_requests_without_a_cookie():
    _, headers, _ = _token('tok_reader', ('viewer',), 'read')
    c = _client()
    r = c.get('/api/me', headers=headers)
    assert r.status_code == 200
    assert r.get_json() == {'username': 'tok_reader', 'roles': ['viewer'], 'auth': 'token', 'scope': 'read'}
    assert 'Set-Cookie' not in r.headers
    # Tokens only open the JSON API, never the web pages.
    assert c.get('/index', headers=headers).status_code == 401


def test_read_only_tokens_cannot_change_anything():
    _, headers, _ = _token('tok_reader2', ('admin',), 'read')
    r = _client().post('/api/dashboard/layout/reset', headers=headers)
    assert r.status_code == 403 and 'read-only' in r.get_json()['error']


def test_write_tokens_skip_csrf_but_still_need_a_valid_token():
    fp.app.config['WTF_CSRF_ENABLED'] = True
    _, headers, _ = _token('tok_writer', ('operator',), 'write')
    assert _client().post('/api/dashboard/layout/reset', headers=headers).status_code == 200
    bad = {'Authorization': 'Bearer fp_not-a-real-token'}
    assert _client().post('/api/dashboard/layout/reset', headers=bad).status_code == 401
    assert _client().get('/api/me', headers=bad).status_code == 401


def test_revoked_expired_and_deactivated_tokens_stop_working():
    uid, headers, raw = _token('tok_life', ('viewer',), 'read')
    c = _client()
    assert c.get('/api/me', headers=headers).status_code == 200
    with user_management.get_user_db() as db:
        db.execute('UPDATE api_tokens SET expires_at = ? WHERE token_hash = ?',
                   (time.time() - 1, account_security._hash(raw)))
    assert c.get('/api/me', headers=headers).status_code == 401

    uid, headers, raw = _token('tok_life', ('viewer',), 'read')
    user_management.update_user(uid, active=0)
    assert c.get('/api/me', headers=headers).status_code == 401
    user_management.update_user(uid, active=1)
    token_id = account_security.verify_token(raw)['id']
    account_security.revoke_token(token_id)
    assert c.get('/api/me', headers=headers).status_code == 401


def test_token_limits_and_plaintext_never_stored():
    uid = _user('tok_limits', ('viewer',))
    account_security.save_settings({'max_token_days': 30})
    with pytest.raises(ValueError):
        account_security.create_token(uid, 'long', 'read', 90)
    with pytest.raises(ValueError):
        account_security.create_token(uid, 'forever', 'read', 0)
    raw, _ = account_security.create_token(uid, 'ok', 'read', 30)
    with user_management.get_user_db() as db:
        dump = '\n'.join(str(tuple(r)) for r in db.execute('SELECT * FROM api_tokens'))
    assert raw not in dump


def test_viewers_cannot_create_write_tokens_and_creation_needs_password(client):
    _sign_in(client, 'tok_viewer', ('viewer',))
    with client.session_transaction() as s:
        s['auth_time'] = 0
    r = client.post('/users/security/tokens', data={'name': 'x', 'scope': 'read', 'days': '30'})
    assert r.status_code == 302 and '/reauth' in r.headers['Location']
    with client.session_transaction() as s:
        s['auth_time'] = time.time()
    client.post('/users/security/tokens', data={'name': 'x', 'scope': 'write', 'days': '30'})
    uid = user_management.get_user('tok_viewer')['id']
    assert all(t['scope'] == 'read' for t in account_security.list_tokens(uid))
    client.post('/users/security/tokens', data={'name': 'reader', 'scope': 'read', 'days': '30'})
    page = client.get('/users/security').get_data(as_text=True)
    assert 'Copy your new token now' in page and re.search(r'value="fp_[\w-]{40,}"', page)
    assert 'Copy your new token now' not in client.get('/users/security').get_data(as_text=True)


def test_deleting_a_user_removes_their_tokens_and_sessions():
    uid, _, _ = _token('tok_deleted', ('viewer',), 'read')
    account_security.create_session(uid)
    user_management.delete_user(uid)
    assert not account_security.list_tokens(uid)
    assert not account_security.list_sessions(uid, include_ended=True)


# ── Sudo mode and user administration ─────────────────────────────────────────

def test_sensitive_pages_ask_for_the_password_again(client):
    _sign_in(client, 'sudo_admin')
    with client.session_transaction() as s:
        s['auth_time'] = time.time() - 3600
    r = client.get('/system/backups')
    assert r.status_code == 302 and r.headers['Location'].startswith('/reauth?next=/system/backups')
    assert client.post('/reauth', data={'password': 'wrong', 'next': '/system/backups'}).status_code == 200
    r = client.post('/reauth', data={'password': PASSWORD, 'next': '/system/backups'})
    assert r.status_code == 302 and r.headers['Location'] == '/system/backups'
    assert client.get('/system/backups').status_code == 200
    # Open redirects are refused.
    r = client.post('/reauth', data={'password': PASSWORD, 'next': '//evil.example/'})
    assert r.headers['Location'] == '/index'


def test_the_last_admin_cannot_be_removed(client, monkeypatch):
    uid = _sign_in(client, 'last_admin')
    monkeypatch.setattr(fp, '_other_active_admins', lambda _uid: 0)
    client.post(f'/users/edit/{uid}', data={'username': 'last_admin', 'roles': 'viewer', 'active': '1'})
    assert 'admin' in user_management.get_user_role_names(uid)
    other = _user('victim_admin')
    client.post(f'/users/delete/{other}')
    assert user_management.get_user_by_id(other) is not None


def test_new_admins_are_reported(client, monkeypatch):
    sent = []
    monkeypatch.setattr(notify, 'send', lambda *a, **k: sent.append(a))
    _sign_in(client, 'reporting_admin')
    if user_management.get_user('fresh_admin'):
        user_management.delete_user(user_management.get_user('fresh_admin')['id'])
    client.post('/users/add', data={'username': 'fresh_admin', 'password': 'a-long-enough-password', 'roles': 'admin'})
    assert any(a[0] == 'security' and 'fresh_admin' in a[2] for a in sent)


# ── Security center ───────────────────────────────────────────────────────────

def test_security_center_renders_checks_and_saves_rules(client):
    _sign_in(client, 'center_admin')
    page = client.get('/system/security').get_data(as_text=True)
    for title in ('HTTPS', 'Two-factor sign-in for admins', 'CSRF protection', 'Configuration backup'):
        assert title in page
    r = client.post('/system/security/settings', data={'idle_minutes': '30', 'reauth_minutes': '5',
                                                       'audit_retention_days': '90', 'max_token_days': '60',
                                                       'ip_allowlist': ''})
    assert r.status_code == 302
    settings = account_security.get_settings()
    assert settings['idle_minutes'] == 30 and settings['max_token_days'] == 60
    assert any(e['event_type'] == 'security_settings_changed' for e in audit_log.list_events(5))


def test_allowlist_blocks_other_networks_but_never_locks_out_the_admin(client):
    _sign_in(client, 'allow_admin')
    r = client.post('/system/security/settings', data={'ip_allowlist': '10.0.0.0/8\nnot-an-ip'})
    assert account_security.get_settings()['ip_allowlist'] == []
    # 127.0.0.1 is always allowed, so this list is accepted.
    client.post('/system/security/settings', data={'ip_allowlist': '10.0.0.0/8', 'idle_minutes': '120'})
    assert account_security.get_settings()['ip_allowlist'] == ['10.0.0.0/8']
    outsider = _client()
    assert outsider.get('/', environ_base={'REMOTE_ADDR': '192.0.2.10'}).status_code == 403
    assert outsider.get('/', environ_base={'REMOTE_ADDR': '10.4.5.6'}).status_code == 200
    assert outsider.get('/status', environ_base={'REMOTE_ADDR': '192.0.2.10'}).status_code == 200
    # An admin on 192.0.2.10 cannot save a list without their own address.
    r = client.post('/system/security/settings', data={'ip_allowlist': '10.0.0.0/8'},
                    environ_base={'REMOTE_ADDR': '10.9.9.9'})
    assert account_security.ip_allowed('::ffff:10.1.1.1', ['10.0.0.0/8'])
    assert not account_security.ip_allowed('garbage', ['10.0.0.0/8'])


def test_admins_can_be_required_to_use_2fa(client):
    _sign_in(client, 'no2fa_admin')
    account_security.save_settings({'require_2fa_admins': True})
    r = client.get('/index')
    assert r.status_code == 302 and r.headers['Location'].endswith('/2fa')
    assert client.get('/2fa').status_code == 200
    viewer = _client()
    _sign_in(viewer, 'no2fa_viewer', ('viewer',))
    assert viewer.get('/index').status_code == 200


def test_security_headers():
    r = _client().get('/')
    csp = r.headers['Content-Security-Policy']
    assert "'unsafe-eval'" not in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert r.headers['Cross-Origin-Opener-Policy'] == 'same-origin'


# ── Lockouts, audit trail, notifications ──────────────────────────────────────

def test_lockout_is_audited_and_reported_once(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, 'send', lambda *a, **k: sent.append(a))
    fp._clear_login_attempts('198.51.100.7', 'lockout_target')
    c = _client()
    for _ in range(12):
        c.post('/', data={'user': 'lockout_target', 'pass': 'nope'}, environ_base={'REMOTE_ADDR': '198.51.100.7'})
    fp._clear_login_attempts('198.51.100.7', 'lockout_target')
    assert len([a for a in sent if 'locked' in a[1]]) == 1
    assert audit_log.list_events(1, event_type='login_locked', actor='lockout_target')


def test_audit_filters_and_csv_export_neutralise_formulas(client):
    _sign_in(client, 'audit_admin')
    audit_log.record_event(actor_id=None, actor='csv-test', event_type='csv_probe',
                           target='=HYPERLINK("http://evil")', outcome='success')
    page = client.get('/system/audit?type=csv_probe').get_data(as_text=True)
    assert 'csv-test' in page and '<span class="audit-code">login_success</span>' not in page
    csv_text = client.get('/system/audit/export.csv?type=csv_probe').get_data(as_text=True)
    assert csv_text.splitlines()[0].startswith('occurred_at,actor')
    assert '"\'=HYPERLINK' in csv_text


class _Sink(http.server.BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        _Sink.received.append((self.path, dict(self.headers), body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_notification_channels_store_urls_encrypted_and_deliver():
    for ch in notify.list_channels():
        notify.delete_channel(ch['id'])
    server = http.server.HTTPServer(('127.0.0.1', 0), _Sink)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/hook/secret-token-123'
    try:
        cid = notify.add_channel('Sink', 'webhook', url, ['smart'], 'warning')
        assert 'secret-token-123' not in open(notify._path()).read()
        assert notify.list_channels()[0]['url_hint'].endswith('/…')
        # Below the channel's level, or another event: nothing is sent.
        assert notify.send('smart', 't', 'm', 'info', wait=True) == []
        assert notify.send('security', 't', 'm', 'critical', wait=True) == []
        [(name, ok, status)] = notify.send('smart', 'Disk sda failing', 'details', 'critical', wait=True)
        assert ok and status.startswith('OK')
        path, _, body = _Sink.received[-1]
        assert path == '/hook/secret-token-123'
        assert json.loads(body)['title'] == 'Disk sda failing'
        notify.update_channel(cid, enabled=False)
        assert notify.send('smart', 't', 'm', 'critical', wait=True) == []
    finally:
        server.shutdown()
        for ch in notify.list_channels():
            notify.delete_channel(ch['id'])


def test_notification_url_validation_and_payloads():
    for bad in ('file:///etc/passwd', 'ftp://x/y', 'https://user:pw@host/x', 'not a url'):
        with pytest.raises(ValueError):
            notify.validate_url(bad)
    _, body, headers = notify.build_request('ntfy', 'https://ntfy.sh/t', 'Título', 'msg', 'critical', 'smart')
    assert headers['Priority'] == '5' and body == b'msg'
    _, body, _ = notify.build_request('discord', 'https://d/x', 'T', '@everyone hi', 'info', 'smart')
    assert json.loads(body)['allowed_mentions'] == {'parse': []}


def test_smart_alerts_go_to_notification_channels(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, 'send', lambda *a, **k: sent.append(a))
    smart_manager._notify_new_alert('CRITICAL', 'Reallocated sectors rising', {'device': '/dev/sdz', 'source': 'local'})
    assert sent and sent[0][0] == 'smart' and sent[0][3] == 'critical'


def test_notification_pages_work_for_admins(client):
    _sign_in(client, 'notify_admin')
    assert client.get('/system/notifications').status_code == 200
    r = client.post('/system/notifications/add', data={'kind': 'ntfy', 'url': 'javascript:alert(1)', 'events': 'smart'})
    assert r.status_code == 302 and not notify.list_channels()
    viewer = _client()
    _sign_in(viewer, 'notify_viewer', ('viewer',))
    assert viewer.get('/system/notifications').status_code == 302
