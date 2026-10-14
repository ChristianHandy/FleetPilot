# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vulnerability (CVE) scan of the servers, FleetPilot itself and appliance services.

What is scanned:
- Linux servers (hosts.json), over SSH: the installed packages (dpkg, apk or rpm)
  are looked up in OSV.dev for the distribution's security data (Debian, Ubuntu,
  Alpine, Rocky Linux, AlmaLinux). Proxmox VE/Backup Server, TrueNAS SCALE and
  Raspberry Pi OS are Debian underneath and are covered the same way.
- Docker containers on those servers: their images are scanned with Trivy when
  Trivy is installed on the server.
- FleetPilot itself: its Python packages (PyPI) and the machine it runs on.
- pfSense and OPNsense: their own `pkg audit` (FreeBSD VuXML).

Only package names and versions are sent to OSV.dev (https://osv.dev, run by
Google, no account). Nothing is sent in offline mode (FLEETPILOT_OFFLINE).
FLEETPILOT_OSV_URL points FleetPilot at a mirror of the OSV API instead.
"""
import concurrent.futures
import json
import logging
import math
import os
import re
import sqlite3
import db_util
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

import requests

import safe_errors
import ssh_helper

logger = logging.getLogger(__name__)

OSV_API = os.environ.get("FLEETPILOT_OSV_URL", "https://api.osv.dev").rstrip("/")
SEVERITIES = ("critical", "high", "medium", "low", "unknown")
_DB_PATH: Optional[str] = None
_lock = threading.Lock()
_progress: Dict = {"running": False}

# One SSH call: which system is this, and what is installed?
INVENTORY_COMMAND = (
    "cat /etc/os-release 2>/dev/null; echo @@fp:pkg; "
    "if command -v dpkg-query >/dev/null 2>&1; then echo dpkg; "
    "dpkg-query -W -f='${source:Package}\\t${source:Version}\\n' 2>/dev/null; "
    "elif command -v apk >/dev/null 2>&1; then echo apk; apk list -I 2>/dev/null; "
    "elif command -v rpm >/dev/null 2>&1; then echo rpm; "
    "rpm -qa --qf '%{NAME}\\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\\n' 2>/dev/null; fi; "
    "echo @@fp:docker; (docker ps --format '{{.Names}}\\t{{.Image}}' 2>/dev/null || "
    "sudo -n docker ps --format '{{.Names}}\\t{{.Image}}' 2>/dev/null); "
    "echo @@fp:trivy; command -v trivy 2>/dev/null"
)


class Unsupported(Exception):
    """The target exists, but there is no vulnerability data for it."""


# ── Database ─────────────────────────────────────────────────────────────────

def init_db(data_dir: str) -> None:
    global _DB_PATH
    _DB_PATH = os.path.join(data_dir, "vulnerabilities.db")
    with _db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS targets (
                id TEXT PRIMARY KEY, kind TEXT, name TEXT, address TEXT, system TEXT, ecosystem TEXT,
                status TEXT, message TEXT, packages INTEGER DEFAULT 0, scanned_at REAL, duration REAL);
            CREATE TABLE IF NOT EXISTS findings (
                target_id TEXT, vuln_id TEXT, package TEXT, installed TEXT, fixed TEXT, severity TEXT,
                score REAL, summary TEXT, aliases TEXT, published TEXT, first_seen REAL,
                PRIMARY KEY (target_id, vuln_id, package));
            CREATE TABLE IF NOT EXISTS vulns (id TEXT PRIMARY KEY, modified TEXT, data TEXT, fetched REAL);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        """)


