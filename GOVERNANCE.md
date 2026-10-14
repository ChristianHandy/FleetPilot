# Governance

FleetPilot is a single-maintainer open source project. This document says who decides what, who can reach the project's sensitive resources, and how that changes as people join.

## Roles and responsibilities

| Role | Who | Responsibilities |
|---|---|---|
| **Maintainer** | [@ChristianHandy](https://github.com/ChristianHandy) | Sets the direction and the [roadmap](ROADMAP.md), reviews pull requests against the [review standards](CONTRIBUTING.md#code-review) and merges them, publishes releases, answers issues and security reports, enforces the code of conduct, manages the repository settings and secrets |
| **Contributor** | Anyone who opens an issue, discussion or pull request | Follows [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md), signs off every commit (DCO), adds tests with new functionality |
| **Security contact** | the maintainer | Receives private vulnerability reports and code of conduct reports, answers within 48 hours, coordinates the fix and the advisory (see [SECURITY.md](SECURITY.md)) |
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

FleetPilot must be able to keep going if the maintainer dies, is incapacitated or stops working on it: issues can still be opened and closed, pull requests merged and releases published within a week.

- **Repository:** the maintainer has named an account successor in GitHub's [account successor settings](https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-access-to-your-personal-repositories/maintaining-ownership-continuity-of-your-personal-accounts-repositories). After GitHub confirms the loss of the maintainer, the successor can manage, transfer or archive the repository, including issues, pull requests, settings and releases.
- **Releases:** releases are built and signed by the release workflow (Sigstore keyless provenance from GitHub Actions), so no private key is needed to publish one. Only the OpenPGP tag signature is personal; a successor publishes a new signing key in `SECURITY.md` and `docs/security/release-signing-key.asc`, and releases stay verifiable through their provenance.
- **Other resources:** the GitHub Pages site and the workflows live in the repository and move with it. The community-scripts.org entry is maintained in that project's own repository and can be updated by anyone through a pull request there.
- **License:** FleetPilot is GPL-3.0, so anyone may continue it as a fork; no further legal rights are needed.

A second maintainer will be appointed under the rules above as soon as one is available. Until then the bus factor is 1, and pull requests cannot get a second human review (OpenSSF Baseline OSPS-QA-07.01 is not met).
