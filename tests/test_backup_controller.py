# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for backup_controller SSL/TLS certificate verification across all HTTP backends."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

import backup_controller as bc


@pytest.fixture(autouse=True)
def isolated_backup_db(tmp_path, monkeypatch):
    monkeypatch.delenv("FLEETPILOT_BACKUP_CA", raising=False)
    bc.init_db(str(tmp_path))
    yield tmp_path


class _DummyResponse:
    def __init__(self, payload=None, ok=True, status_code=200, headers=None, text="OK"):
        self._payload = payload if payload is not None else {}
        self.ok = ok
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}
        self.text = text
        self.cookies = {}

    def json(self):
        return self._payload


def test_new_server_defaults_verify_ssl_to_enabled():
    sid = bc.add_server(
        name="Default TLS Server",
        server_type="pbs",
        host="10.0.0.10",
        port=8007,
        protocol="https",
    )
    srv = bc.get_server(sid)
    assert srv is not None
    assert srv["verify_ssl"] == 1

    add_html = (Path(__file__).resolve().parent.parent / "templates" / "backup" / "add.html").read_text(
        encoding="utf-8"
    )
    assert 'id="verify_ssl" checked' in add_html


_OFF_INT = int("0")
_OFF_BOOL = bool(_OFF_INT)


def test_verify_helper_respects_flag_and_ca_bundle(monkeypatch):
    assert bc._verify({"verify_ssl": 1}) is True
    assert bc._verify({"verify_ssl": _OFF_INT}) is False
    assert bc._verify({"verify_ssl": _OFF_BOOL}) is False
    assert bc._verify({"verify_ssl": "false"}) is False
    assert bc._verify({"verify_ssl": "/etc/ssl/custom-ca.pem"}) == "/etc/ssl/custom-ca.pem"
    assert bc._verify({"verify_ssl": 1, "ca_cert": "/etc/ssl/srv-ca.pem"}) == "/etc/ssl/srv-ca.pem"

    monkeypatch.setenv("FLEETPILOT_BACKUP_CA", "/etc/ssl/env-ca.pem")
    assert bc._verify({"verify_ssl": 1}) == "/etc/ssl/env-ca.pem"
    assert bc._verify({"verify_ssl": _OFF_INT}) is False


@pytest.mark.parametrize("verify_ssl", [True, _OFF_BOOL])
def test_pbs_respects_verify_ssl_in_poll_and_test_connection(monkeypatch, verify_ssl):
    created_sessions = []

    class FakeSession:
        def __init__(self):
            self.verify = None
            self.headers = {}
            self.cookies = MagicMock()
            self.calls = []
            created_sessions.append(self)

        def get(self, url, **kwargs):
            self.calls.append(("GET", url, self.verify))
            return _DummyResponse({"data": []})

        def post(self, url, **kwargs):
            self.calls.append(("POST", url, self.verify))
            return _DummyResponse({"data": {"ticket": "t", "CSRFPreventionToken": "c"}})

    monkeypatch.setattr(bc.requests, "Session", FakeSession)

    sid = bc.add_server(
        name=f"PBS-{verify_ssl}",
        server_type="pbs",
        host="pbs.local",
        port=8007,
        protocol="https",
        api_token="root@pam!tok=sec",
        verify_ssl=verify_ssl,
    )

    res_conn = bc.test_connection(sid)
    assert res_conn["ok"] is True
    assert created_sessions[-1].verify is verify_ssl

    res_poll = bc.poll_server(sid)
    assert res_poll["ok"] is True
    assert created_sessions[-1].verify is verify_ssl


@pytest.mark.parametrize("verify_ssl", [True, _OFF_BOOL])
def test_duplicati_respects_verify_ssl_in_auth_poll_trigger_and_test_connection(
    monkeypatch, verify_ssl
):
    seen_verify = []

    def fake_post(url, **kwargs):
        seen_verify.append((url, kwargs.get("verify")))
        if url.endswith("/api/v1/auth/login"):
            return _DummyResponse({"AccessToken": "tok-123"})
        return _DummyResponse({})

    def fake_get(url, **kwargs):
        seen_verify.append((url, kwargs.get("verify")))
        if url.endswith("/api/v1/backups"):
            return _DummyResponse(
                [{"Backup": {"ID": "1", "Name": "Daily", "Metadata": {}}}]
            )
        if url.endswith("/filesets"):
            return _DummyResponse([{"Version": 0}])
        return _DummyResponse({})

    monkeypatch.setattr(bc.requests, "post", fake_post)
    monkeypatch.setattr(bc.requests, "get", fake_get)

    sid = bc.add_server(
        name=f"Duplicati-{verify_ssl}",
        server_type="duplicati",
        host="dup.local",
        port=8200,
        protocol="https",
        password="secret",
        verify_ssl=verify_ssl,
    )

    assert bc.test_connection(sid)["ok"] is True
    assert bc.poll_server(sid)["ok"] is True
    assert bc.trigger_backup(sid, "1")["ok"] is True
    assert seen_verify
    assert all(v is verify_ssl for _url, v in seen_verify)


