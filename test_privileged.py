"""Root helpers and self-update for both install types: install.sh (git, service user) and release tarballs run as root."""
import time

import account_security
import app as fp
import privileged
import user_management


def test_service_user_goes_through_sudo(monkeypatch):
    monkeypatch.setattr(privileged.os, "geteuid", lambda: 1000)
    assert privileged.command("disk-action", "validate", "read", "sdb") == \
        ["sudo", "-n", "/usr/local/lib/fleetpilot/disk-action", "validate", "read", "sdb"]


def test_root_without_installed_helpers_runs_the_bundled_ones(monkeypatch):
    monkeypatch.setattr(privileged.os, "geteuid", lambda: 0)
    monkeypatch.setattr(privileged, "INSTALLED_DIR", "/nonexistent")
    disk = privileged.command("disk-action", "quick", "ext4", "sdb")
    assert disk[0] == "/bin/sh" and disk[1].endswith("scripts/fleetpilot-disk-action") and disk[2:] == ["quick", "ext4", "sdb"]
    assert privileged.command("proxy-apply", "status")[0] == "/usr/bin/python3"
    assert "sudo" not in privileged.command("update", "check")


def _admin_client():
    fp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    user = user_management.get_user("update_admin")
    uid = user["id"] if user else user_management.create_user("update_admin", "update-test-passphrase", None, ["admin"])
    client = fp.app.test_client()
    with client.session_transaction() as s:
        s.update(user_id=uid, username="update_admin", pw_tag=fp._password_tag(user_management.get_user_by_id(uid)),
                 sid=account_security.create_session(uid), auth_time=time.time())
    return client


def test_release_install_explains_how_to_update(monkeypatch):
    monkeypatch.setattr(privileged, "is_git_checkout", lambda: False)
    client = _admin_client()
    page = client.get("/fleetpilot_update").get_data(as_text=True)
    assert "installed from a release" in page and 'id="startBtn"' not in page
    assert client.post("/fleetpilot_update", data={"action": "start"}).status_code == 409


def test_old_update_links_lead_to_the_protected_update_page():
    client = _admin_client()
    for method in (client.get, client.post):
        response = method("/dashboard_version/update")
        assert response.status_code == 302 and response.headers["Location"].endswith("/fleetpilot_update")
