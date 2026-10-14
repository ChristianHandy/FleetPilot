# Governance

FleetPilot is a single-maintainer open source project. This document says who decides what, who can reach the project's sensitive resources, and how that changes as people join.

## Roles and responsibilities

| Role | Who | Responsibilities |
|---|---|---|
| **Maintainer** | [@ChristianHandy](https://github.com/ChristianHandy) | Sets the direction, reviews and merges pull requests, publishes releases, answers issues and security reports, manages the repository settings and secrets |
| **Contributor** | Anyone who opens an issue, discussion or pull request | Follows [CONTRIBUTING.md](CONTRIBUTING.md), signs off every commit (DCO), adds tests with new functionality |
| **Automation** | GitHub Actions, Dependabot | Tests, analysis and release builds with least-privilege tokens; dependency update pull requests. Automation never merges and never holds long-lived secrets |

AI coding assistants (Claude) help write code and documentation. Their changes go through the same pull requests and checks as everyone's, and the maintainer reviews and merges them.

## Members with access to sensitive resources

| Resource | Access |
|---|---|
| GitHub repository (admin: settings, branch rules, secrets, security alerts) | @ChristianHandy |
| Release signing key (OpenPGP `09D7 7410 5F9A A1DE 6B12 6AD1 F73D EF20 4C54 E71D`, signs tags) | @ChristianHandy |
| Release workflow (Sigstore keyless signing of build provenance) | GitHub Actions, only from version tags on this repository; tag creation is limited to the maintainer |
| GitHub Pages site and repository secrets (`SCORECARD_TOKEN`, optional) | @ChristianHandy |
| Private vulnerability reports (GitHub security advisories) | @ChristianHandy |
| community-scripts.org submission (DevScripts) | @ChristianHandy |

This list is updated in the same pull request that grants or removes access.

## Granting escalated permissions

Write access, admin rights, access to secrets or the signing key are only given to a collaborator who:

1. has contributed accepted pull requests over at least three months,
2. uses two-factor authentication on GitHub and signs commits,
3. was reviewed by the maintainer (contributions, conduct, identity confirmed outside GitHub), and
4. is added to the table above in a pull request before the access is granted.

Access follows least privilege: triage or write access first, admin only when needed. Access that has not been used for six months is removed.

## Decisions

The maintainer decides, after discussion in the issue, pull request or [Discussions](https://github.com/ChristianHandy/FleetPilot/discussions). Security-relevant changes (authentication, installer, release pipeline, root helpers) need passing CI, including CodeQL, and an explicit note in the pull request.

## Continuity

If the maintainer becomes unavailable, the repository stays public under GPL-3.0 and can be forked. A second maintainer will be appointed under the rules above as soon as one is available; until then, pull requests cannot get a second human review (OpenSSF Baseline OSPS-QA-07.01 is not met).
