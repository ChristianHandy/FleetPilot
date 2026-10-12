"""Regression tests for the CodeQL findings: redirects, paths, error text, XSS, commands."""
import io
import os

import pytest

import app as fp
import config_backup
import disktool_core
import safe_errors


def test_local_url_only_allows_paths_on_this_site():
    with fp.app.test_request_context('/'):
        for bad in ('https://evil.example/', '//evil.example', '/\\evil.example', '/\t/evil.example',
                    'javascript:alert(1)', 'evil.example', '///evil.example'):
            assert fp._local_url(bad) == '/index', bad
        assert fp._local_url('/hosts?x=1') == '/hosts?x=1'


def test_back_ignores_foreign_referrers():
    with fp.app.test_request_context('/', headers={'Referer': 'https://evil.example/x'}):
        assert fp._back() == '/index'
    with fp.app.test_request_context('/', base_url='http://fp.local', headers={'Referer': 'http://fp.local/hosts?a=1'}):
        assert fp._back() == '/hosts?a=1'


def test_error_messages_hide_exception_details():
    secret = 'https://admin:hunter2@10.0.0.5/api failed at /opt/fleetpilot/app.py'
    for exc in (RuntimeError(secret), OSError(secret), ValueError(secret), TimeoutError(secret)):
        message = safe_errors.public_error(exc, 'Test')
        assert 'hunter2' not in message and '/opt' not in message and message.startswith('Test')


def test_smart_upload_filename_is_never_used_as_a_path(tmp_path, monkeypatch):
    monkeypatch.setattr(disktool_core, 'UPLOAD_DIR', tmp_path / 'uploads')
    target = tmp_path / 'escaped.txt'

    class Upload:
        filename = '../escaped.txt'
        stream = io.BytesIO(b'194 Temperature_Celsius 0x0022 100 100 000 Old_age Always - 41\n')

        def save(self, path):  # the old code called this with the client's name
            raise AssertionError('upload was written to disk')

    disktool_core.import_smart_data(Upload(), 'sdx')
    assert not target.exists()


def test_disk_commands_only_accept_existing_devices(monkeypatch):
    monkeypatch.setattr(disktool_core, '_present_block_devices', lambda: ['sda', 'nvme0n1'])
    assert disktool_core.local_block_device('nvme0n1') == 'nvme0n1'
    for bad in ('sdz', 'sda;reboot', '../sda', ''):
        with pytest.raises(ValueError):
            disktool_core.local_block_device(bad)


def test_backup_path_uses_the_listed_file(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    path = config_backup.create_backup(str(data))
    name = os.path.basename(path)
    assert config_backup.backup_path(str(data), name) == path
    assert config_backup.backup_path(str(data), '../' + name) is None
    assert config_backup.backup_path(str(data), 'fleetpilot-missing.tar.gz') is None


def test_addon_paths_stay_inside_the_addon_folder():
    assert fp._new_addon_path('good_plugin.py').endswith(os.sep + 'good_plugin.py')
    for bad in ('../app.py', '/etc/passwd.py', 'x.sh', 'a b.py', ''):
        path = fp._new_addon_path(bad)
        assert path is None or os.path.dirname(path) == os.path.realpath(fp._ADDON_DIR), bad
    assert fp._existing_file(fp._ADDON_DIR, '../app.py') is None
    assert fp._existing_file(fp._ADDON_DIR, 'plugin_manager.py')


def test_checkmk_unknown_host_does_not_echo_input(monkeypatch):
    monkeypatch.setattr(fp, '_check_cmk_token', lambda: True)
    with fp.app.test_client() as c:
        r = c.get('/api/checkmk/host/<script>alert(1)</script>')
    assert r.status_code == 404 and b'<script>alert(1)' not in r.data
