# OpenSSF Best Practices: answers for the "passing" level

The project is registered as [#15465](https://www.bestpractices.dev/projects/15465). To change answers, sign in at bestpractices.dev with GitHub. Many fields are filled in automatically. Copy the rest from below: **status**, then the **justification** (most fields accept a URL).

`R` = https://github.com/ChristianHandy/FleetPilot

## Basics

| Criterion | Status | Justification |
|---|---|---|
| description_good | Met | R#readme: what FleetPilot does, for whom, features table |
| interact | Met | Issues R/issues, Discussions R/discussions, contributing R/blob/main/CONTRIBUTING.md |
| contribution | Met | R/blob/main/CONTRIBUTING.md: fork, branch, pull request, CI |
| contribution_requirements | Met | R/blob/main/CONTRIBUTING.md#coding-style and #test-policy |
| floss_license | Met | GPL-3.0 (R/blob/main/LICENSE) |
| floss_license_osi | Met | GPL-3.0 is OSI approved |
| license_location | Met | R/blob/main/LICENSE |
| documentation_basics | Met | R/blob/main/docs/installation.md, R/blob/main/docs/user-guide.md |
| documentation_interface | Met | User guide section 9 "Integrations": REST API, `/metrics`, Home Assistant (R/blob/main/docs/user-guide.md) |
| sites_https | Met | GitHub and https://christianhandy.github.io/FleetPilot/ are HTTPS only |
| discussion | Met | GitHub Issues and Discussions: searchable, URL-addressable, no proprietary client |
| english | Met | Documentation, code and issues in English (German also accepted) |
| maintained | Met | Regular releases and commits (R/releases, R/commits/main) |

## Change control

| Criterion | Status | Justification |
|---|---|---|
| repo_public | Met | R |
| repo_track | Met | Git: every change with author and time |
| repo_interim | Met | All changes land on `main` through pull requests, between releases |
| repo_distributed | Met (SUGGESTED) | Git |
| version_unique | Met | Tags vX.Y.Z (R/tags) |
| version_semver | Met (SUGGESTED) | Semantic versioning, see CHANGELOG.md header |
| version_tags | Met (SUGGESTED) | Signed tags per release |
| release_notes | Met | R/blob/main/CHANGELOG.md; the release workflow publishes the notes on R/releases |
| release_notes_vulns | Met | Security fixes are listed in CHANGELOG.md (e.g. the Security sections of 1.7.0) with CVE/advisory where one exists |

## Reporting

| Criterion | Status | Justification |
|---|---|---|
| report_process | Met | R/issues; described in CONTRIBUTING.md |
| report_tracker | Met (SUGGESTED) | GitHub Issues |
| report_responses | Met | Issues are answered (few so far; all answered) |
| enhancement_responses | Met | Feature requests answered in Issues/Discussions |
| report_archive | Met | R/issues?q=is%3Aissue (public, searchable) |
| vulnerability_report_process | Met | R/blob/main/SECURITY.md |
| vulnerability_report_private | Met | Private vulnerability reporting is enabled: R/security/advisories/new |
| vulnerability_report_response | Met | SECURITY.md: acknowledgement within 48 hours (no reports in the last 6 months) |

## Quality

| Criterion | Status | Justification |
|---|---|---|
| build | Met | Python, no compile step; `install.sh` and the Proxmox helper install it reproducibly from hash-locked requirements |
| build_common_tools | Met (SUGGESTED) | pip, standard Python tooling |
| build_floss_tools | Met | All FLOSS |
| test | Met | pytest suite, ~200 tests (`test_*.py`), see CONTRIBUTING.md |
| test_invocation | Met (SUGGESTED) | `python -m pytest -q` |
| test_most | Met (SUGGESTED) | Tests for every module, including a test that boots the whole app against an emulated homelab (`test_demo_lab.py`) |
| test_continuous_integration | Met (SUGGESTED) | R/actions/workflows/tests.yml on every pull request and push, Python 3.11–3.13 |
| test_policy | Met | CONTRIBUTING.md#test-policy |
| tests_are_added | Met | Recent feature PRs add tests (e.g. #64 test_demo_lab.py, #65 test_vuln_scanner.py) |
| tests_documented_added | Met (SUGGESTED) | CONTRIBUTING.md#test-policy |
| warnings | Met | ruff (crash-class rules) and Bandit run in CI (tests.yml); CodeQL on every PR |
| warnings_fixed | Met | CI fails on findings; CodeQL alerts are fixed (R/security/code-scanning) |
| warnings_strict | Met (SUGGESTED) | Bandit fails on high severity; ruff fails on any selected finding |

## Security

| Criterion | Status | Justification |
|---|---|---|
| know_secure_design | Met | SECURITY.md "Security Architecture": least privilege (read-only install, unprivileged service user, three root helpers with fixed arguments), secure defaults, defence in depth |
| know_common_errors | Met | Parameterized SQL, argument-list commands, CSRF protection, CSP, validated device input, fuzzed parsers (SECURITY.md) |
| crypto_published | Met | Only published algorithms: TLS, SSH, scrypt/PBKDF2, Fernet (AES-CBC + HMAC-SHA256), HMAC-SHA256 for the audit chain, TOTP, WebAuthn |
| crypto_call | Met | Uses `cryptography`, `paramiko`, `werkzeug.security`, Python `ssl`/`secrets`; no own crypto primitives |
| crypto_floss | Met | All crypto libraries are FLOSS |
| crypto_keylength | Met | Ed25519 SSH keys, 256-bit secret key, AES-128 (Fernet), TLS from the system |
| crypto_working | Met | No broken algorithms (no MD5/SHA-1/DES/RC4 for security) |
| crypto_weaknesses | Met (SUGGESTED) | No SHA-1 for security purposes |
| crypto_pfs | Met (SUGGESTED) | nginx TLS 1.2/1.3 only with ECDHE key exchange (R/blob/main/deploy/nginx-fleetpilot-tls.conf, used by install.sh; same in the community-scripts installer) |
| crypto_password_storage | Met | Salted scrypt (PBKDF2-HMAC-SHA256, 600,000 iterations, in FIPS mode), see user_management.py |
| crypto_random | Met | `secrets` module for tokens, passwords and keys |
| delivery_mitm | Met | Code delivered over HTTPS (GitHub); installers clone over HTTPS; dependencies installed with `--require-hashes` |
| delivery_unsigned | Met | No hash retrieved over HTTP; release tags are GPG-signed |
| vulnerabilities_fixed_60_days | Met | No unpatched medium-or-higher vulnerability older than 60 days (R/security) |
| vulnerabilities_critical_fixed | Met (SUGGESTED) | Critical issues fixed promptly |
| no_leaked_credentials | Met | No credentials in the repository; demo data uses RFC 5737 addresses and placeholder passwords |

## Analysis

| Criterion | Status | Justification |
|---|---|---|
| static_analysis | Met | CodeQL on every PR and push (R/actions/workflows/codeql.yml), Bandit in CI |
| static_analysis_common_vulnerabilities | Met (SUGGESTED) | CodeQL security queries for Python (injection, path traversal, SSRF, ...) and Bandit |
| static_analysis_fixed | Met | Findings fixed (R/security/code-scanning?query=is%3Aclosed) |
| static_analysis_often | Met (SUGGESTED) | Every commit to main and every pull request |
| dynamic_analysis | Met (SUGGESTED) | Atheris fuzzing in CI (fuzz.yml weekly and on main; ClusterFuzzLite on pull requests) |
| dynamic_analysis_unsafe | N/A | Python (memory-safe) |
| dynamic_analysis_enable_assertions | Met (SUGGESTED) | Fuzzers and tests run with assertions on |
| dynamic_analysis_fixed | Met | Fuzzer findings fixed (e.g. invalid router XML now rejected cleanly, router_manager._safe_xml) |

## After the badge is granted

The page shows a project number. Put the badge into the README next to the Scorecard badge:

```markdown
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/NUMBER/badge)](https://www.bestpractices.dev/projects/NUMBER)
```

Scorecard's "CII-Best-Practices" check picks it up at its next run.
