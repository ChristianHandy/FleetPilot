# Security Policy

## Reporting a Vulnerability

The security of FleetPilot and the systems it manages is taken seriously. If you discover a vulnerability, please follow responsible disclosure practices.

**Do not open a public GitHub issue for security reports.** Public disclosure before a fix is available puts all users at risk.

Instead, please report vulnerabilities through one of the following channels:

- **GitHub Private Vulnerability Reporting** — use the [Security tab](../../security/advisories/new) of this repository to submit a private advisory directly to the maintainers.
- **Email** — contact the maintainers directly if a private advisory is not suitable for your report.

A useful report should include the following information:

| Field | Description |
|---|---|
| **Description** | A clear summary of the vulnerability and the affected component |
| **Steps to Reproduce** | A minimal, reliable reproduction path |
| **Impact** | What an attacker could achieve by exploiting this issue |
| **Suggested Fix** | Optional, but appreciated if you have a recommendation |

We aim to acknowledge all security reports within **48 hours** and to release a fix or mitigation for critical issues as quickly as possible. You will be credited in the release notes unless you prefer to remain anonymous.

---

## Supported Versions

FleetPilot follows a rolling release model. Security fixes are applied exclusively to the latest version. We strongly recommend always running the most recent commit from the `main` branch.

| Version | Security Updates |
|---|---|
| Latest (`main`) | :white_check_mark: Supported |
| Any prior release | :x: Not supported |

---

## Security Architecture

FleetPilot implements the following security controls by default:

| Control | Implementation |
|---|---|
| **No hardcoded credentials** | All secrets are loaded from environment variables at runtime |
| **Password hashing** | User passwords are hashed using `werkzeug.security` (PBKDF2-HMAC-SHA256) |
| **Secure session keys** | `SECRET_KEY` is generated via `secrets.token_hex(32)` if not explicitly set |
| **SQL injection prevention** | All database queries use parameterized execution |
| **Command injection prevention** | Device names, plugin identifiers, and filesystem types are strictly validated against allowlists before being passed to system commands |
| **Secure file transfer** | SSH key installation uses SFTP rather than shell execution |
| **Template injection protection** | Plugin names are validated (alphanumeric and underscores only) before template rendering |
| **Security headers** | Content-Security-Policy without `unsafe-eval` and with `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff`, `Cross-Origin-Opener-Policy`, `Strict-Transport-Security` on HTTPS |
| **Server-side sessions** | Each sign-in has a server record; sessions can be listed and ended per device, end after an idle timeout, and end when the password changes or the account is disabled |
| **Password confirmation** | User management, backups, API token creation and security settings ask for the password again after a configurable time |
| **Two-factor sign-in** | TOTP, YubiKey OTP and WebAuthn security keys; admins can be required to use 2FA |
| **API tokens** | Per-user, hashed, expiring, read-only or read/write; accepted only on `/api/` and never turned into browser sessions |
| **Login throttling** | Per-address and per-account limits; lockouts are audited and can be pushed to a notification channel |
| **Network allowlist** | Optional list of allowed networks; FleetPilot refuses a list that would lock out the admin saving it |
| **Audit trail** | Sign-ins and state-changing requests, filterable and exportable as CSV (formula-safe), with a retention period |
| **Debug mode off by default** | Flask debug mode is disabled unless `FLASK_DEBUG=true` is explicitly set |

---

## Deployment Hardening Guide

The controls listed above protect the application itself. The following steps are your responsibility as the operator and are **required before any production deployment**.

### 1. Set Secure Environment Variables

Never rely on default credentials. Configure the following variables in a `.env` file with restricted permissions:

```bash
# Restrict file permissions immediately
chmod 600 .env
```

```bash
# Generate a cryptographically secure session key
export SECRET_KEY=$(openssl rand -hex 32)

# Set a strong, unique admin username and password
export DASHBOARD_USERNAME=your_admin_username
export DASHBOARD_PASSWORD=your_strong_password

# Ensure debug mode is explicitly disabled
export FLASK_DEBUG=false
```

| Variable | Requirement | Notes |
|---|---|---|
| `SECRET_KEY` | **Required** | Must be at least 32 random bytes. Changing this invalidates all active sessions. |
| `DASHBOARD_USERNAME` | **Required** | Change from the default `admin`. |
| `DASHBOARD_PASSWORD` | **Required** | Use a strong, unique password. |
| `FLASK_DEBUG` | **Required** | Must be `false` in production. Debug mode exposes source code and an interactive console. |

### 2. Enforce HTTPS/TLS

**Never expose FleetPilot over plain HTTP.** Without TLS, session cookies, login credentials, and SSH passwords entered through the UI are transmitted in clear text and are trivially interceptable.

Deploy FleetPilot behind a TLS-terminating reverse proxy such as **Nginx**, **Caddy**, or **Traefik**. Caddy is recommended for automatic certificate management via Let's Encrypt:

```
fleetpilot.internal {
    reverse_proxy 127.0.0.1:5000
}
```

Additionally, set the following Flask configuration to enforce secure cookies over HTTPS:

```bash
export SESSION_COOKIE_SECURE=true
export SESSION_COOKIE_HTTPONLY=true
export SESSION_COOKIE_SAMESITE=Lax
```

### 3. Isolate Network Access

