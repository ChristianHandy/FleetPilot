# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for scripts/ai_detect.py, the AI-assistance report on pull requests."""
import importlib.util
import pathlib
import subprocess
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location("ai_detect", _SCRIPTS / "ai_detect.py")
detect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detect)

TEMPLATE = "## What changes for users\n\nStuff.\n\n## AI assistance\n\n{answer}\n"
PLAIN = [("app.py", f"value_{n} = compute({n})") for n in range(60)]
AI_STYLE = ([("app.py", "# ── Helpers ──────────────────────")] * 4
            + [("app.py", "log('✓ Done — everything is ready')")] * 6
            + [("app.py", "# Security: this ensures that the input is validated")] * 4
            + PLAIN[:30])


def test_added_code_lines_skip_tests_docs_and_non_code():
    diff = ("+++ b/app.py\n@@ -0,0 +1,2 @@\n+a = 1\n+b = 2\n"
            "+++ b/test_app.py\n@@ -0,0 +1 @@\n+assert True\n"
            "+++ b/README.md\n@@ -0,0 +1 @@\n+text\n"
            "+++ b/docs/x.py\n@@ -0,0 +1 @@\n+c = 3\n")
    assert detect.added_code_lines(diff) == [("app.py", "a = 1"), ("app.py", "b = 2")]


def test_style_score_needs_enough_code_and_separates_styles():
    assert detect.style_score(PLAIN[:10]) == (None, {})
    plain, _ = detect.style_score(PLAIN)
    styled, hits = detect.style_score(AI_STYLE)
    assert plain == 0
    assert styled >= 50 and {"section dividers", "check-mark/emoji in output", "em dashes"} <= set(hits)


def test_ai_section_is_read_from_the_template():
    assert detect.ai_section(TEMPLATE.format(answer="Written with Claude Code.")) == "Written with Claude Code."
    assert detect.ai_section(TEMPLATE.format(answer="<!-- Say whether ... -->")) == "<!-- Say whether ... -->"
    assert detect.ai_section("No template at all") is None


def test_assess_outcomes():
    empty = "<!-- Say whether and how AI tools helped with this contribution. -->"
    assert detect.assess([("abc", "Co-Authored-By: Claude")], None, 10)[0] == "declared"
    assert detect.assess([], "Copilot suggested the tests.", 80)[0] == "declared"
    assert detect.assess([], empty, 80)[0] == "check"
    assert detect.assess([], "No AI tools were used.", 80)[0] == "check"
    assert detect.assess([], empty, 10)[0] == "unanswered"
    assert detect.assess([], None, None)[0] == "unanswered"
    assert detect.assess([], "None.", 5)[0] == "ok"


def _repo(tmp_path, message, author="Dev <dev@example.org>"):
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("-c", "user.name=Dev", "-c", "user.email=dev@example.org", "commit", "-q", "--allow-empty", "-m", "base")
    (tmp_path / "app.py").write_text("\n".join(text for _, text in AI_STYLE) + "\n")
    run("add", "app.py")
    name, email = author.split(" <")
    run("-c", f"user.name={name}", "-c", f"user.email={email.rstrip('>')}", "commit", "-q", "-m", message)