def _db() -> sqlite3.Connection:
    if not _DB_PATH:
        raise RuntimeError("vuln_scanner.init_db() was not called.")
    conn = sqlite3.connect(_DB_PATH, timeout=15, factory=db_util.ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn


def get_settings() -> Dict:
    with _db() as db:
        rows = dict(db.execute("SELECT key, value FROM settings").fetchall())
    return {"auto_scan": rows.get("auto_scan") == "1", "last_full_scan": float(rows.get("last_full_scan") or 0)}


def set_setting(key: str, value) -> None:
    with _db() as db:
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def enabled() -> Tuple[bool, str]:
    """Whether scans may contact OSV.dev, and why not."""
    from constants import offline_mode
    if offline_mode() and "FLEETPILOT_OSV_URL" not in os.environ:
        return False, "Offline mode is on (FLEETPILOT_OFFLINE), so FleetPilot does not contact OSV.dev."
    return True, ""


# ── Severity ─────────────────────────────────────────────────────────────────

_CVSS3 = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}, "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62}, "C": {"H": 0.56, "L": 0.22, "N": 0.0},
}


def _roundup(value: float) -> float:
    as_int = round(value * 100000)
    return as_int / 100000.0 if as_int % 10000 == 0 else (math.floor(as_int / 10000) + 1) / 10.0


def cvss3_score(vector: str) -> Optional[float]:
    """Base score of a CVSS 3.x vector such as CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H."""
    parts = dict(p.split(":", 1) for p in vector.split("/")[1:] if ":" in p)
    try:
        changed = parts["S"] == "C"
        pr = {"N": 0.85, "L": 0.68 if changed else 0.62, "H": 0.5 if changed else 0.27}[parts["PR"]]
        cia = [_CVSS3["C"][parts[k]] for k in ("C", "I", "A")]
        av, ac, ui = _CVSS3["AV"][parts["AV"]], _CVSS3["AC"][parts["AC"]], _CVSS3["UI"][parts["UI"]]
    except KeyError:
        return None
    iss = 1 - (1 - cia[0]) * (1 - cia[1]) * (1 - cia[2])
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
    if impact <= 0:
        return 0.0
    exploitability = 8.22 * av * ac * pr * ui
    return _roundup(min(1.08 * (impact + exploitability) if changed else impact + exploitability, 10))


def cvss4_level(vector: str) -> Optional[str]:
    """Severity level of a CVSS 4.0 vector, estimated through the matching CVSS 3.1 base metrics.

    The exact 4.0 score needs FIRST's macro-vector table; for sorting and alerting
    the level is enough, so no number is shown for these records.
    """
    p = dict(x.split(":", 1) for x in vector.split("/")[1:] if ":" in x)
    try:
        v3 = (f"CVSS:3.1/AV:{p['AV']}/AC:{'H' if p['AC'] == 'H' or p.get('AT') == 'P' else 'L'}/PR:{p['PR']}"
              f"/UI:{'N' if p['UI'] == 'N' else 'R'}/S:{'C' if 'H' in (p.get('SC'), p.get('SI'), p.get('SA')) else 'U'}"
              f"/C:{p['VC']}/I:{p['VI']}/A:{p['VA']}")
    except KeyError:
        return None
    score = cvss3_score(v3)
    return level_for_score(score) if score is not None else None


