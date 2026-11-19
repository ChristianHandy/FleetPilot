# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vulnerability matching: per-distribution package lists from recorded
command output, matching installed versions against OSV data (HTTP mocked),
severity counting for the dashboard, and vulnerability-feed failures."""
import pytest

import vuln_scanner as vs


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "_DB_PATH", None)
    vs.init_db(str(tmp_path))
    return tmp_path


# ── Building the package list per distribution ──────────────────────────────

def test_parse_inventory_rpm_with_epochs():
    text = ('NAME="Rocky Linux"\nID="rocky"\nVERSION_ID="9.4"\n@@fp:pkg\nrpm\n'
            'openssl\t1:3.0.7-39.el9\ncurl\t0:8.0.1-5.el9\n'
            '@@fp:docker\n@@fp:trivy\n')
    inv = vs.parse_inventory(text)
    assert inv["manager"] == "rpm"
    # The rpm format carries the epoch: 1:3.0.7-39 is not 3.0.7-39.
    assert inv["packages"] == [("curl", "0:8.0.1-5.el9"), ("openssl", "1:3.0.7-39.el9")]
    assert inv["release"]["ID"] == "rocky"


def test_parse_inventory_dpkg_skips_malformed_lines():
    text = ('ID=debian\nVERSION_ID="13"\n@@fp:pkg\ndpkg\n'
            'openssl\t3.5.1-1\n'
            'a-line-without-a-version\n'
            '\t9.9\n'
            'curl\t8.14.1-2\n'
            '@@fp:docker\n@@fp:trivy\n')
    inv = vs.parse_inventory(text)
    assert inv["packages"] == [("curl", "8.14.1-2"), ("openssl", "3.5.1-1")]


def test_parse_inventory_apk_uses_the_origin_package():
    text = ('ID=alpine\n@@fp:pkg\napk\n'
            'libssl3-3.3.2-r0 x86_64 {openssl} (Apache-2.0) [installed]\n'
            'zlib-1.3.1-r0 aarch64 {zlib} (Zlib) [installed]\n'
            'a line that is not apk output\n'
            '@@fp:docker\n@@fp:trivy\n')
    inv = vs.parse_inventory(text)
    assert inv["packages"] == [("openssl", "3.3.2-r0"), ("zlib", "1.3.1-r0")]


def test_parse_inventory_containers_and_missing_trivy():
    text = ('ID=debian\n@@fp:pkg\ndpkg\ncurl\t8.14.1-2\n'
            '@@fp:docker\nweb\tnginx:1.27.0\ndb\tpostgres:16\n@@fp:trivy\n')
    inv = vs.parse_inventory(text)
    assert inv["containers"] == [{"name": "web", "image": "nginx:1.27.0"},
                                  {"name": "db", "image": "postgres:16"}]
    assert inv["trivy"] == ""


def test_parse_inventory_without_a_package_manager():
    # A Windows host answers none of the inventory sections.
    inv = vs.parse_inventory("Microsoft Windows Server 2022\n")
    assert inv["manager"] == ""
    assert inv["packages"] == []
    assert inv["containers"] == []


# ── Matching installed versions against the vulnerability data ──────────────

class _Resp:
    def __init__(self, data, error=None):
        self._data = data
        self._error = error

    def json(self):
        return self._data

    def raise_for_status(self):
        if self._error:
            raise self._error


_OPENSSL_CVE = {
    "id": "DEBIAN-CVE-2025-9999", "aliases": ["CVE-2025-9999"],
    "summary": "Buffer overflow in openssl", "published": "2025-10-01T00:00:00Z",
    "severity": [{"type": "CVSS_V3",
                  "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
    "affected": [{"package": {"name": "openssl", "ecosystem": "Debian:13"},
                  "ranges": [{"type": "ECOSYSTEM",
                              "events": [{"introduced": "0"}, {"fixed": "3.5.4-1"}]}]}],
}


def _fake_osv_by_version(monkeypatch, affected, records):
    """OSV stand-in: a package is matched only at the affected versions."""
    def post(url, json=None, timeout=None):
        assert url.endswith("/v1/querybatch")
        results = []
        for query in json["queries"]:
            key = (query["package"]["name"], query["version"])
            ids = ["DEBIAN-CVE-2025-9999"] if key in affected else []
            results.append({"vulns": [{"id": i} for i in ids]})
        return _Resp({"results": results})

    monkeypatch.setattr(vs.requests, "post", post)
    monkeypatch.setattr(vs.requests, "get",
                        lambda url, timeout=None: _Resp(records[url.rsplit("/", 1)[1]]))


def test_only_versions_below_the_fixed_one_match(db, monkeypatch):
    _fake_osv_by_version(monkeypatch, {("openssl", "3.5.1-1")},
                         {"DEBIAN-CVE-2025-9999": _OPENSSL_CVE})
    findings = vs.findings_from_osv("Debian:13", [("openssl", "3.5.1-1"),
                                                  ("curl", "8.14.1-2"),
                                                  ("zlib1g", "1.3.2")])
    assert len(findings) == 1
    finding = findings[0]
    assert finding["package"] == "openssl"
    assert finding["installed"] == "3.5.1-1"
    assert finding["fixed"] == "3.5.4-1"          # installed is below the fix
    assert finding["severity"] == "critical" and finding["score"] == 9.8


def test_versions_at_and_above_the_fixed_one_do_not_match(db, monkeypatch):
    _fake_osv_by_version(monkeypatch, {("openssl", "3.5.1-1")},
                         {"DEBIAN-CVE-2025-9999": _OPENSSL_CVE})
    assert vs.findings_from_osv("Debian:13", [("openssl", "3.5.4-1")]) == []
    assert vs.findings_from_osv("Debian:13", [("openssl", "3.5.5-1")]) == []


def test_withdrawn_records_are_skipped(db, monkeypatch):
    withdrawn = dict(_OPENSSL_CVE, withdrawn="2025-11-01T00:00:00Z")
    _fake_osv_by_version(monkeypatch, {("openssl", "3.5.1-1")},
                         {"DEBIAN-CVE-2025-9999": withdrawn})
    assert vs.findings_from_osv("Debian:13", [("openssl", "3.5.1-1")]) == []


def test_fixed_version_ignores_git_ranges_and_other_ecosystems():
    vuln = {"affected": [
        {"package": {"name": "openssl", "ecosystem": "PyPI"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "9.9"}]}]},
        {"package": {"name": "openssl", "ecosystem": "Debian:13"},
         "ranges": [{"type": "GIT", "events": [{"fixed": "abc123"}]}]},
    ]}
    assert vs.fixed_version(vuln, "openssl", "Debian:13") == ""


def test_fixed_version_searches_later_ranges_of_the_same_entry():
    vuln = {"affected": [
        {"package": {"name": "curl", "ecosystem": "Debian:13"},
         "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]},
                    {"type": "ECOSYSTEM",
                     "events": [{"introduced": "7.0"}, {"fixed": "8.14.1-2"}]}]},
    ]}
    assert vs.fixed_version(vuln, "curl", "Debian:13") == "8.14.1-2"


# ── Severity counting and the dashboard summary ─────────────────────────────

def _finding(vuln_id, package, severity, fixed, score=None):
    return {"vuln_id": vuln_id, "package": package, "installed": "1.0",
            "fixed": fixed, "severity": severity, "score": score,
            "summary": "s", "aliases": [vuln_id], "published": "2025-01-01"}


def test_summary_counts_severities_across_targets(db):
    web = {"id": "host:web", "kind": "server", "name": "web"}
    dbt = {"id": "host:db", "kind": "server", "name": "db"}
    crit = _finding("CVE-2025-1", "openssl", "critical", "1.1", 9.8)
    high = _finding("CVE-2025-2", "curl", "high", "", 7.5)
    med = _finding("CVE-2025-3", "zlib1g", "medium", "1.2", 5.0)
    vs._store(web, [crit, high], "ok", packages=10)
    vs._store(dbt, [crit, med], "ok", packages=8)

    summary = vs.summary()
    assert summary["total"] == 4
    assert summary["critical"] == 2 and summary["high"] == 1
    assert summary["fixable"] == 3 and summary["critical_fixable"] == 2
    assert summary["affected"] == 2 and summary["scanned"] == 2
    assert summary["last_scan"] is not None

    targets = {t["id"]: t for t in vs.get_targets()}
    assert targets["host:web"]["counts"] == {"critical": 1, "high": 1}
    assert targets["host:web"]["fixable"] == 1 and targets["host:web"]["total"] == 2
    assert targets["host:db"]["counts"] == {"critical": 1, "medium": 1}

    grouped = vs.get_findings()                 # worst first
    assert [g["vuln_id"] for g in grouped] == ["CVE-2025-1", "CVE-2025-2", "CVE-2025-3"]
    assert len(grouped[0]["targets"]) == 2      # the shared CVE groups both servers


# ── Vulnerability-feed failures ─────────────────────────────────────────────

def test_query_osv_propagates_feed_errors(monkeypatch):
    monkeypatch.setattr(vs.requests, "post",
                        lambda url, json=None, timeout=None:
                        _Resp({}, error=vs.requests.HTTPError("503 Service Unavailable")))
    with pytest.raises(vs.requests.HTTPError):
        vs.query_osv("Debian:13", [("openssl", "3.5.1-1")])


def test_get_vulns_skips_records_that_fail_to_download(db, monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        vid = url.rsplit("/", 1)[1]
        calls.append(vid)
        if vid == "BAD-1":
            raise vs.requests.ConnectionError("connection refused")
        return _Resp({"id": vid, "summary": "ok"})

    monkeypatch.setattr(vs.requests, "get", fake_get)
    out = vs.get_vulns(["BAD-1", "GOOD-1"])
    assert set(out) == {"GOOD-1"}

    calls.clear()
    out = vs.get_vulns(["GOOD-1"])              # cached for a week: no new fetch
    assert out["GOOD-1"]["summary"] == "ok"
    assert calls == []


def test_scan_target_records_an_error_when_the_feed_is_down(db, monkeypatch):
    def down(ecosystem, packages):
        raise vs.requests.ConnectionError("no route to host")

    monkeypatch.setattr(vs, "query_osv", down)
    target = {"id": "fleetpilot:python", "kind": "fleetpilot",
              "name": "FleetPilot (Python packages)", "address": ""}
    assert vs.scan_target(target) == []
    rows = {t["id"]: t for t in vs.get_targets()}
    assert rows["fleetpilot:python"]["status"] == "error"
    assert rows["fleetpilot:python"]["total"] == 0