def test_main_reports_declared_commits(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, "Add helpers\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert detect.main(["HEAD~1", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "AI assistance is declared." in out and "Co-Authored-By: Claude" in out and "::warning" not in out


def test_main_warns_and_strict_fails_without_a_declaration(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, "Add helpers")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    body = tmp_path / "body.md"
    body.write_text(TEMPLATE.format(answer="<!-- Say whether and how AI tools helped. -->"))
    assert detect.main(["HEAD~1", "HEAD", "--pr-body", str(body)]) == 0
    assert "::warning title=AI assistance::" in capsys.readouterr().out
    assert detect.main(["HEAD~1", "HEAD", "--pr-body", str(body), "--strict"]) == 1


def test_block_ai_fails_on_declared_ai_and_on_a_high_score(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    declared = tmp_path / "declared"
    declared.mkdir()
    _repo(declared, "Add helpers\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    monkeypatch.chdir(declared)
    assert detect.main(["HEAD~1", "HEAD", "--block-ai"]) == 1
    assert "(declared)" in capsys.readouterr().out
    styled = tmp_path / "styled"
    styled.mkdir()
    _repo(styled, "Add helpers")
    monkeypatch.chdir(styled)
    body = tmp_path / "body.md"
    body.write_text(TEMPLATE.format(answer="No AI tools were used."))
    assert detect.main(["HEAD~1", "HEAD", "--pr-body", str(body), "--block-ai"]) == 1
    assert "style score" in capsys.readouterr().out


def test_block_ai_passes_plain_code_without_a_declaration(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("-c", "user.name=Dev", "-c", "user.email=dev@example.org", "commit", "-q", "--allow-empty", "-m", "base")
    (tmp_path / "app.py").write_text("\n".join(text for _, text in PLAIN) + "\n")
    run("add", "app.py")
    run("-c", "user.name=Dev", "-c", "user.email=dev@example.org", "commit", "-q", "-m", "Add values")
    monkeypatch.chdir(tmp_path)
    body = tmp_path / "body.md"
    body.write_text(TEMPLATE.format(answer="None."))
    assert detect.main(["HEAD~1", "HEAD", "--pr-body", str(body), "--block-ai"]) == 0
    assert "::error" not in capsys.readouterr().out


def test_comment_check_is_fast_on_hostile_input():
    import time
    start = time.monotonic()
    assert detect._empty("<!--" + "--><!--" * 20000 + "-->")
    assert not detect._empty("<!--" + "--><!--" * 20000)       # unclosed comment: not empty
    assert not detect._empty("<!-- x --> Used Copilot")
    assert time.monotonic() - start < 1


def test_artifacts_are_found_in_code_but_not_in_docs_or_the_detector():
    lines = [
        ("app.py", 3, "# Here's the updated code with better error handling"),
        ("app.py", 9, "    # ... existing code ..."),
        ("lib.py", 1, "```python"),
        ("config.py", 2, "API_KEY = 'your_api_key_here'"),
        ("svc.py", 5, "# In a real implementation this would call the API"),
        ("x.py", 7, "# Generated by ChatGPT"),
        ("README.md", 1, "Here's the updated code"),
        ("scripts/ai_detect.py", 1, "as an AI language model"),
        ("ok.py", 1, "value = compute()"),
    ]
    kinds = [(p, k) for p, _, k, _ in detect.find_artifacts(lines)]
    assert kinds == [("app.py", "chat leftover"), ("app.py", "elided code"), ("lib.py", "markdown code fence"),
                     ("config.py", "placeholder secret"), ("svc.py", "stub instead of code"),
                     ("x.py", "model or tool signature")]


def test_ai_tool_files_are_artifacts():
    found = detect.find_artifacts([], ["CLAUDE.md", "sub/AGENTS.md", ".cursorrules",
                                       ".github/copilot-instructions.md", "README.md", "docs/guide.md"])
    assert [p for p, *_ in found] == ["CLAUDE.md", "sub/AGENTS.md", ".cursorrules", ".github/copilot-instructions.md"]


def test_an_artifact_fails_the_pull_request_check_even_when_nothing_is_declared(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("-c", "user.name=Dev", "-c", "user.email=dev@example.org", "commit", "-q", "--allow-empty", "-m", "base")
    (tmp_path / "app.py").write_text("x = 1\n# rest of the code remains the same\n")
    run("add", "app.py")
    run("-c", "user.name=Dev", "-c", "user.email=dev@example.org", "commit", "-q", "-m", "Small change")
    monkeypatch.chdir(tmp_path)
    assert detect.main(["HEAD~1", "HEAD"]) == 1
    assert "::error file=app.py,line=2,title=AI artifact::elided code" in capsys.readouterr().out


def test_whole_repository_has_no_ai_artifacts(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(pathlib.Path(__file__).resolve().parent.parent)
    assert detect.main(["--all"]) == 0
