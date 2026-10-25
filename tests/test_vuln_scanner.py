# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vulnerability scan: inventories, OSV data, severities and notifications."""
import json

import pytest

import vuln_scanner as vs


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "_DB_PATH", None)
    vs.init_db(str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("vector, score", [
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N", 5.5),
    ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N", 5.9),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0),
])
def test_cvss3_base_score(vector, score):
    assert vs.cvss3_score(vector) == score


def test_severity_sources():
    v3 = {"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]}
    assert vs.severity_of(v3) == ("critical", 9.8)
    v4 = {"severity": [{"type": "CVSS_V4", "score": "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"}]}
    assert vs.severity_of(v4) == ("critical", None)
    ubuntu = {"severity": [{"type": "Ubuntu", "score": "medium"}]}
    assert vs.severity_of(ubuntu) == ("medium", None)
    debian = {"affected": [{"package": {"name": "curl"}, "ecosystem_specific": {"urgency": "unimportant"}}]}
    assert vs.severity_of(debian, "curl") == ("low", None)
    assert vs.severity_of({"id": "X"}) == ("unknown", None)


def test_fixed_version_is_taken_from_the_exact_release():
    vuln = {"affected": [
        {"package": {"name": "openssl", "ecosystem": "Ubuntu:22.04:LTS"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "3.0.2-0ubuntu1.17"}]}]},
        {"package": {"name": "openssl", "ecosystem": "Ubuntu:24.04:LTS"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "3.0.13-0ubuntu3.2"}]}]},
        {"package": {"name": "openssl", "ecosystem": "Debian:13"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}]},
    ]}
    assert vs.fixed_version(vuln, "openssl", "Ubuntu:24.04:LTS") == "3.0.13-0ubuntu3.2"
    assert vs.fixed_version(vuln, "openssl", "Debian:13") == ""          # known, not fixed yet


@pytest.mark.parametrize("release, ecosystem", [
    ({"ID": "debian", "VERSION_ID": "13"}, "Debian:13"),
    ({"ID": "raspbian", "VERSION_ID": "12"}, "Debian:12"),
    ({"ID": "ubuntu", "VERSION_ID": "24.04"}, "Ubuntu:24.04:LTS"),
    ({"ID": "ubuntu", "VERSION_ID": "25.04"}, "Ubuntu:25.04"),
    ({"ID": "alpine", "VERSION_ID": "3.20.3"}, "Alpine:v3.20"),
    ({"ID": "rocky", "VERSION_ID": "9.4"}, "Rocky Linux:9"),
])
def test_ecosystems(release, ecosystem):
    assert vs.ecosystem_for(release) == ecosystem


def test_unsupported_systems_say_why():
    with pytest.raises(vs.Unsupported, match="Fedora"):
        vs.ecosystem_for({"ID": "fedora", "VERSION_ID": "42", "PRETTY_NAME": "Fedora Linux 42"})


def test_parse_inventory():
    text = ('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_ID="13"\n@@fp:pkg\ndpkg\n'
            'openssl\t3.5.1-1\nopenssl\t3.5.1-1\ncurl\t8.14.1-2\n@@fp:docker\nweb\tnginx:1.27.0\n'
            '@@fp:trivy\n/usr/bin/trivy\n')
    inv = vs.parse_inventory(text)
    assert inv["release"]["VERSION_ID"] == "13"
    assert inv["packages"] == [("curl", "8.14.1-2"), ("openssl", "3.5.1-1")]
    assert inv["containers"] == [{"name": "web", "image": "nginx:1.27.0"}]
    assert inv["trivy"] == "/usr/bin/trivy"
    alpine = vs.parse_inventory("ID=alpine\n@@fp:pkg\napk\nlibcrypto3-3.3.2-r0 x86_64 {openssl} (Apache-2.0) "
                                "[installed]\n@@fp:docker\n@@fp:trivy\n")
    assert alpine["packages"] == [("openssl", "3.3.2-r0")]


def test_parse_pkg_audit():
    log = ("curl-8.9.1 is vulnerable:\n  curl -- netrc and redirect credential leak\n  CVE: CVE-2024-11053\n"
           "  WWW: https://vuxml.freebsd.org/freebsd/1.html\n\n1 problem(s) in 1 installed package(s) found.\n")
    findings = vs.parse_pkg_audit(log)
    assert [(f["vuln_id"], f["package"], f["installed"]) for f in findings] == [("CVE-2024-11053", "curl", "8.9.1")]
    assert findings[0]["summary"] == "curl -- netrc and redirect credential leak"


def test_trivy_report():
    report = {"Results": [{"Vulnerabilities": [
        {"VulnerabilityID": "CVE-2024-1", "PkgName": "openssl", "InstalledVersion": "3.0.11", "FixedVersion": "3.0.13",
         "Severity": "HIGH", "Title": "t", "CVSS": {"nvd": {"V3Score": 7.5}}}]}]}
    count, findings = vs.findings_from_trivy(report)
    assert count == 1 and findings[0]["severity"] == "high" and findings[0]["score"] == 7.5


