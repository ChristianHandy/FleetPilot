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
