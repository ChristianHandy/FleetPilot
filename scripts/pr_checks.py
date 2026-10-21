# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks on what a pull request changes, run by tests.yml and pr-check.yml.

    python3 scripts/pr_checks.py changed-coverage BASE coverage.json   # changed lines are tested
    python3 scripts/pr_checks.py changelog BASE HEAD [--labels FILE]   # CHANGELOG.md is updated
    python3 scripts/pr_checks.py translations BASE HEAD                # no new untranslated text
    python3 scripts/pr_checks.py size BASE HEAD                        # warn on very large changes

Each prints a short summary (also to the job summary on GitHub) and exits 1 when the
check fails. "size" only warns.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

MIN_COVERED = 70          # percent of changed executable lines that tests must run
MIN_CHANGED = 10          # fewer changed executable lines than this: nothing to judge
LARGE_PR = 800            # changed lines (lock files left out) above which reviews get hard
NO_CHANGELOG_LABEL = "no changelog"
# Changes that users don't notice and that need no changelog entry.
NO_ENTRY_NEEDED = re.compile(r"^(tests/|test_[^/]*\.py|conftest\.py|docs/|\.github/|demo/|fuzz/|\.clusterfuzzlite/|"
                             r"integrations/home-assistant/tests/)|\.md$|(^|/)requirements[^/]*-lock\.txt$|"
                             r"^(ruff\.toml|pytest\.ini|\.coveragerc|\.gitignore|\.gitattributes)$")
LOCK_FILES = re.compile(r"(^|/)(requirements[^/]*-lock\.txt|package-lock\.json)$")


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, errors="replace").stdout


def summary(text):
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


def changed_lines(diff_text):
    """{path: set of line numbers} added or changed in a unified diff (-U0)."""
    changed, path = {}, None
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@") and path:
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            start, count = int(match.group(1)), int(match.group(2) or 1)
            if count:
                changed.setdefault(path, set()).update(range(start, start + count))
    return changed


def changed_coverage(changed, coverage_files):
    """(covered, executable, [(path, missing lines)]) for the changed lines that coverage measures."""
    covered = executable = 0
    missing = []
    for path, lines in sorted(changed.items()):
        data = coverage_files.get(path)
        if not data:
            continue
        executed, not_run = set(data["executed_lines"]), set(data["missing_lines"])
        covered += len(lines & executed)
        executable += len(lines & (executed | not_run))
        if lines & not_run:
            missing.append((path, sorted(lines & not_run)))
    return covered, executable, missing


def _ranges(numbers):
    out, start, prev = [], None, None
    for n in numbers:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return ", ".join(out)


def cmd_changed_coverage(args):
    with open(args.coverage, encoding="utf-8") as fh:
        files = json.load(fh)["files"]
    diff = git("diff", "-U0", "--no-color", f"{args.base}...HEAD", "--", "*.py")
    covered, executable, missing = changed_coverage(changed_lines(diff), files)
    if executable < MIN_CHANGED:
        summary(f"## Changed lines tested\n\nOnly {executable} changed executable lines; nothing to judge.")
        return 0
    percent = 100 * covered / executable
    lines = ["## Changed lines tested", "",
             f"**{percent:.0f} %** of {executable} changed executable lines are run by the tests "
             f"(at least {MIN_COVERED} % needed)."]
    if missing:
        lines += ["", "Not run by any test:", ""] + [f"- `{p}`: lines {_ranges(n)}" for p, n in missing[:40]]
    summary("\n".join(lines))
    for path, numbers in missing[:40]:
        print(f"::notice file={path},line={numbers[0]},title=Not tested::lines {_ranges(numbers)} are not run by any test")
    if percent < MIN_COVERED:
        print(f"::error title=Changed lines tested::Only {percent:.0f} % of the changed lines are tested; "
              f"add tests for the lines listed in the summary.")
        return 1
    return 0


