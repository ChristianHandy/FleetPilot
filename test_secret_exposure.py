# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stored credentials are never sent back: not in pages, not in scripts, not in the API.

Every module that stores a password, API key or token gets one with a unique
marker. Then every GET route is requested, for each stored object, as an admin
and as a viewer, and no response may contain a marker.
"""
import itertools
import uuid
import socket
import subprocess
import time

import pytest
from flask import url_for

import account_security
import app as fp
import backup_controller
import corsair_commander
import fan_controller
import router_manager
import scheduled_shutdown
import storage_controller
import user_management
import vm_controller

MARK = 'Zq7-leak-'


def _secrets():
    """Store one credential per module; return {marker: description} and the ids that were created."""
    ids, secrets = set(), {}
    tag = uuid.uuid4().hex[:6]   # names are unique per table

    def mark(name):
        value = f'{MARK}{name}-pw'
        secrets[value] = name
        return value

    ids.add(scheduled_shutdown.add_schedule(
        f'leak-test-{tag}', '192.0.2.50', 22, 'root', mark('schedule'), '', '23:00', ['Mon'], False, 5, 'shutdown'))
    ids.add(backup_controller.add_server(f'leak-pbs-{tag}', 'pbs', '192.0.2.51', 8007, 'https', 'root@pam',
                                         mark('backup-password'), mark('backup-token')))
    ids.add(fan_controller.add_device(f'leak-fan-{tag}', 'lm_sensors', '192.0.2.52', 22, 'root', mark('fan')))
    ids.add(storage_controller.add_endpoint(f'leak-nas-{tag}', 'truenas', '192.0.2.53', 443, mark('storage')))
    ids.add(vm_controller.add_endpoint(f'leak-pve-{tag}', 'proxmox', '192.0.2.54', 8006, 'root@pam', mark('vm')))
    ids.add(corsair_commander.add_device(f'leak-corsair-{tag}', '192.0.2.55', 22, 'root', mark('corsair')))
    ids.add(router_manager.add_router({'name': f'leak-router-{tag}', 'platform': 'opnsense', 'host': '192.0.2.56',
                                       'api_key': mark('router-key'), 'api_secret': mark('router-secret')}))
    return secrets, sorted(i for i in ids if isinstance(i, int))


def _urls(ids):
    for rule in sorted(fp.app.url_map.iter_rules(), key=str):
        if rule.endpoint in ('static', 'logout', 'set_language', 'set_theme') or 'GET' not in rule.methods:
            continue
        ints = [n for n in rule.arguments if type(rule._converters.get(n)).__name__ == 'IntegerConverter']
        others = {n: 'x' for n in rule.arguments if n not in ints}
        for combo in itertools.product(ids or [1], repeat=len(ints)):
            with fp.app.test_request_context():
                yield url_for(rule.endpoint, **others, **dict(zip(ints, combo)))


def _offline(*args, **kwargs):
    raise OSError('network disabled in tests')


def _client(username, role):
    user_management.init_user_db()
    user = user_management.get_user(username)
    uid = user['id'] if user else user_management.create_user(username, 'leak-test-pass', None, [role])
    client = fp.app.test_client()
    with client.session_transaction() as s:
        s.update(user_id=uid, username=username, auth_time=time.time(),
                 pw_tag=fp._password_tag(user_management.get_user_by_id(uid)),
                 sid=account_security.create_session(uid, '127.0.0.1', 'pytest'))
    return client


@pytest.mark.parametrize('role', ['viewer', 'admin'])
def test_stored_credentials_are_never_sent_back(monkeypatch, role):
    monkeypatch.setattr(socket.socket, 'connect', _offline)
    monkeypatch.setattr(socket, 'create_connection', _offline)
    monkeypatch.setattr(subprocess, 'Popen', _offline)
    fp.app.config['TESTING'] = True
    secrets, ids = _secrets()
    client = _client(f'leak_{role}', role)
    leaks = []
    for url in sorted(set(_urls(ids))):
        response = client.get(url)
        body = response.get_data(as_text=True)
        response.close()
        leaks += [f'{url}: {name}' for value, name in secrets.items() if value in body]
    assert not leaks, f'Credentials sent to a {role}:\n' + '\n'.join(sorted(set(leaks)))