class _Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


def _fake_osv(monkeypatch, records, hits):
    def post(url, json=None, timeout=None):
        assert url.endswith("/v1/querybatch")
        return _Resp({"results": [{"vulns": [{"id": i} for i in hits.get(q["package"]["name"], [])]}
                                  for q in json["queries"]]})
    monkeypatch.setattr(vs.requests, "post", post)
    monkeypatch.setattr(vs.requests, "get", lambda url, timeout=None: _Resp(records[url.rsplit("/", 1)[1]]))


def test_findings_from_osv_merge_advisories_for_the_same_cve(db, monkeypatch):
    ghsa = {"id": "GHSA-1", "aliases": ["CVE-2023-30861"], "summary": "Session disclosure",
            "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"}],
            "affected": [{"package": {"name": "flask", "ecosystem": "PyPI"},
                          "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.3.2"}]}]}]}
    pysec = {"id": "PYSEC-1", "aliases": ["CVE-2023-30861"], "details": "Flask ...",
             "affected": [{"package": {"name": "flask", "ecosystem": "PyPI"},
                           "ranges": [{"type": "GIT", "events": [{"fixed": "abc123"}]}]}]}
    _fake_osv(monkeypatch, {"GHSA-1": ghsa, "PYSEC-1": pysec}, {"flask": ["PYSEC-1", "GHSA-1"]})
    findings = vs.findings_from_osv("PyPI", [("flask", "2.2.0"), ("jinja2", "3.1.6")])
    assert len(findings) == 1
    assert findings[0]["vuln_id"] == "GHSA-1" and findings[0]["fixed"] == "2.3.2"
    assert findings[0]["severity"] == "high" and findings[0]["aliases"] == ["CVE-2023-30861"]


def test_first_scan_is_the_baseline_and_later_findings_notify(db, monkeypatch):
    sent = []
    import notify
    monkeypatch.setattr(notify, "send", lambda event, title, message, level="warning", **k: sent.append(
        (event, title, level)))
    target = {"id": "host:web", "kind": "server", "name": "web"}
    finding = {"vuln_id": "DEBIAN-CVE-2025-1", "package": "openssl", "installed": "3.5.1-1", "fixed": "3.5.4-1",
               "severity": "critical", "score": 9.8, "summary": "s", "aliases": ["CVE-2025-1"], "published": ""}
    assert vs._store(target, [finding], "ok") == []                   # baseline
    second = dict(finding, vuln_id="DEBIAN-CVE-2025-2", aliases=["CVE-2025-2"])
    new = vs._store(target, [finding, second], "ok")
    assert [f["vuln_id"] for f in new] == ["DEBIAN-CVE-2025-2"]
    vs._notify(new)
    assert sent == [("vulnerability", "FleetPilot: 1 new vulnerabilities with a fix", "critical")]
    summary = vs.summary()
    assert summary["critical_fixable"] == 2 and summary["affected"] == 1
    grouped = vs.get_findings()
    assert [g["vuln_id"] for g in grouped] == ["DEBIAN-CVE-2025-1", "DEBIAN-CVE-2025-2"]
    assert vs._store(target, [], "error", "timed out") == []           # a failed scan keeps the last result
    assert len(vs.get_findings()) == 2


def test_offline_mode_blocks_scans(monkeypatch):
    monkeypatch.setenv("FLEETPILOT_OFFLINE", "true")
    monkeypatch.delenv("FLEETPILOT_OSV_URL", raising=False)
    assert vs.enabled()[0] is False
    monkeypatch.setenv("FLEETPILOT_OSV_URL", "https://osv.mirror.example")
    assert vs.enabled()[0] is True


def test_routes(monkeypatch):
    import app as fp
    import user_management
    import account_security
    import time
    fp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    client = fp.app.test_client()
    user = user_management.get_user(fp.USERNAME) if hasattr(fp, "USERNAME") else None
    if not user:
        pytest.skip("no admin account in this test environment")
    with client.session_transaction() as s:
        s.update(user_id=user["id"], username=user["username"],
                 pw_tag=fp._password_tag(user_management.get_user_by_id(user["id"])),
                 sid=account_security.create_session(user["id"]), auth_time=time.time())
    assert client.get("/vulnerabilities").status_code == 200
    data = client.get("/api/vulnerabilities").get_json()
    assert set(data) == {"summary", "targets", "findings"}
    monkeypatch.setenv("FLEETPILOT_OFFLINE", "true")
    monkeypatch.delenv("FLEETPILOT_OSV_URL", raising=False)
    resp = client.post("/vulnerabilities/scan", headers={"Accept": "application/json"})
    assert resp.status_code == 409 and "Offline" in resp.get_json()["message"]
    json.dumps(data)
