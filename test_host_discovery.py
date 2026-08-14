"""Safety and behavior checks for FleetPilot passive host capability discovery."""
import host_discovery


def test_proxmox_and_ssh_detection():
    original_tcp = host_discovery._tcp_open
    original_http = host_discovery._http_reachable
    try:
        host_discovery._tcp_open = lambda _host, port, timeout=0: port in {22, 8006}
        host_discovery._http_reachable = lambda _url: True
        result = host_discovery.discover_management_capabilities('192.168.1.52')
        assert result['state'] == 'manageable'
        assert result['manageable'] is True
        assert 'SSH management' in result['capabilities']
        assert 'Proxmox VE API' in result['capabilities']
        assert 'VM Controller' in result['suggested_modules']
    finally:
        host_discovery._tcp_open = original_tcp
        host_discovery._http_reachable = original_http


def test_web_only_detection_is_not_manageable():
    original_tcp = host_discovery._tcp_open
    original_http = host_discovery._http_reachable
    try:
        host_discovery._tcp_open = lambda _host, port, timeout=0: port == 443
        host_discovery._http_reachable = lambda _url: False
        result = host_discovery.discover_management_capabilities('nas.example')
        assert result['state'] == 'web_only'
        assert result['manageable'] is False
        assert result['suggested_modules'] == []
    finally:
        host_discovery._tcp_open = original_tcp
        host_discovery._http_reachable = original_http


def test_invalid_empty_host_is_safe():
    result = host_discovery.discover_management_capabilities('')
    assert result['state'] == 'invalid'
    assert result['manageable'] is False


def test_service_hub_template_is_present():
    with open('templates/index.html', encoding='utf-8') as handle:
        content = handle.read()
    assert 'FleetPilot Service Hub' in content
    assert 'How the proxy works' in content
    assert 'Manageable host discovery' in content
    assert '/hosts/discover_all' in content


def test_templates_compile():
    from jinja2 import Environment, FileSystemLoader
    environment = Environment(loader=FileSystemLoader('templates'))
    environment.get_template('index.html')
    environment.get_template('proxy_services.html')


if __name__ == '__main__':
    test_proxmox_and_ssh_detection()
    test_web_only_detection_is_not_manageable()
    test_invalid_empty_host_is_safe()
    test_service_hub_template_is_present()
    test_templates_compile()
    print('host discovery tests: OK')
