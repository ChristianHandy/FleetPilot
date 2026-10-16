# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
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
import re
import time
import paramiko
from typing import Optional

logger = logging.getLogger(__name__)

# Path to the known_hosts file used by FleetPilot
# Set by init() at startup
_KNOWN_HOSTS_FILE: Optional[str] = None


def _sanitize_for_log(value: object) -> str:
    """Return a single-line representation safe for plain-text logs."""
    return str(value).replace("\r", "").replace("\n", "")


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


def strict_host_keys() -> bool:
    """True when unknown SSH host keys must be rejected instead of trusted on first use."""
    return os.environ.get("FLEETPILOT_SSH_STRICT_HOST_KEYS", "").strip().lower() in ("1", "true", "yes", "on")


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


HANDSHAKE_RETRY_DELAY = 3


def _new_client(kh_path: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()

    # Load existing known hosts
    if os.path.exists(kh_path):
        try:
            client.load_host_keys(kh_path)
        except Exception as exc:
            logger.warning("SSH: Could not load known_hosts from %s: %s", kh_path, exc)

    # Also load system-wide known_hosts for additional trust anchors
    client.load_system_host_keys()

    # Unknown hosts: trust on first use, or refuse them in strict mode
    # (FLEETPILOT_SSH_STRICT_HOST_KEYS=true; host keys must be added to known_hosts in advance).
    if strict_host_keys():
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(_TOFUPolicy(kh_path))
    return client


def create_client(
    hostname: str,
    port: int = 22,
    username: str = "root",
    password: Optional[str] = None,
    key_filename: Optional[str] = None,
    timeout: float = 10.0,
    known_hosts_path: Optional[str] = None,
    allow_agent: bool = False,
    look_for_keys: Optional[bool] = None,
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
        allow_agent:      Whether to allow the local SSH agent (disabled by default).
        look_for_keys:    Whether to search default private keys. If omitted,
                          enabled only when no explicit key file is supplied.

    Returns:
        A connected and authenticated paramiko.SSHClient.

    Raises:
        paramiko.AuthenticationException: If authentication fails.
        paramiko.SSHException:            On SSH protocol errors.
        socket.timeout:                   If connection times out.
        OSError:                          On network errors.
    """
    kh_path = known_hosts_path or _get_known_hosts_path()

    client = _new_client(kh_path)

    connect_kwargs: dict = {
        "hostname": hostname,
        "port": port,
        "username": username,
        "timeout": timeout,
        # paramiko waits only 15 s for the server's banner by default; a busy Windows sshd can take longer.
        "banner_timeout": max(timeout, 15),
        "auth_timeout": max(timeout, 30),
        "allow_agent": bool(allow_agent),
        "look_for_keys": (key_filename is None) if look_for_keys is None else bool(look_for_keys),
    }
    if password:
        connect_kwargs["password"] = password
    if key_filename:
        connect_kwargs["key_filename"] = key_filename

    try:
        client.connect(**connect_kwargs)
    except (paramiko.AuthenticationException, paramiko.BadHostKeyException):
        raise
    except (EOFError, paramiko.SSHException) as exc:
        # A busy server (Windows' sshd while installing updates) drops or garbles a handshake now and
        # then; one more try fixes that. Unreachable hosts (OSError, timeouts) are not retried.
        logger.info(
            "SSH: handshake with %s failed (%s), retrying once",
            _sanitize_for_log(hostname),
            exc or type(exc).__name__,
        )
        client.close()
        time.sleep(HANDSHAKE_RETRY_DELAY)
        client = _new_client(kh_path)
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


# Terminal control sequences that package managers write to a pty: colours (zypper, pacman), cursor moves,
# and OSC sequences such as systemd's OSC 3008 context markers that sudo emits since systemd 257.
_TERMINAL_CODES = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-Z\\-_]')


def plain_text(line: str) -> str:
    """``line`` without terminal control sequences; of a line redrawn with carriage returns, its final state."""
    line = _TERMINAL_CODES.sub('', line.rstrip('\r\n'))
    return line.rsplit('\r', 1)[-1]


def output_lines(stdout):
    """Yield an SSH command's output line by line as plain text, decoded leniently (one stray byte must not end
    an update)."""
    raw = stdout.channel.makefile('rb')
    for line in iter(raw.readline, b''):
        yield plain_text(line.decode('utf-8', errors='replace')) + '\n'
