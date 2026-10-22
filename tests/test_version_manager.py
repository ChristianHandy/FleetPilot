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