def cmd_changelog(args):
    changed = [p for p in git("diff", "--name-only", f"{args.base}...{args.head}").split() if p]
    needs = [p for p in changed if not NO_ENTRY_NEEDED.search(p)]
    labels = []
    if args.labels and os.path.exists(args.labels):
        with open(args.labels, encoding="utf-8") as fh:
            labels = [line.strip().lower() for line in fh if line.strip()]
    if not needs:
        summary("## Changelog\n\nOnly tests, docs or CI changed; no entry needed.")
        return 0
    if "CHANGELOG.md" in changed:
        summary("## Changelog\n\n`CHANGELOG.md` is updated.")
        return 0
    if NO_CHANGELOG_LABEL in labels:
        summary(f"## Changelog\n\nNo entry: the pull request has the label \"{NO_CHANGELOG_LABEL}\".")
        return 0
    summary("## Changelog\n\n**Missing.** These changes affect users but `CHANGELOG.md` has no entry under "
            "**Unreleased**:\n\n" + "\n".join(f"- `{p}`" for p in needs[:30]) +
            f"\n\nAdd a line, or ask a maintainer for the label \"{NO_CHANGELOG_LABEL}\" if users won't notice.")
    print("::error file=CHANGELOG.md,title=Changelog::Add an entry under Unreleased for this change.")
    return 1


def missing_counts(root):
    # The report exits 1 whenever something is missing, so its output is what counts.
    run = subprocess.run([sys.executable, os.path.join(root, "scripts", "missing_translations.py")], cwd=root,
                         check=False, capture_output=True, text=True)
    counts = {lang: int(n) for lang, n in re.findall(r"^(\w\w): (\d+)$", run.stdout, re.M)}
    if not counts and run.returncode not in (0, 1):
        raise RuntimeError(f"missing_translations.py failed: {run.stderr.strip()[-500:]}")
    return counts


def cmd_translations(args):
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = os.path.join(tmp, "base")
        git("worktree", "add", "--detach", "-q", base_dir, args.base)
        try:
            before = missing_counts(base_dir) if os.path.exists(
                os.path.join(base_dir, "scripts", "missing_translations.py")) else {}
        finally:
            git("worktree", "remove", "--force", base_dir)
    after = missing_counts(os.getcwd())
    rows = [f"| {lang} | {before.get(lang, '-')} | {n} |" for lang, n in sorted(after.items())]
    lines = ["## Translations", "", "| Language | Missing before | Missing after |", "|---|---|---|"] + rows
    new_de = after.get("de", 0) - before.get("de", after.get("de", 0))
    if new_de > 0:
        lines += ["", f"**{new_de} new interface text(s) without a German translation.** Run "
                  "`python3 scripts/missing_translations.py --lang de` and add them to `i18n.py`."]
        summary("\n".join(lines))
        print(f"::error file=i18n.py,title=Translations::{new_de} new text(s) need a German translation.")
        return 1
    summary("\n".join(lines + ["", "No new untranslated German text."]))
    return 0


def cmd_size(args):
    added = deleted = 0
    for row in git("diff", "--numstat", f"{args.base}...{args.head}").splitlines():
        parts = row.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and not LOCK_FILES.search(parts[2]):
            added, deleted = added + int(parts[0]), deleted + int(parts[1])
    total = added + deleted
    summary(f"## Size\n\n{total} changed lines (+{added} / -{deleted}, lock files left out).")
    if total > LARGE_PR:
        print(f"::warning title=Large pull request::{total} changed lines. Smaller pull requests get reviewed "
              "faster and more carefully; consider splitting it.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("changed-coverage")
    p.add_argument("base")
    p.add_argument("coverage")
    for name in ("changelog", "translations", "size"):
        p = sub.add_parser(name)
        p.add_argument("base")
        p.add_argument("head")
        if name == "changelog":
            p.add_argument("--labels", help="file with the pull request's labels, one per line")
    args = parser.parse_args(argv)
    return {"changed-coverage": cmd_changed_coverage, "changelog": cmd_changelog,
            "translations": cmd_translations, "size": cmd_size}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
