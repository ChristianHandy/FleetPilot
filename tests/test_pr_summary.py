# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for scripts/pr_summary.py, the summary comment on pull requests."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location("pr_summary",
                                               pathlib.Path(__file__).resolve().parent.parent / "scripts" / "pr_summary.py")
summary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(summary)

SHA = "d6b1f82a9c0e4b1f7d2a3c4e5f60718293a4b5c6"


def _pr(**extra):
    return {"number": 7, "head": {"sha": SHA}, "base": {"ref": "main"}, "mergeable": True, "draft": False, **extra}


def _run(name, conclusion="success", status="completed", run_id=1):
    return {"id": run_id, "name": name, "status": status, "conclusion": conclusion,
            "details_url": f"https://example.invalid/{run_id}"}


def _all_required(conclusion="success"):
    return [_run(n, conclusion, run_id=i) for i, n in enumerate(summary.REQUIRED, 1)]


def test_files_are_grouped_by_area():
    files = [{"filename": f, "additions": 1, "deletions": 0} for f in (
        "app.py", "templates/index.html", "tests/test_app.py", ".github/workflows/x.yml", "requirements-lock.txt",
        "FleetPilotAndroid/app/Main.java", "docs/guide.md", "README.md", "install.sh", "i18n.py",
        "addons/ping.py", "scripts/pr_summary.py", "LICENSE")]
    got = {a: n for a, n, _, _ in summary.areas(files)}
    assert got == {"App code": 1, "Web pages": 1, "Tests": 1, "Workflows and CI": 1, "Dependencies": 1,
                   "Android app": 1, "Documentation": 2, "Install and update scripts": 1, "Translations": 1,
                   "Plugins": 1, "Developer scripts": 1, "Other files": 1}


def test_a_re_run_replaces_the_older_result():
    runs = [_run("Safe to merge", "failure", run_id=5), _run("Safe to merge", "success", run_id=9)]
    assert summary.state(summary.latest_checks(runs)["Safe to merge"]) == "passed"


def test_verdicts():
    checks = summary.latest_checks(_all_required())
    assert summary.verdict(_pr(), checks)[0] == "ready"
    assert summary.verdict(_pr(mergeable=None), checks)[0] == "ready"   # GitHub has not computed it yet
    assert summary.verdict(_pr(mergeable=False), checks)[0] == "blocked"
    assert summary.verdict(_pr(draft=True), checks)[0] == "blocked"
    waiting = dict(checks, **{"AI assistance": _run("AI assistance", None, "in_progress", 99)})
    assert summary.verdict(_pr(), waiting)[0] == "waiting"
    missing = {n: r for n, r in checks.items() if n != "Analyze (python)"}
    assert summary.verdict(_pr(), missing)[0] == "waiting"
    failed = dict(checks, **{"AI assistance": _run("AI assistance", "failure", run_id=99)})
    level, _, reasons = summary.verdict(_pr(), failed)
    assert level == "blocked" and "*AI assistance*" in reasons[0]


def test_render_shows_checks_failures_and_hints():
    runs = _all_required() + [_run("pytest (Python 3.11)", "failure", run_id=50),
                              _run("pytest (Python 3.12)", "failure", run_id=51),
                              _run("AI assistance", "failure", run_id=52),
                              _run("Fortify SAST (SSC)", "failure", run_id=53),
                              _run("zizmor", run_id=54), _run("pr-fuzzing", None, "queued", 55)]
    files = [{"filename": "app.py", "status": "modified", "additions": 3, "deletions": 1}]
    body = summary.render(_pr(), files, runs)
    assert body.startswith(summary.MARKER + "\n## :red_circle: Not ready to merge")
    assert "1 files, +3 / -1 lines." in body and "| App code | 1 | +3 | -1 |" in body
    assert "| [pytest (Python 3.11)](https://example.invalid/50) | :x: failed |" in body
    assert "| [Safe to merge](https://example.invalid/5) | :white_check_mark: passed |" in body
    assert "Other checks: 1 passed, 1 failed, 1 running." in body
    assert "- [Fortify SAST (SSC)](https://example.invalid/53)" in body
    assert body.count("**pytest:**") == 1
    assert "`/allow-ai d6b1f82 <reason>`" in body


def test_render_ready_and_long_file_lists():
    files = [{"filename": f"docs/{n}.md", "additions": 1, "deletions": 1} for n in range(305)]
    body = summary.render(_pr(), files, _all_required())
    assert "## :green_circle: Ready to merge" in body and "How to fix" not in body
    assert "- ... and 5 more" in body


class FakeGitHub:
    def __init__(self, comments=(), open_prs=None, head=SHA):
        self.comments, self.calls = list(comments), []
        self.open_prs = [{"number": 7, "head": {"sha": SHA}}] if open_prs is None else open_prs
        self.head = head

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "pulls/7":
            return _pr(head={"sha": self.head})
        return {}

    def pages(self, path, key=None):
        if path.startswith("pulls?"):
            return self.open_prs
        if path == "issues/7/comments":
            return self.comments
        if path == "pulls/7/files":
            return [{"filename": "app.py", "additions": 1, "deletions": 0}]
        return _all_required()


def test_main_creates_then_updates_one_comment(capsys):
    gh = FakeGitHub()
    assert summary.main([SHA], gh) == 0
    method, path, body = gh.calls[-1]
    assert (method, path) == ("POST", "issues/7/comments") and "Ready to merge" in body["body"]
    mine = {"id": 3, "user": {"login": summary.BOT}, "body": summary.MARKER + "\nold"}
    someone = {"id": 4, "user": {"login": "visitor"}, "body": summary.MARKER + "\nfake"}
    gh = FakeGitHub(comments=[someone, mine])
    assert summary.main([SHA, "7"], gh) == 0
    assert gh.calls[-1][:2] == ("PATCH", "issues/comments/3")
    assert "updated on #7" in capsys.readouterr().out


def test_main_skips_unknown_or_outdated_commits(capsys):
    assert summary.main([SHA], FakeGitHub(open_prs=[])) == 0
    assert "nothing to do" in capsys.readouterr().out
    gh = FakeGitHub(head="0" * 40)
    assert summary.main([SHA], gh) == 0
    assert "moved on" in capsys.readouterr().out
    assert not any(m in ("POST", "PATCH") for m, _, _ in gh.calls)
