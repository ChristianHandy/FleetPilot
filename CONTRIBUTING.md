# Contributing to FleetPilot

Thanks for helping. Bug reports, ideas, translations, documentation and code are all welcome. Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md). Where the project is heading is in the [roadmap](ROADMAP.md), and who decides what is in [GOVERNANCE.md](GOVERNANCE.md).

**New here?** Issues labelled [good first issue](https://github.com/ChristianHandy/FleetPilot/labels/good%20first%20issue) are small, self-contained tasks (a test, a translation, a documentation fix) that need little knowledge of the code.

## Reporting bugs and asking for features

- **Bugs and feature requests:** [GitHub Issues](https://github.com/ChristianHandy/FleetPilot/issues). Include your FleetPilot version (shown in the sidebar), how you installed it, what you did, what happened and what you expected. Logs (`journalctl -u fleetpilot`) help, but remove addresses and names you don't want to share.
- **Questions and ideas:** [GitHub Discussions](https://github.com/ChristianHandy/FleetPilot/discussions).
- **Security problems:** never in a public issue. Follow [SECURITY.md](SECURITY.md) (private vulnerability reporting).

Reports in English or German are fine; issues are usually answered within a few days.

## Contributing code

1. Fork the repository and create a branch from `main`.
2. Make your change. Keep it focused: one fix or feature per pull request.
3. Add or update tests (see the test policy below) and the documentation it touches (`docs/user-guide.md`, `docs/de/benutzerhandbuch.md`, `CHANGELOG.md` under "Unreleased").
4. Run the checks locally:
   ```bash
   pip install --require-hashes -r requirements-lock.txt -r requirements-dev-lock.txt
   python -m coverage run -m pytest -q && python -m coverage report   # tests, and coverage must not drop
   ruff check .                                                     # coding standard
   ```
5. Open a pull request against `main` and describe what changes for users and how you tested it.

`main` is protected: every change goes through a pull request, and CI must pass before it is merged. CI runs the tests on Python 3.11–3.13, a linter, Bandit, pip-audit, CodeQL, the fuzzers, and a test that boots the live demo.

By contributing you agree that your contribution is licensed under the project's license, [GPL-3.0-or-later](LICENSE).

## Sign-off (DCO)

Every commit must be signed off: `git commit -s` adds a `Signed-off-by: Your Name <you@example.com>` line matching the commit's author. With it you certify the [Developer Certificate of Origin](https://developercertificate.org): you wrote the change, or otherwise have the right to submit it under the project's license. A check (`dco.yml`) fails pull requests with commits that are not signed off. To fix the last commit, run `git commit --amend -s`; for older commits, run `git rebase --signoff main`.

## Building and running from source

FleetPilot is Python and needs no compile step. You need:

- Python 3.11 or newer with `venv` and `pip`
- For packages without wheels on your platform: a C compiler and the development headers (Debian/Ubuntu: `build-essential python3-dev libffi-dev libssl-dev`)
- `openssh-client`; optionally `smartmontools`, `lm-sensors` and `nginx` (the installer sets these up for production)

```bash
git clone https://github.com/ChristianHandy/FleetPilot.git && cd FleetPilot
python3 -m venv venv && venv/bin/pip install --require-hashes -r requirements-lock.txt
cp .env.example .env && venv/bin/python app.py      # development server on http://localhost:5000
```

All Python dependencies, with exact versions and hashes, are in `requirements-lock.txt` (see [docs/dependencies.md](docs/dependencies.md)). For production, use `install.sh` or the Proxmox helper ([docs/installation.md](docs/installation.md)): they install the same lock file into a read-only directory with nginx and a service user.

## Test policy

- **New functionality must come with automated tests** in a `test_*.py` file at the top level (pytest). This is a rule, not a wish: a pull request that adds major functionality without tests is not merged until they are added.
- **Bug fixes come with a test** that fails without the fix whenever that is practical.
- Code that talks to devices is tested against recorded or emulated output. See `test_routers.py` and the emulated lab in `demo/live/lab`.
- Parsers for data from the network belong in the fuzzer (`fuzz/fuzz_parsers.py`).
- **Coverage must not drop.** CI measures statement and branch coverage and fails below the floor in `.coveragerc`, which is raised as coverage grows. The goal is 90% of statements and 80% of branches.

## Code review

Every change, including the maintainer's own, goes through a pull request and is reviewed before it is merged.

**How:** the reviewer reads the whole diff on GitHub, checks the CI results, and for user-visible changes runs the change locally, against real devices or the emulated lab of the live demo (`python demo/build_live.py`). Questions and requested changes are left as review comments; every conversation must be resolved before merging (branch protection enforces this).

**What is checked:**

- **Purpose:** the change is wanted (an issue, the roadmap or a clear explanation) and does one thing.
- **Correctness:** it does what it says, including error cases and the devices and operating systems it affects.
- **Security:**
  - input from forms, APIs and devices is validated
  - no shell strings, unparameterized SQL or new paths built from untrusted input
  - role checks on new routes
  - secrets are not logged or shown
  - changes to authentication, the installers, root helpers or the release pipeline are called out in the description
- **Tests:** new functionality has tests, a fixed bug has a regression test, and the tests would fail without the change.
- **Style and docs:** the code follows the coding style below; user-facing changes update the user guides, the translations and `CHANGELOG.md`.
- **Dependencies:** any new dependency follows [docs/dependencies.md](docs/dependencies.md).

**Required to merge:**

- all required checks pass: tests on Python 3.11–3.13, CodeQL, the lint, Bandit, pip-audit, dependency review and DCO
- every review conversation is resolved
- the reviewer approves. While FleetPilot has one maintainer, the maintainer reviews contributors' pull requests, and their own (and AI-assisted) changes are reviewed by the maintainer against this list before merging, without a second person (see [GOVERNANCE.md](GOVERNANCE.md#continuity))

A pull request that does not meet these is not merged, however small.

## Coding style

- **Python:** Python 3.11+ following [PEP 8](https://peps.python.org/pep-0008/), enforced by [ruff](https://docs.astral.sh/ruff/) with the rules in `ruff.toml`; CI fails on any finding. Lines up to 120 columns. Follow the style of the surrounding code. A rare, justified exception is marked where it happens: `# noqa: <rule>  (reason)`.
- **Warnings are errors:** the test suite fails on any warning (`pytest.ini`), including unclosed files and database connections. Fix the cause; silence a third-party warning only in `pytest.ini`, with a comment saying why.
- **License header:** every source file starts with these two lines, in the file's comment syntax (a test checks this):
  ```
  SPDX-FileCopyrightText: Copyright the FleetPilot contributors
  SPDX-License-Identifier: GPL-3.0-or-later
  ```
- **Templates** use the shared components in `templates/_macros.html` and the styles in `static/style.css`. Values inside `<script>` go through `|tojson`.
- **Shell scripts** use `set -euo pipefail` where possible and quote every variable.
- **Security rules:**
  - No secrets in code.
  - Parameterized SQL.
  - Commands with argument lists, never shell strings built from user input.
  - Validate everything that comes from a device or a form.
  - New dependencies are pinned with hashes in the lock files (`uv pip compile --generate-hashes`).
- **Interface:** user-facing text is plain, short English. Add German translations (`i18n.py`) and an easy-language text (`easy_language.py`) for new pages.
- **Accessibility:** new pages must be usable with a keyboard and a screen reader (labels, headings, focus). See `docs/accessibility.md`.

## Releases

- **Versioning:** [semantic versioning](https://semver.org) (`vMAJOR.MINOR.PATCH`). Tags are signed, and the release workflow publishes the release with an SBOM and the notes from `CHANGELOG.md`. Pre-releases use tags like `v1.8.0-beta.2`. Files built elsewhere (the Android APK) go into a draft release for the tag before the tag is pushed; the workflow then keeps the draft's notes, adds the files to `SHA256SUMS` and the signed provenance, and publishes the draft.
- **Security fixes** are listed in the release notes with their CVE or advisory where one exists.
