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
