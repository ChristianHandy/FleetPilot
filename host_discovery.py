"""Safe capability discovery for FleetPilot-managed hosts.

Discovery is deliberately passive: it checks only the configured address and a
small allow-list of management ports. It does not authenticate, guess
credentials, enumerate networks, or execute remote commands. Results help users
select the appropriate FleetPilot modules after adding a host.
"""
from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

CONNECT_TIMEOUT = 1.25
_HTTP_TIMEOUT = 2.0
_ALLOWED_PORTS = {
    'ssh': 22,
    'proxmox_api': 8006,
    'https': 443,
    'http': 80,
}


def _tcp_open(host: str, port: int, timeout: float = CONNECT_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_reachable(url: str) -> bool:
    """Return whether a management URL responds; certificate trust is not assessed.

    A self-signed certificate is common on internal Proxmox installations. This
    probe only determines reachability and never follows redirects or submits
    credentials.
    """
    try:
        request = urllib.request.Request(url, method='GET', headers={'User-Agent': 'FleetPilot-capability-check/1.3'})
        context = ssl._create_unverified_context() if url.startswith('https://') else None
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT, context=context) as response:
            return 100 <= int(getattr(response, 'status', 200)) < 600
    except (urllib.error.URLError, ValueError, OSError):
        return False


def discover_management_capabilities(host: str, ssh_port: int = 22) -> Dict[str, Any]:
    """Detect safe-to-probe management interfaces on one explicitly configured host."""
    host = str(host or '').strip()
    try:
        ssh_port = int(ssh_port or 22)
    except (TypeError, ValueError):
        ssh_port = 22
    ssh_port = ssh_port if 1 <= ssh_port <= 65535 else 22

    capabilities: List[str] = []
    suggested_modules: List[str] = []
    details: Dict[str, Any] = {
        'ssh_port': ssh_port,
        'ports': {},
    }
    if not host:
        return {
            'state': 'invalid', 'manageable': False, 'capabilities': capabilities,
            'suggested_modules': suggested_modules, 'details': details,
            'message': 'No host address was supplied.',
            'checked_at': datetime.now(timezone.utc).isoformat(),
        }

    ssh = _tcp_open(host, ssh_port)
    proxmox_port = _tcp_open(host, _ALLOWED_PORTS['proxmox_api'])
    https = _tcp_open(host, _ALLOWED_PORTS['https'])
    http = _tcp_open(host, _ALLOWED_PORTS['http'])
    details['ports'] = {'ssh': ssh, 'proxmox_api': proxmox_port, 'https': https, 'http': http}

    if ssh:
        capabilities.append('SSH management')
        suggested_modules.extend(['Update Manager', 'Hardware Overview', 'Fan & Cooling', 'Storage & Disks'])
    if proxmox_port and _http_reachable(f'https://{host}:{_ALLOWED_PORTS["proxmox_api"]}/api2/json/version'):
        capabilities.append('Proxmox VE API')
        suggested_modules.append('VM Controller')
    elif proxmox_port:
        capabilities.append('HTTPS service on port 8006')
    if https:
        capabilities.append('HTTPS service')
    elif http:
        capabilities.append('HTTP service')

    # Deduplicate while preserving the practical order shown in the UI.
    suggested_modules = list(dict.fromkeys(suggested_modules))
    manageable = bool(ssh or proxmox_port)
    if manageable:
        state = 'manageable'
        message = 'A supported management interface was found. Review the suggested modules before configuring credentials or actions.'
    elif http or https:
        state = 'web_only'
        message = 'A web service is reachable, but no FleetPilot management interface was detected.'
    else:
        state = 'unreachable'
        message = 'No supported management interface responded at the configured address.'

    return {
        'state': state,
        'manageable': manageable,
        'capabilities': capabilities,
        'suggested_modules': suggested_modules,
        'details': details,
        'message': message,
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }
