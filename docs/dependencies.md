# Dependencies

How FleetPilot selects, obtains and tracks the software it depends on, and what happens when a dependency has a vulnerability or an unsuitable license.

## Selecting a dependency

A new dependency needs a reason that the standard library or an existing dependency cannot cover. Before it is added, the maintainer checks:

- **License:** compatible with GPL-3.0 (see the license policy below).
- **Maintenance:** recent releases, an active maintainer, a security policy, and preferably a good [OpenSSF Scorecard](https://scorecard.dev).
- **Known vulnerabilities:** none open (OSV.dev, GitHub advisories).
- **Footprint:** prefer small, widely used packages; avoid packages that run code at install time when a wheel is available.

## Obtaining dependencies

| Kind | Declared in | Locked in | Installed with |
|---|---|---|---|
| Python runtime | `requirements.txt` (minimum versions) | `requirements-lock.txt` (exact versions and SHA-256 hashes for every file) | `pip install --require-hashes -r requirements-lock.txt` (installers, CI, release SBOM) |
| Python dev and test | `requirements-dev.in` | `requirements-dev-lock.txt` | same |
| Fuzzing | `requirements-fuzz.in` | `requirements-fuzz-lock.txt` | same |
| GitHub Actions | workflows | every action pinned to a full commit SHA (enforced by repository settings) | GitHub |
| Fuzzing build image | `.clusterfuzzlite/Dockerfile` | pinned by digest | Docker |
| System packages | `install.sh` (`apt-get`) | Debian/Ubuntu archives (signed) | apt |
| Live demo | `demo/build_live.py` | wheels downloaded with the hashes from `requirements-lock.txt`; Pyodide at a pinned version | browser |

Lock files are generated with `uv pip compile --universal --python-version 3.11 --generate-hashes`. A test (`test_requirements_lock.py`) checks that the lock satisfies `requirements.txt` and that every pin has a hash.

## Tracking dependencies

- **Dependabot:** proposes version updates weekly (pip, GitHub Actions) or monthly (Docker, NuGet, Gradle), always after a **7-day cooldown**. Security updates are proposed at once.
- **Software composition analysis (SCA)** runs on every pull request and push:
  - **dependency review:** blocks pull requests that add or upgrade to a vulnerable or malicious package, or to a disallowed license.
  - **pip-audit:** checks the whole lock file.
- **SBOM:** every release carries a CycloneDX SBOM of `requirements-lock.txt`.

## SCA policy

**Vulnerabilities:**

| Finding | Threshold | Action |
|---|---|---|
| Malicious package (OSV `MAL-` / GitHub malware advisory) | any | Blocked; removed immediately, release withdrawn if affected |
| Known vulnerability with a fix | any severity | Blocked in pull requests; fixed on `main` within 7 days (critical/high: 48 hours) |
| Known vulnerability without a fix | medium or higher | Mitigated or the dependency replaced within 30 days; documented in the security advisory if FleetPilot is affected |
| Vulnerability that does not affect FleetPilot | any | Suppressed only with a written reason (the code path is not used) recorded in a VEX statement, see below |

**Licenses:** dependencies must use a license compatible with GPL-3.0. The allowed SPDX licenses are listed in `.github/workflows/dependency-review.yml` (MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0, LGPL, GPL-3.0 and similar). Anything else fails the dependency review and needs the maintainer's explicit approval.

**Before a release**, SCA must be clean: pip-audit passes on the release commit, there is no open Dependabot or code scanning alert of medium or higher severity without a documented decision, and the release SBOM is generated from the same lock file.

## VEX

When a dependency has a vulnerability that does not affect FleetPilot (for example, the vulnerable function is never called), FleetPilot publishes an [OpenVEX](https://openvex.dev) statement with the justification in `docs/security/vex.openvex.json` and in the release notes, instead of ignoring the finding silently. There are currently no such cases, so the document contains no statements.
