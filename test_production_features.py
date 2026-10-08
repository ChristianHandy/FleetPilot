"""Tests for backups, Prometheus metrics, SMART alert de-duplication and email settings."""
import io
import json
import os
import sqlite3
import tarfile

import pytest

import app as fp
import config_backup
import email_config
import smart_manager
import user_management


@pytest.fixture
def admin_client():
    fp.app.config['TESTING'] = True
    fp.app.config['WTF_CSRF_ENABLED'] = False
    user_management.init_user_db()
    user = user_management.get_user('features_admin')
    uid = user['id'] if user else user_management.create_user('features_admin', 'features-admin-pass', None, ['admin'])
    with fp.app.test_client() as c:
        with c.session_transaction() as s:
            s['user_id'] = uid
            s['username'] = 'features_admin'
            s['pw_tag'] = fp._password_tag(user_management.get_user_by_id(uid))
            s['sid'] = __import__('account_security').create_session(uid, '127.0.0.1', 'pytest')
            s['auth_time'] = __import__('time').time()
        yield c
    fp.app.config['WTF_CSRF_ENABLED'] = True


def _make_data_dir(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    con = sqlite3.connect(data / 'users.db')
    con.execute('create table t (v text)')
    con.execute("insert into t values ('original')")
    con.commit()
    con.close()
    (data / 'hosts.json').write_text('{"a": {"host": "192.0.2.1"}}')
    (data / '.secret_key').write_text('k' * 64)
    (data / 'initial_admin_password').write_text('admin:x')
    return data


def test_backup_round_trip_restores_on_next_start(tmp_path):
    data = _make_data_dir(tmp_path)
    archive = config_backup.create_backup(str(data), '9.9.9')
    assert oct(os.stat(archive).st_mode & 0o777) == '0o600'
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
    assert {'users.db', 'hosts.json', '.secret_key', config_backup.MANIFEST} <= names
    assert 'initial_admin_password' not in names

    # Change the live data, stage the backup, apply it as a restart would.
    (data / 'hosts.json').write_text('{}')
    with open(archive, 'rb') as fh:
        manifest = config_backup.stage_restore(str(data), fh)
    assert manifest['fleetpilot_version'] == '9.9.9'
    assert config_backup.apply_pending_restore(str(data))
    assert json.loads((data / 'hosts.json').read_text()) == {'a': {'host': '192.0.2.1'}}
    assert any(p.name.startswith('pre-restore-') for p in data.iterdir())


def test_restore_rejects_tampered_or_foreign_archives(tmp_path):
    data = _make_data_dir(tmp_path)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        evil = b'pwned'
        info = tarfile.TarInfo('../../etc/cron.d/x')
        info.size = len(evil)
        tar.addfile(info, io.BytesIO(evil))
    buf.seek(0)
    with pytest.raises(ValueError):
        config_backup.stage_restore(str(data), buf)
    assert not config_backup.restore_pending(str(data))

    archive = config_backup.create_backup(str(data))
    raw = io.BytesIO()
    with tarfile.open(archive) as src, tarfile.open(fileobj=raw, mode='w:gz') as dst:
        for m in src.getmembers():
            payload = src.extractfile(m).read()
            if m.name == 'hosts.json':
                payload = b'{"changed": true}'
                m.size = len(payload)
            dst.addfile(m, io.BytesIO(payload))
    raw.seek(0)
    with pytest.raises(ValueError, match='Checksum'):
        config_backup.stage_restore(str(data), raw)


def test_backup_pages_require_admin_and_work(admin_client):
    assert admin_client.get('/system/backups').status_code == 200
    r = admin_client.post('/system/backups/create')
    assert r.status_code == 302
    name = config_backup.list_backups(fp.DATA_DIR)[0]['name']
    r = admin_client.get(f'/system/backups/download/{name}')
    assert r.status_code == 200 and r.data[:2] == b'\x1f\x8b'
    assert admin_client.get('/system/backups/download/..%2Fusers.db').status_code == 404
    assert admin_client.post(f'/system/backups/delete/{name}').status_code == 302


def test_metrics_requires_token_and_renders():
    fp.app.config['TESTING'] = True
    with fp.app.test_client() as c:
        assert c.get('/metrics').status_code == 401
        token = fp._get_or_create_cmk_token()
        r = c.get('/metrics', headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'fleetpilot_info{version=' in body and '# TYPE fleetpilot_hosts gauge' in body


def test_smart_alerts_are_not_duplicated(monkeypatch):
    sent = []
    monkeypatch.setattr(smart_manager, '_notify_new_alert', lambda *a: sent.append(a))
    disk_id = smart_manager.register_disk('local', '/dev/test-dup', serial='DUP1', model='Test')
    parsed = {'reallocated': 8, 'pending': 0, 'uncorrectable': 0, 'temp': 40, 'overall_status': 'PASSED'}
    for _ in range(3):
        smart_manager._check_and_alert(disk_id, 'WARNING', parsed)
    alerts = [a for a in smart_manager.get_active_alerts() if a['disk_id'] == disk_id]
    assert len(alerts) == 1 and len(sent) == 1


def test_email_password_is_encrypted_and_not_rendered(admin_client):
    settings = email_config.load_email_settings()
    settings.update(smtp_server='smtp.example.com', smtp_password='s3cret-smtp-pass')
    email_config.save_email_settings(settings)
    raw = open(email_config._config_path()).read()
    assert 's3cret-smtp-pass' not in raw
    assert email_config.load_email_settings()['smtp_password'] == 's3cret-smtp-pass'
    page = admin_client.get('/email_settings').get_data(as_text=True)
    assert 's3cret-smtp-pass' not in page
    # Saving the notification form must not wipe the SMTP settings.
    admin_client.post('/email_settings', data={'section': 'notifications', 'report_interval': 'daily'})
    after = email_config.load_email_settings()
    assert after['smtp_server'] == 'smtp.example.com' and after['smtp_password'] == 's3cret-smtp-pass'


def test_password_policy_and_current_password(admin_client):
    r = admin_client.post('/users/add', data={'username': 'shortpw', 'password': 'short', 'roles': 'viewer'})
    assert r.status_code == 302 and user_management.get_user('shortpw') is None
    r = admin_client.post('/users/profile', data={'password': 'a-much-longer-password', 'current_password': 'wrong'})
    assert user_management.verify_password('features_admin', 'features-admin-pass')


def test_error_pages_are_friendly(admin_client):
    r = admin_client.get('/this-page-does-not-exist')
    assert r.status_code == 404 and b'Page not found' in r.data
    r = admin_client.get('/api/does-not-exist')
    assert r.status_code == 404 and r.is_json
