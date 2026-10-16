# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows PCs and servers: version and support status, encoded PowerShell, updates, power, inventory."""
import base64
import io
import json
import os
import re
import shutil
import subprocess
import time
from datetime import date

import pytest

import account_security
import app as fp
import hw_info
import smart_manager
import updater
import user_management
import windows_host as wh

TODAY = date(2026, 10, 16)


def info(caption, edition, build, installation='Client', display='', ubr=1000):
    return {'caption': caption, 'edition': edition, 'build': build, 'ubr': ubr, 'installation': installation,
            'display_version': display, 'arch': '64-bit', 'hostname': 'HOST'}


@pytest.mark.parametrize('fields,name,channel,end,status', [
    (info('Microsoft Windows 11 Enterprise Evaluation', 'EnterpriseEval', 26300, display='26H2'),
     'Windows 11 Enterprise Evaluation 26H2', 'General Availability', '2029-10-09', 'supported'),
    (info('Microsoft Windows 11 Pro', 'Professional', 26300, display='26H2'), 'Windows 11 Pro 26H2',
     'General Availability', '2028-10-10', 'supported'),
    (info('Microsoft Windows 11 Home', 'Core', 28000, display='26H1'), 'Windows 11 Home 26H1',
     'General Availability', '2028-03-14', 'supported'),
    # Microsoft's evaluation ISOs report the edition with an "Eval" suffix.
    (info('Microsoft Windows 11 IoT Enterprise LTSC Evaluation', 'IoTEnterpriseSEval', 26100, display='24H2'),
     'Windows 11 IoT Enterprise LTSC Evaluation 2024', 'Long-Term Servicing Channel', '2034-10-10', 'supported'),
    (info('Microsoft Windows 11 Home', 'Core', 26200, display='25H2'), 'Windows 11 Home 25H2',
     'General Availability', '2027-10-12', 'supported'),
    (info('Microsoft Windows 11 Pro', 'Professional', 26100, display='24H2'), 'Windows 11 Pro 24H2',
     'General Availability', '2026-10-13', 'ended'),
    (info('Microsoft Windows 11 Enterprise', 'Enterprise', 26100, display='24H2'), 'Windows 11 Enterprise 24H2',
     'General Availability', '2027-10-12', 'supported'),
    (info('Microsoft Windows 11 Education', 'Education', 22631, display='23H2'), 'Windows 11 Education 23H2',
     'General Availability', '2026-11-10', 'ending'),
    (info('Microsoft Windows 10 Pro', 'Professional', 19045, display='22H2'), 'Windows 10 Pro 22H2',
     'General Availability', '2025-10-14', 'ended'),
    (info('Microsoft Windows 11 Enterprise LTSC 2024', 'EnterpriseS', 26100), 'Windows 11 Enterprise LTSC 2024',
     'Long-Term Servicing Channel', '2029-10-09', 'supported'),
    (info('Microsoft Windows 11 IoT Enterprise LTSC 2024', 'IoTEnterpriseS', 26100),
     'Windows 11 IoT Enterprise LTSC 2024', 'Long-Term Servicing Channel', '2034-10-10', 'supported'),
    (info('Microsoft Windows 10 Enterprise LTSC 2021', 'EnterpriseS', 19044), 'Windows 10 Enterprise LTSC 2021',
     'Long-Term Servicing Channel', '2027-01-12', 'ending'),
    (info('Microsoft Windows 10 IoT Enterprise LTSC 2021', 'IoTEnterpriseS', 19044),
     'Windows 10 IoT Enterprise LTSC 2021', 'Long-Term Servicing Channel', '2032-01-13', 'supported'),
    (info('Microsoft Windows 10 Enterprise N LTSC 2019', 'EnterpriseSN', 17763),
     'Windows 10 Enterprise N LTSC 2019', 'Long-Term Servicing Channel', '2029-01-09', 'supported'),
    (info('Microsoft Windows 10 Enterprise LTSB 2016', 'EnterpriseS', 14393), 'Windows 10 Enterprise LTSB 2016',
     'Long-Term Servicing Channel', '2026-10-13', 'ended'),
    (info('Microsoft Windows Server 2025 Datacenter', 'ServerDatacenter', 26100, 'Server'),
     'Windows Server 2025 Datacenter', 'Long-Term Servicing Channel', '2034-10-10', 'supported'),
    (info('Microsoft Windows Server 2022 Standard', 'ServerStandard', 20348, 'Server Core'),
     'Windows Server 2022 Standard (Server Core)', 'Long-Term Servicing Channel', '2031-10-14', 'supported'),
    (info('Microsoft Windows Server 2019 Standard', 'ServerStandard', 17763, 'Server'),
     'Windows Server 2019 Standard', 'Long-Term Servicing Channel', '2029-01-09', 'supported'),
    (info('Microsoft Windows Server 2016 Datacenter', 'ServerDatacenter', 14393, 'Server'),
     'Windows Server 2016 Datacenter', 'Long-Term Servicing Channel', '2027-01-12', 'ending'),
    (info('Microsoft Windows Server Datacenter', 'ServerDatacenter', 25398, 'Server Core'),
     'Windows Server Datacenter 23H2 (Server Core)', 'Annual Channel', '2025-10-24', 'ended'),
])
def test_every_serviced_release_is_named_with_its_support_end(fields, name, channel, end, status):
    result = wh.identify(fields, today=TODAY)
    assert (result['name'], result['channel'], result['support_end'], result['support_status']) == \
        (name, channel, end, status)
    assert result['kind'] == ('server' if 'Server' in name else 'client')
    assert result['version'] == f"10.0.{fields['build']}.{fields['ubr']}"