def level_for_score(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    return "critical" if score >= 9 else "high" if score >= 7 else "medium" if score >= 4 else "low"


_WORDS = {"critical": "critical", "high": "high", "important": "high", "moderate": "medium", "medium": "medium",
          "low": "low", "negligible": "low", "unimportant": "low"}


def severity_of(vuln: Dict, package: str = "") -> Tuple[str, Optional[float]]:
    """(critical|high|medium|low|unknown, CVSS score or None) from an OSV record."""
    for entry in vuln.get("severity") or []:
        if entry.get("type") == "CVSS_V3":
            score = cvss3_score(entry.get("score", ""))
            if score is not None:
                return level_for_score(score), score
    for entry in vuln.get("severity") or []:
        if entry.get("type") == "CVSS_V4":
            level = cvss4_level(entry.get("score", ""))
            if level:
                return level, None
    words = [entry.get("score", "") for entry in vuln.get("severity") or [] if entry.get("type") == "Ubuntu"]
    words.append((vuln.get("database_specific") or {}).get("severity", ""))
    for affected in vuln.get("affected") or []:
        if not package or (affected.get("package") or {}).get("name") == package:
            words.append(str((affected.get("ecosystem_specific") or {}).get("urgency", "")))
            words.append(str((affected.get("database_specific") or {}).get("severity", "")))
    for word in words:
        level = _WORDS.get(str(word).lower().rstrip("*").strip())
        if level:
            return level, None
    return "unknown", None


def fixed_version(vuln: Dict, package: str, ecosystem: str) -> str:
    """The version that fixes ``package`` in exactly this ecosystem (e.g. Ubuntu:24.04:LTS), or ""."""
    for exact in (True, False):
        for affected in vuln.get("affected") or []:
            pkg = affected.get("package") or {}
            eco = str(pkg.get("ecosystem", ""))
            if pkg.get("name") != package or not (eco == ecosystem if exact else
                                                  eco.split(":")[0] == ecosystem.split(":")[0]):
                continue
            for rng in affected.get("ranges") or []:
                if rng.get("type") == "GIT":
                    continue
                for event in rng.get("events") or []:
                    if event.get("fixed"):
                        return str(event["fixed"])
            if exact:
                return ""          # listed for this release, but not fixed there yet
    return ""


def cve_ids(vuln: Dict) -> List[str]:
    ids = [vuln.get("id", "")] + list(vuln.get("aliases") or []) + list(vuln.get("upstream") or [])
    seen = []
    for i in ids:
        if i.startswith("CVE-") and i not in seen:
            seen.append(i)
    return seen


# ── Inventories ──────────────────────────────────────────────────────────────

def _os_release(text: str) -> Dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"')
    return out


def ecosystem_for(release: Dict[str, str]) -> str:
    """The OSV ecosystem of a Linux distribution, or raise Unsupported."""
    ident = release.get("ID", "").lower()
    like = release.get("ID_LIKE", "").lower().split()
    version = release.get("VERSION_ID", "")
    pretty = release.get("PRETTY_NAME") or ident or "This system"
    if ident in ("debian", "raspbian") and version:
        return f"Debian:{version.split('.')[0]}"
    if ident == "ubuntu" and version:
        major, _, minor = version.partition(".")
        lts = minor == "04" and major.isdigit() and int(major) % 2 == 0
        return f"Ubuntu:{version}" + (":LTS" if lts else "")
    if ident == "alpine" and version:
        return "Alpine:v" + ".".join(version.split(".")[:2])
    if ident == "rocky" and version:
        return f"Rocky Linux:{version.split('.')[0]}"
    if ident == "almalinux" and version:
        return f"AlmaLinux:{version.split('.')[0]}"
    if "debian" in like and ident not in ("ubuntu",):
        raise Unsupported(f"{pretty} is based on Debian, but its own packages have no vulnerability data.")
    raise Unsupported(f"{pretty}: OSV.dev has no vulnerability data for this system yet.")


def parse_inventory(text: str) -> Dict:
    """Split the output of INVENTORY_COMMAND."""
    head, _, rest = text.partition("@@fp:pkg")
    pkgs, _, rest = rest.partition("@@fp:docker")
    docker, _, trivy = rest.partition("@@fp:trivy")
    release = _os_release(head)
    lines = [line for line in pkgs.strip().splitlines() if line.strip()]
    manager = lines[0].strip() if lines else ""
    packages = set()
    for line in lines[1:]:
        if manager in ("dpkg", "rpm"):
            name, _, version = line.partition("\t")
            if name and version:
                packages.add((name.strip(), version.strip()))
        elif manager == "apk":
            m = re.match(r"(\S+)-([^-\s]+-r\d+) \S+ \{([^}]+)\}", line)
            if m:
                packages.add((m.group(3), m.group(2)))
    containers = []
    for line in docker.strip().splitlines():
        name, _, image = line.partition("\t")
        if name and image:
            containers.append({"name": name.strip(), "image": image.strip()})
    return {"release": release, "manager": manager, "packages": sorted(packages), "containers": containers,
            "trivy": trivy.strip().splitlines()[0] if trivy.strip() else ""}


def _ssh(host: Dict):
    key = host.get("ssh_key") or None
    return ssh_helper.create_client(host["host"], port=int(host.get("port") or 22), username=host.get("user") or "root",
                                    key_filename=key if key and os.path.exists(key) else None,
                                    password=host.get("password") or None, timeout=15)


def _run(client, command: str, timeout: int = 120) -> str:
    _, stdout, _ = client.exec_command(command, timeout=timeout)
    return stdout.read().decode("utf-8", errors="replace")


def _local_inventory() -> Dict:
    result = subprocess.run(["/bin/sh", "-c", INVENTORY_COMMAND], capture_output=True, text=True, timeout=120)
    return parse_inventory(result.stdout)


def _python_packages() -> List[Tuple[str, str]]:
    from importlib import metadata
    seen = {}
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "").strip()
        if name:
            seen[re.sub(r"[-_.]+", "-", name).lower()] = dist.version
    return sorted(seen.items())


