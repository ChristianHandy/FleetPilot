# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The API the Android app uses, called with personal API tokens as the app does."""
import pytest

import account_security
import app as fp
import fan_controller
import user_management
import vm_controller


def _token(role, scope):
    name = f'app_{role}_{scope}'
    user_management.init_user_db()
    user = user_management.get_user(name)
    uid = user['id'] if user else user_management.create_user(name, 'app-test-pass', None, [role])
    raw, _ = account_security.create_token(uid, 'Android app', scope, 30)
    return {'Authorization': f'Bearer {raw}'}


@pytest.fixture
def client():
    fp.app.config['TESTING'] = True
    return fp.app.test_client()


def test_me_and_hosts_with_a_read_token(client, monkeypatch):
    monkeypatch.setattr(fp, 'load_hosts', lambda: {
        'web1': {'host': '192.0.2.1', 'mac': 'aa:bb:cc:dd:ee:ff', 'group': 'rack', 'management': {'state': 'manageable'}},
        'nas': {'host': '192.0.2.2'}})
    headers = _token('viewer', 'read')
    me = client.get('/api/me', headers=headers).get_json()
    assert me['auth'] == 'token' and me['scope'] == 'read' and me['roles'] == ['viewer']
    hosts = {h['name']: h for h in client.get('/api/hosts', headers=headers).get_json()}
    assert hosts['web1']['state'] == 'manageable' and hosts['web1']['can_wake'] and hosts['web1']['group'] == 'rack'
    assert hosts['nas']['state'] == 'unknown' and not hosts['nas']['can_wake']
    assert client.get('/api/hosts', headers={'Authorization': 'Bearer fp_wrong'}).status_code in (302, 401)


def test_read_tokens_cannot_act(client):
    headers = _token('admin', 'read')
    for path in ('/api/hosts/web1/wol', '/api/vms/1/action', '/api/fans/1/set_fan'):
        assert client.post(path, headers=headers).status_code == 403, path


def test_vm_list_and_power_action(client, monkeypatch):
    monkeypatch.setattr(vm_controller, 'list_endpoints', lambda: [
        {'id': 1, 'name': 'pve', 'platform': 'proxmox', 'username': 'root@pam'},
        {'id': 2, 'name': 'down', 'platform': 'proxmox'},
        {'id': 3, 'name': 'veeam', 'platform': 'veeam'}])

    def vms(ep_id):
        if ep_id == 2:
            raise ConnectionError('unreachable')
        return [{'vmid': 101, 'name': 'docker', 'status': 'running', 'node': 'pve1', 'type': 'qemu', 'cpu': 0.12,
                 'cpus': 4, 'mem': 2 ** 30, 'maxmem': 2 ** 32, 'uptime': 3600, 'secret_field': 'x'}]
    monkeypatch.setattr(vm_controller, 'get_all_vms', vms)
    data = client.get('/api/vms', headers=_token('viewer', 'read')).get_json()['endpoints']
    assert data[0]['vms'][0] == {'vmid': 101, 'name': 'docker', 'status': 'running', 'node': 'pve1', 'type': 'qemu',
                                 'cpu': 0.12, 'cpus': 4, 'mem': 2 ** 30, 'maxmem': 2 ** 32, 'uptime': 3600}
    assert 'username' not in data[0] and data[1]['error'] and data[1]['vms'] == []
    assert data[2]['vms'] == [] and data[2]['error'] is None

    calls = []
    monkeypatch.setattr(vm_controller, 'vm_power_action',
                        lambda ep, node, vmid, action, rtype: calls.append((ep, node, vmid, action, rtype)) or {'ok': True})
    form = {'node': 'pve1', 'vmid': '101', 'rtype': 'qemu', 'action': 'start'}
    assert client.post('/api/vms/1/action', data=form, headers=_token('operator', 'write')).status_code == 403
    assert client.post('/api/vms/1/action', data=form, headers=_token('admin', 'write')).get_json() == {'ok': True}
    assert calls == [(1, 'pve1', 101, 'start', 'qemu')]
    bad = client.post('/api/vms/1/action', data=dict(form, action='destroy'), headers=_token('admin', 'write'))
    assert bad.status_code == 400


def test_fan_speed_from_the_app(client, monkeypatch):
    monkeypatch.setattr(fan_controller, 'get_device', lambda dev_id: {'id': dev_id, 'name': 'rig'} if dev_id == 1 else None)
    seen = []
    monkeypatch.setattr(fan_controller, 'set_fan_speed',
                        lambda dev, channel, speed, extra: seen.append((channel, speed)) or {'ok': True, 'message': 'set'})
    form = {'channel': 'pwm1', 'mode': 'fixed', 'speed': '40'}
    assert client.post('/api/fans/1/set_fan', data=form, headers=_token('viewer', 'write')).status_code == 403
    assert client.post('/api/fans/1/set_fan', data=form, headers=_token('operator', 'write')).get_json()['ok']
    assert seen == [('pwm1', 40.0)]
    assert client.post('/api/fans/9/set_fan', data=form, headers=_token('operator', 'write')).status_code == 404
