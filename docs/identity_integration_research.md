# FleetPilot identity integration research

Collected 2026-08-13 for the production-hardening design.

## Microsoft Entra ID OIDC

Microsoft documents OpenID Connect (OIDC) as its standard web-app SSO protocol. The tenant-scoped authority exposes discovery, authorize, token, JWKS, UserInfo, and logout endpoints. A web app should use a registered redirect URI, the authorization-code flow, OIDC `openid` scope, and validate token signature and claims through a supported validation library rather than hand-written validation. Authorization should derive roles/permissions from validated claims or application-managed role mappings.

Source: https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc

## Microsoft Entra MFA

Microsoft Entra MFA can be enforced for an application using Conditional Access. The official guidance recommends users have more than one authentication method; supported methods include Microsoft Authenticator, FIDO2 security keys, passkeys, software/hardware OATH tokens, SMS, and voice. Microsoft recommends rolling out Conditional Access and MFA with a pilot group before wider deployment.

Source: https://learn.microsoft.com/en-us/entra/identity/authentication/howto-mfa-getstarted

## Linux LDAP / directory integration

Microsoft documents a provisioning route in which Entra ID provisions users into an existing on-premises LDAP directory used by Linux NSS/PAM. This is for Linux systems that already rely on LDAP. It requires an existing POSIX-capable LDAP directory, a Windows-hosted provisioning agent, Microsoft Entra ID P1/P2 licensing, role permissions, and TLS-protected LDAP communication. Microsoft does not provision Entra passwords to the directory. This path is identity provisioning for Linux systems; it is not the preferred direct SSO path for a modern web application.

Source: https://learn.microsoft.com/en-us/entra/identity/app-provisioning/on-premises-ldap-connector-linux

## FleetPilot design implications

1. Preferred Microsoft path: direct Entra OIDC login in FleetPilot, with group-to-role mapping, then enforce MFA in Entra Conditional Access. FleetPilot does not handle Entra passwords or second-factor secrets in this mode.
2. Preferred Linux/AD path: FleetPilot may support read-only LDAP/LDAPS authentication against an existing AD DS/OpenLDAP directory, but must use a dedicated least-privileged bind account, TLS certificate validation, user/group allowlists, and a local break-glass admin account.
3. Built-in fallback MFA: FleetPilot can retain its existing TOTP/WebAuthn-security-key compatible local MFA for local accounts, but organization-managed Entra MFA should be the preferred control when OIDC is enabled.
4. SSO setup requires an Entra application registration, a stable HTTPS FleetPilot URL, a redirect URI, tenant/client identifiers, and a securely stored client credential. It should be enabled only during a staged rollout after testing with a pilot admin group.
