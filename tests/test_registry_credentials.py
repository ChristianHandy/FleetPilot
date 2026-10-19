# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The server registry never hands out SSH passwords and stores them encrypted."""
import contextlib
import sqlite3
import time

import pytest

import account_security
import app as fp
import server_registry
import user_management

PASSWORD = "registry-test-Secret-91"
KEY = "/root/.ssh/registry_test_key"


def _raw_password(reg, name):
    with contextlib.closing(sqlite3.connect(reg._db_path)) as conn:
        return conn.execute("SELECT password FROM servers WHERE name=?", (name,)).fetchone()[0]


def test_passwords_are_encrypted_and_only_returned_for_connecting(tmp_path):
    reg = server_registry.ServerRegistry(str(tmp_path))
    try:
        sid = reg.upsert_server("pve-test", "192.0.2.10", user="root", password=PASSWORD, ssh_key=KEY)
        stored = _raw_password(reg, "pve-test")
        assert stored and PASSWORD not in stored

        for srv in (reg.get_server(id=sid), reg.get_server(name="pve-test"), *reg.list_servers()):
            assert "password" not in srv and srv["has_password"] is True
        assert reg.get_credentials(id=sid) == {"password": PASSWORD, "ssh_key": KEY}
        assert reg.get_credentials(name="pve-test")["password"] == PASSWORD

        reg.upsert_server("pve-test", "192.0.2.10", password=None, notes="kept")
        assert reg.get_credentials(id=sid)["password"] == PASSWORD
        reg.upsert_server("pve-test", "192.0.2.10", password="")
        assert reg.get_credentials(id=sid)["password"] == ""
        assert reg.get_server(id=sid)["has_password"] is False
    finally:
        reg.close()


def test_plain_text_passwords_from_older_versions_are_encrypted_on_start(tmp_path):
    reg = server_registry.ServerRegistry(str(tmp_path))
    reg.upsert_server("old-host", "192.0.2.11")
    reg.close()
    with contextlib.closing(sqlite3.connect(tmp_path / "server_registry.db")) as conn:
        conn.execute("UPDATE servers SET password=? WHERE name='old-host'", (PASSWORD,))
        conn.commit()
    reg = server_registry.ServerRegistry(str(tmp_path))
    try:
        assert PASSWORD not in _raw_password(reg, "old-host")
        assert reg.get_credentials(name="old-host")["password"] == PASSWORD
    finally:
        reg.close()


def test_public_view_has_no_password_and_no_key():
    shown = server_registry.ServerRegistry.public({"id": 1, "name": "a", "password": "x", "ssh_key": KEY})
    assert "password" not in shown and "ssh_key" not in shown and shown["has_ssh_key"] is True


@pytest.fixture
def client():
    fp.app.config["TESTING"] = True
    with fp.app.test_client() as c:
        yield c


def _login(client, username, role):
    user_management.init_user_db()
    user = user_management.get_user(username)
    user_id = user["id"] if user else user_management.create_user(username, "registry-test-pass", None, [role])
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["pw_tag"] = fp._password_tag(user_management.get_user_by_id(user_id))
        sess["sid"] = account_security.create_session(user_id, "127.0.0.1", "pytest")
        sess["auth_time"] = time.time()
        sess["username"] = username


@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_registry_api_never_returns_credentials(client, role):
    if not fp._REGISTRY_AVAILABLE:
        pytest.skip("registry not available")
    reg = server_registry.get_registry(fp.DATA_DIR)
    sid = reg.upsert_server("exposure-test", "192.0.2.12", password=PASSWORD, ssh_key=KEY)
    try:
        _login(client, f"registry_{role}", role)
        for path in ("/api/registry/servers", f"/api/registry/servers/{sid}", "/api/registry/suggest"):
            response = client.get(path)
            assert response.status_code == 200
            body = response.get_data(as_text=True)
            assert PASSWORD not in body and KEY not in body, path
        assert client.get(f"/api/registry/servers/{sid}").get_json()["has_password"] is True
        page = client.get("/fans/add")
        assert PASSWORD not in page.get_data(as_text=True)
    finally:
        reg.delete_server(sid)
