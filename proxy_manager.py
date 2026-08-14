"""FleetPilot-managed reverse-proxy route registry.

Only administrators can manage the registry through FleetPilot.  The service
account stores route data in the persistent data directory, while a separate
root-owned helper validates and renders the final HAProxy configuration.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

_DATA_DIR = Path(os.environ.get("FLEETPILOT_DATA_DIR", Path(__file__).parent / "data"))
ROUTES_FILE = _DATA_DIR / "proxy_routes.json"
HELPER = "/usr/local/lib/fleetpilot/proxy-apply"

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,47}$")
_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9][A-Za-z0-9-]*$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._~/%-]*$")
_ROUTE_TYPES = {'http_path', 'proxmox_tls'}
_RESERVED_PUBLIC_PORTS = {80, 443, 8080, 8404}


def configure(data_dir: str | Path) -> None:
    global _DATA_DIR, ROUTES_FILE
    _DATA_DIR = Path(data_dir)
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    ROUTES_FILE = _DATA_DIR / "proxy_routes.json"


def _valid_host(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(_HOST_RE.fullmatch(value)) and ".." not in value and not value.endswith(".")


def _valid_path(value: str, *, allow_root: bool = False) -> bool:
    return bool(_PATH_RE.fullmatch(value)) and (allow_root or value != "/") and "//" not in value and ".." not in value


def normalize_route(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a user-supplied route and return only safe configuration fields."""
    name = str(payload.get("name", "")).strip()
    prefix = str(payload.get("path_prefix", "")).strip().rstrip("/") or "/"
    host = str(payload.get("backend_host", "")).strip().lower()
    health_path = str(payload.get("health_path", "/")).strip() or "/"
    route_type = str(payload.get('route_type', 'http_path')).strip().lower() or 'http_path'
    try:
        port = int(payload.get("backend_port", 0))
    except (TypeError, ValueError) as error:
        raise ValueError("Backend port must be a number.") from error

    try:
        public_port = int(payload.get('public_port', 0) or 0)
    except (TypeError, ValueError) as error:
        raise ValueError('Public port must be a number.') from error

    if route_type not in _ROUTE_TYPES:
        raise ValueError('Unsupported route type.')
    if not _NAME_RE.fullmatch(name):
        raise ValueError("Service name must start with a letter and use only letters, numbers, hyphens, or underscores.")
    if not _valid_path(prefix):
        raise ValueError("Path prefix must be an absolute path such as /immich and must not contain traversal or duplicate slashes.")
    if prefix in {"/healthz", "/proxy"}:
        raise ValueError("This path prefix is reserved by FleetPilot.")
    if not _valid_host(host):
        raise ValueError("Backend host must be a valid IPv4, IPv6, or DNS host name.")
    if not 1 <= port <= 65535:
        raise ValueError("Backend port must be between 1 and 65535.")
    if not _valid_path(health_path, allow_root=True):
        raise ValueError("Health path must be an absolute, safe path.")
    if route_type == 'proxmox_tls':
        if port != 8006:
            raise ValueError('A Proxmox TLS route must use the standard Proxmox HTTPS port 8006.')
        if not 1024 <= public_port <= 65535 or public_port in _RESERVED_PUBLIC_PORTS:
            raise ValueError('Choose a dedicated unprivileged public port that is not reserved by FleetPilot.')
    else:
        public_port = 0

    return {
        "id": str(payload.get("id") or uuid.uuid4().hex[:12]),
        "name": name,
        "path_prefix": prefix,
        "backend_host": host,
        "backend_port": port,
        "health_path": health_path,
        "route_type": route_type,
        "public_port": public_port,
        "enabled": bool(payload.get("enabled", True)),
    }


def load_routes() -> list[dict[str, Any]]:
    if not ROUTES_FILE.exists():
        return []
    try:
        raw = json.loads(ROUTES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Unable to read proxy route registry: {error}") from error
    if not isinstance(raw, list):
        raise RuntimeError("Proxy route registry is invalid.")
    routes: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise RuntimeError("Proxy route registry contains an invalid entry.")
        routes.append(normalize_route(entry))
    return sorted(routes, key=lambda item: (-len(item["path_prefix"]), item["name"].lower()))


def save_routes(routes: list[dict[str, Any]]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    normalized = [normalize_route(route) for route in routes]
    names = [item["name"].lower() for item in normalized]
    prefixes = [item["path_prefix"] for item in normalized if item['route_type'] == 'http_path']
    public_ports = [item['public_port'] for item in normalized if item['route_type'] == 'proxmox_tls']
    if len(names) != len(set(names)):
        raise ValueError("Each proxy service needs a unique name.")
    if len(prefixes) != len(set(prefixes)):
        raise ValueError("Each HTTP proxy service needs a unique path prefix.")
    if len(public_ports) != len(set(public_ports)):
        raise ValueError('Each Proxmox TLS route needs a unique public port.')
    fd, temporary = tempfile.mkstemp(prefix="proxy_routes.", suffix=".json", dir=_DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o640)
        os.replace(temporary, ROUTES_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def add_route(payload: dict[str, Any]) -> dict[str, Any]:
    route = normalize_route(payload)
    routes = load_routes()
    save_routes([*routes, route])
    return route


def remove_route(route_id: str) -> dict[str, Any]:
    routes = load_routes()
    removed = next((item for item in routes if item["id"] == route_id), None)
    if removed is None:
        raise ValueError("Proxy route was not found.")
    save_routes([item for item in routes if item["id"] != route_id])
    return removed


def restore_routes(routes: list[dict[str, Any]]) -> None:
    save_routes(routes)


def apply() -> tuple[bool, str]:
    """Ask the fixed root-owned helper to validate, render and reload HAProxy."""
    try:
        result = subprocess.run(
            ["sudo", "-n", HELPER, "apply"],
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"Unable to apply HAProxy configuration: {error}"
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part).strip()
    return result.returncode == 0, output or "HAProxy configuration applied."


def status() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["sudo", "-n", HELPER, "status"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"Unable to obtain HAProxy status: {error}"
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part).strip()
    return result.returncode == 0, output or "No status returned."


def test_route(route: dict[str, Any]) -> tuple[bool, str]:
    scheme = 'https' if route.get('route_type') == 'proxmox_tls' else 'http'
    url = f"{scheme}://{route['backend_host']}:{route['backend_port']}{route['health_path']}"
    try:
        result = subprocess.run(
            ["curl", "-k", "-fsS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "8", url],
            capture_output=True,
            text=True,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"Health check failed: {error}"
    code = result.stdout.strip() or "unreachable"
    return result.returncode == 0, f"{url} returned {code}."
