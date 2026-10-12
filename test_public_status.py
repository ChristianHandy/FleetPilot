from jinja2 import Environment, FileSystemLoader


def test_public_status_template_is_read_only_and_hides_private_backend_addresses():
    environment = Environment(loader=FileSystemLoader('templates'))
    template = environment.get_template('public_status.html')
    rendered = template.render(
        generated_at='2026-08-14 12:00:00',
        services=[{
            'name': 'pve01', 'url': 'https://192.168.1.100:8101/',
            'kind': 'Proxmox console', 'status': 'healthy', 'detail': 'Reachable',
        }],
        hosts=[{'name': 'pve01', 'role': 'Proxmox host', 'status': 'available'}],
    )
    assert 'Service Status' in rendered
    assert '192.168.1.100:8101' in rendered
    assert '192.168.1.90' not in rendered
    assert 'Proxmox root' not in rendered
    assert 'management actions' in rendered


if __name__ == '__main__':
    test_public_status_template_is_read_only_and_hides_private_backend_addresses()
    print('public status tests: OK')


def test_service_map_uses_the_address_the_visitor_opened():
    """It used to show a hard-coded 192.168.1.100 on every installation."""
    import app as fp
    route = {"name": "pve01", "path_prefix": "/pve01", "backend_host": "192.0.2.10", "backend_port": 8006,
             "route_type": "proxmox_tls", "public_port": 8101, "enabled": False}
    with fp.app.test_request_context("/", base_url="https://fleetpilot.example:443"):
        services = fp._build_service_map({}, [route])
    assert services[0]["public_url"] == "https://fleetpilot.example/"
    assert services[1]["public_url"] == "https://fleetpilot.example:8101/"
    assert "192.168.1.100" not in str(services)