def test_windows_10_registry_name_on_windows_11_and_unknown_builds():
    # The registry's ProductName still says "Windows 10" on Windows 11.
    win11 = wh.identify(info('Windows 10 Pro', 'Professional', 26100, display='24H2'), today=TODAY)
    assert win11['name'] == 'Windows 11 Pro 24H2'
    esu = wh.identify(info('Microsoft Windows 10 Enterprise', 'Enterprise', 19045, display='22H2'), today=TODAY)
    assert 'Extended Security Updates' in esu['support_note']
    insider = wh.identify(info('Microsoft Windows 11 Pro', 'Professional', 27900, display='26H1'), today=TODAY)
    assert insider['support_status'] == 'unknown' and insider['support_end'] is None and insider['release'] == '26H1'
    assert wh.identify(info('Microsoft Windows 11 Pro', 'Professional', 26100), today=date(2026, 6, 1))[
        'support_status'] == 'ending'


def test_parse_info_reads_the_json_line():
    out = 'Windows PowerShell banner\r\n' + json.dumps(info('Microsoft Windows 11 Pro', 'Professional', 26200)) + '\r\n'
    assert wh.parse_info(out)['name'].startswith('Windows 11 Pro')
    with pytest.raises(ValueError):
        wh.parse_info("'powershell.exe' is not recognized as an internal or external command")


def _decode(command):
    assert command.startswith(wh.POWERSHELL)
    return base64.b64decode(command[len(wh.POWERSHELL):]).decode('utf-16-le')


ALL_COMMANDS = {
    'detect': wh.DETECT_COMMAND, 'info': wh.INFO_COMMAND, 'hw': wh.HW_COMMAND, 'winget': wh.WINGET_COMMAND,
    'smartctl-scan': wh.SMARTCTL_SCAN_COMMAND, 'update': wh.update_command(True), 'check': wh.update_command(False),
    **{f'upload-{i}': c for i, c in enumerate(wh.upload_commands(wh.UPDATE_WORKER))},
}


@pytest.mark.parametrize('name', sorted(ALL_COMMANDS))
def test_commands_fit_cmd_exe_and_need_no_quoting(name):
    command = ALL_COMMANDS[name]
    assert len(command) < 8000            # cmd.exe accepts at most 8191 characters
    assert re.fullmatch(r'[A-Za-z0-9 .\-]+ [A-Za-z0-9+/=]+', command)   # nothing a shell could interpret
    assert _decode(command).startswith('# fleetpilot:')