# ── OSV.dev ──────────────────────────────────────────────────────────────────

def query_osv(ecosystem: str, packages: List[Tuple[str, str]]) -> List[Tuple[str, str, List[str]]]:
    """[(package, version, [vuln ids])] for the packages OSV knows vulnerabilities for."""
    found = []
    for start in range(0, len(packages), 1000):
        chunk = packages[start:start + 1000]
        body = {"queries": [{"package": {"name": n, "ecosystem": ecosystem}, "version": v} for n, v in chunk]}
        resp = requests.post(f"{OSV_API}/v1/querybatch", json=body, timeout=60)
        resp.raise_for_status()
        for (name, version), result in zip(chunk, resp.json().get("results", [])):
            ids = [v["id"] for v in result.get("vulns") or []]
            token = result.get("next_page_token")
            while token:                                 # more than one page for this package
                more = requests.post(f"{OSV_API}/v1/query", timeout=60, json={
                    "package": {"name": name, "ecosystem": ecosystem}, "version": version,
                    "page_token": token}).json()
                ids += [v["id"] for v in more.get("vulns") or []]
                token = more.get("next_page_token")
            if ids:
                found.append((name, version, ids))
    return found


def get_vulns(ids: List[str]) -> Dict[str, Dict]:
    """OSV records by id; cached for a week, so repeat scans only fetch new ones."""
    out, missing = {}, []
    week_ago = time.time() - 7 * 86400
    with _db() as db:
        for vid in set(ids):
            row = db.execute("SELECT data, fetched FROM vulns WHERE id=?", (vid,)).fetchone()
            if row and row["fetched"] > week_ago:
                out[vid] = json.loads(row["data"])
            else:
                missing.append(vid)

    def fetch(vid):
        resp = requests.get(f"{OSV_API}/v1/vulns/{requests.utils.quote(vid, safe='')}", timeout=30)
        resp.raise_for_status()
        return vid, resp.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for future in [pool.submit(fetch, vid) for vid in missing]:
            try:
                vid, data = future.result()
            except Exception as exc:
                logger.warning("[vulns] Could not fetch a record from OSV.dev: %s", exc)
                continue
            out[vid] = data
            with _db() as db:
                db.execute("INSERT OR REPLACE INTO vulns (id, modified, data, fetched) VALUES (?,?,?,?)",
                           (vid, data.get("modified", ""), json.dumps(data), time.time()))
    return out


