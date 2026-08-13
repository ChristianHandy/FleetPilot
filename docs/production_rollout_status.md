# FleetPilot Production Rollout Status

**Author:** Manus AI  
**Deployment target:** Raspberry Pi, `192.168.1.170`  
**Live revision:** `06c4683`  
**Status:** Operational internal deployment; HTTPS/SSO readiness remains staged.

## Completed rollout

FleetPilot has been refactored around a unified **Storage & Disks** workspace and deployed from the GitHub `main` branch to the Raspberry Pi. The application now runs behind Nginx through **Gunicorn** rather than Flask’s development server. Gunicorn is intentionally configured with a single worker and four threads, which prevents duplicated in-process pollers and task monitors while retaining reasonable concurrency for the current Raspberry Pi deployment.

The production foundation now contains append-only audit logging, a protected audit-trail page, a protected production-status page, a `/healthz` endpoint, proxy-aware session controls, and hardened system service settings. Audit events intentionally exclude request bodies and secrets such as passwords, SSH credentials, tokens, and command output.

| Area | Delivered state | Verification |
|---|---|---|
| Application runtime | Gunicorn runs as the dedicated `fleetpilot` service account, bound to `127.0.0.1:5000` behind Nginx. | `systemctl` reports **active** and `/healthz` returns `{"status":"ok"}`. |
| Storage operations | The former Disk Tools functions are surfaced through **Storage & Disks** at `/storage/workspace`. | Authenticated request returned HTTP 200. |
| Operational accountability | An append-only SQLite audit store records state-changing actions, and administrators can view it at `/system/audit`. | Live database is active and recorded successful login activity. |
| Deployment hardening | The system service uses `ProtectSystem=full`, `ProtectHome=true`, a private temporary directory, limited write paths, a restrictive umask, and a dedicated service account. | Active unit properties were inspected on the Raspberry Pi. |
| Secret handling | `/opt/fleetpilot/.env` is owned by `root:fleetpilot` and is mode `0640`. | Service restarted and remained healthy after the change. |
| Production visibility | Administrators have a **Production Status** navigation entry at `/system/production`. | Authenticated request returned HTTP 200. |

## Revisions deployed

| Revision | Purpose |
|---|---|
| `cbe7d96` | Production Storage workspace, audit foundation, runtime configuration, deployment templates, and identity research documents. |
| `fbdb810` | Startup correction for the new protected routes. The live service was restored and verified immediately after this repair. |
| `06c4683` | Adds the Production Status entry to the administrator System navigation. |

## Security validation

The new production-hardening tests pass locally. The live Raspberry Pi was verified after deployment with an authenticated session against **Storage & Disks**, **Production Status**, and **Audit Trail**. The dependency manifest was independently scanned with `pip-audit`, which reported no known vulnerable Python packages.

GitHub still displays one high-severity Dependabot alert for the repository. Its details could not be retrieved through the configured GitHub integration because that token does not have permission to read Dependabot alerts. This must be resolved by opening the alert as the repository owner, identifying the affected ecosystem and fixed version, then applying the small targeted update. It has not been guessed or silently dismissed.

## Remaining production gates

The present instance is suitable for a trusted internal LAN during the staged rollout. It is **not yet a complete internet-facing production deployment** because HTTPS, secure cookies, full CSRF enforcement, and external identity provider configuration have intentionally not been enabled before their prerequisites are available and tested.

| Priority | Required action | Reason |
|---|---|---|
| High | Put FleetPilot behind a stable HTTPS endpoint, then set `FLEETPILOT_COOKIE_SECURE=true`, `FLEETPILOT_PRODUCTION=true`, and validate sign-in. | Secure session cookies require HTTPS. |
| High | Test all legacy state-changing forms, then enable `WTF_CSRF_ENABLED=true`. | Legacy endpoints must include CSRF tokens before global enforcement. |
| High | Enable TOTP for the local `admin` account at `/2fa/setup` and retain it as break-glass access. | Preserves recoverable administrator access before SSO rollout. |
| High | Investigate and update the single GitHub Dependabot alert with owner access. | Resolves the outstanding repository security signal. |
| Medium | Implement Microsoft Entra ID using OpenID Connect only after a stable HTTPS redirect URI is available. | Supports Conditional Access and Entra MFA without FleetPilot handling user passwords. |
| Medium | Add LDAP/LDAPS only with TLS validation, a least-privileged bind account, and group-to-role mapping. | Avoids insecure directory authentication and unbounded privilege inheritance. |
| Infrastructure | Enable Wake-on-LAN in the pve02 BIOS, bring all four nodes online, then set up the Proxmox QDevice on the Raspberry Pi. | A QDevice is required for safe one-server overnight cluster operation. |

## Identity implementation route

Microsoft Entra ID should be implemented first for organisations already using Microsoft 365. FleetPilot should authenticate via OpenID Connect, limit accepted tenants and groups, map groups to existing roles, and keep a local MFA-protected administrator as a break-glass account. The detailed design notes are in [`identity_integration_research.md`](identity_integration_research.md).

LDAP/Active Directory integration should be a secondary option for on-premises organisations. It should use LDAPS with certificate validation, a restricted bind service account, explicit group-to-role mappings, rate limiting, audit events for authentication failures, and no storage of directory passwords.

## Operator URLs

| Function | URL |
|---|---|
| FleetPilot | `http://192.168.1.170/` or `http://192.168.1.100/` |
| Storage & Disks | `/storage/workspace` |
| Production Status | `/system/production` |
| Audit Trail | `/system/audit` |
| Health check | `/healthz` |

> The current links are intentionally HTTP-only while the local reverse-proxy/TLS rollout is pending. Do not expose these endpoints directly to the internet in their current state.

## Related documents

- [`production_profile.md`](production_profile.md) — intended company profile, roles, acceptance criteria, and deployment model.
- [`identity_integration_research.md`](identity_integration_research.md) — Microsoft Entra, LDAP/LDAPS, MFA, and rollout research.
- [`deploy/fleetpilot.service`](../deploy/fleetpilot.service) — current systemd service template.
- [`deploy/nginx-fleetpilot.conf`](../deploy/nginx-fleetpilot.conf) — reverse-proxy template.