FleetPilot is an administrative tool and must not be reachable from the public internet. Restrict access at the network level:

- Bind the application to `127.0.0.1` only and let the reverse proxy handle external connections.
- Require a **VPN connection** (e.g., WireGuard, Tailscale) to reach the management interface.
- Use firewall rules (`ufw`, `iptables`, or a network-level ACL) to allow access only from trusted management hosts or subnets.

FleetPilot can also enforce this itself: **System → Security center → Allowed networks** accepts addresses and CIDR
ranges. The server itself and the public status page are always reachable. Behind a reverse proxy, set
`FLEETPILOT_TRUST_PROXY=true` so FleetPilot sees real client addresses.

### 4. Use a Production WSGI Server

Flask's built-in development server is single-threaded, not hardened, and not suitable for production. Use **Gunicorn** or **uWSGI** instead:

```bash
gunicorn --bind 127.0.0.1:5000 --workers 4 --timeout 120 app:app
```

For a persistent deployment, manage the process with `systemd` or a container runtime.

### 5. Manage Root Privileges Carefully

Disk management features require `sudo` or `root` access, which significantly expands the blast radius of any vulnerability. Mitigate this risk by:

- Running FleetPilot on a **dedicated, isolated management node** — not on a general-purpose server.
- Configuring `/etc/sudoers` to grant passwordless execution only for the specific utilities required (e.g., `smartctl`, `mkfs.*`, `wipefs`, `badblocks`), rather than granting unrestricted `sudo` access.
- Running the application inside a **VM or container** to limit the impact of a potential compromise.

### 6. Harden SSH Connectivity

By default, the SSH client uses `AutoAddPolicy`, which accepts any host key on first connection. This is acceptable for initial setup but is vulnerable to Man-in-the-Middle (MitM) attacks in a production environment.

To harden SSH connectivity:
- Pre-populate the `~/.ssh/known_hosts` file on the FleetPilot server by connecting to each managed host manually once.
- Change `AutoAddPolicy` to `paramiko.WarningPolicy` or `paramiko.RejectPolicy` in the SSH client configuration within `app.py`.
- Protect the `~/.ssh/` directory on the FleetPilot server with strict permissions (`chmod 700 ~/.ssh`).

---

## Known Limitations

The following security gaps are acknowledged. Contributions to address them are welcome.

| Limitation | Risk | Recommended Mitigation |
|---|---|---|
| **SSH `AutoAddPolicy`** | Vulnerable to MitM attacks on first connection | Pre-populate `known_hosts` and switch to `RejectPolicy` (see above) |
| **Inline scripts in templates** | The CSP must allow `'unsafe-inline'` scripts, so it limits but does not stop injected scripts | Templates escape all remote data; moving scripts to files would allow a nonce-based CSP |
| **In-memory login throttling** | Counters reset when FleetPilot restarts and are per worker | Also rate-limit at the reverse proxy, or use fail2ban on the audit log |
| **Session cookie flags** | Cookies lack `Secure` flag on plain HTTP | Run behind HTTPS; the Security center flags plain HTTP |

---

## Production Readiness Checklist

Before going live, verify each of the following:

- [ ] `SECRET_KEY` is a random value of at least 32 bytes and is not committed to version control
- [ ] `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` have been changed from their defaults
- [ ] `FLASK_DEBUG` is set to `false`
- [ ] `.env` file permissions are set to `600`
- [ ] HTTPS/TLS is enforced via a reverse proxy
- [ ] `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, and `SESSION_COOKIE_SAMESITE` are configured
- [ ] The application port is not directly reachable from untrusted networks
- [ ] VPN or network-level access control is in place
- [ ] A production WSGI server (Gunicorn / uWSGI) is used
- [ ] `sudo` access is scoped to specific disk utilities only
- [ ] SSH `known_hosts` is pre-populated for all managed hosts
- [ ] Dependency updates are scheduled regularly
- [ ] Backups of `hosts.json`, `users.db`, and `update_settings.json` are configured
- [ ] Monitoring and alerting are configured for the host system
- [ ] **System → Security center** shows no red checks
- [ ] Every administrator uses two-factor sign-in, and "Require 2FA for administrators" is on
- [ ] A notification channel receives security events (lockouts, new admins)

---

## Dependency Security

FleetPilot depends on several third-party libraries. Monitor the following security advisory feeds to stay informed of upstream vulnerabilities:

- **Flask** — [github.com/pallets/flask/security](https://github.com/pallets/flask/security)
- **Paramiko** — [github.com/paramiko/paramiko/security](https://github.com/paramiko/paramiko/security)
- **APScheduler** — [github.com/agronholm/apscheduler/security](https://github.com/agronholm/apscheduler/security)
- **Werkzeug** — [github.com/pallets/werkzeug/security](https://github.com/pallets/werkzeug/security)

To update all dependencies:

```bash
pip install --upgrade -r requirements.txt
```

Consider pinning dependency versions in `requirements.txt` and enabling [Dependabot](https://docs.github.com/en/code-security/dependabot) to receive automated pull requests for security updates.

---

## Disclaimer

FleetPilot requires elevated system privileges for disk management operations. This inherently carries risk. The software is provided for use in **trusted, isolated environments only**. The maintainers accept no liability for damage, data loss, or security incidents resulting from its deployment or misuse.