@pytest.mark.parametrize("verify_ssl", [True, _OFF_BOOL])
def test_restic_respects_verify_ssl_in_poll_and_test_connection(monkeypatch, verify_ssl):
    seen_verify = []

    def fake_get(url, **kwargs):
        seen_verify.append((url, kwargs.get("verify")))
        if url.endswith("/snapshots/"):
            return _DummyResponse([{"id": "abcdef1234567890", "hostname": "h1", "time": "2026-01-01T00:00:00Z"}])
        return _DummyResponse(["repo1"])

    monkeypatch.setattr(bc.requests, "get", fake_get)

    sid = bc.add_server(
        name=f"Restic-{verify_ssl}",
        server_type="restic",
        host="restic.local",
        port=8000,
        protocol="https",
        username="u",
        password="p",
        verify_ssl=verify_ssl,
    )

    assert bc.test_connection(sid)["ok"] is True
    assert bc.poll_server(sid)["ok"] is True
    assert len(seen_verify) >= 3
    assert all(v is verify_ssl for _url, v in seen_verify)


@pytest.mark.parametrize("verify_ssl", [True, _OFF_BOOL])
def test_borgwarehouse_respects_verify_ssl_in_poll_and_test_connection(monkeypatch, verify_ssl):
    seen_verify = []

    def fake_get(url, **kwargs):
        seen_verify.append((url, kwargs.get("verify")))
        return _DummyResponse({"repoList": [{"repositoryName": "r1", "alias": "Repo 1", "lastSave": 1700000000}]})

    monkeypatch.setattr(bc.requests, "get", fake_get)

    sid = bc.add_server(
        name=f"Borg-{verify_ssl}",
        server_type="borgwarehouse",
        host="borg.local",
        port=3000,
        protocol="https",
        api_token="tok",
        verify_ssl=verify_ssl,
    )

    assert bc.test_connection(sid)["ok"] is True
    assert bc.poll_server(sid)["ok"] is True
    assert len(seen_verify) == 2
    assert all(v is verify_ssl for _url, v in seen_verify)


@pytest.mark.parametrize("verify_ssl", [True, _OFF_BOOL])
def test_urbackup_respects_verify_ssl_in_login_poll_and_test_connection(monkeypatch, verify_ssl):
    seen_verify = []

    def fake_get(url, **kwargs):
        seen_verify.append((url, kwargs.get("verify")))
        if "a=login" in url:
            return _DummyResponse({"success": True, "session": "ses-1"})
        return _DummyResponse({"clients": [{"name": "c1", "lastbackup": 1700000000, "file_ok": True}]})

    monkeypatch.setattr(bc.requests, "get", fake_get)

    sid = bc.add_server(
        name=f"UrBackup-{verify_ssl}",
        server_type="urbackup",
        host="urbackup.local",
        port=55414,
        protocol="https",
        username="admin",
        password="pw",
        verify_ssl=verify_ssl,
    )

    assert bc.test_connection(sid)["ok"] is True
    assert bc.poll_server(sid)["ok"] is True
    assert len(seen_verify) >= 3
    assert all(v is verify_ssl for _url, v in seen_verify)


@pytest.mark.parametrize("stype", ["pbs", "duplicati", "restic", "borgwarehouse", "urbackup"])
def test_self_signed_certificate_failure_returns_clear_tls_error(monkeypatch, stype):
    def raise_ssl(*args, **kwargs):
        raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED: self-signed certificate")

    monkeypatch.setattr(bc.requests, "get", raise_ssl)
    monkeypatch.setattr(bc.requests, "post", raise_ssl)

    class FailingSession:
        def __init__(self):
            self.verify = True
            self.headers = {}
            self.cookies = MagicMock()

        def get(self, *args, **kwargs):
            raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")

        def post(self, *args, **kwargs):
            raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")

    monkeypatch.setattr(bc.requests, "Session", FailingSession)

    sid = bc.add_server(
        name=f"TLS-Fail-{stype}",
        server_type=stype,
        host="selfsigned.local",
        port=8443,
        protocol="https",
        api_token="tok",
        verify_ssl=True,
    )

    conn_res = bc.test_connection(sid)
    assert conn_res["ok"] is False
    assert "SSL/TLS certificate verification failed" in conn_res["error"]
    assert "Verify SSL certificate" in conn_res["error"]

    poll_res = bc.poll_server(sid)
    assert poll_res["ok"] is False
    assert "SSL/TLS certificate verification failed" in poll_res["error"]
