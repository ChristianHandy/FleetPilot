# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for scripts/ai_override.py, a maintainer's override of the AI assistance check."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location("ai_override",
                                               pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ai_override.py")
override = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(override)

HEAD = "d6b1f82a9c0e4b1f7d2a3c4e5f60718293a4b5c6"


def _comment(login, body, association="OWNER"):
    return {"user": {"login": login}, "author_association": association, "body": body,
            "html_url": f"https://example.invalid/{login}"}


def test_owner_can_allow_the_current_commit_with_a_reason():
    found = override.find_override([_comment("ChristianHandy", "/allow-ai d6b1f82 release PR, reviewed")],
                                   HEAD, "someone")
    assert found == ("ChristianHandy", "release PR, reviewed", "https://example.invalid/ChristianHandy")


def test_full_sha_and_text_around_the_command_work():
    body = f"Looked at it.\n/allow-ai {HEAD} security fix\nThanks!"
    assert override.find_override([_comment("maint", body, "MEMBER")], HEAD, "someone")[1] == "security fix"


def test_no_override_without_reason_for_another_commit_or_from_the_wrong_person():
    cases = [
        _comment("ChristianHandy", "/allow-ai d6b1f82"),                      # no reason
        _comment("ChristianHandy", "/allow-ai 1234567 reviewed"),             # other commit
        _comment("ChristianHandy", "/allow-ai d6b1f8 reviewed"),              # too short
        _comment("visitor", "/allow-ai d6b1f82 trust me", "CONTRIBUTOR"),     # not a maintainer
        _comment("visitor", "/allow-ai d6b1f82 trust me", "NONE"),
        _comment("ChristianHandy", "please /allow-ai d6b1f82 later"),         # not at the start of a line
    ]
    for comment in cases:
        assert override.find_override([comment], HEAD, "someone") is None, comment["body"]


def test_members_and_collaborators_cannot_allow_their_own_pull_request():
    for association in ("MEMBER", "COLLABORATOR"):
        assert override.find_override([_comment("helper", "/allow-ai d6b1f82 mine", association)], HEAD,
                                      "helper") is None


def test_the_owner_can_allow_their_own_pull_request():
    assert override.find_override([_comment("ChristianHandy", "/allow-ai d6b1f82 mine")], HEAD,
                                  "ChristianHandy")[0] == "ChristianHandy"


def test_the_newest_valid_override_wins():
    comments = [_comment("ChristianHandy", "/allow-ai d6b1f82 first"),
                _comment("helper", "/allow-ai d6b1f82 second", "COLLABORATOR")]
    assert override.find_override(comments, HEAD, "someone")[0] == "helper"


def test_main_reports_and_exits(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(override, "fetch_comments",
                        lambda repo, number, token: [_comment("ChristianHandy", "/allow-ai d6b1f82 ok then")])
    assert override.main(["7", HEAD, "contributor"]) == 0
    assert "::notice title=AI assistance::Allowed by @ChristianHandy" in capsys.readouterr().out
    assert override.main(["7", "0" * 40, "contributor"]) == 1
    assert "/allow-ai 0000000 <reason>" in capsys.readouterr().out
