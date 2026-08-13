"""Runtime hardening helpers for FleetPilot's single-site production profile."""
from __future__ import annotations

import os
from datetime import timedelta
from typing import Any
from werkzeug.middleware.proxy_fix import ProxyFix


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configure_app(app: Any) -> dict[str, Any]:
    """Apply environment-controlled production defaults without storing secrets.

    `FLEETPILOT_TRUST_PROXY` must be enabled only when Nginx/HAProxy is the
    trusted, local reverse proxy in front of FleetPilot.  It is deliberately
    disabled by default to prevent client-controlled forwarding headers.
    """
    production = _flag("FLEETPILOT_PRODUCTION", False)
    trust_proxy = _flag("FLEETPILOT_TRUST_PROXY", False)
    cookie_secure = _flag("FLEETPILOT_COOKIE_SECURE", False)
    session_minutes = max(15, min(int(os.environ.get("FLEETPILOT_SESSION_MINUTES", "480")), 1440))

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cookie_secure,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=session_minutes),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        PREFERRED_URL_SCHEME="https" if cookie_secure else "http",
    )
    if trust_proxy:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    return {
        "production": production,
        "trust_proxy": trust_proxy,
        "cookie_secure": cookie_secure,
        "session_minutes": session_minutes,
        "secret_key_configured": bool(os.environ.get("SECRET_KEY")),
        "csrf_enabled": _flag("WTF_CSRF_ENABLED", False),
    }