def findings_from_osv(ecosystem: str, packages: List[Tuple[str, str]]) -> List[Dict]:
    hits = query_osv(ecosystem, packages)
    records = get_vulns([vid for _, _, ids in hits for vid in ids])
    findings = {}
    for name, version, ids in hits:
        for vid in ids:
            vuln = records.get(vid, {"id": vid})
            if vuln.get("withdrawn"):
                continue
            level, score = severity_of(vuln, name)
            summary = vuln.get("summary") or (vuln.get("details") or "").strip().split("\n")[0]
            aliases = cve_ids(vuln)
            finding = {"vuln_id": vid, "package": name, "installed": version,
                       "fixed": fixed_version(vuln, name, ecosystem), "severity": level, "score": score,
                       "summary": summary[:300], "aliases": aliases, "published": (vuln.get("published") or "")[:10]}
            # Advisories from several databases (GHSA, PYSEC, ...) often describe the same CVE: keep the best one.
            key = (name, aliases[0] if aliases else vid)
            old = findings.get(key)
            if old is None or (_rank(level), not finding["fixed"]) < (_rank(old["severity"]), not old["fixed"]):
                findings[key] = finding
    return list(findings.values())


# ── Other sources: Trivy and pkg audit ───────────────────────────────────────

def findings_from_trivy(report: Dict) -> Tuple[int, List[Dict]]:
    packages, findings = set(), []
    for result in report.get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            packages.add(v.get("PkgName"))
            score = None
            for source in (v.get("CVSS") or {}).values():
                score = source.get("V3Score") or score
            level = str(v.get("Severity", "unknown")).lower()
            findings.append({"vuln_id": v.get("VulnerabilityID", ""), "package": v.get("PkgName", ""),
                             "installed": v.get("InstalledVersion", ""), "fixed": v.get("FixedVersion", ""),
                             "severity": level if level in SEVERITIES else "unknown", "score": score,
                             "summary": (v.get("Title") or v.get("Description") or "")[:300],
                             "aliases": [v.get("VulnerabilityID")] if str(v.get("VulnerabilityID")).startswith(
                                 "CVE-") else [], "published": (v.get("PublishedDate") or "")[:10]})
    return len(packages), findings


def parse_pkg_audit(text: str) -> List[Dict]:
    """Findings from FreeBSD `pkg audit` output (pfSense, OPNsense)."""
    findings = []
    for block in re.split(r"\n\s*\n", text):
        m = re.search(r"^(\S+)-([^-\s]+) is vulnerable:", block, re.M)
        if not m:
            continue
        lines = [line.strip() for line in block.splitlines()[1:] if line.strip()]
        title = next((line for line in lines if not re.match(r"(CVE|WWW):", line)), "")
        cves = re.findall(r"CVE:\s*(CVE-\d+-\d+)", block) or [f"VUXML:{m.group(1)}-{m.group(2)}"]
        for cve in cves:
            findings.append({"vuln_id": cve, "package": m.group(1), "installed": m.group(2), "fixed": "",
                             "severity": "unknown", "score": None, "summary": title[:300],
                             "aliases": [cve] if cve.startswith("CVE-") else [], "published": ""})
    return findings


# ── Scanning ─────────────────────────────────────────────────────────────────

def _store(target: Dict, findings: List[Dict], status: str, message: str = "", packages: int = 0,
           started: float = 0.0) -> List[Dict]:
    """Save one target's result. Returns findings that were not there before."""
    now = time.time()
    with _lock, _db() as db:
        # The first successful scan of a target is the baseline: nothing in it counts as "new".
        baseline = not db.execute("SELECT 1 FROM targets WHERE id=? AND status='ok'", (target["id"],)).fetchone()
        old = {(r["vuln_id"], r["package"]): r["first_seen"]
               for r in db.execute("SELECT vuln_id, package, first_seen FROM findings WHERE target_id=?",
                                   (target["id"],))}
        db.execute("INSERT OR REPLACE INTO targets (id, kind, name, address, system, ecosystem, status, message, "
                   "packages, scanned_at, duration) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (target["id"], target["kind"], target["name"], target.get("address", ""),
                    target.get("system", ""), target.get("ecosystem", ""), status, message[:500], packages, now,
                    round(now - started, 1) if started else None))
        if status == "error":
            return []                                  # keep the last good result
        db.execute("DELETE FROM findings WHERE target_id=?", (target["id"],))
        new = []
        for f in findings:
            first = old.get((f["vuln_id"], f["package"]), now)
            db.execute("INSERT OR REPLACE INTO findings (target_id, vuln_id, package, installed, fixed, severity, "
                       "score, summary, aliases, published, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (target["id"], f["vuln_id"], f["package"], f["installed"], f["fixed"], f["severity"],
                        f["score"], f["summary"], json.dumps(f["aliases"]), f["published"], first))
            if (f["vuln_id"], f["package"]) not in old and not baseline:
                new.append(dict(f, target=target["name"]))
    return new


