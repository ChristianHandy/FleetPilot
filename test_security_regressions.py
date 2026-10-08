"""Regression tests for access-control and CSRF fixes."""
import re

import pytest

import app as fp
import secret_box
import user_management


def _user(username, role):
    user_management.init_user_db()
    existing = user_management.get_user(username)
    if existing:
        return existing['id']
    return user_management.create_user(username, 'regression-test-pass', None, [role])


@pytest.fixture
def client():
    fp.app.config['TESTING'] = True
    with fp.app.test_client() as c:
        yield c


def _login(client, username, role):
    user_id = _user(username, role)
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['pw_tag'] = __import__('app')._password_tag(user_management.get_user_by_id(user_id))
        sess['sid'] = __import__('account_security').create_session(user_id, '127.0.0.1', 'pytest')
        sess['auth_time'] = __import__('time').time()
        sess['username'] = username
    return user_id


def test_data_dir_files_are_not_downloadable(client):
    for path in ('/api/sync/manifest', '/api/sync/pull/users.db', '/api/sync/pull/.checkmk_token'):
        assert client.get(path).status_code == 404


def test_viewer_cannot_trigger_actions(client):
    fp.app.config['WTF_CSRF_ENABLED'] = False
    try:
        _login(client, 'regression_viewer', 'viewer')
        assert client.post('/api/hosts/anything/wol').status_code == 403
        assert client.post('/api/registry/servers', json={}).status_code == 403
        response = client.post('/hosts/anything/shutdown')
        assert response.status_code == 302 and response.headers['Location'].endswith('/index')
    finally:
        fp.app.config['WTF_CSRF_ENABLED'] = True


def test_deactivated_user_session_is_rejected(client):
    user_id = _login(client, 'regression_inactive', 'admin')
    user_management.update_user(user_id, active=0)
    try:
        response = client.get('/index')
        assert response.status_code == 302 and '/?next=' in response.headers['Location'].replace('%2F', '/')
    finally:
        user_management.update_user(user_id, active=1)


def test_post_without_csrf_token_is_rejected(client):
    if fp._csrf is None:
        pytest.skip('CSRF disabled in this environment')
    fp.app.config['WTF_CSRF_ENABLED'] = True  # other tests switch it off
    _login(client, 'regression_admin', 'admin')
    assert client.post('/api/dashboard/layout/reset').status_code == 400
    page = client.get('/index').get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    assert client.post('/api/dashboard/layout/reset', headers={'X-CSRFToken': token}).status_code == 200


def test_update_routes_reject_get(client):
    _login(client, 'regression_admin', 'admin')
    assert client.get('/update/anything').status_code == 405
    assert client.get('/disks/toggle_auto').status_code == 405


def test_secret_box_round_trip_and_legacy_plaintext():
    box = secret_box.SecretBox('raw32')
    token = box.encrypt('hunter2')
    assert token != 'hunter2' and box.decrypt(token) == 'hunter2'
    assert box.decrypt('stored-before-encryption') == 'stored-before-encryption'