def test_upload_rebuilds_the_worker_and_locks_the_folder():
    commands = wh.upload_commands(wh.UPDATE_WORKER)
    scripts = [_decode(c) for c in commands]
    assert 'icacls.exe' in scripts[0] and '*S-1-5-18' in scripts[0] and '*S-1-5-32-544' in scripts[0]
    data = ''.join(re.search(r"'([A-Za-z0-9+/=]{20,})'\)$", s).group(1) for s in scripts)
    assert base64.b64decode(data) == b'\xef\xbb\xbf' + wh.UPDATE_WORKER.encode('utf-8')
    runner = _decode(wh.update_command(True, minutes=45))
    assert '-Mode install' in runner and 'AddMinutes(45)' in runner and wh.RESULT_MARKER in runner
    assert "-UserId 'SYSTEM'" in runner and 'Unregister-ScheduledTask' in runner
    assert '-Mode check' in _decode(wh.update_command(False))


def test_parse_result():
    assert wh.parse_result('Installing...') is None
    one = {'title': 'KB1', 'kb': '1', 'security': True}
    r = wh.parse_result('\ufeff' + wh.RESULT_MARKER + '\ufeff' + json.dumps({'ok': True, 'updates': one}) + '\r\n')
    assert r['ok'] and r['updates'] == [one]
    assert wh.parse_result(wh.RESULT_MARKER + json.dumps({'ok': True, 'updates': None}))['updates'] == []


def test_smartctl_scan_and_commands_are_validated():
    out = ('SMARTCTL=C:\\Program Files\\smartmontools\\bin\\smartctl.exe\r\n'
           '/dev/sda -d ata # /dev/sda, ATA device\r\n/dev/nvme0 -d nvme # /dev/nvme0, NVMe device\r\n'
           '/dev/csmi0,0 -d ata # /dev/csmi0,0, port 0\r\n/dev/sda -d ata # duplicate\r\n')
    path, devices = wh.parse_smartctl_scan(out)
    assert path.endswith('smartctl.exe') and devices == ['sda', 'nvme0', 'csmi0']
    assert "& 'C:\\Program Files\\smartmontools\\bin\\smartctl.exe' -a /dev/sda" in _decode(
        wh.smartctl_command(path, '-a', 'sda'))
    assert wh.parse_smartctl_scan("SMARTCTL=C:\\x';calc.exe;'\\smartctl.exe\n/dev/sda") == (None, [])
    assert wh.parse_smartctl_scan('') == (None, [])
    for bad in ((path, '-s on', 'sda'), (path, '-a', 'sda;x'), ("C:\\evil'\\smartctl.exe", '-a', 'sda')):
        with pytest.raises(ValueError):
            wh.smartctl_command(*bad)


@pytest.mark.skipif(not (shutil.which('pwsh') or os.environ.get('PWSH')), reason='PowerShell is not installed')
@pytest.mark.parametrize('name', sorted(ALL_COMMANDS) + ['worker'])
def test_powershell_scripts_parse(tmp_path, name):
    script = wh.UPDATE_WORKER if name == 'worker' else _decode(ALL_COMMANDS[name])
    path = tmp_path / 'script.ps1'
    path.write_text(script, encoding='utf-8')
    check = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
             f"'{path}', [ref]$null, [ref]$e); $e | ForEach-Object {{ $_.Message }}")
    out = subprocess.run([os.environ.get('PWSH') or shutil.which('pwsh'), '-NoProfile', '-Command', check],
                         capture_output=True, text=True, timeout=120)
    assert out.stdout.strip() == '' and out.returncode == 0, out.stdout + out.stderr


# ── A Windows host behind SSH ────────────────────────────────────────────────

class Channel:
    def __init__(self, code, data=b''):
        self.code, self.data = code, data

    def recv_exit_status(self):
        return self.code

    def makefile(self, mode='r'):
        return io.BytesIO(self.data)


class Stream:
    def __init__(self, text, code=0):
        data = text if isinstance(text, bytes) else text.encode()
        text = data.decode('utf-8', errors='replace')
        self.lines = text.splitlines(keepends=True)
        self.text, self.data, self.channel = text, data, Channel(code, data)

    def read(self):
        return self.data

    def readline(self):
        return self.lines.pop(0) if self.lines else ''