def list_targets(hosts: Dict[str, Dict], routers: List[Dict]) -> List[Dict]:
    from constants import is_localhost
    targets = [{"id": "fleetpilot:python", "kind": "fleetpilot", "name": "FleetPilot (Python packages)",
                "address": ""},
               {"id": "fleetpilot:system", "kind": "fleetpilot", "name": "FleetPilot server (operating system)",
                "address": "localhost"}]
    for name, host in sorted(hosts.items()):
        if not is_localhost(host.get("host", "")):
            targets.append({"id": f"host:{name}", "kind": "server", "name": name, "address": host.get("host", ""),
                            "host": host})
    for router in routers:
        targets.append({"id": f"router:{router['id']}", "kind": "router", "name": router["name"],
                        "address": router.get("host", ""), "router": router})
    return targets


def scan_target(target: Dict) -> List[Dict]:
    """Scan one target and store the result. Returns the new findings."""
    started = time.time()
    new = []
    try:
        if target["id"] == "fleetpilot:python":
            packages = _python_packages()
            target.update(system="Python " + ".".join(map(str, __import__("sys").version_info[:3])),
                          ecosystem="PyPI")
            return _store(target, findings_from_osv("PyPI", packages), "ok", packages=len(packages),
                          started=started)
        if target["kind"] == "router":
            return _scan_router(target, started)
        if target["id"] == "fleetpilot:system":
            inventory = _local_inventory()
        else:
            client = _ssh(target["host"])
            try:
                inventory = parse_inventory(_run(client, INVENTORY_COMMAND))
                new = _scan_containers(target, client, inventory)
            finally:
                client.close()
        release = inventory["release"]
        target["system"] = release.get("PRETTY_NAME", "")
        if not release:
            raise Unsupported("No /etc/os-release: not a Linux system (Windows: keep Windows Update and winget "
                              "updates current; FleetPilot can install them from Hosts).")
        target["ecosystem"] = ecosystem_for(release)
        if not inventory["packages"]:
            raise Unsupported("FleetPilot could not read the list of installed packages.")
        findings = findings_from_osv(target["ecosystem"], inventory["packages"])
        return _store(target, findings, "ok", packages=len(inventory["packages"]), started=started) + new
    except Unsupported as exc:
        return _store(target, [], "unsupported", str(exc), started=started)
    except Exception as exc:
        logger.warning("[vulns] Scan of %s failed: %s", target["name"], exc)
        return _store(target, [], "error", safe_errors.public_error(exc, f"Scanning {target['name']}"),
                      started=started)


def _scan_containers(host_target: Dict, client, inventory: Dict) -> List[Dict]:
    new = []
    for container in inventory["containers"]:
        target = {"id": f"container:{host_target['name']}:{container['name']}", "kind": "container",
                  "name": f"{container['name']} on {host_target['name']}", "address": host_target.get("address", ""),
                  "system": container["image"], "ecosystem": "Trivy"}
        started = time.time()
        if not inventory["trivy"]:
            _store(target, [], "unsupported", f"Install Trivy on {host_target['name']} to scan this container's "
                                              "image (https://trivy.dev).", started=started)
            continue
        try:
            output = _run(client, f"trivy image --quiet --format json --scanners vuln "
                                  f"{_quote(container['image'])} 2>/dev/null", timeout=600)
            count, findings = findings_from_trivy(json.loads(output[output.find("{"):] or "{}"))
            new += _store(target, findings, "ok", packages=count, started=started)
        except Exception as exc:
            _store(target, [], "error", safe_errors.public_error(exc, "Trivy"), started=started)
    return new


