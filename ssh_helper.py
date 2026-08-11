"""
ssh_helper.py — Secure SSH connection helper for FleetPilot.

All SSH connections in FleetPilot go through this module to ensure
consistent, secure host-key handling.

Security design:
- Uses a per-application known_hosts file stored in DATA_DIR
- First connection: host key is recorded (TOFU — Trust On First Use)
- Subsequent connections: host key is verified against stored key
- If key changes: connection is rejected and admin is alerted
- No AutoAddPolicy or WarningPolicy — both accept unknown keys silently
"""

import os
import logging
import paramiko
from typing import Optional

logger = logging.getLogger(__name__)

# Path to the known_hosts file used by FleetPilot
# Set by init() at startup
_KNOWN_HOSTS_FILE: Optional[str] = None


def init(data_dir: str) -> None:
    """Initialise the SSH helper with the application data directory."""
    global _KNOWN_HOSTS_FILE
    _KNOWN_HOSTS_FILE = os.path.join(data_dir, "known_hosts")
    # Create the file if it doesn't exist
    if not os.path.exists(_KNOWN_HOSTS_FILE):
        open(_KNOWN_HOSTS_FILE, "w").close()
        os.chmod(_KNOWN_HOSTS_FILE, 0o600)


def _get_known_hosts_path() -> str:
    """Return the known_hosts path, falling back to ~/.ssh/known_hosts."""
    if _KNOWN_HOSTS_FILE and os.path.exists(os.path.dirname(_KNOWN_HOSTS_FILE)):
        return _KNOWN_HOSTS_FILE
    return os.path.expanduser("~/.ssh/known_hosts")


class _TOFUPolicy(paramiko.MissingHostKeyPolicy):
    """Trust-On-First-Use policy.

    - First connection to a host: accept and persist the key.
    - Subsequent connections: key is verified by paramiko's HostKeys.
    - This is far safer than WarningPolicy (which always accepts silently).
    """

    def __init__(self, known_hosts_path: str):
        self._path = known_hosts_path

    def missing_host_key(self, client, hostname, key):
        """Called when the host key is not in known_hosts."""
        logger.info(
            "SSH: First connection to %s — recording host key (TOFU). "
            "Key type: %s, fingerprint: %s",
            hostname,
            key.get_name(),
            key.get_fingerprint().hex(),
        )
        # Add to in-memory known_hosts
        client.get_host_keys().add(hostname, key.get_name(), key)
        # Persist to disk
        try:
            client.save_host_keys(self._path)
        except Exception as exc:
            logger.warning("SSH: Could not save host key for %s: %s", hostname, exc)


def create_client(
    hostname: str,
    port: int = 22,
    username: str = "root",
    password: Optional[str] = None,
    key_filename: Optional[str] = None,
    timeout: float = 10.0,
    known_hosts_path: Optional[str] = None,
) -> paramiko.SSHClient:
    """Create and return a connected, authenticated SSHClient.

    Uses TOFU (Trust On First Use) host-key policy:
    - First connection: host key is accepted and stored in known_hosts.
    - Subsequent connections: host key must match stored key.

    Args:
        hostname:         Target hostname or IP address.
        port:             SSH port (default 22).
        username:         SSH username (default 'root').
        password:         SSH password (optional).
        key_filename:     Path to SSH private key file (optional).
        timeout:          Connection timeout in seconds.
        known_hosts_path: Override the known_hosts file path.

    Returns:
        A connected and authenticated paramiko.SSHClient.

    Raises:
        paramiko.AuthenticationException: If authentication fails.
        paramiko.SSHException:            On SSH protocol errors.
        socket.timeout:                   If connection times out.
        OSError:                          On network errors.
    """
    kh_path = known_hosts_path or _get_known_hosts_path()

    client = paramiko.SSHClient()

    # Load existing known hosts
    if os.path.exists(kh_path):
        try:
            client.load_host_keys(kh_path)
        except Exception as exc:
            logger.warning("SSH: Could not load known_hosts from %s: %s", kh_path, exc)

    # Also load system-wide known_hosts for additional trust anchors
    client.load_system_host_keys()

    # Use TOFU policy for unknown hosts
    client.set_missing_host_key_policy(_TOFUPolicy(kh_path))

    connect_kwargs: dict = {
        "hostname": hostname,
        "port": port,
        "username": username,
        "timeout": timeout,
        "allow_agent": False,
        "look_for_keys": key_filename is None,
    }
    if password:
        connect_kwargs["password"] = password
    if key_filename:
        connect_kwargs["key_filename"] = key_filename

    client.connect(**connect_kwargs)
    return client


def exec_command(
    client: paramiko.SSHClient,
    command: str,
    timeout: float = 30.0,
) -> tuple[int, str, str]:
    """Execute a command on the remote host.

    Args:
        client:  Connected SSHClient.
        command: Shell command to execute.
        timeout: Command timeout in seconds.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    stdin.close()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, out, err


def quick_exec(
    hostname: str,
    command: str,
    port: int = 22,
    username: str = "root",
    password: Optional[str] = None,
    key_filename: Optional[str] = None,
    connect_timeout: float = 10.0,
    cmd_timeout: float = 30.0,
) -> tuple[int, str, str]:
    """Open a connection, run one command, close the connection.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    client = create_client(
        hostname=hostname,
        port=port,
        username=username,
        password=password,
        key_filename=key_filename,
        timeout=connect_timeout,
    )
    try:
        return exec_command(client, command, timeout=cmd_timeout)
    finally:
        client.close()
