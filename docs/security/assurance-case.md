# Security assurance case

This document argues why FleetPilot meets its security requirements. It is built on:

- [../architecture.md](../architecture.md): components, actors, trust boundaries
- [threat-model.md](threat-model.md): assets, attack surface, threats and mitigations

Every claim points to the code, test or workflow that backs it. If a claim here stops being true, that is a bug: report it like any other ([SECURITY.md](../../SECURITY.md)).

Last review: October 2026 (v1.7.x). Reviewed with every release that changes an attack surface.

## 1. Claim

**FleetPilot, installed as documented, protects the homelab it manages from people who are not signed in to FleetPilot, keeps signed-in users within their role, and does not become the way into the managed systems.**

This rests on four arguments:

1. The threats are known and each one has a mitigation (section 2).
2. Trust boundaries are identified and every crossing is checked (section 3).
3. Secure design principles are applied (section 4).
4. Common implementation weaknesses are countered (section 5).

Section 6 lists the evidence that keeps the arguments true over time. Section 7 lists what is *not* claimed.

## 2. Threat model

The full model is in [threat-model.md](threat-model.md): assets, attack surface, STRIDE threats with their mitigations, and residual risks.

In short: FleetPilot holds SSH access and credentials for the whole fleet, so the assets that matter most are:

- its private key and the stored device credentials
- admin sessions
- the FleetPilot server itself
- the integrity of what it reports
- its supply chain

The attackers considered are:

- someone on the network who is not signed in
- a signed-in user trying to exceed their role
- a compromised or hostile managed device whose output FleetPilot parses
- a compromised dependency or release

## 3. Trust boundaries

