# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for scripts/pr_checks.py, the checks on what a pull request changes."""
import importlib.util
import json
import pathlib
import subprocess

_spec = importlib.util.spec_from_file_location("pr_checks", pathlib.Path(__file__).parent / "scripts" / "pr_checks.py")
checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checks)


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=Dev", "-c", "user.email=dev@example.org", "-c", "commit.gpgsign=false",
                    *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path, files_before, files_after):
    _git(tmp_path, "init", "-q")
    for name, text in files_before.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "base")
    for name, text in files_after.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "change")


def test_changed_lines_and_ranges():
    diff = "+++ b/a.py\n@@ -1,0 +2,3 @@\n+x\n+y\n+z\n@@ -9 +12 @@\n+w\n+++ b/b.py\n@@ -3,2 +2,0 @@\n"
    assert checks.changed_lines(diff) == {"a.py": {2, 3, 4, 12}}
    assert checks._ranges([1, 2, 3, 7, 9, 10]) == "1-3, 7, 9-10"


def test_changed_coverage_counts_only_executable_lines():
    files = {"a.py": {"executed_lines": [1, 2, 3], "missing_lines": [4, 5]}}
    covered, executable, missing = checks.changed_coverage({"a.py": {2, 4, 6}, "unmeasured.py": {1}}, files)
    assert (covered, executable, missing) == (1, 2, [("a.py", [4])])


def test_changed_coverage_command_fails_below_the_minimum(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    _repo(tmp_path, {"a.py": ""}, {"a.py": "".join(f"x{n} = {n}\n" for n in range(20))})
    cov = tmp_path / "cov.json"
    cov.write_text(json.dumps({"files": {"a.py": {"executed_lines": list(range(1, 11)),
                                                  "missing_lines": list(range(11, 21))}}}))
    monkeypatch.chdir(tmp_path)
    assert checks.main(["changed-coverage", "HEAD~1", str(cov)]) == 1
    assert "50 %" in capsys.readouterr().out
    cov.write_text(json.dumps({"files": {"a.py": {"executed_lines": list(range(1, 19)), "missing_lines": [19, 20]}}}))
    assert checks.main(["changed-coverage", "HEAD~1", str(cov)]) == 0


def test_changelog_required_only_for_user_visible_changes(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    labels = tmp_path / "labels"
    tmp_path = tmp_path / "repo"
    tmp_path.mkdir()
    monkeypatch.chdir(tmp_path)
    _repo(tmp_path, {"app.py": "a\n", "CHANGELOG.md": "x\n"}, {"app.py": "b\n"})
    assert checks.main(["changelog", "HEAD~1", "HEAD"]) == 1
    labels.write_text("bug\nno changelog\n")
    assert checks.main(["changelog", "HEAD~1", "HEAD", "--labels", str(labels)]) == 0
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "noop")
    (tmp_path / "test_app.py").write_text("t\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("g\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "tests and docs")
    assert checks.main(["changelog", "HEAD~1", "HEAD"]) == 0
    (tmp_path / "app.py").write_text("c\n")
    (tmp_path / "CHANGELOG.md").write_text("x\n- c\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "with entry")
    assert checks.main(["changelog", "HEAD~1", "HEAD"]) == 0


def test_size_warns_but_never_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(tmp_path)
    _repo(tmp_path, {}, {"big.py": "x\n" * 900, "requirements-lock.txt": "y\n" * 5000})
    assert checks.main(["size", "HEAD~1", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "900 changed lines" in out and "::warning title=Large pull request::" in out


def test_translations_fail_on_new_untranslated_german_text(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    counter = ("import re,glob\n"
               "n=sum(len(re.findall(r'NEW', open(f).read())) for f in glob.glob('templates/*.html'))\n"
               "print('Missing translations:'); print(f'de: {n}'); print('fr: 0')\n")
    _repo(tmp_path, {"scripts/missing_translations.py": counter, "templates/a.html": "NEW\n"},
          {"templates/a.html": "NEW\nNEW\n"})
    monkeypatch.chdir(tmp_path)
    assert checks.main(["translations", "HEAD~1", "HEAD"]) == 1
    assert "1 new interface text" in capsys.readouterr().out
    assert checks.main(["translations", "HEAD", "HEAD"]) == 0
