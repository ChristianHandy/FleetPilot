"""
safe_errors.py — turn exceptions into messages that are safe to show in the browser.

Exception text can contain file paths, host names, URLs with credentials or
library internals. It is written to the server log; callers get a short,
fixed message that only depends on the kind of error.
"""
import logging
import socket

logger = logging.getLogger('fleetpilot')

try:
    import requests as _requests
    _TIMEOUTS = (TimeoutError, socket.timeout, _requests.Timeout)
    _UNREACHABLE = (ConnectionError, _requests.ConnectionError, OSError)
except ImportError:  # pragma: no cover
    _TIMEOUTS = (TimeoutError, socket.timeout)
    _UNREACHABLE = (ConnectionError, OSError)

try:
    import paramiko as _paramiko
    _AUTH = (_paramiko.AuthenticationException,)
except ImportError:  # pragma: no cover
    _AUTH = ()


class AuthenticationError(Exception):
    """A device or service rejected the user name, password, key or token."""


def public_error(exc, action='The request'):
    """Log ``exc`` and return a message for users that reveals no internals."""
    logger.warning('%s failed: %s: %s', action, type(exc).__name__, exc)
    if isinstance(exc, AuthenticationError) or (_AUTH and isinstance(exc, _AUTH)):
        return f'{action} failed: the user name or password was rejected.'
    if isinstance(exc, _TIMEOUTS):
        return f'{action} timed out.'
    if isinstance(exc, PermissionError):
        return f'{action} failed: permission denied.'
    if isinstance(exc, _UNREACHABLE):
        return f'{action} failed: the device could not be reached.'
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return f'{action} failed: invalid input or response.'
    return f'{action} failed. Details are in the FleetPilot log.'
