# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare a FleetPilot release: work out the next version and write it everywhere.

    python3 scripts/release.py next KIND        # print the next version
    python3 scripts/release.py apply VERSION    # set VERSION and close the changelog section
    python3 scripts/release.py stable-base      # print the newest stable tag (base of a hotfix)

KIND is one of:

    beta     the next beta: 1.8.0 -> 1.9.0-beta.1, 1.9.0-beta.1 -> 1.9.0-beta.2
    release  the main release: 1.9.0-beta.2 -> 1.9.0, or 1.8.0 -> 1.9.0 without a beta
    major    1.9.0 -> 2.0.0
    patch    a subrelease from main: 1.8.0 -> 1.8.1 (not while main is on a beta)
    hotfix   the same bump as patch, made on the release branch of the newest stable
             release (release/1.8 for v1.8.0) instead of main

"apply" writes the version to fleetpilot_version.py and the Android app (versionName,
and versionCode + 1), and turns the changelog's Unreleased section into the new
version's section. It refuses when Unreleased is empty. Used by prepare-release.yml.
"""
import datetime
import os
import pathlib
import re
import subprocess
import sys

# RELEASE_ROOT lets the workflow run this script (from main) on an older release branch.
ROOT = pathlib.Path(os.environ.get("RELEASE_ROOT") or pathlib.Path(__file__).resolve().parent.parent)
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")
KINDS = ("beta", "release", "major", "patch", "hotfix")


class ReleaseError(Exception):
    pass


def parse(version):
    match = VERSION_RE.match(version)
    if not match:
        raise ReleaseError(f"{version!r} is not a version like 1.8.1 or 1.9.0-beta.1")
    major, minor, patch, beta = match.groups()
    return int(major), int(minor), int(patch), int(beta) if beta else None


def next_version(kind, current):
    major, minor, patch, beta = parse(current)
    if kind == "beta":
        if beta is not None:
            return f"{major}.{minor}.{patch}-beta.{beta + 1}"
        return f"{major}.{minor + 1}.0-beta.1"
    if kind == "release":
        if beta is not None:
            return f"{major}.{minor}.{patch}"
        return f"{major}.{minor + 1}.0"
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind in ("patch", "hotfix"):
        if beta is not None:
            raise ReleaseError(f"{current} is a beta; a patch of the last stable release is a hotfix "
                               "(made on its release branch), or finish the beta with 'release'")
        return f"{major}.{minor}.{patch + 1}"
    raise ReleaseError(f"unknown kind {kind!r}; use one of {', '.join(KINDS)}")


def current_version(root=ROOT):
    text = (root / "fleetpilot_version.py").read_text(encoding="utf-8")
    return re.search(r'^VERSION = "([^"]+)"', text, re.M).group(1)


def stable_base(tags):
    """The newest stable tag (vX.Y.Z without a suffix) among ``tags``."""
    stable = [t for t in tags if t.startswith("v") and VERSION_RE.match(t[1:]) and "-" not in t]
    if not stable:
        raise ReleaseError("no stable release tag found")
    return max(stable, key=lambda t: parse(t[1:])[:3])


def _replace(text, name, pattern, repl):
    new, count = re.subn(pattern, repl, text, count=1, flags=re.M)
    if count != 1:
        raise ReleaseError(f"{name}: pattern {pattern!r} not found")
    return new


def close_changelog(text, version, date):
    head = "## [Unreleased]\n"
    start = text.find(head)
    if start < 0:
        raise ReleaseError("CHANGELOG.md has no '## [Unreleased]' section")
    body_start = start + len(head)
    end = text.find("\n## [", body_start)
    end = len(text) if end < 0 else end + 1
    body = text[body_start:end]
    if not body.strip():
        raise ReleaseError("nothing under Unreleased in CHANGELOG.md; merge the changes "
                           "(each with a changelog line) before preparing a release")
    if f"## [{version}]" in text:
        raise ReleaseError(f"CHANGELOG.md already has a section for {version}")
    return text[:body_start] + f"\n## [{version}] — {date}\n" + body.rstrip("\n") + "\n\n" + text[end:]


def apply(version, root=ROOT, date=None):
    """Write ``version`` everywhere; every file is checked before any is written."""
    parse(version)
    current = current_version(root)
    if parse(version) == parse(current):
        raise ReleaseError(f"the version already is {version}")
    date = date or datetime.date.today().isoformat()
    paths = {"changelog": root / "CHANGELOG.md", "version": root / "fleetpilot_version.py",
             "gradle": root / "FleetPilotAndroid" / "app" / "build.gradle.kts"}
    missing = [str(p.relative_to(root)) for p in paths.values() if not p.exists()]
    if missing:
        raise ReleaseError("missing: " + ", ".join(missing))
    old = {k: p.read_text(encoding="utf-8") for k, p in paths.items()}
    new = {"changelog": close_changelog(old["changelog"], version, date),
           "version": _replace(old["version"], "fleetpilot_version.py", r'^VERSION = "[^"]+"', f'VERSION = "{version}"')}
    code = re.search(r"^\s*versionCode = (\d+)", old["gradle"], re.M)
    if not code:
        raise ReleaseError("build.gradle.kts: versionCode not found")
    gradle = _replace(old["gradle"], "build.gradle.kts", r"^(\s*)versionCode = \d+",
                      rf"\g<1>versionCode = {int(code.group(1)) + 1}")
    new["gradle"] = _replace(gradle, "build.gradle.kts", r'^(\s*)versionName = "[^"]+"',
                             rf'\g<1>versionName = "{version}"')
    # Release branches older than 1.8.1 still pin the version in this test.
    for test in (root / "tests" / "test_production_hardening.py", root / "test_production_hardening.py"):
        if test.exists() and f"'{current}'" in test.read_text(encoding="utf-8"):
            paths["test"] = test
            new["test"] = (test.read_text(encoding="utf-8").replace(f"'v{current}'", f"'v{version}'")
                           .replace(f"'{current}'", f"'{version}'")
                           .replace(f"FleetPilot v{current}'", f"FleetPilot v{version}'"))
    for key, text in new.items():
        paths[key].write_text(text, encoding="utf-8")
    return current


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) == 2 and argv[0] == "next":
            print(next_version(argv[1], current_version()))
        elif len(argv) == 2 and argv[0] == "apply":
            old = apply(argv[1])
            print(f"{old} -> {argv[1]}")
        elif argv == ["stable-base"]:
            tags = subprocess.run(["git", "tag", "--list", "v*"], cwd=ROOT, check=True,
                                  capture_output=True, text=True).stdout.split()
            print(stable_base(tags))
        else:
            sys.exit(__doc__)
    except ReleaseError as exc:
        print(f"::error title=Release::{exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
