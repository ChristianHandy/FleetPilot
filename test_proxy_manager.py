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
    proxy_manager.configure(original_dir)


if __name__ == '__main__':
    test_normalize_route()
    test_rejects_unsafe_route_inputs()
    test_registry_round_trip_and_duplicate_protection()
    print('proxy manager tests: OK')