class WindowsHost:
    """Answers FleetPilot's encoded PowerShell scripts like a Windows 11 PC."""

    def __init__(self, info_fields=None, result=None, upload_code=0, winget='No applicable upgrade found.',
                 smartctl=''):
        self.info = info_fields or info('Microsoft Windows 11 Pro', 'Professional', 26200, display='25H2')
        self.result = result if result is not None else {
            'ok': True, 'mode': 'install', 'installed': 2, 'failed': 0, 'reboot': True, 'error': None,
            'updates': [{'title': 'KB5066835', 'security': True}, {'title': 'KB2267602', 'security': False}]}
        self.upload_code, self.winget, self.smartctl = upload_code, winget, smartctl
        self.scripts, self.commands, self.closed = [], [], False

    def exec_command(self, command, timeout=None, get_pty=False):
        self.commands.append(command)
        if not command.startswith(wh.POWERSHELL):
            if command.startswith('shutdown '):
                return None, Stream(''), Stream('')
            return None, Stream('', 1), Stream(f"'{command.split()[0]}' is not recognized\r\n", 1)
        script = _decode(command)
        self.scripts.append(script)
        marker = script.split('\n', 1)[0]
        if marker == '# fleetpilot:detect':
            out = 'windows\r\n'
        elif marker == '# fleetpilot:windows-info':
            out = json.dumps(self.info) + '\r\n'
        elif marker == '# fleetpilot:upload':
            return None, Stream('', self.upload_code), Stream('Access to the path is denied.\r\n')
        elif marker == '# fleetpilot:run-as-system':
            out = 'Searching for updates...\r\nFound 2 update(s).\r\nInstalling...\r\n'
            if self.result:
                out += wh.RESULT_MARKER + json.dumps(self.result) + '\r\n'
        elif marker == '# fleetpilot:winget':
            out = self.winget + '\r\n'
        elif marker == '# fleetpilot:windows-hw':
            out = json.dumps({'platform': 'windows', 'os': 'Windows 11 Pro', 'disks': [{'name': 'PhysicalDrive0'}]})
        elif marker == '# fleetpilot:install-key':
            out = 'installed:C:\\ProgramData\\ssh\\administrators_authorized_keys\r\n'
        elif marker == '# fleetpilot:smartctl-scan':
            out = self.smartctl
        elif marker == '# fleetpilot:smartctl':
            out = ('smartctl 7.4\r\nDevice Model:     Samsung SSD 990 PRO 2TB\r\nSerial Number:    S7HENJ0X\r\n'
                   'User Capacity:    2,000,398,934,016 bytes\r\nSMART overall-health self-assessment test result: '
                   'PASSED\r\n')
        else:
            out = ''
        return None, Stream(out), Stream('')

    def close(self):
        self.closed = True


def test_windows_update_installs_as_system_then_runs_winget():
    host, log = WindowsHost(winget='Successfully installed Mozilla.Firefox'), []
    assert updater._run_windows_update(host, False, log.append) == []
    text = '\n'.join(log)
    assert 'Windows 11 Pro 25H2, build 10.0.26200.1000 (General Availability)' in text
    assert 'Found 2 update(s).' in text and 'Windows updates installed: 2' in text
    assert 'needs a restart' in text and 'Successfully installed Mozilla.Firefox' in text
    markers = [s.split('\n', 1)[0] for s in host.scripts]
    assert markers == ['# fleetpilot:windows-info', '# fleetpilot:upload', '# fleetpilot:upload',
                       '# fleetpilot:run-as-system', '# fleetpilot:winget']


def test_windows_update_problems_are_reported():
    log = []
    host = WindowsHost(info('Microsoft Windows 10 Enterprise LTSB 2016', 'EnterpriseS', 14393))
    updater._run_windows_update(host, True, log.append)
    assert any('ended support' in line for line in log)
    assert not any('fleetpilot:winget' in s for s in host.scripts)          # repository-only: no winget
    assert updater._run_windows_update(WindowsHost(upload_code=1), True, log.append) == [
        'Could not prepare Windows Update (Access to the path is denied.). The SSH account must be an administrator.']
    failed = dict(WindowsHost().result, failed=1, error='0x80240022')
    problems = updater._run_windows_update(WindowsHost(result=failed), True, log.append)
    assert problems == ['Windows Update: 0x80240022', '1 Windows update(s) failed to install']
    assert updater._run_windows_update(WindowsHost(result={}), True, log.append)[0].startswith(
        'Windows Update gave no result')
    # Past the wait limit the runner leaves Windows installing and says so (seen on slow Ceph storage).
    running = {'ok': False, 'mode': 'running', 'error': 'still installing after 120 minutes. Windows continues ...'}
    assert updater._run_windows_update(WindowsHost(result=running), True, log.append) == [
        'Windows Update: still installing after 120 minutes. Windows continues ...']
    runner = _decode(wh.update_command(True))
    assert 'Stop-ScheduledTask' not in runner and '-Hours 24' in runner


