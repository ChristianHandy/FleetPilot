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

FleetPilot follows a rolling model: each release is supported **until the next release is published**. Security fixes go into `main` and ship in a new release, usually within days for high and critical issues. Releases are not backported.

| Version | Security Updates |
|---|---|
| Latest release and `main` | :white_check_mark: Supported |
| Any earlier release | :x: Ends on the day the next release is published; update with the installer or the Proxmox helper |

The release notes say when a release fixes a security problem, so you can decide how urgently to update.

---

## Verifying a Release

Each release (from v1.7.1 on) carries the source archive, a CycloneDX SBOM, `SHA256SUMS`, and SLSA build provenance signed through Sigstore. **Integrity and authenticity:** check that the files match and were built by this repository's release workflow from its tag:

```bash
sha256sum -c SHA256SUMS
gh attestation verify fleetpilot-X.Y.Z.tar.gz --repo ChristianHandy/FleetPilot \
  --signer-workflow ChristianHandy/FleetPilot/.github/workflows/release.yml
```

**Expected identity:** the provenance must be signed by the workflow `.github/workflows/release.yml` of `ChristianHandy/FleetPilot`, running for a `refs/tags/vX.Y.Z` tag (`gh attestation verify` prints both). Nobody holds a private key for this signature; it comes from GitHub's OIDC identity of that workflow run.

Release tags are signed by the maintainer's OpenPGP key:

```text
09D7 7410 5F9A A1DE 6B12  6AD1 F73D EF20 4C54 E71D   ChristianHandy <christianhandy180@gmail.com>
```

```bash
gpg --import docs/security/release-signing-key.asc
git tag -v vX.Y.Z
```

Older releases that carry a `SHA256SUMS.asc` are signed with the same key (`gpg --verify SHA256SUMS.asc SHA256SUMS`). The measures that protect the code, the build and the releases are listed under [Security and supply chain](README.md#security-and-supply-chain).

---

## Secrets and Credentials Policy

**Project secrets** (GitHub account, repository secrets, the release signing key):

- Held only by the people listed in [GOVERNANCE.md](GOVERNANCE.md); GitHub accounts with access use two-factor authentication.
- The signing key lives in the maintainer's GPG keyring with a passphrase and expires every two years (renewed before it expires).
- Releases need no stored secret: provenance is signed keylessly through OIDC.
- Repository secrets (only the optional read-only `SCORECARD_TOKEN`) are fine-grained, least-privilege, expire within a year and are rotated when they expire or someone leaves.
- Workflows get no write permissions by default; secrets are never printed or passed to pull requests from forks.
- Secret scanning with push protection blocks committed credentials. A leaked credential is revoked first, then removed from history.

**Secrets of a FleetPilot installation:**

- `SECRET_KEY` and the generated passwords are created with a CSPRNG and stored in files readable only by the service user.
- Device credentials are encrypted at rest; the SSH key is created per installation.
- Rotation: change `SECRET_KEY` (this signs everyone out and needs stored device credentials re-entered), regenerate the SSH key from Hosts, and rotate API tokens through their expiry.

---

## Design and Threat Model

- [docs/architecture.md](docs/architecture.md): components, actors and actions, trust boundaries
- [docs/security/threat-model.md](docs/security/threat-model.md): security assessment, attack surface, threats and mitigations
- [docs/dependencies.md](docs/dependencies.md): how dependencies are chosen, locked and tracked; SCA and VEX policy

---

## Security Architecture

FleetPilot implements the following security controls by default:

| Control | Implementation |
|---|---|
| **No hardcoded credentials** | All secrets are loaded from environment variables at runtime |
| **Password hashing** | User passwords are hashed with salted scrypt (`werkzeug.security`); with `FLEETPILOT_FIPS=true`, PBKDF2-HMAC-SHA256 with 600,000 iterations |
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

## High-security deployment

For government, defence, finance, healthcare and other regulated sites. These
settings map to NIST SP 800-53 / 800-63B, BSI IT-Grundschutz and TR-02102,
DISA STIG and FIPS 140-3. FleetPilot itself is not certified; an accredited
assessment of the complete installation is still required.

1. **Sandbox the service:** install `deploy/fleetpilot-strict.conf` as
   `/etc/systemd/system/fleetpilot.service.d/strict.conf`. It removes sudo
   (local disk formatting and local fan control are then unavailable),
   enables a system-call filter and restricts network targets to private
   ranges. `systemd-analyze security fleetpilot` drops from 5.8 to 1.2.
2. **TLS:** use `deploy/nginx-fleetpilot-tls.conf` (TLS 1.2/1.3, forward-secret
   AEAD suites, HSTS) with a certificate from your internal CA.
3. **Environment** (`/opt/fleetpilot/.env`):
   `FLEETPILOT_FIPS=true` on FIPS-enabled systems, `FLEETPILOT_SSH_STRICT_HOST_KEYS=true`
   after loading all managed hosts into `known_hosts`, `FLEETPILOT_OFFLINE=true`
   in air-gapped networks. No page loads anything from third parties; fonts,
   Bootstrap and Chart.js are served by FleetPilot.
4. **System → Security center:** require 2FA for administrators, add the
   system-use notice, set lockout to 3 attempts / 15 minutes, idle timeout
   15 minutes, session lifetime 12 hours, allowed networks, and keep audit
   events for your retention period.
5. **Audit forwarding:** every audit event is also logged as JSON by the
   `fleetpilot.audit` logger (journald). Forward the journal to your SIEM so
   records exist outside FleetPilot. The audit trail inside FleetPilot is
   HMAC-chained; the Security center reports any changed or removed event.

| Control | Where |
|---|---|
| Identification & MFA (IA-2, 800-63B AAL2) | TOTP, WebAuthn/FIDO2, YubiKey; required for admins |
| Re-authentication (IA-11) | Password confirmation for user, backup, token, 2FA and security changes |
| Account lockout (AC-7) | Security center → lockout attempts / minutes |
| System use notification (AC-8) | Security center → notice before sign-in |
| Session termination (AC-12) | Idle timeout, absolute lifetime, per-device sign-out |
| Least privilege (AC-6) | Viewer / operator / admin roles; read-only API tokens |
| Audit (AU-2, AU-3, AU-9) | Audit trail with HMAC chain, CSV export, journald/SIEM output |
| Boundary protection (SC-7) | Allowed networks, strict systemd profile, offline mode |
| Transmission confidentiality (SC-8) | TLS reference config, HSTS, secure cookies |
| Cryptography (SC-13) | FIPS mode, AES/HMAC-SHA256 for stored secrets, HMAC-SHA256 session cookies |
| Flaw remediation (SI-2) | Dependabot, pip-audit, CodeQL, OpenSSF Scorecard in CI |

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
