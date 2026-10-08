# FleetPilot small-company production profile

FleetPilot is being hardened as an **internal infrastructure operations platform** for a single site or a small number of trusted sites. Its first production profile is aimed at organisations operating approximately 1–25 managed servers and a small IT or operations team.

## Suitable use cases

| Organisation type | Typical FleetPilot use |
|---|---|
| Managed service provider / internal IT team | Host inventory, patch tasks, storage visibility, backup and health operations |
| Engineering, manufacturing, or design office | Proxmox, NAS, Linux server, and workstation operations from one internal console |
| Branch office or retail back office | Local infrastructure monitoring and controlled maintenance tasks |
| School, lab, or training centre | Small server fleet and storage administration with role separation |
| Small professional-services business | Internal infrastructure visibility, auditability, and operations handover |

## Explicit boundaries

FleetPilot is **not** a compliance-certified product. It must not be represented as automatically meeting ISO 27001, SOC 2, HIPAA, PCI DSS, or equivalent requirements. Those outcomes require organisation-specific policy, risk assessment, legal review, logging retention, incident response, and independent verification.

The initial single-node deployment remains a single point of failure. A company using FleetPilot for business-critical operations should protect the Raspberry Pi/host with reliable power, backups, monitoring, and a documented break-glass process.

## Access model

| Role | Intended access |
|---|---|
| Viewer | Read-only dashboards, inventory, health, and task visibility |
| Operator | Controlled infrastructure operations, including approved disk and update tasks |
| Administrator | User/role management, identity configuration, audit review, and platform configuration |

Destructive disk operations require an Operator or Administrator role, explicit target confirmation, durable server-side task tracking, and an audit event. The UI must never make raw formatting appear as a read-only action.

## Production acceptance criteria for the initial profile

1. FleetPilot runs behind Nginx with Gunicorn rather than Flask’s development server.
2. Persistent data is writable only by the FleetPilot service account and is backed up.
3. `SECRET_KEY`, administrator credentials, and service configuration are supplied through a protected environment file rather than source code.
4. HTTPS is required before external, VPN, or SSO access is enabled.
5. Login CSRF protection, secure session cookies, rate limiting, and a stable reverse-proxy trust boundary are enabled and tested.
6. Mutating operations are recorded in the audit database without recording secrets or command bodies.
7. Disk actions use the restricted root-owned helper only; the web application itself does not receive unrestricted root access.
8. Local TOTP or security-key MFA is enabled for administrators before production handover.

## Identity rollout order

1. Keep one local break-glass administrator with strong password and local MFA.
2. Pilot Microsoft Entra OIDC or LDAP/LDAPS with an administrator test group.
3. Map validated directory groups to FleetPilot Viewer, Operator, and Administrator roles.
4. Enforce Microsoft MFA with Conditional Access for OIDC users, or retain FleetPilot MFA for local/LDAP users.
5. Only then disable normal local user provisioning for non-break-glass accounts.

## Production checklist

Work through this before handing FleetPilot over. Everything here is configuration; no code changes are needed.

| Item | How |
|---|---|
| Service runs under gunicorn with one worker | `deploy/fleetpilot.service` or the installers; `gunicorn.conf.py` pins `workers = 1` |
| Not reachable directly from other networks | gunicorn binds to `127.0.0.1` by default; publish it through Nginx/HAProxy |
| HTTPS with secure cookies | TLS on the proxy, then `FLEETPILOT_COOKIE_SECURE=true` and `FLEETPILOT_TRUST_PROXY=true` |
| Strong secrets | Leave `SECRET_KEY` empty to have one generated in the data folder, or set 64 random hex characters |
| First admin password | Read `data/initial_admin_password`, sign in, change it under **My Profile**, then delete the file |
| CSRF protection on | `WTF_CSRF_ENABLED=true` (default; older `.env` files may still say `false`) |
| MFA for administrators | **My Profile → Two-factor authentication** |
| Backups | **System → Backups**. Daily backups run at 03:00 and keep 7 (`FLEETPILOT_AUTO_BACKUP`, `FLEETPILOT_BACKUP_HOUR`, `FLEETPILOT_BACKUP_KEEP`). Copy them off the host regularly; they contain password hashes and encrypted credentials. If `SECRET_KEY` is set in the environment, store it with the backups. |
| Alerts | **System → Email Config**: SMTP, then enable SMART alerts and error notifications and send a test email |
| Monitoring | Scrape `/metrics` with the API token from the CheckMK page (`Authorization: Bearer <token>`) |
| Data folder private | FleetPilot sets the data folder to `0700` and its files to `0600` at start |

### Restoring a backup

1. **System → Backups → Restore**, upload the archive. It is checked against its manifest, checksums and SQLite integrity.
2. Restart the service (`sudo systemctl restart fleetpilot`). The current files move to `data/pre-restore-<time>/` before the backup is put in place.
