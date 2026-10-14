# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The installer makes the code directory root-owned: FleetPilot may only write to its data dir."""
import io
import os
import shutil
import stat
import subprocess
import sys

import pytest

import app as fp

HERE = os.path.dirname(os.path.abspath(__file__))


def _make_read_only(root):
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames + dirnames:
            path = os.path.join(dirpath, name)
            os.chmod(path, os.stat(path).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    os.chmod(root, 0o500)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_app_starts_with_read_only_code_directory(tmp_path):
    code = tmp_path / "code"
    shutil.copytree(HERE, code, ignore=shutil.ignore_patterns(
        ".git", "data", "logs", "uploads", "__pycache__", "venv", ".venv", "*.db", "static/host_images"))
    data = tmp_path / "data"
    data.mkdir()
    (code / "logs").mkdir()
    _make_read_only(code)
    os.chmod(code / "logs", 0o700)   # the installer gives the service data/ and logs/ only
    env = dict(os.environ, FLEETPILOT_DATA_DIR=str(data), PYTHONDONTWRITEBYTECODE="1",
               FLEETPILOT_ROUTER_POLL_MINUTES="0")
    script = ("import app, disktool_core as d, version_manager as v\n"
              "assert app.app.test_client().get('/healthz').status_code == 200\n"
              "v.save_version_data({'checked': True})\n"
              "print(d.export_smart_data())\n")
    try:
        result = subprocess.run([sys.executable, "-c", script], cwd=code, env=env,
                                capture_output=True, text=True, timeout=120)
    finally:
        for dirpath, dirnames, _ in os.walk(code):
            os.chmod(dirpath, 0o700)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().splitlines()[-1].startswith(str(data))


def test_host_image_is_stored_in_data_dir_and_served_sandboxed(monkeypatch):
    import account_security
    import time
    import user_management
    fp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    hosts = {"img-host": {"host": "192.0.2.50", "user": "root"}}
    monkeypatch.setattr(fp, "load_hosts", lambda: hosts)
    monkeypatch.setattr(fp, "save_hosts", lambda h: None)
    user = user_management.get_user("img_operator")
    uid = user["id"] if user else user_management.create_user("img_operator", "image-test-passphrase", None, ["operator"])
    client = fp.app.test_client()
    with client.session_transaction() as s:
        s.update(user_id=uid, username="img_operator", pw_tag=fp._password_tag(user_management.get_user_by_id(uid)),
                 sid=account_security.create_session(uid), auth_time=time.time())
    resp = client.post("/hosts/upload_image/img-host",
                       data={"image": (io.BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'/>"), "x.svg")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200, resp.data
    url = resp.get_json()["image_url"]
    assert url == "/hosts/images/img-host.svg" and hosts["img-host"]["custom_image"] == url
    assert os.path.exists(os.path.join(fp.DATA_DIR, "host_images", "img-host.svg"))
    served = client.get(url)
    assert served.status_code == 200 and "sandbox" in served.headers["Content-Security-Policy"]
    served.close()
    assert fp.app.test_client().get(url).status_code in (302, 401)      # login required


def test_smart_collection_reads_hosts_from_data_dir(tmp_path, monkeypatch):
    import json
    import smart_manager
    (tmp_path / "hosts.json").write_text(json.dumps({"nas": {"host": "192.0.2.77", "user": "root"}}))
    monkeypatch.setenv("FLEETPILOT_DATA_DIR", str(tmp_path))
    seen = []
    monkeypatch.setattr(smart_manager, "collect_ssh_host_disks",
                        lambda **kw: seen.append((kw["host_name"], kw["key_path"])) or [])
    smart_manager.collect_all_ssh_hosts()
    assert seen == [("nas", None)]       # None: the default key (id_ed25519 first) is picked later
