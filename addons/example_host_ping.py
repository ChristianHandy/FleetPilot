# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
FleetPilot Example Plugin: Host Ping Button
============================================
Adds a "Ping" action button to every host card on the Hosts page.
Clicking the button pings the host's IP and shows the round-trip time.

Hooks used: host_card_action
Routes added: GET /plugins/ping?ip=<ip>

Install: Place this file in the addons/ directory and restart FleetPilot.
"""

import socket
import time
import logging

logger = logging.getLogger("fleetpilot.host_ping")


# Ports tried in order; the first one that answers decides the reported time
PROBE_PORTS = (80, 22)

# Per-attempt connection timeout in seconds
PROBE_TIMEOUT = 2.0


def probe_host(ip: str, ports=PROBE_PORTS, timeout=PROBE_TIMEOUT) -> dict:
    """
    TCP-probe a host and report what the attempt that answered took

    Two things went wrong when this was inline in the route: the timer was
    started once before the port 80 attempt, so a host without a web server
    was charged the full port 80 timeout even though SSH answered in a
    millisecond; and a refused connection was treated as no answer at all, so
    a host that is up but has neither port open was reported as "Timeout".

    A *refused* connection is an answer: the host sent an RST, so it is
    reachable and only the port is closed. Such a host is reported as up with
    ``error="port closed"``, and the probe keeps looking for an open port so
    the answer names a port something is actually listening on.

    Args:
        ip: address to probe
        ports: ports to try, in order
        timeout: connection timeout per attempt, in seconds

    Returns:
        ``{"ok", "ms", "port", "error"}``. ``ok`` says whether the host
        answered at all, ``ms`` is the round-trip time of the attempt that
        answered (``None`` when nothing did), ``port`` the port that answered
        and ``error`` one of ``None``, ``"port closed"``, ``"timeout"``,
        ``"dns"`` or ``"unreachable"``.
    """
    last_error = None
    refused = None

    for port in ports:
        start = time.monotonic()
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                pass
        except ConnectionRefusedError:
            # The host answered with an RST: reachable, nothing listening here
            if refused is None:
                refused = (port, round((time.monotonic() - start) * 1000))
            last_error = "port closed"
        except socket.timeout:
            last_error = "timeout"
        except socket.gaierror:
            last_error = "dns"
        except OSError:
            last_error = "unreachable"
        else:
            return {"ok": True, "ms": round((time.monotonic() - start) * 1000),
                    "port": port, "error": None}

    if refused is not None:
        return {"ok": True, "ms": refused[1], "port": refused[0],
                "error": "port closed"}

    return {"ok": False, "ms": None, "port": None, "error": last_error or "unreachable"}


def _ping_button(host: dict) -> str:
    """Return an HTML button that triggers a client-side ping request."""
   ip = host.get("address") 
    if not ip:
        return ""
    return f"""
<button
  class="btn btn-sm btn-secondary"
  style="font-size:0.75rem; padding:0.25rem 0.6rem"
 data-host="{ip}"
onclick="fpPing(this, this.dataset.host)"
  title="Ping {ip}">
  <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"
       viewBox="0 0 24 24" style="margin-right:4px; vertical-align:-1px">
    <circle cx="12" cy="12" r="10"/>
    <polyline points="12 8 12 12 14 14"/>
  </svg>
  Ping
</button>
<script>
/* Injected once per page by example_host_ping plugin */
if (!window._fpPingLoaded) {{
  window._fpPingLoaded = true;
  window.fpPing = function(btn, ip) {{
    btn.disabled = true;
    btn.textContent = '…';
    fetch('/plugins/ping?ip=' + encodeURIComponent(ip))
      .then(r => r.json())
      .then(d => {{
        btn.textContent = d.ok
          ? d.ms + ' ms' + (d.port ? ' (' + d.port + ')' : '')
          : (d.error || 'unreachable');
        btn.style.color = d.ok ? '#10b981' : '#ef4444';
        setTimeout(() => {{
          btn.disabled = false;
          btn.innerHTML = '<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" style="margin-right:4px;vertical-align:-1px"><circle cx="12" cy="12" r="10"/><polyline points="12 8 12 12 14 14"/></svg>Ping';
          btn.style.color = '';
        }}, 3000);
      }})
      .catch(() => {{
        btn.textContent = 'Error';
        btn.style.color = '#ef4444';
        btn.disabled = false;
      }});
  }};
}}
</script>
"""


addon_meta = {
    "name":        "Host Ping Button",
    "version":     "1.0.0",
    "author":      "FleetPilot Team",
    "description": "Adds a Ping button to every host card. Shows round-trip time via a lightweight TCP probe.",
    "scope":       "hosts",

    "host_card_action": _ping_button,
}


def register(app, core):
    """Add the /plugins/ping API endpoint."""
    from flask import Blueprint, jsonify, request, session
    from functools import wraps

    bp = Blueprint("host_ping_plugin", __name__)

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("user_id"):
                from flask import redirect, url_for
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    @bp.route("/plugins/ping")
    @login_required
    def ping():
        ip = request.args.get("ip", "").strip()
        if not ip:
            return jsonify({"ok": False, "error": "no ip"}), 400
        result = probe_host(ip)
        result["ip"] = ip
        return jsonify(result)

    app.register_blueprint(bp)
    logger.info("[host_ping] /plugins/ping route registered")