def test_windows_output_in_the_oem_code_page_does_not_end_the_update():
    # Found on German Server 2022: titles came as code page 850 ("f\x81r" is "für"), and the strict UTF-8
    # readline raised in the middle of the update. Scripts now write UTF-8, and odd bytes are replaced.
    class GermanHost(WindowsHost):
        def exec_command(self, command, timeout=None, get_pty=False):
            stdin, out, err = super().exec_command(command, timeout, get_pty)
            if self.scripts and self.scripts[-1].startswith('# fleetpilot:run-as-system'):
                out = Stream(b'Kumulatives Update f\x81r Windows Server 2022 (KB5066782)\r\n' + out.data)
            return stdin, out, err

    log = []
    assert updater._run_windows_update(GermanHost(), True, log.append) == []
    assert 'Kumulatives Update f\ufffdr Windows Server 2022 (KB5066782)' in log
    for command in (wh.HW_COMMAND, wh.INFO_COMMAND, wh.update_command(True)):
        assert _decode(command).split('\n')[1] == wh.UTF8_OUTPUT       # marker line first, then UTF-8 output


def test_a_timeout_is_named_in_the_update_log(monkeypatch):
    # A busy Windows sshd timed out with an empty message: the log read "Error updating w22core:".
    def slow(*a, **k):
        raise TimeoutError()
    monkeypatch.setattr(updater.ssh_helper, 'create_client', slow)
    monkeypatch.setattr(updater.email_config, 'get_error_notifications_enabled', lambda: False)
    log = []
    updater.run_update('192.0.2.80', 'Administrator', 'w22core', log)
    assert any(line.endswith('✗ Error updating w22core: the host did not answer in time') for line in log)


def test_run_update_detects_windows_in_any_ssh_shell(monkeypatch):
    host = WindowsHost()
    monkeypatch.setattr(updater.ssh_helper, 'create_client', lambda *a, **k: host)
    monkeypatch.setattr(updater.email_config, 'get_error_notifications_enabled', lambda: False)
    log = []
    updater.run_update('192.0.2.80', 'Administrator', 'desk', log, repo_only=False)
    assert any('Detected Windows operating system' in line for line in log)
    assert any('Update completed successfully for desk' in line for line in log) and host.closed
    assert host.commands[0] == wh.DETECT_COMMAND


# ── Routes: detection, shutdown, editing ─────────────────────────────────────

@pytest.fixture
def operator(monkeypatch, tmp_path):
    user_management.init_user_db()
    user = user_management.get_user('win_operator')
    uid = user['id'] if user else user_management.create_user('win_operator', 'win-test-pass', None, ['admin'])
    client = fp.app.test_client()
    with client.session_transaction() as s:
        s.update(user_id=uid, username='win_operator', auth_time=time.time(),
                 pw_tag=fp._password_tag(user_management.get_user_by_id(uid)),
                 sid=account_security.create_session(uid, '127.0.0.1', 'pytest'))
    store = {'desk': {'host': '192.0.2.81', 'user': 'Administrator', 'port': 22, 'custom_image': '/img.png',
                      'management': {'state': 'manageable'}}}
    monkeypatch.setattr(fp, 'load_hosts', lambda: json.loads(json.dumps(store)))
    monkeypatch.setattr(fp, 'save_hosts', lambda hosts, **kw: store.clear() or store.update(hosts))
    before = fp.app.config.get('WTF_CSRF_ENABLED', True)
    fp.app.config['WTF_CSRF_ENABLED'] = False
    yield client, store
    fp.app.config['WTF_CSRF_ENABLED'] = before