From [architecture.md](../architecture.md#trust-boundaries), with how each crossing is checked:

| Boundary | Data crossing it | Checks |
|---|---|---|
| Browser / API client → FleetPilot | HTTP requests, forms, uploads, API calls | TLS (nginx); session validated on every request (`_validate_session` in `app.py`); role decorators on every route, verified by `test_route_authorization.py`; CSRF token on every state-changing browser request; input validation; size limits (`MAX_CONTENT_LENGTH`) |
| Monitoring → FleetPilot | `/metrics`, CheckMK agent data | Separate monitoring token, compared in constant time |
| FleetPilot → managed devices | SSH commands, HTTPS API calls | Pinned SSH host keys (TOFU or strict, `ssh_helper.py`); TLS verification where configured; commands built from validated values only |
| Managed devices → FleetPilot | Command output, XML, JSON | Treated as untrusted: size limits, XML without DTDs (`router_manager._safe_xml`), values validated before use in a command, path or URL (API paths only from names the device itself reported); the parsers are fuzzed (`fuzz/`) |
| App user → root | Updates, proxy routes, disk tools | Only through the root helpers in `/usr/local/lib/fleetpilot`, with fixed arguments and one narrow sudo rule (`privileged.py`, `test_privileged.py`) |
| FleetPilot → internet | Update checks, OSV.dev, notifications | Outbound only, optional, off in offline mode; no credentials of managed systems are sent |
| Source → installed system | Code, dependencies, releases | Branch protection, required CI, hash-locked dependencies, actions pinned to commits, signed tags, Sigstore build provenance |

## 4. Secure design principles

The principles of Saltzer and Schroeder, and how FleetPilot applies them:

| Principle | How it is applied |
|---|---|
| **Economy of mechanism** | One Flask application with SQLite and files; no separate database server, message queue or agent on managed hosts. Security functions are shared: one SSH helper, one secret box, one audit log, one set of role decorators. |
| **Fail-safe defaults** | The defaults are secure:<ul><li>CSRF protection, the HSTS header, server-side sessions with an idle timeout, and pinned SSH host keys are on by default.</li><li>Debug mode is off.</li><li>An unknown session or a disabled account is treated as anonymous.</li><li>Every route needs sign-in except a short, tested list (`PUBLIC` in `test_route_authorization.py`).</li><li>Insecure settings are shown in the Security center.</li></ul> |
| **Complete mediation** | Every request is checked:<ul><li>`_validate_session` checks the session on every request, whatever the route's decorator.</li><li>Role checks are on each route, tested for every route.</li><li>Re-authentication is required for sensitive actions (`recent_auth_required`).</li><li>Device API calls only use names the device itself reported.</li></ul> |
| **Open design** | The source, threat model, this assurance case and the security tests are public. Security comes from keys and passwords, not from hidden behaviour. |
| **Separation of privilege** | Sign-in can need two factors (TOTP, passkeys, YubiKey), and admins can be required to use them. The repository needs passing CI and a pull request to change `main`; a release needs a signed tag and the release workflow. |
| **Least privilege** | FleetPilot runs as the `fleetpilot` user without a login shell, with the code directory read-only. Root is only reachable through fixed helpers. Users get roles: viewer, operator, admin. API tokens can be read-only and expire. CI jobs get per-job, minimal token permissions. |
| **Least common mechanism** | Each user has their own sessions and tokens. The public status page has its own data function, which never returns addresses. The monitoring token is separate from user accounts. |
| **Psychological acceptability** | The Security center lists what is weak and how to fix it, in plain language (English, German and easy language). The installers set up HTTPS, the service user and sudo rules without manual steps. |

## 5. Common implementation weaknesses

Mapped to the [OWASP Top 10 (2021)](https://owasp.org/Top10/) and the most relevant [CWE Top 25](https://cwe.mitre.org/top25/) entries:

| Weakness | Countermeasure | Evidence |
|---|---|---|
| A01 Broken access control (CWE-862, CWE-863, CWE-22) | <ul><li>Role decorators on every route, plus a per-request session check.</li><li>File names are checked with `secure_filename` and `realpath` against their folder.</li><li>Downloads are limited to their own directories.</li></ul> | `test_route_authorization.py`, `test_security_regressions.py`, `test_user_management.py` |
| A02 Cryptographic failures (CWE-327, CWE-319) | <ul><li>Passwords: salted scrypt (PBKDF2-HMAC-SHA256 with 600,000 iterations in FIPS mode).</li><li>Device credentials: Fernet (AES-128-CBC with HMAC-SHA256).</li><li>Tokens: stored only as hashes.</li><li>TLS 1.2 and 1.3 only (nginx).</li><li>HSTS and Secure cookies on HTTPS.</li><li>The audit chain uses HMAC-SHA256.</li><li>SHA-1 appears only where RFC 6238 requires it for TOTP.</li></ul> | `user_management.py`, `secret_box.py`, `audit_log.py`, `test_account_security.py` |
| A03 Injection (CWE-78, CWE-89, CWE-79) | <ul><li>Every SQL query is parameterized.</li><li>Local commands use argument lists, never `shell=True` with input.</li><li>Values put into remote commands are checked against allowlists or quoted with `shlex.quote`.</li><li>Jinja templates escape by default.</li><li>Values reach inline scripts only JSON-encoded (`|tojson`).</li></ul> | Bandit and CodeQL (security-extended) on every change, `test_disktool_security.py`, `test_codeql_fixes.py`, `test_template_scripts.py` |
| A04 Insecure design | The threat model and this assurance case are reviewed with every release that changes an attack surface. | [threat-model.md](threat-model.md) |
| A05 Security misconfiguration | <ul><li>Secure defaults (section 4).</li><li>The Security center checks the running installation.</li><li>Security headers on every response: CSP without `unsafe-eval`, `frame-ancestors 'none'`, `X-Frame-Options`, `nosniff`, and COOP/CORP.</li></ul> | `test_production_hardening.py`, `test_strict_compliance.py` |
| A06 Vulnerable and outdated components | <ul><li>Hash-locked dependencies.</li><li>pip-audit and dependency review on every change, with a 7-day cooldown.</li><li>Dependabot security updates.</li><li>OSV scanning of FleetPilot's own packages in the vulnerability scan.</li></ul> | [../dependencies.md](../dependencies.md) |
| A07 Identification and authentication failures (CWE-287, CWE-307) | <ul><li>Sign-in throttling and lockout per address and per account.</li><li>A timing-equalised check for unknown users.</li><li>Two-factor sign-in.</li><li>Sessions end on idle, on a password change and on account disable.</li><li>The session ID is rotated at sign-in.</li></ul> | `test_account_security.py`, `test_webauthn_support.py` |
| A08 Software and data integrity failures (CWE-502) | <ul><li>No `pickle`, no `eval`, no unsafe YAML loading.</li><li>Backups are verified before a restore is applied.</li><li>Releases carry signed provenance, and tags are signed.</li><li>Workflows are audited by zizmor and CodeQL.</li></ul> | `.github/workflows/release.yml`, `zizmor.yml` |
| A09 Security logging and monitoring failures (CWE-117) | <ul><li>HMAC-chained audit trail of sign-ins and every state-changing request, with optional SIEM export.</li><li>Line breaks in logged names are escaped (`safe_errors.log_text`).</li></ul> | `audit_log.py`, `test_production_features.py` |
| A10 Server-side request forgery (CWE-918) | <ul><li>Device API paths are built only from names the device reported.</li><li>Device addresses are set by admins only.</li><li>Outbound internet requests go only to fixed services, or to a mirror an admin configured.</li></ul> | `vm_controller.py`, `backup_controller.py`, `test_codeql_fixes.py` |
| CWE-20 Improper input validation, CWE-400 Resource exhaustion | <ul><li>Allowlists for device names, filesystem types, plugin names and host names.</li><li>Size and time limits on device answers and uploads.</li><li>Fuzzing of every parser for device data in CI and on each pull request (ClusterFuzzLite).</li></ul> | `fuzz/`, `.clusterfuzzlite/` |

## 6. Evidence that keeps this true

- **Every pull request runs:**
  - the tests on Python 3.11–3.13, including the security tests named above
  - CodeQL (security-extended)
  - Bandit, pip-audit and dependency review
  - zizmor and ClusterFuzzLite
- **Fuzzing:** the scheduled fuzzing workflow runs the parsers for longer.
- **Branch protection:** these checks must pass before anything reaches `main`.
- **Scorecard:** the project's OpenSSF Scorecard is published at [scorecard.dev](https://scorecard.dev/viewer/?uri=github.com/ChristianHandy/FleetPilot).

## 7. What is not claimed

These limits are documented so that nobody relies on protection FleetPilot does not give (see also [SECURITY.md](../../SECURITY.md#known-limitations)):

- **Admins are fully trusted.** An admin can run commands on every managed machine; that is FleetPilot's purpose.
- **Plugins run with FleetPilot's own privileges.** Install only plugins you trust.
- **SSH host keys are trusted on first use**, unless strict mode is on. An attacker who is already in the middle at the very first connection is not detected.
- **The CSP allows inline scripts.** It limits an injected script, but does not stop one.
- **A compromised FleetPilot server compromises the fleet.** No design can prevent this for a tool that holds the fleet's credentials, so protect the server and expose it only to your LAN or a VPN.
- **There is no second human reviewer** while the project has one maintainer ([GOVERNANCE.md](../../GOVERNANCE.md)).
