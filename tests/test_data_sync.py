# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the data-sync file allow-list and sync-token check."""
import os
import types

import pytest

import data_sync

LONG_TOKEN = "s" * 32


@pytest.fixture
def sync_dirs(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    app_dir = tmp_path / "app"
    data_dir.mkdir()
    app_dir.mkdir()
    monkeypatch.setattr(data_sync, "_data_dir", str(data_dir))
    monkeypatch.setattr(data_sync, "_app_dir", str(app_dir))
    return str(data_dir), str(app_dir)


def _request(token=None):
    headers = {} if token is None else {"X-Sync-Token": token}
    return types.SimpleNamespace(headers=headers)


@pytest.mark.parametrize("fname", data_sync.SYNC_FILES)
def test_every_data_file_maps_into_the_data_dir(sync_dirs, fname):
    data_dir, _app_dir = sync_dirs
    assert data_sync._resolve_sync_path(fname) == os.path.join(data_dir, fname)


def test_users_db_maps_into_the_app_dir(sync_dirs):
    _data_dir, app_dir = sync_dirs
    assert data_sync._resolve_sync_path("users.db") == os.path.join(
        app_dir, "users.db"
    )


@pytest.mark.parametrize(
    "fname",
    [
        "../hosts.json",
        "/etc/passwd",
        "hosts.json/../users.db",
        "HOSTS.JSON",
        "",
        "secrets.json",
    ],
)
def test_unlisted_and_traversal_names_are_rejected(sync_dirs, fname):
    assert data_sync._resolve_sync_path(fname) is None


def test_token_ok_without_a_configured_token(monkeypatch):
    monkeypatch.setattr(data_sync, "SYNC_TOKEN", "")
    assert data_sync._token_ok(_request()) is False
    assert data_sync._token_ok(_request("")) is False
    assert data_sync._token_ok(_request(LONG_TOKEN)) is False


def test_token_ok_with_a_too_short_configured_token(monkeypatch):
    short = "x" * (data_sync._MIN_TOKEN_LEN - 1)
    monkeypatch.setattr(data_sync, "SYNC_TOKEN", short)
    assert data_sync._token_ok(_request(short)) is False


def test_token_ok_with_the_configured_token(monkeypatch):
    monkeypatch.setattr(data_sync, "SYNC_TOKEN", LONG_TOKEN)
    assert data_sync._token_ok(_request(LONG_TOKEN)) is True


def test_token_ok_rejects_wrong_and_missing_tokens(monkeypatch):
    monkeypatch.setattr(data_sync, "SYNC_TOKEN", LONG_TOKEN)
    assert data_sync._token_ok(_request("s" * 31 + "x")) is False
    assert data_sync._token_ok(_request()) is False
    assert data_sync._token_ok(_request("")) is False
