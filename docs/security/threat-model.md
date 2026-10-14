# Threat model and security assessment

FleetPilot holds SSH access and credentials for every machine and appliance it manages. Whoever controls FleetPilot controls the homelab, so it is the most valuable target in it. This assessment follows the architecture in [../architecture.md](../architecture.md). It is reviewed with every release that changes an attack surface (authentication, installers, root helpers, new device types, release pipeline).

Last review: October 2026 (v1.7.x).

## Assets

1. SSH private key and stored device credentials (root access to the fleet)
2. Admin accounts and sessions
3. The FleetPilot server itself (root via the root helpers)
4. Integrity of what FleetPilot shows (disk alerts, vulnerabilities, update results)
5. The software supply chain (code, dependencies, releases, installers)

## Attack surface

| Entry point | Exposure | Who can reach it |
|---|---|---|
| Web interface and `/api/` (HTTPS 443) | Usually LAN only; sometimes published through a reverse proxy | Anyone on the network before sign-in; users after |
| `/metrics`, CheckMK endpoint | Token-protected | Monitoring systems |
| Public status page | Optional, unauthenticated, read-only | Anyone it is published to |
| Output of managed devices (SSH, TR-064 SOAP/XML, JSON APIs) | Parsed by FleetPilot | A compromised or hostile device on the LAN |
| Uploads (host images, SMART imports, backup restores) | Admin or operator only | Signed-in users |
| Plugins / add-ons | Run in-process | Admins who install them |
| Installers (`curl \| bash`), updates, dependencies | Run as root once, then on update | The supply chain |

## Threats and mitigations (STRIDE)

| Threat | Example | Mitigations |
|---|---|---|
| **Spoofing** a user | Password guessing, stolen session | scrypt hashes, sign-in throttling and lockout, 2FA (TOTP, passkeys, YubiKey), admin 2FA can be required, server-side sessions ending on idle/password change, re-authentication for sensitive actions, optional network allowlist |
| **Spoofing** a device | Man in the middle on SSH | Host keys trusted on first use and pinned afterwards; strict mode refuses unknown keys |
| **Tampering** with requests | CSRF, clickjacking, XSS | CSRF tokens, SameSite cookies, CSP without `unsafe-eval`, `frame-ancestors 'none'`, autoescaped templates, CodeQL on every change |
| **Tampering** via device output | Malicious XML/JSON/command output from a compromised router or host | Bounded parsers, XML without DTDs, values validated before use in commands or paths, parsers fuzzed in CI |
| **Tampering** with the server | Command injection into root actions | Root helpers with fixed arguments and allowlists, no shell strings from input, read-only code directory |
| **Repudiation** | An admin denies a change | HMAC-chained audit trail of sign-ins and state-changing requests, SIEM export |
| **Information disclosure** | Leaking credentials or internal addresses | Credentials encrypted at rest and never shown again, generic error messages, public status page without private addresses, SSRF guards (API paths only from names the device reported) |
| **Denial of service** | Slow or huge device answers, request floods | Timeouts and size limits on device answers, fuzzing with time limits, sign-in rate limits |
| **Elevation of privilege** | Viewer acts as admin; app user becomes root | Role checks on every route (tested), one narrow sudo rule for the helpers, systemd hardening (`ProtectSystem`, `ProtectHome`, limited writable paths; the strict profile adds `NoNewPrivileges`) |
| **Supply chain** | Malicious dependency or tampered release | Hash-locked dependencies, dependency review and pip-audit block known-vulnerable or malicious packages, 7-day update cooldown, actions pinned to commits, signed tags, Sigstore build provenance, branch protection |

## Most likely and most impactful problems

| Risk | Likelihood | Impact | Status |
|---|---|---|---|
| FleetPilot exposed to the internet without 2FA | Medium | Critical | Security center flags missing 2FA and HTTP; docs recommend LAN or VPN only |
| A compromised managed host attacks FleetPilot through its output | Low | High | Parsers validated and fuzzed; output never reaches a shell |
| Stolen `SECRET_KEY` and data directory | Low | Critical | Data directory 0750 owned by the service user; backups written 0600; device credentials encrypted at rest |
| Vulnerable dependency | Medium | Medium–High | pip-audit and dependency review on every change, Dependabot security updates |
| Malicious plugin | Low | Critical | Plugins are admin-only and documented as trusted code |

## Residual risks

- Plugins run with FleetPilot's privileges; only install plugins you trust.
- Trust on first use accepts the first host key; use strict host keys where this matters.
- Single maintainer: no second human review of changes (see [GOVERNANCE.md](../../GOVERNANCE.md)).

## How to report

See [SECURITY.md](../../SECURITY.md).
