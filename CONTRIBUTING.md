# Contributing to FleetPilot

Thanks for helping. Bug reports, ideas, translations, documentation and code are all welcome.

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
   python -m pytest -q
   ruff check --select F821,F811,F823,F632,F601,F707,E9 --exclude FleetPilotCS,FleetPilotAndroid .
   ```
5. Open a pull request against `main` and describe what changes for users and how you tested it.

`main` is protected: every change goes through a pull request, and CI must pass before it is merged. CI runs the tests on Python 3.11–3.13, a linter, Bandit, pip-audit, CodeQL, the fuzzers, and a test that boots the live demo.

By contributing you agree that your contribution is licensed under the project's license, [GPL-3.0](LICENSE).

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

- **New functionality comes with automated tests** in a `test_*.py` file at the top level (pytest). Pull requests that add features without tests are asked to add them.
- **Bug fixes come with a test** that fails without the fix whenever that is practical.
- Code that talks to devices is tested against recorded or emulated output. See `test_routers.py` and the emulated lab in `demo/live/lab`.
- Parsers for data from the network belong in the fuzzer (`fuzz/fuzz_parsers.py`).

## Coding style

- **Code:** Python 3.11+, following the style of the surrounding code (PEP 8, 120 columns). Templates use the shared components in `templates/_macros.html` and the styles in `static/style.css`.
- **Security rules:**
  - No secrets in code.
  - Parameterized SQL.
  - Commands with argument lists, never shell strings built from user input.
  - Validate everything that comes from a device or a form.
  - New dependencies are pinned with hashes in the lock files (`uv pip compile --generate-hashes`).
- **Interface:** user-facing text is plain, short English. Add German translations (`i18n.py`) and an easy-language text (`easy_language.py`) for new pages.
- **Accessibility:** new pages must be usable with a keyboard and a screen reader (labels, headings, focus). See `docs/accessibility.md`.

## Releases

- **Versioning:** [semantic versioning](https://semver.org) (`vMAJOR.MINOR.PATCH`). Tags are signed, and the release workflow publishes the release with an SBOM and the notes from `CHANGELOG.md`.
- **Security fixes** are listed in the release notes with their CVE or advisory where one exists.