def test_detect_os_recognises_windows_and_shutdown_uses_windows_commands(operator, monkeypatch):
    client, store = operator
    host = WindowsHost(info('Microsoft Windows Server 2022 Standard', 'ServerStandard', 20348, 'Server Core'))
    monkeypatch.setattr(fp.ssh_helper, 'create_client', lambda **k: host)
    result = client.get('/hosts/detect_os/desk').get_json()
    assert result['ok'] and result['os']['type'] == 'windows'
    assert store['desk']['os_type'] == 'windows' and store['desk']['windows']['support_end'] == '2031-10-14'
    assert store['desk']['os_profiles'][0]['name'] == 'Windows Server 2022 Standard (Server Core)'
    page = client.get('/hosts').get_data(as_text=True)
    assert 'Supported until 2031-10-14' in page

    assert client.post('/hosts/desk/shutdown').get_json()['ok']
    assert host.commands[-1] == wh.SHUTDOWN_COMMAND


def test_editing_a_host_keeps_what_the_form_does_not_show(operator):
    client, store = operator
    store['desk'].update(os_type='windows', windows={'support_end': '2031-10-14'})
    form = {'name': 'desk', 'host': '192.0.2.82', 'user': 'Administrator', 'port': '22'}
    assert client.post('/hosts/edit/desk', data=form).status_code in (302, 303)
    desk = store['desk']
    assert desk['host'] == '192.0.2.82' and desk['custom_image'] == '/img.png'
    assert desk['os_type'] == 'windows' and desk['windows'] and desk['management']['state'] == 'manageable'
    client.post('/hosts/edit/desk', data=dict(form, name='desk2', os_name=['Debian 13'], os_type=['linux'],
                                             os_default=['0']))
    assert 'desk' not in store and store['desk2']['os_type'] == 'linux' and store['desk2']['custom_image']
    assert fp._host_os_type({'os_profiles': [{'type': 'windows', 'default': True}]}) == 'windows'
    assert fp._host_os_type({}) == 'linux'


def test_hardware_inventory_and_smart_on_windows(tmp_path, monkeypatch):
    host = WindowsHost()
    monkeypatch.setattr(hw_info.ssh_helper, 'create_client', lambda **k: host)
    data = hw_info.HwInfoCollector(str(tmp_path)).collect('192.0.2.83', 22, 'Administrator', server_name='desk')
    assert data['platform'] == 'windows' and data['disks'][0]['name'] == 'PhysicalDrive0'

    host = WindowsHost(smartctl='SMARTCTL=C:\\Program Files\\smartmontools\\bin\\smartctl.exe\r\n'
                                '/dev/sda -d ata # /dev/sda, ATA device\r\n')
    monkeypatch.setattr(smart_manager.ssh_helper, 'create_client', lambda **k: host)
    previous = smart_manager.DB_FILE
    smart_manager.init_db(str(tmp_path))
    try:
        smart_manager.collect_ssh_host_disks('desk', '192.0.2.83', 'Administrator', password='pw')
        disks = smart_manager.get_all_disks()
        assert [d['device'] for d in disks] == ['desk:sda'] and disks[0]['model'] == 'Samsung SSD 990 PRO 2TB'
        assert any(s.startswith('# fleetpilot:smartctl\n') and '-a /dev/sda' in s for s in host.scripts)
        assert not any('sudo' in c for c in host.commands)
    finally:
        smart_manager.DB_FILE = previous


def test_ssh_key_goes_where_windows_openssh_reads_it(operator, monkeypatch):
    client, _ = operator
    host = WindowsHost()
    monkeypatch.setattr(fp.ssh_helper, 'create_client', lambda **k: host)
    monkeypatch.setattr(fp, 'get_local_public_key', lambda: 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBx7 fleetpilot@fp')
    page = client.post('/hosts/install_key/desk', data={'password': 'pw'}).get_data(as_text=True)
    script = [s for s in host.scripts if s.startswith('# fleetpilot:install-key')][0]
    assert "administrators_authorized_keys" in script and "'*S-1-5-32-544:F'" in script and 'Encoding ASCII' in script
    assert "$key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBx7 fleetpilot@fp'" in script
    assert 'Could not install' not in page and host.closed
    for bad in ("ssh-ed25519 AAAA' ; Remove-Item C:\\ -Recurse ; '", 'not a key', ''):
        with pytest.raises(ValueError):
            wh.install_key_command(bad)
