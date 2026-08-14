"""Focused safety checks for FleetPilot proxy route management."""
from pathlib import Path
import tempfile

import proxy_manager


def test_normalize_route():
    route = proxy_manager.normalize_route({
        'id': 'a' * 12,
        'name': 'Immich',
        'path_prefix': '/immich',
        'backend_host': '192.168.1.42',
        'backend_port': '2283',
        'health_path': '/',
        'enabled': True,
    })
    assert route['backend_port'] == 2283
    assert route['path_prefix'] == '/immich'


def test_normalize_proxmox_tls_route():
    route = proxy_manager.normalize_route({
        'id': 'b' * 12, 'name': 'pve01', 'path_prefix': '/pve01',
        'backend_host': '192.168.1.90', 'backend_port': 8006,
        'health_path': '/', 'route_type': 'proxmox_tls', 'public_port': 8101,
        'enabled': True,
    })
    assert route['route_type'] == 'proxmox_tls'
    assert route['public_port'] == 8101
    for field, invalid in {'backend_port': 8443, 'public_port': 80}.items():
        candidate = dict(route)
        candidate[field] = invalid
        try:
            proxy_manager.normalize_route(candidate)
        except ValueError:
            continue
        raise AssertionError(f'invalid Proxmox TLS {field} was accepted')


def test_normalize_unraid_tls_route():
    route = proxy_manager.normalize_route({
        'id': 'c' * 12, 'name': 'unraid', 'path_prefix': '/unraid',
        'backend_host': '192.168.1.133', 'backend_port': 443,
        'health_path': '/', 'route_type': 'unraid_tls', 'public_port': 8200,
        'enabled': True,
    })
    assert route['route_type'] == 'unraid_tls'
    assert route['public_port'] == 8200
    for field, invalid in {'backend_port': 80, 'public_port': 8201}.items():
        candidate = dict(route)
        candidate[field] = invalid
        try:
            proxy_manager.normalize_route(candidate)
        except ValueError:
            continue
        raise AssertionError(f'invalid Unraid TLS {field} was accepted')


def test_rejects_unsafe_route_inputs():
    base = {
        'name': 'Service', 'path_prefix': '/service', 'backend_host': '192.168.1.20',
        'backend_port': 8080, 'health_path': '/', 'enabled': True,
    }
    for field, invalid in {
        'name': 'bad name',
        'path_prefix': '/../secret',
        'backend_host': 'host;command',
        'backend_port': 70000,
        'health_path': '//bad',
    }.items():
        candidate = dict(base)
        candidate[field] = invalid
        try:
            proxy_manager.normalize_route(candidate)
        except ValueError:
            continue
        raise AssertionError(f'unsafe value for {field} was accepted')


def test_registry_round_trip_and_duplicate_protection():
    original_dir = proxy_manager._DATA_DIR
    with tempfile.TemporaryDirectory() as temp:
        proxy_manager.configure(temp)
        added = proxy_manager.add_route({
            'name': 'Immich', 'path_prefix': '/immich', 'backend_host': '192.168.1.42',
            'backend_port': 2283, 'health_path': '/', 'enabled': True,
        })
        assert proxy_manager.load_routes()[0]['id'] == added['id']
        try:
            proxy_manager.add_route({
                'name': 'Other', 'path_prefix': '/immich', 'backend_host': '192.168.1.43',
                'backend_port': 8080, 'health_path': '/', 'enabled': True,
            })
        except ValueError:
            pass
        else:
            raise AssertionError('duplicate path prefix was accepted')
        proxy_manager.add_route({
            'name': 'pve01', 'path_prefix': '/pve01', 'backend_host': '192.168.1.90',
            'backend_port': 8006, 'health_path': '/', 'route_type': 'proxmox_tls',
            'public_port': 8101, 'enabled': True,
        })
        try:
            proxy_manager.add_route({
                'name': 'pve02', 'path_prefix': '/pve02', 'backend_host': '192.168.1.56',
                'backend_port': 8006, 'health_path': '/', 'route_type': 'proxmox_tls',
                'public_port': 8101, 'enabled': True,
            })
        except ValueError:
            pass
        else:
            raise AssertionError('duplicate Proxmox TLS public port was accepted')
    proxy_manager.configure(original_dir)


if __name__ == '__main__':
    test_normalize_route()
    test_normalize_proxmox_tls_route()
    test_normalize_unraid_tls_route()
    test_rejects_unsafe_route_inputs()
    test_registry_round_trip_and_duplicate_protection()
    print('proxy manager tests: OK')
