# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""scripts/ai_share.py counts declared AI help per month and leaves bots and lock files out."""
import importlib.util
import pathlib
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ai_share.py"


@pytest.fixture
def ai_share():
    spec = importlib.util.spec_from_file_location("ai_share", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _commit(repo, author, message, files, date):
    for name, lines in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n" * lines)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    name, email = author.split(" <")
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email.rstrip(">"), "GIT_AUTHOR_DATE": date,
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "GIT_COMMITTER_DATE": date,
           "PATH": "/usr/bin:/bin", "HOME": str(repo)}
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message], cwd=repo, check=True,
                   env=env)


def test_monthly_share_counts_declared_ai_and_skips_bots_and_lock_files(tmp_path, ai_share, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    jan, feb = "2026-01-10T12:00:00+00:00", "2026-02-10T12:00:00+00:00"
    _commit(tmp_path, "Ann <ann@example.org>", "by hand", {"a.py": 30}, jan)
    _commit(tmp_path, "Ann <ann@example.org>", "with help\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
            {"b.py": 10}, jan)
    _commit(tmp_path, "copilot-swe-agent[bot] <1+Copilot@users.noreply.github.com>", "agent", {"c.py": 60}, feb)
    _commit(tmp_path, "dependabot[bot] <2+dependabot[bot]@users.noreply.github.com>", "bump",
            {"d.py": 1000}, feb)
    _commit(tmp_path, "Ann <ann@example.org>", "lock only", {"requirements-lock.txt": 500}, feb)
    monkeypatch.chdir(tmp_path)

    months = ai_share.monthly("HEAD")

    assert list(months) == ["2026-01", "2026-02"]
    assert months["2026-01"] == {"ai": 10, "all": 40, "ai_commits": 1, "commits": 2}
    assert ai_share.share(months["2026-01"]) == 25.0
    # Dependabot is left out; the lock file counts as a commit without lines.
    assert months["2026-02"] == {"ai": 60, "all": 60, "ai_commits": 1, "commits": 2}
    chart = ai_share.svg(months)
    assert chart.startswith("<svg") and "Jan 2026: 25.0 %" in chart and "goal: as low as we can get" in chart


def test_codebase_share_attributes_current_lines_by_blame(tmp_path, ai_share, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    day = "2026-03-01T12:00:00+00:00"
    _commit(tmp_path, "Ann <ann@example.org>", "by hand", {"app.py": 30, "notes.md": 50}, day)
    _commit(tmp_path, "Ann <ann@example.org>", "with help\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
            {"lib/tool.py": 10}, day)
    _commit(tmp_path, "dependabot[bot] <2+dependabot[bot]@users.noreply.github.com>", "bump",
            {"lib/bot.py": 100}, day)
    _commit(tmp_path, "Ann <ann@example.org>", "vendored", {"static/vendor/x.js": 400}, day)
    monkeypatch.chdir(tmp_path)
    result = ai_share.codebase("HEAD")
    assert (result["ai"], result["all"], result["files"]) == (10, 40, 2)   # md, bot and vendor lines left out
    assert result["share"] == 25.0
    assert result["areas"]["lib"] == {"ai": 10, "all": 10, "share": 100.0}
    assert result["areas"]["core"]["share"] == 0.0


def test_badge_shows_the_rounded_share(ai_share):
    svg = ai_share.badge(79.6)
    assert 'aria-label="AI-written code: 80 %"' in svg and svg.startswith("<svg") and "#d64545" in svg
    assert "#2f9e44" in ai_share.badge(10)


def test_trend_measures_all_code_at_each_month_end(tmp_path, ai_share, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    ai = "with help\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    _commit(tmp_path, "Ann <ann@example.org>", ai, {"app.py": 30}, "2026-03-10T12:00:00+00:00")
    _commit(tmp_path, "Ann <ann@example.org>", "by hand", {"tool.py": 10}, "2026-03-20T12:00:00+00:00")
    (tmp_path / "app.py").write_text("y\n" * 30)   # every AI-written line rewritten by hand
    _commit(tmp_path, "Ann <ann@example.org>", "rewritten by hand", {}, "2026-04-05T12:00:00+00:00")
    monkeypatch.chdir(tmp_path)
    months = ai_share.monthly("HEAD")
    assert list(months) == ["2026-03", "2026-04"]
    assert ai_share.trend("HEAD", months) == {"2026-03": 75.0, "2026-04": 0.0}


def test_chart_draws_the_trend_line_only_when_given(ai_share):
    months = {"2026-03": {"ai": 3, "all": 4, "ai_commits": 1, "commits": 2},
              "2026-04": {"ai": 0, "all": 30, "ai_commits": 0, "commits": 1}}
    plain = ai_share.svg(months)
    assert "<polyline" not in plain and "all code at month end" not in plain
    chart = ai_share.svg(months, {"2026-03": 75.0, "2026-04": 0.0})
    assert chart.count("<circle") == 2 and "<polyline" in chart and "all code at month end" in chart
    assert "2026-03: 75.0 % of all code" in chart and "2026-03: 75.0 % of changed lines, 75.0 % of all code" in chart


def test_direction_says_whether_the_ai_share_goes_up_or_down(ai_share):
    assert ai_share.direction({"2026-08": 55.6, "2026-10": 78.4}) == ("up", 22.8, "2026-08")
    assert ai_share.direction({"2026-09": 60.0, "2026-10": 52.0}) == ("down", -8.0, "2026-09")
    assert ai_share.direction({"2026-09": 60.0, "2026-10": 60.2})[0] == "flat"
    assert ai_share.direction({"2026-10": 60.0}) is None
    months = {"2026-09": {"ai": 6, "all": 10, "ai_commits": 1, "commits": 1},
              "2026-10": {"ai": 1, "all": 10, "ai_commits": 1, "commits": 1}}
    assert "▼ going down: -8.0 points since Sep 2026" in ai_share.svg(months, {"2026-09": 60.0, "2026-10": 52.0})
    assert "going" not in ai_share.svg(months)
