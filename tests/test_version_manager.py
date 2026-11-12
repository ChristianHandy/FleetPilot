# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for version_manager branch name validation and update check interval."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

import version_manager


@pytest.mark.parametrize("name", [
    "main",
    "release/v1.2.3",
    "feature/my-branch_2",
])
def test_sanitize_branch_name_accepted(name):
    assert version_manager.sanitize_branch_name(name) == name


@pytest.mark.parametrize("name", [
    "",
    None,
    "--upload-pack=x",
    "/etc",
    "a/../b",
    "a/./b",
    "a.",
    "a b",
    "a;b",
    "a" * 256,
])
def test_sanitize_branch_name_rejected(name):
    with pytest.raises(ValueError):
        version_manager.sanitize_branch_name(name)


def test_should_check_for_updates_no_last_check():
    with patch.object(version_manager, "load_version_data", return_value={"last_check": None}):
        assert version_manager.should_check_for_updates() is True


def test_should_check_for_updates_old():
    old = (datetime.now() - timedelta(hours=25)).isoformat()
    with patch.object(version_manager, "load_version_data", return_value={"last_check": old}):
        assert version_manager.should_check_for_updates() is True


def test_should_check_for_updates_recent():
    recent = (datetime.now() - timedelta(hours=1)).isoformat()
    with patch.object(version_manager, "load_version_data", return_value={"last_check": recent}):
        assert version_manager.should_check_for_updates() is False


def test_should_check_for_updates_unparseable():
    with patch.object(version_manager, "load_version_data", return_value={"last_check": "not-a-date"}):
        assert version_manager.should_check_for_updates() is True


# ── Release comparison in check_for_updates (#209) ─────────────────────────
#
# GitHub's target_commitish for a release is the branch name ("main"), not a
# commit SHA, so the old SHA comparison reported "new release available" on
# every check. These tests mock the GitHub responses and pin the version
# comparison, the dismissal handling and the fall-through to the commit check.

@pytest.mark.parametrize("candidate, current, expected", [
    ("v1.9.0", "1.8.1", True),
    ("1.8.0", "1.8.1", False),
    ("1.8.1", "1.8.1", False),
    ("v1.10.0", "v1.9.9", True),
    ("1.8.0-beta.2", "1.8.0", False),   # a pre-release is older than its release
    ("1.8.0", "1.8.0-beta.2", True),
    ("", "1.8.0", False),
    ("1.8.0", "", False),
    ("not-a-version", "1.8.0", False),
])
def test_is_newer_version(candidate, current, expected):
    assert version_manager._is_newer_version(candidate, current) is expected


@pytest.mark.parametrize("candidate, current, expected", [
    ("v1.9.0", "1.8.1", True),
    ("1.8.0", "1.8.1", False),
    ("1.8.0-beta.2", "1.8.0", False),
    ("1.8.0", "1.8.0-beta.2", True),
    ("1.10.0", "1.9.9", True),
    ("not-a-version", "1.8.0", False),
])
def test_is_newer_version_without_packaging(monkeypatch, candidate, current, expected):
    # The fallback key parser must agree with packaging on the common shapes.
    monkeypatch.setattr(version_manager, "_packaging_version", None)
    assert version_manager._is_newer_version(candidate, current) is expected


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload


_CURRENT_SHA = "a" * 40


def _release(tag):
    # target_commitish is what GitHub really returns: the branch name.
    return {"tag_name": tag, "target_commitish": "main",
            "html_url": f"https://example.test/releases/{tag}",
            "name": f"FleetPilot {tag}"}


def _commit(sha):
    return {"sha": sha, "html_url": "https://example.test/commit",
            "commit": {"message": "Fix a bug\n\nDetails"}}


def _run_update_check(monkeypatch, release, commit, current="v1.8.1", saved=None):
    stored = {"last_check": None, "current_version": None, "latest_version": None,
              "update_available": False, "update_type": None, "update_url": None,
              "update_description": None, "notification_dismissed": False,
              "last_notified": None}
    if saved:
        stored.update(saved)
    monkeypatch.setattr(version_manager, "load_version_data", lambda: dict(stored))
    monkeypatch.setattr(version_manager, "save_version_data", lambda data: None)
    monkeypatch.setattr(version_manager, "get_current_commit_sha", lambda: _CURRENT_SHA)
    monkeypatch.setattr(version_manager, "get_current_branch", lambda: "main")
    monkeypatch.setattr(version_manager, "get_current_version", lambda: current)
    monkeypatch.setattr(version_manager, "fire_app_hook", lambda *a, **k: None)
    monkeypatch.setattr("constants.offline_mode", lambda: False)

    def fake_get(url, timeout=None):
        return _FakeResponse(release if url.endswith("/releases/latest") else commit)

    monkeypatch.setattr(version_manager.requests, "get", fake_get)
    return version_manager.check_for_updates()


def test_update_check_same_version_is_not_an_update(monkeypatch):
    data = _run_update_check(monkeypatch, _release("v1.8.1"), _commit(_CURRENT_SHA))
    assert data["update_available"] is False
    assert data["update_type"] is None


def test_update_check_older_release_is_not_an_update(monkeypatch):
    data = _run_update_check(monkeypatch, _release("v1.8.0"), _commit(_CURRENT_SHA))
    assert data["update_available"] is False


def test_update_check_newer_release(monkeypatch):
    data = _run_update_check(monkeypatch, _release("v1.9.0"), _commit(_CURRENT_SHA))
    assert data["update_available"] is True
    assert data["update_type"] == "release"
    assert data["latest_version"] == "v1.9.0"
    assert data["notification_dismissed"] is False


def test_update_check_keeps_dismissal_for_the_same_release(monkeypatch):
    saved = {"latest_version": "v1.9.0", "notification_dismissed": True}
    data = _run_update_check(monkeypatch, _release("v1.9.0"), _commit(_CURRENT_SHA),
                             saved=saved)
    assert data["update_available"] is True
    assert data["notification_dismissed"] is True


def test_update_check_rearms_dismissal_for_a_newer_release(monkeypatch):
    saved = {"latest_version": "v1.9.0", "notification_dismissed": True}
    data = _run_update_check(monkeypatch, _release("v2.0.0"), _commit(_CURRENT_SHA),
                             saved=saved)
    assert data["update_available"] is True
    assert data["notification_dismissed"] is False


def test_update_check_prerelease_of_the_running_version_is_not_an_update(monkeypatch):
    data = _run_update_check(monkeypatch, _release("v1.8.0-beta.2"),
                             _commit(_CURRENT_SHA), current="v1.8.0")
    assert data["update_available"] is False


def test_update_check_release_after_its_prerelease(monkeypatch):
    data = _run_update_check(monkeypatch, _release("v1.8.0"),
                             _commit(_CURRENT_SHA), current="v1.8.0-beta.2")
    assert data["update_available"] is True
    assert data["update_type"] == "release"


def test_update_check_falls_through_to_a_newer_commit(monkeypatch):
    data = _run_update_check(monkeypatch, _release("v1.8.1"), _commit("b" * 40))
    assert data["update_available"] is True
    assert data["update_type"] == "commit"
    assert data["latest_version"] == "bbbbbbb"