def _quote(value: str) -> str:
    import shlex
    return shlex.quote(value)


def _scan_router(target: Dict, started: float) -> List[Dict]:
    import router_manager
    router = router_manager.get_router(target["router"]["id"], secrets=True)
    platform = router["platform"]
    target["system"] = router_manager.PLATFORMS.get(platform, {}).get("label", platform)
    if platform == "opnsense":
        driver = router_manager.OpnsenseDriver(router)
        driver._call("POST", "/api/core/firmware/audit")
        log = ""
        for _ in range(60):
            time.sleep(2)
            status = driver._get("/api/core/firmware/upgradestatus") or {}
            log = status.get("log", "")
            if status.get("status") == "done":
                break
    elif platform == "pfsense":
        with router_manager.PfsenseDriver(router) as driver:
            log = driver.text("pkg audit -F 2>&1", timeout=180)
    else:
        notes = {"fritzbox": "AVM ships security fixes as FRITZ!OS updates; check them under Routers.",
                 "fritzrepeater": "AVM ships security fixes as FRITZ!OS updates; check them under Routers.",
                 "openwrt": "There is no vulnerability feed for OpenWrt packages; the update check under Routers "
                            "lists upgradable packages."}
        raise Unsupported(notes.get(platform, "This device type has no vulnerability data."))
    target["ecosystem"] = "FreeBSD pkg audit"
    findings = parse_pkg_audit(log)
    m = re.search(r"(\d+) problem\(s\) in (\d+) installed package", log)
    return _store(target, findings, "ok", packages=int(m.group(2)) if m else 0, started=started)


def scan_all(hosts: Dict[str, Dict], routers: List[Dict], only: Optional[str] = None) -> List[Dict]:
    """Scan every target (or one). Updates progress(); notifies about new fixable high/critical findings."""
    targets = list_targets(hosts, routers)
    if only:
        targets = [t for t in targets if t["id"] == only]
    _progress.update(running=True, total=len(targets), done=0, current="", started=time.time(), error="")
    new = []
    try:
        if not only:
            keep = {t["id"] for t in targets}
            with _lock, _db() as db:
                for row in db.execute("SELECT id FROM targets").fetchall():
                    if row["id"] not in keep and not row["id"].startswith("container:"):
                        db.execute("DELETE FROM targets WHERE id=?", (row["id"],))
                        db.execute("DELETE FROM findings WHERE target_id=?", (row["id"],))
        for target in targets:
            _progress["current"] = target["name"]
            new += scan_target(target)
            _progress["done"] += 1
        if not only:
            set_setting("last_full_scan", time.time())
        _notify(new)
    except Exception as exc:
        _progress["error"] = safe_errors.public_error(exc, "The scan")
    finally:
        _progress.update(running=False, current="", finished=time.time())
    return new


def start_scan(hosts: Dict[str, Dict], routers: List[Dict], only: Optional[str] = None) -> bool:
    """Run scan_all in the background. False if a scan is already running."""
    if _progress.get("running"):
        return False
    _progress["running"] = True
    threading.Thread(target=scan_all, args=(hosts, routers, only), daemon=True, name="vuln-scan").start()
    return True


def progress() -> Dict:
    return dict(_progress)


