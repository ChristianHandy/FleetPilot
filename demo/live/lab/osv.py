# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The demo's OSV.dev: real vulnerability records, captured when the demo is built.

build_snapshot() asks the real https://api.osv.dev about exactly the package
versions that exist in the emulated lab (installed, older and updated versions,
and the container images) and stores the answers. In the browser the lab answers
FleetPilot's OSV requests from that file, so the demo shows genuine CVE data
without contacting anything. Without a snapshot (offline build) nothing is found.
"""
import json
import os
import urllib.parse

SNAPSHOT = os.environ.get("FLEETPILOT_LAB_OSV") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                   "osv-snapshot.json")
ECOSYSTEMS = {"debian": "Debian:13", "raspbian": "Debian:12", "ubuntu": "Ubuntu:24.04:LTS"}
_data = None


def _snapshot():
    global _data
    if _data is None:
        try:
            with open(SNAPSHOT, encoding="utf-8") as fh:
                _data = json.load(fh)
        except (OSError, ValueError):
            _data = {"queries": {}, "vulns": {}}
    return _data


def lookup(ecosystem, package, version):
    data = _snapshot()
    return [data["vulns"][i] for i in data["queries"].get(f"{ecosystem}|{package}|{version}", [])
            if i in data["vulns"]]


def latest(ecosystem, package):
    """The newest fixed version of a package in the snapshot (what an up-to-date machine runs), or None."""
    return _snapshot().get("latest", {}).get(f"{ecosystem}|{package}")


def _order(c):
    if c == "~":
        return -1
    if c.isdigit():
        return 0
    return ord(c) if c.isalpha() else ord(c) + 256


def _verrevcmp(a, b):
    i = j = 0
    while i < len(a) or j < len(b):
        first_diff = 0
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = _order(a[i]) if i < len(a) else 0
            bc = _order(b[j]) if j < len(b) else 0
            if ac != bc:
                return ac - bc
            i, j = i + 1, j + 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and a[i].isdigit() and j < len(b) and b[j].isdigit():
            first_diff = first_diff or ord(a[i]) - ord(b[j])
            i, j = i + 1, j + 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def compare_versions(a, b):
    """dpkg's version comparison (also right for Ubuntu): <0, 0 or >0."""
    def split(v):
        epoch, _, rest = v.rpartition(":") if ":" in v else ("0", "", v)
        upstream, _, revision = rest.rpartition("-") if "-" in rest else (rest, "", "")
        return int(epoch or 0), upstream, revision
    ea, ua, ra = split(a)
    eb, ub, rb = split(b)
    return (ea - eb) or _verrevcmp(ua, ub) or _verrevcmp(ra, rb)


def score_and_level(record, package):
    import vuln_scanner
    level, score = vuln_scanner.severity_of(record, package)
    return score, level


def answer(method, path, body):
    """(status, content type, body) for a request to the OSV API."""
    data = _snapshot()

    def ids_for(query):
        pkg = query.get("package") or {}
        key = f"{pkg.get('ecosystem')}|{pkg.get('name')}|{query.get('version')}"
        return [{"id": i, "modified": data["vulns"].get(i, {}).get("modified", "")}
                for i in data["queries"].get(key, [])]

    if method == "POST" and path == "/v1/querybatch":
        queries = json.loads(body or b"{}").get("queries", [])
        results = [{"vulns": ids_for(q)} if ids_for(q) else {} for q in queries]
        return 200, "application/json", json.dumps({"results": results})
    if method == "POST" and path == "/v1/query":
        found = ids_for(json.loads(body or b"{}"))
        return 200, "application/json", json.dumps({"vulns": found} if found else {})
    if method == "GET" and path.startswith("/v1/vulns/"):
        record = data["vulns"].get(urllib.parse.unquote(path[len("/v1/vulns/"):]))
        if record:
            return 200, "application/json", json.dumps(record)
        return 404, "application/json", json.dumps({"code": 5, "message": "Bug not found."})
    return 404, "application/json", "{}"


# ── Build time ───────────────────────────────────────────────────────────────

def lab_queries():
    """Every (ecosystem, package, version) that can occur in the lab."""
    from .inventory import build
    from .machines import IMAGES, OLDER, Machine
    from .net import lab
    if not lab.devices:
        build()
    wanted = set()
    for device in lab.devices:
        eco = ECOSYSTEMS.get(getattr(device, "os", ""))
        if not eco or not isinstance(device, Machine):
            continue
        for pkg, version in device.packages.items():
            wanted.add((eco, pkg, version))
        for pkg, old, new in device.updates:
            wanted |= {(eco, pkg, old), (eco, pkg, new)}
        for pkg, old in OLDER.get(device.os, {}).items():
            wanted.add((eco, pkg, old))
    for packages in IMAGES.values():
        wanted |= {("Debian:12", pkg, version) for pkg, version in packages.items()}
    return sorted(wanted)


def _trim(record, wanted):
    """Keep what FleetPilot reads; drop the affected entries of other packages and releases."""
    keys = ("id", "summary", "aliases", "upstream", "severity", "published", "modified", "database_specific",
            "withdrawn")
    out = {k: record[k] for k in keys if k in record}
    out["details"] = (record.get("details") or "")[:600]
    out["affected"] = [a for a in record.get("affected") or []
                       if ((a.get("package") or {}).get("ecosystem"), (a.get("package") or {}).get("name")) in wanted]
    return out


def build_snapshot(path, api="https://api.osv.dev"):
    import concurrent.futures
    import requests

    def query(queries, found):
        for start in range(0, len(queries), 1000):
            chunk = queries[start:start + 1000]
            resp = requests.post(f"{api}/v1/querybatch", timeout=120, json={"queries": [
                {"package": {"ecosystem": e, "name": n}, "version": v} for e, n, v in chunk]})
            resp.raise_for_status()
            for (eco, name, version), result in zip(chunk, resp.json()["results"]):
                ids = [x["id"] for x in result.get("vulns") or []]
                if ids:
                    found[f"{eco}|{name}|{version}"] = ids

    def fetch_all(ids, vulns, wanted):
        def fetch(vid):
            r = requests.get(f"{api}/v1/vulns/{urllib.parse.quote(vid, safe='')}", timeout=60)
            r.raise_for_status()
            return vid, _trim(r.json(), wanted)
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            vulns.update(pool.map(fetch, sorted(set(ids) - set(vulns))))

    queries = lab_queries()
    wanted = {(e, n) for e, n, _ in queries}
    found, vulns = {}, {}
    query(queries, found)
    fetch_all([i for ids in found.values() for i in ids], vulns, wanted)

    # The newest fixed version per package is what a fully updated machine runs.
    newest = {}
    for eco, name, version in queries:
        newest[(eco, name)] = max([newest.get((eco, name), version), version], key=_key)
    for record in vulns.values():
        for affected in record.get("affected", []):
            key = ((affected.get("package") or {}).get("ecosystem"), (affected.get("package") or {}).get("name"))
            for rng in affected.get("ranges") or []:
                for event in rng.get("events", []):
                    if event.get("fixed") and key in newest:
                        newest[key] = max([newest[key], event["fixed"]], key=_key)
    extra = [(e, n, v) for (e, n), v in newest.items() if (e, n, v) not in set(queries)]
    query(extra, found)
    fetch_all([i for ids in found.values() for i in ids], vulns, wanted)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"source": api, "queries": found, "vulns": vulns,
                   "latest": {f"{e}|{n}": v for (e, n), v in newest.items()}}, fh, separators=(",", ":"))
    return len(found), len(vulns)


def _key(version):
    import functools
    return functools.cmp_to_key(compare_versions)(version)