def _notify(new: List[Dict]) -> None:
    serious = [f for f in new if f["severity"] in ("critical", "high") and f.get("fixed")]
    if not serious:
        return
    try:
        import notify
        lines = [f"{f['target']}: {(f['aliases'] or [f['vuln_id']])[0]} in {f['package']} {f['installed']} "
                 f"({f['severity']}, fixed in {f['fixed']})" for f in serious[:20]]
        more = f"\n…and {len(serious) - 20} more." if len(serious) > 20 else ""
        notify.send("vulnerability", f"FleetPilot: {len(serious)} new vulnerabilities with a fix",
                    "\n".join(lines) + more + "\nInstall the updates from Hosts or Update Dashboard.",
                    level="critical" if any(f["severity"] == "critical" for f in serious) else "warning")
    except Exception as exc:
        logger.warning("[vulns] Notification failed: %s", exc)


def start_schedule(load_hosts, load_routers) -> None:
    """Scan once a day when automatic scans are on."""
    def _schedule_loop():
        while True:
            time.sleep(900)
            try:
                settings = get_settings()
                if settings["auto_scan"] and enabled()[0] and time.time() - settings["last_full_scan"] > 86400:
                    scan_all(load_hosts(), load_routers())
            except Exception as exc:
                logger.warning("[vulns] Scheduled scan failed: %s", exc)

    threading.Thread(target=_schedule_loop, daemon=True, name="vuln-schedule").start()


# ── Reading results ──────────────────────────────────────────────────────────

def _rank(severity: str) -> int:
    return SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES)


def get_targets() -> List[Dict]:
    with _db() as db:
        targets = [dict(r) for r in db.execute("SELECT * FROM targets ORDER BY kind, name")]
        counts = db.execute("SELECT target_id, severity, COUNT(*) AS n, SUM(fixed != '') AS fixable "
                            "FROM findings GROUP BY target_id, severity").fetchall()
    by_target = {}
    for row in counts:
        entry = by_target.setdefault(row["target_id"], {"counts": {}, "fixable": 0, "total": 0})
        entry["counts"][row["severity"]] = row["n"]
        entry["fixable"] += row["fixable"] or 0
        entry["total"] += row["n"]
    order = {"fleetpilot": 0, "server": 1, "container": 2, "router": 3}
    for t in targets:
        t.update(by_target.get(t["id"], {"counts": {}, "fixable": 0, "total": 0}))
    return sorted(targets, key=lambda t: (order.get(t["kind"], 9), t["name"].lower()))


def get_findings() -> List[Dict]:
    """Findings grouped by vulnerability and package, worst first."""
    with _db() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT f.*, t.name AS target_name FROM findings f JOIN targets t ON t.id = f.target_id")]
    groups = {}
    for r in rows:
        key = (r["vuln_id"], r["package"])
        g = groups.setdefault(key, dict(r, targets=[], aliases=json.loads(r["aliases"] or "[]")))
        g["targets"].append({"id": r["target_id"], "name": r["target_name"], "installed": r["installed"],
                             "fixed": r["fixed"]})
        g["first_seen"] = min(g["first_seen"], r["first_seen"])
        g["fixed"] = g["fixed"] or r["fixed"]
    out = list(groups.values())
    out.sort(key=lambda g: (_rank(g["severity"]), -(g["score"] or 0), not g["fixed"], -len(g["targets"]),
                            g["vuln_id"]))
    return out


def summary() -> Dict:
    with _db() as db:
        row = db.execute("SELECT COUNT(*) AS total, SUM(fixed != '') AS fixable, "
                         "SUM(severity='critical') AS critical, SUM(severity='high') AS high, "
                         "SUM(severity='critical' AND fixed != '') AS critical_fixable, "
                         "COUNT(DISTINCT target_id) AS affected FROM findings").fetchone()
        scanned = db.execute("SELECT COUNT(*) AS n, MAX(scanned_at) AS last FROM targets WHERE status='ok'"
                             ).fetchone()
    return {"total": row["total"] or 0, "fixable": row["fixable"] or 0, "critical": row["critical"] or 0,
            "high": row["high"] or 0, "critical_fixable": row["critical_fixable"] or 0,
            "affected": row["affected"] or 0, "scanned": scanned["n"] or 0, "last_scan": scanned["last"]}
